package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.ProcessingTask;
import com.mneme.entity.User;
import com.mneme.dto.internal.IngestionResult;
import com.mneme.mapper.KnowledgeBaseMapper;
import com.mneme.mapper.KnowledgeDocumentMapper;
import com.mneme.mapper.ProcessingTaskMapper;
import com.mneme.mapper.UserMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.client.RestTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.nio.file.Path;
import java.util.UUID;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@Testcontainers(disabledWithoutDocker = true)
class TaskLeaseConcurrencyTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("mneme-test-password");
    static JdbcTemplate jdbc;
    static DataSourceTransactionManager manager;
    @TempDir Path root;
    private final List<ExecutorService> pools = new ArrayList<>();
    private ExecutorService pool(int size) {
        var pool = Executors.newFixedThreadPool(size); pools.add(pool); return pool;
    }
    @AfterEach void stopPools() { pools.forEach(ExecutorService::shutdownNow); }

    @BeforeAll static void database() {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        jdbc = new JdbcTemplate(source);
        manager = new DataSourceTransactionManager(source);
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
    }

    @Test void onlyOneOwnerWinsAcrossTwoInstancesAndBothQueues() throws Exception {
        var pool = pool(2);
        try (var a = new TaskLeaseService(jdbc, manager, 30); var b = new TaskLeaseService(jdbc, manager, 30)) {
            for (var queue : TaskLeaseService.Queue.values()) {
                long id = task(queue);
                var start = new CountDownLatch(1);
                var x = pool.submit(() -> { start.await(); return a.claim(queue, id, false); });
                var y = pool.submit(() -> { start.await(); return b.claim(queue, id, false); });
                start.countDown();
                var first = x.get(10, TimeUnit.SECONDS); var second = y.get(10, TimeUnit.SECONDS);
                assertThat((first == null) ^ (second == null)).isTrue();
                try (var winner = first == null ? second : first) {
                    assertThat(winner.owner()).hasSize(36);
                    assertThat(winner.fence()).isEqualTo(1);
                    winner.write(row -> { winner.finish("completed", null); return null; });
                }
            }
        }
    }

    @Test void expiredOwnerCannotRenewCommitCompleteOrFailAfterTakeover() {
        try (var a = new TaskLeaseService(jdbc, manager, 300); var b = new TaskLeaseService(jdbc, manager, 300)) {
            for (var queue : TaskLeaseService.Queue.values()) {
                long id = task(queue);
                try (var old = a.claim(queue, id, false)) {
                    // Advance the persisted lease past the five-minute boundary without a wall-clock sleep.
                    expire(queue, id);
                    b.recover(queue);
                    try (var next = b.claim(queue, id, false)) {
                        assertThat(next.owner()).isNotEqualTo(old.owner());
                        assertThat(next.fence()).isEqualTo(old.fence() + 1);
                        assertThatThrownBy(() -> old.write(row -> { throw new AssertionError("stale callback ran"); }))
                            .isInstanceOf(TaskLeaseService.LostLease.class);
                        assertThatThrownBy(old::renew).isInstanceOf(TaskLeaseService.LostLease.class);
                        assertThatThrownBy(() -> old.write(row -> { old.finish("failed", "stale"); return null; }))
                            .isInstanceOf(TaskLeaseService.LostLease.class);
                        next.write(row -> { next.finish("completed", null); return null; });
                        assertThat(state(queue, id)).isEqualTo("completed");
                        assertThatThrownBy(() -> old.write(row -> { old.finish("completed", null); return null; }))
                            .isInstanceOf(TaskLeaseService.LostLease.class);
                    }
                }
            }
        }
    }

    @Test void heartbeatKeepsSlowAttemptExclusiveBeyondItsOriginalLease() throws Exception {
        try (var a = new TaskLeaseService(jdbc, manager, 3); var b = new TaskLeaseService(jdbc, manager, 3)) {
            for (var queue : TaskLeaseService.Queue.values()) {
                long id = task(queue);
                try (var lease = a.claim(queue, id, false)) {
                    lease.startHeartbeat();
                    // Real elapsed time, not a mocked scheduler or database timestamp.
                    new CountDownLatch(1).await(4, TimeUnit.SECONDS);
                    b.recover(queue);
                    assertThat(b.claim(queue, id, false)).isNull();
                    lease.write(row -> { lease.finish("completed", null); return null; });
                }
            }
        }
    }

    @Test void businessChangesTerminalStateAndNotificationRollbackTogether() {
        try (var service = new TaskLeaseService(jdbc, manager, 30)) {
            long id = task(TaskLeaseService.Queue.PROCESSING);
            long user = jdbc.queryForObject("SELECT user_id FROM processing_task WHERE id=?", Long.class, id);
            var events = new NotificationService(jdbc, new ObjectMapper());
            var redis = mock(org.springframework.data.redis.core.StringRedisTemplate.class);
            ReflectionTestUtils.setField(events, "redisEnabled", true);
            ReflectionTestUtils.setField(events, "redis", redis);
            var snapshot = new ProcessingTask(); snapshot.setUserId(user); snapshot.setStatus("completed");
            try (var lease = service.claim(TaskLeaseService.Queue.PROCESSING, id, false)) {
                assertThatThrownBy(() -> lease.finish("completed", null)).isInstanceOf(IllegalStateException.class);
                assertThatThrownBy(() -> lease.write(row -> {
                    jdbc.update("UPDATE user SET email='must-rollback@example.test' WHERE id=?", user);
                    lease.finish("completed", null);
                    events.publish(snapshot);
                    verifyNoInteractions(redis);
                    throw new IllegalStateException("injected failure");
                })).isInstanceOf(IllegalStateException.class);
                assertThat(state(TaskLeaseService.Queue.PROCESSING, id)).isEqualTo("processing");
                assertThat(jdbc.queryForObject("SELECT email FROM user WHERE id=?", String.class, user)).isNotEqualTo("must-rollback@example.test");
                assertThat(events.recent(user)).isEmpty();
                verifyNoInteractions(redis);
                lease.write(row -> { lease.finish("completed", null); events.publish(snapshot); return null; });
                assertThat(events.recent(user)).hasSize(1);
                verify(redis).convertAndSend(eq("mneme:notifications"), anyString());
            }
        }
    }

    @Test void cancellationCleanupAlsoRequiresUniqueUnexpiredOwner() {
        var queue = TaskLeaseService.Queue.PROCESSING;
        try (var a = new TaskLeaseService(jdbc, manager, 30); var b = new TaskLeaseService(jdbc, manager, 30)) {
            long id = task(queue);
            try (var old = a.claim(queue, id, false)) {
                jdbc.update("UPDATE processing_task SET status='cancelling' WHERE id=?", id);
                assertThat(b.claim(queue, id, true)).isNull();
                expire(queue, id);
                try (var next = b.claim(queue, id, true)) {
                    assertThat(next.fence()).isEqualTo(2);
                    assertThatThrownBy(() -> old.write(row -> { old.finish("cancelled", null); return null; }))
                        .isInstanceOf(TaskLeaseService.LostLease.class);
                    next.write(row -> { next.finish("cancelled", null); return null; });
                    assertThat(state(queue, id)).isEqualTo("cancelled");
                }
            }
        }
    }

    @Test void suspendedAccountWorkerCannotWriteStepOrFailureAfterSuccessorCompletes() throws Exception {
        var pool = pool(1);
        long pauseSeconds = Long.getLong("mneme.test.pause-seconds", 0L);
        try (var a = new TaskLeaseService(jdbc, manager, 300); var b = new TaskLeaseService(jdbc, manager, 300)) {
            long id = task(TaskLeaseService.Queue.ACCOUNT_DELETION);
            long userId = jdbc.queryForObject("SELECT user_id FROM account_deletion_task WHERE id=?", Long.class, id);
            var users = mock(UserMapper.class); var user = new User(); user.setId(userId);
            when(users.selectById(userId)).thenReturn(user);
            var entered = new CountDownLatch(1); var resume = new CountDownLatch(1);
            var http = mock(RestTemplate.class);
            doAnswer(call -> { entered.countDown(); assertThat(resume.await(pauseSeconds + 20, TimeUnit.SECONDS)).isTrue(); return null; })
                .when(http).delete(contains("knowledge/admin/user"));
            var worker = new AccountDeletionService(users, jdbc, http, mock(OperationLogService.class),
                "http://agent", root.toString(), 8, mock(ObjectStorageService.class), a);
            try (var old = a.claim(TaskLeaseService.Queue.ACCOUNT_DELETION, id, false)) {
                var running = pool.submit(() -> worker.execute(old));
                try {
                    assertThat(entered.await(10, TimeUnit.SECONDS)).isTrue();
                    if (pauseSeconds > 0) {
                        assertThat(pauseSeconds).isGreaterThan(300);
                        new CountDownLatch(1).await(pauseSeconds, TimeUnit.SECONDS);
                    } else {
                        expire(TaskLeaseService.Queue.ACCOUNT_DELETION, id);
                    }
                    b.recover(TaskLeaseService.Queue.ACCOUNT_DELETION);
                    try (var next = b.claim(TaskLeaseService.Queue.ACCOUNT_DELETION, id, false)) {
                        next.write(row -> {
                            jdbc.update("UPDATE account_deletion_task SET current_step='user_delete' WHERE id=?", id);
                            next.finish("completed", null); return null;
                        });
                    }
                } finally { resume.countDown(); }
                running.get(10, TimeUnit.SECONDS);
                verify(users, never()).deleteById(anyLong());
                assertThat(state(TaskLeaseService.Queue.ACCOUNT_DELETION, id)).isEqualTo("completed");
                assertThat(jdbc.queryForObject("SELECT current_step FROM account_deletion_task WHERE id=?", String.class, id)).isEqualTo("user_delete");
                verify(http, times(1)).delete(anyString());
            }
        }
    }

    @Test void suspendedIngestionCannotPublishDocumentResultAfterTakeover() throws Exception {
        var pool = pool(1);
        try (var a = new TaskLeaseService(jdbc, manager, 300); var b = new TaskLeaseService(jdbc, manager, 300)) {
            long id = task(TaskLeaseService.Queue.PROCESSING);
            var task = new ProcessingTask(); task.setId(id); task.setAggregateId(9L);
            task.setTaskId(jdbc.queryForObject("SELECT task_id FROM processing_task WHERE id=?", String.class, id));
            task.setUserId(jdbc.queryForObject("SELECT user_id FROM processing_task WHERE id=?", Long.class, id));
            task.setTaskType("document_ingest"); task.setStatus("processing");
            task.setPayload("{\"file_path\":\"source.txt\",\"user_id\":\"1\",\"kb_id\":\"2\",\"document_id\":\"9\"}");
            var entered = new CountDownLatch(1); var resume = new CountDownLatch(1);
            var http = mock(RestTemplate.class); var storage = mock(ObjectStorageService.class);
            var documents = mock(KnowledgeDocumentMapper.class); var notifications = mock(NotificationService.class);
            when(storage.materialize(anyString())).thenReturn(root.resolve("source.txt"));
            when(http.postForObject(anyString(), any(), eq(IngestionResult.class))).thenAnswer(call -> {
                entered.countDown(); assertThat(resume.await(20, TimeUnit.SECONDS)).isTrue();
                return new IngestionResult("done", "9", 99, java.util.Map.of());
            });
            var worker = new ProcessingTaskService(mock(ProcessingTaskMapper.class), documents, mock(KnowledgeBaseMapper.class),
                new ObjectMapper(), http, new SimpleMeterRegistry(), notifications, jdbc, storage, a);
            ReflectionTestUtils.setField(worker, "pythonAgentUrl", "http://agent");
            try (var old = a.claim(TaskLeaseService.Queue.PROCESSING, id, false)) {
                var running = pool.submit(() -> ReflectionTestUtils.invokeMethod(worker, "execute", task, old));
                try {
                    assertThat(entered.await(10, TimeUnit.SECONDS)).isTrue();
                    expire(TaskLeaseService.Queue.PROCESSING, id); b.recover(TaskLeaseService.Queue.PROCESSING);
                    try (var next = b.claim(TaskLeaseService.Queue.PROCESSING, id, false)) {
                        next.write(row -> { next.finish("completed", null); return null; });
                    }
                } finally { resume.countDown(); }
                running.get(10, TimeUnit.SECONDS);
                verifyNoInteractions(documents, notifications);
                assertThat(state(TaskLeaseService.Queue.PROCESSING, id)).isEqualTo("completed");
            }
        }
    }

    private long task(TaskLeaseService.Queue queue) {
        String key = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO user(username,password_hash) VALUES(?,'hash')", "lease_" + key);
        long user = jdbc.queryForObject("SELECT id FROM user WHERE username=?", Long.class, "lease_" + key);
        if (queue == TaskLeaseService.Queue.PROCESSING) {
            jdbc.update("INSERT INTO processing_task(task_id,task_type,user_id,idempotency_key,payload) VALUES(?,'document_ingest',?,?,'{}')", key, user, key);
            return jdbc.queryForObject("SELECT id FROM processing_task WHERE task_id=?", Long.class, key);
        }
        jdbc.update("INSERT INTO account_deletion_task(operation_id,user_id,status,current_step,next_attempt_at) VALUES(?,?,'pending','queued',UTC_TIMESTAMP())", key, user);
        return jdbc.queryForObject("SELECT id FROM account_deletion_task WHERE operation_id=?", Long.class, key);
    }
    private void expire(TaskLeaseService.Queue queue, long id) {
        jdbc.update("UPDATE " + queue.table + " SET lease_until=TIMESTAMPADD(SECOND,-301,UTC_TIMESTAMP(6)),locked_at=TIMESTAMPADD(SECOND,-601,UTC_TIMESTAMP(6)) WHERE id=?", id);
    }
    private String state(TaskLeaseService.Queue queue, long id) {
        return jdbc.queryForObject("SELECT status FROM " + queue.table + " WHERE id=?", String.class, id);
    }
}

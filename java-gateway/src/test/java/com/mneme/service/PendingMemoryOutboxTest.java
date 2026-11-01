package com.mneme.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.ChatResponse;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.web.client.RestTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@Testcontainers(disabledWithoutDocker = true)
class PendingMemoryOutboxTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("memory-outbox-test");
    static JdbcTemplate jdbc;
    static DataSourceTransactionManager manager;
    static SqlSessionTemplate template;
    static final ObjectMapper json = new ObjectMapper();
    long user, session, message;
    ChatSessionService sessions;
    PendingMemoryService pending;
    TaskLeaseService leases;
    NotificationService events;

    @BeforeAll static void database() throws Exception {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        jdbc = new JdbcTemplate(source); manager = new DataSourceTransactionManager(source);
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
        var config = new MybatisConfiguration(); config.setMapUnderscoreToCamelCase(true);
        config.addMapper(ChatMessageMapper.class); config.addMapper(ChatSessionMapper.class);
        config.addMapper(PendingMemoryMapper.class); config.addMapper(ProcessingTaskMapper.class);
        var factory = new MybatisSqlSessionFactoryBean(); factory.setDataSource(source); factory.setConfiguration(config);
        template = new SqlSessionTemplate(factory.getObject());
    }

    @BeforeEach void setup() {
        String name = "outbox_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        jdbc.update("INSERT INTO user(username,password_hash,status) VALUES(?,'hash','active')", name);
        user = jdbc.queryForObject("SELECT id FROM user WHERE username=?", Long.class, name);
        jdbc.update("INSERT INTO chat_session(user_id,title) VALUES(?,'outbox')", user);
        session = jdbc.queryForObject("SELECT id FROM chat_session WHERE user_id=?", Long.class, user);
        jdbc.update("INSERT INTO chat_message(session_id,role,content,status,answer_generation) VALUES(?,'assistant','partial','processing',1)", session);
        message = jdbc.queryForObject("SELECT id FROM chat_message WHERE session_id=?", Long.class, session);
        var target = new ChatSessionService(template.getMapper(ChatSessionMapper.class), template.getMapper(ChatMessageMapper.class), jdbc, json);
        var proxy = new ProxyFactory(target); proxy.setProxyTargetClass(true);
        proxy.addAdvice(new TransactionInterceptor(manager, new AnnotationTransactionAttributeSource()));
        sessions = (ChatSessionService) proxy.getProxy();
        pending = new PendingMemoryService(template.getMapper(PendingMemoryMapper.class), mock(MemoryService.class));
        leases = new TaskLeaseService(jdbc, manager, 30); events = mock(NotificationService.class);
    }
    @AfterEach void cleanup() { leases.close(); jdbc.update("DELETE FROM user WHERE id=?", user); }

    ProcessingTaskService worker() {
        return new ProcessingTaskService(template.getMapper(ProcessingTaskMapper.class), mock(KnowledgeDocumentMapper.class),
            mock(KnowledgeBaseMapper.class), json, mock(RestTemplate.class), new SimpleMeterRegistry(), events,
            jdbc, mock(ObjectStorageService.class), leases, pending);
    }
    ChatResponse.PendingMemory candidate(String id) {
        var item = new ChatResponse.PendingMemory(); item.setTempId(id); item.setCategory("preference");
        item.setContent("private-outbox-marker"); item.setTopic("learning"); item.setConfidence(0.75);
        return item;
    }
    ProcessingTask enqueue() {
        sessions.finishAnswer(message, 1L, "verified answer", "[]", List.of(candidate("m_" + message)));
        return task();
    }
    ProcessingTask task() { return template.getMapper(ProcessingTaskMapper.class).selectOne(
        new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ProcessingTask>().eq(ProcessingTask::getUserId, user)); }
    String answerState() { return jdbc.queryForObject("SELECT status FROM chat_message WHERE id=?", String.class, message); }
    long count() { return jdbc.queryForObject("SELECT COUNT(*) FROM pending_memory WHERE user_id=?", Long.class, user); }
    void execute(ProcessingTask task, TaskLeaseService.Lease lease) { ReflectionTestUtils.invokeMethod(worker(), "execute", task, lease); }
    void run() {
        var task = task();
        try (var lease = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), false)) {
            assertThat(lease).isNotNull(); execute(task, lease);
        }
    }

    @Test void answerCommitsBeforeCandidateWritesAndReplayCannotCreateAnotherTask() {
        var task = enqueue();
        assertThat(answerState()).isEqualTo("completed"); assertThat(task.getStatus()).isEqualTo("pending"); assertThat(count()).isZero();
        assertThatThrownBy(() -> sessions.finishAnswer(message, 1, "replay", "[]", List.of(candidate("again"))))
            .isInstanceOf(IllegalStateException.class);
        run();
        assertThat(task().getStatus()).isEqualTo("completed"); assertThat(task().getPayload()).isEqualTo("[]");
        assertThat(count()).isEqualTo(1); assertThat(answerState()).isEqualTo("completed");
    }

    @Test void durableHandoffFailureRollsBackAnswerInsteadOfLosingCandidates() {
        jdbc.update("""
            INSERT INTO processing_task(task_id,task_type,user_id,aggregate_id,idempotency_key,payload)
            VALUES('collision','memory_candidates',?,?,?,'[]')
            """, user, message, "memory:" + message + ":1");
        assertThatThrownBy(() -> sessions.finishAnswer(message, 1, "answer", "[]", List.of(candidate("item"))))
            .isInstanceOf(RuntimeException.class);
        assertThat(answerState()).isEqualTo("processing");
        assertThat(jdbc.queryForObject("SELECT content FROM chat_message WHERE id=?", String.class, message)).isEqualTo("partial");
    }

    @Test void candidateAndTaskCommitRollbackTogetherAndFreshWorkerRetriesWithoutChangingAnswer() {
        enqueue();
        doAnswer(call -> {
            ProcessingTask snapshot = call.getArgument(0);
            if ("completed".equals(snapshot.getStatus())) throw new IllegalStateException("private-outbox-marker");
            return null;
        }).when(events).publish(any());
        run();
        assertThat(answerState()).isEqualTo("completed"); assertThat(count()).isZero();
        assertThat(task().getStatus()).isEqualTo("retry"); assertThat(task().getPayload()).contains("private-outbox-marker");
        assertThat(task().getErrorMessage()).doesNotContain("private-outbox-marker");
        leases.close(); leases = new TaskLeaseService(jdbc, manager, 30); events = mock(NotificationService.class);
        jdbc.update("UPDATE processing_task SET next_attempt_at=UTC_TIMESTAMP() WHERE id=?", task().getId());
        run();
        assertThat(task().getStatus()).isEqualTo("completed"); assertThat(count()).isEqualTo(1);
        assertThat(answerState()).isEqualTo("completed");
    }

    @Test void partialBatchCannotLeakFirstInsertAndResolvedCandidateIsNotResetByRetry() {
        var bad = candidate("bad_" + message); bad.setConfidence(null);
        sessions.finishAnswer(message, 1, "answer", "[]", List.of(candidate("m_" + message), bad));
        run(); assertThat(count()).isZero(); assertThat(task().getStatus()).isEqualTo("retry");
        var task = task();
        jdbc.update("UPDATE processing_task SET payload=?,next_attempt_at=UTC_TIMESTAMP() WHERE id=?",
            "[{\"temp_id\":\"m_" + message + "\",\"category\":\"preference\",\"content\":\"fixed\",\"confidence\":0.75}]", task.getId());
        run(); assertThat(count()).isEqualTo(1);
        jdbc.update("UPDATE pending_memory SET status='dismissed' WHERE user_id=?", user);
        new org.springframework.transaction.support.TransactionTemplate(manager).execute(status -> {
            pending.store(user, session, message, List.of(candidate("m_" + message))); return null;
        });
        assertThat(jdbc.queryForObject("SELECT status FROM pending_memory WHERE user_id=?", String.class, user)).isEqualTo("dismissed");
    }

    @Test void expiredAttemptCannotWriteAfterAnotherInstanceTakesOver() {
        var task = enqueue();
        try (var old = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), false)) {
            jdbc.update("UPDATE processing_task SET lease_until=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP()) WHERE id=?", task.getId());
            leases.recover(TaskLeaseService.Queue.PROCESSING);
            try (var next = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), false)) {
                execute(task, old); assertThat(count()).isZero();
                execute(task, next);
            }
        }
        assertThat(task().getStatus()).isEqualTo("completed"); assertThat(count()).isEqualTo(1);
    }

    @Test void deletingAccountCancelsCandidateWriteAndDropsPayload() {
        var task = enqueue();
        try (var lease = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), false)) {
            jdbc.update("UPDATE user SET status='deleting' WHERE id=?", user); execute(task, lease);
        }
        assertThat(count()).isZero(); assertThat(task().getStatus()).isEqualTo("cancelled");
        assertThat(task().getPayload()).isEqualTo("[]");
        var workspace = new WorkspaceService(jdbc, json, new RestTemplate());
        assertThatThrownBy(() -> workspace.retryTask(user, task.getTaskId())).isInstanceOf(IllegalArgumentException.class);
    }

    @Test void sessionDeletionRemovesDurablePayloadAndOldWorkerCannotResurrectCandidates() {
        var task = enqueue();
        try (var lease = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), false)) {
            sessions.deleteSession(user, session); execute(task, lease);
        }
        assertThat(task()).isNull(); assertThat(count()).isZero();
    }

    @Test void concurrentSessionDeletionAndWorkerLeaveNoTaskOrLateCandidate() throws Exception {
        enqueue();
        var pool = Executors.newFixedThreadPool(2); var start = new CountDownLatch(1);
        try {
            var deletion = pool.submit(() -> { start.await(); sessions.deleteSession(user, session); return true; });
            var write = pool.submit(() -> { start.await(); worker().poll(); return true; });
            start.countDown(); deletion.get(10, TimeUnit.SECONDS); write.get(10, TimeUnit.SECONDS);
        } finally { pool.shutdownNow(); }
        assertThat(task()).isNull();
        // Candidates committed before deletion retain their established SET NULL
        // semantics; candidates cannot be created by a worker after the deletion.
        long before = count(); worker().poll(); assertThat(count()).isEqualTo(before);
    }

    @Test void memoryRetryNeverChangesDocumentWithTheSameNumericId() {
        var task = enqueue();
        jdbc.update("INSERT INTO knowledge_base(user_id,name) VALUES(?,'keep')", user);
        long kb = jdbc.queryForObject("SELECT id FROM knowledge_base WHERE user_id=?", Long.class, user);
        jdbc.update("INSERT INTO knowledge_document(id,kb_id,file_name,file_path,status) VALUES(?,?,'keep.txt','/keep','ready')", message, kb);
        jdbc.update("UPDATE processing_task SET status='failed' WHERE id=?", task.getId());
        new WorkspaceService(jdbc, json, new RestTemplate()).retryTask(user, task.getTaskId());
        assertThat(jdbc.queryForObject("SELECT status FROM knowledge_document WHERE id=?", String.class, message)).isEqualTo("ready");
        run(); assertThat(count()).isEqualTo(1);
    }
}

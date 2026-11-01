package com.mneme.service;

import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.client.RestTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Real MySQL/Flyway saga: unknown cache receipts must not advance or erase its retry manifest. */
@Testcontainers(disabledWithoutDocker = true)
class AccountSessionCleanupTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("mneme-test-password");
    static JdbcTemplate jdbc;
    static DataSourceTransactionManager manager;
    @TempDir Path root;

    @BeforeAll static void database() {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        jdbc = new JdbcTemplate(source);
        manager = new DataSourceTransactionManager(source);
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
    }

    final class Fixture implements AutoCloseable {
        final long user = user(), keep = user();
        final List<String> ownIds = new ArrayList<>(), keepIds = new ArrayList<>();
        final List<List<String>> batches = new ArrayList<>();
        final RestTemplate http = mock(RestTemplate.class);
        final UserMapper users = mock(UserMapper.class);
        final TaskLeaseService leases = new TaskLeaseService(jdbc, manager, 30);
        final AccountDeletionService service = new AccountDeletionService(users, jdbc, http, mock(OperationLogService.class),
            "http://agent", root.toString(), 8, mock(ObjectStorageService.class), leases);
        final long task;
        Fixture(int count) {
            var snapshot = new User(); snapshot.setId(user);
            when(users.selectById(user)).thenReturn(snapshot);
            when(users.deleteById(user)).thenAnswer(call -> jdbc.update("DELETE FROM user WHERE id=?", user));
            // Interleave another tenant's sessions to exercise keyset pagination and scope.
            for (int i = 0; i < count; i++) {
                ownIds.add(session(user));
                if (i % 500 == 0) keepIds.add(session(keep));
            }
            String operation = UUID.randomUUID().toString();
            jdbc.update("INSERT INTO account_deletion_task(operation_id,user_id,status,current_step,next_attempt_at) VALUES(?,?,'pending','memory_cleanup',UTC_TIMESTAMP())", operation, user);
            task = jdbc.queryForObject("SELECT id FROM account_deletion_task WHERE operation_id=?", Long.class, operation);
            healthy();
        }
        long user() {
            String name = UUID.randomUUID().toString();
            jdbc.update("INSERT INTO user(username,password_hash,status) VALUES(?,'QA','deleting')", name);
            return jdbc.queryForObject("SELECT id FROM user WHERE username=?", Long.class, name);
        }
        String session(long user) {
            jdbc.update("INSERT INTO chat_session(user_id,title) VALUES(?,'QA')", user);
            return jdbc.queryForObject("SELECT MAX(id) FROM chat_session WHERE user_id=?", String.class, user);
        }
        void healthy() {
            when(http.postForObject(anyString(), any(), eq(Map.class))).thenAnswer(call -> {
                Map<?, ?> request = call.getArgument(1);
                @SuppressWarnings("unchecked") var ids = (List<String>) request.get("session_ids");
                batches.add(List.copyOf(ids));
                assertThat(call.getArgument(0, String.class)).isEqualTo("http://agent/api/v1/admin/user/" + user + "/session-cache");
                return Map.of("status", "verified", "redis_sessions", 0, "checked_sessions", ids.size());
            });
        }
        void run() {
            try (var lease = leases.claim(TaskLeaseService.Queue.ACCOUNT_DELETION, task, false)) {
                assertThat(lease).isNotNull(); service.execute(lease);
            }
        }
        void retry() {
            jdbc.update("UPDATE account_deletion_task SET next_attempt_at=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP()) WHERE id=?", task);
            run();
        }
        void retained() {
            assertThat(jdbc.queryForObject("SELECT status FROM account_deletion_task WHERE id=?", String.class, task)).isEqualTo("retry");
            assertThat(jdbc.queryForObject("SELECT current_step FROM account_deletion_task WHERE id=?", String.class, task)).isEqualTo("memory_cleanup");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM user WHERE id=?", Integer.class, user)).isEqualTo(1);
            assertThat(jdbc.queryForList("SELECT id FROM chat_session WHERE user_id=? ORDER BY id", String.class, user)).isEqualTo(ownIds);
            verify(users, never()).deleteById(user);
        }
        void completed() {
            assertThat(jdbc.queryForObject("SELECT status FROM account_deletion_task WHERE id=?", String.class, task)).isEqualTo("completed");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM user WHERE id=?", Integer.class, user)).isZero();
            assertThat(jdbc.queryForList("SELECT id FROM chat_session WHERE user_id=? ORDER BY id", String.class, user)).isEmpty();
            assertThat(jdbc.queryForList("SELECT id FROM chat_session WHERE user_id=? ORDER BY id", String.class, keep)).isEqualTo(keepIds);
        }
        public void close() { leases.close(); }
    }

    @Test void paginatesAuthoritativeManifestAndPreservesOtherTenant() {
        try (var f = new Fixture(2001)) {
            f.run(); f.completed();
            assertThat(f.batches).extracting(List::size).containsExactly(1000, 1000, 1);
            assertThat(f.batches.stream().flatMap(List::stream).toList()).isEqualTo(f.ownIds);
            verify(f.http).delete("http://agent/api/v1/admin/user/" + f.user);
        }
    }

    @Test void unknownResidualAndMalformedReceiptsKeepSagaRetryable() {
        Object[] receipts = {null, Map.of(), Map.of("status", "deleted"),
            Map.of("status", "verified", "redis_sessions", 1, "checked_sessions", 1),
            Map.of("status", "verified", "redis_sessions", false, "checked_sessions", 1),
            Map.of("status", "verified", "redis_sessions", "0", "checked_sessions", 1),
            Map.of("status", "verified", "redis_sessions", 0.0, "checked_sessions", 1),
            Map.of("status", "verified", "redis_sessions", 0, "checked_sessions", 0),
            Map.of("status", "verified", "redis_sessions", 0, "checked_sessions", "1")};
        for (Object receipt : receipts) try (var f = new Fixture(1)) {
            when(f.http.postForObject(anyString(), any(), eq(Map.class))).thenReturn((Map<?, ?>) receipt);
            f.run(); f.retained();
            verify(f.http, never()).delete(anyString());
            f.healthy(); f.retry(); f.completed();
        }
    }

    @Test void transportFailureInLaterBatchReplaysFullManifest() {
        try (var f = new Fixture(1001)) {
            when(f.http.postForObject(anyString(), any(), eq(Map.class)))
                .thenReturn(Map.of("status", "verified", "redis_sessions", 0, "checked_sessions", 1000))
                .thenThrow(new IllegalStateException("offline"));
            f.run(); f.retained();
            verify(f.http, never()).delete(anyString());
            f.healthy(); f.retry(); f.completed();
            assertThat(f.batches.stream().flatMap(List::stream).toList()).isEqualTo(f.ownIds);
        }
    }

    @Test void localManifestFailureKeepsCanonicalRowsUntilRetrySucceeds() {
        try (var f = new Fixture(1)) {
            doThrow(new IllegalStateException("manifest unavailable")).when(f.http).delete(anyString());
            f.run(); f.retained();
            doNothing().when(f.http).delete(anyString());
            f.retry(); f.completed();
            assertThat(f.batches).containsExactly(f.ownIds, f.ownIds);
        }
    }

    @Test void emptyCanonicalManifestStillCleansOptionalLocalData() {
        try (var f = new Fixture(0)) {
            f.run(); f.completed();
            verify(f.http, never()).postForObject(anyString(), any(), eq(Map.class));
            verify(f.http).delete("http://agent/api/v1/admin/user/" + f.user);
        }
    }
}

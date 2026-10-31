package com.mneme.migration;

import com.mneme.service.AuthSessionService;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.time.LocalDateTime;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers(disabledWithoutDocker = true)
class AuthSessionActivityTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("mneme-test-password");

    @Test void throttlesHundredsOfRequestsAndConcurrentInstancesWithoutCachingAuthorization() throws Exception {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
        var changed = new AtomicInteger();
        var attempts = new AtomicInteger();
        var jdbc = new JdbcTemplate(source) {
            @Override public int update(String sql, Object... args) {
                int count = super.update(sql, args);
                if (sql.stripLeading().startsWith("UPDATE auth_session SET last_seen_at")) {
                    changed.addAndGet(count);
                    attempts.incrementAndGet();
                }
                return count;
            }
        };
        jdbc.update("INSERT INTO user(username,password_hash) VALUES('activity-test','hash')");
        Long user = jdbc.queryForObject("SELECT id FROM user WHERE username='activity-test'", Long.class);
        var first = new AuthSessionService(jdbc);
        var second = new AuthSessionService(jdbc);
        String session = first.create(user, LocalDateTime.now().plusHours(1), false);
        jdbc.update("UPDATE auth_session SET last_seen_at=DATE_SUB(NOW(), INTERVAL 3 MINUTE) WHERE session_id=?", session);
        changed.set(0); attempts.set(0);
        for (int i = 0; i < 300; i++) assertThat(first.isActive(session, user)).isTrue();
        assertThat(changed.get()).isEqualTo(1);
        assertThat(attempts.get()).isEqualTo(1);

        jdbc.update("UPDATE auth_session SET last_seen_at=DATE_SUB(NOW(), INTERVAL 3 MINUTE) WHERE session_id=?", session);
        changed.set(0); attempts.set(0);
        var pool = Executors.newFixedThreadPool(8);
        try {
            var results = new java.util.ArrayList<java.util.concurrent.Future<Boolean>>();
            for (int i = 0; i < 64; i++) {
                var instance = i % 2 == 0 ? first : second;
                results.add(pool.submit(() -> instance.isActive(session, user)));
            }
            for (var result : results) assertThat(result.get(10, TimeUnit.SECONDS)).isTrue();
            assertThat(changed.get()).isEqualTo(1);
        } finally { pool.shutdownNow(); }

        var lastSeen = jdbc.queryForObject("SELECT last_seen_at FROM auth_session WHERE session_id=?", java.sql.Timestamp.class, session);
        assertThat(second.isActive(session, user + 1)).isFalse();
        first.revoke(session);
        assertThat(second.isActive(session, user)).isFalse();
        assertThat(jdbc.queryForObject("SELECT last_seen_at FROM auth_session WHERE session_id=?", java.sql.Timestamp.class, session)).isEqualTo(lastSeen);
        String expired = first.create(user, LocalDateTime.now().minusMinutes(1), false);
        jdbc.update("UPDATE auth_session SET expires_at=DATE_SUB(NOW(), INTERVAL 1 MINUTE) WHERE session_id=?", expired);
        assertThat(second.isActive(expired, user)).isFalse();
        assertThat(first.isActive("missing", user)).isFalse();
        assertThat(first.isActive("", user)).isFalse();
    }
}

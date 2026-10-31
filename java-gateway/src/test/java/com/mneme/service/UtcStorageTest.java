package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.TimeZone;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers(disabledWithoutDocker = true)
class UtcStorageTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("mneme-test-password");

    @Test void archiveOffsetsAndSessionExpirySurviveNonUtcJvmAndDatabaseTimezones() {
        TimeZone original = TimeZone.getDefault();
        try {
            for (String zone : new String[]{"Asia/Shanghai", "America/Los_Angeles"}) {
                TimeZone.setDefault(TimeZone.getTimeZone(zone));
                String url = MYSQL.getJdbcUrl() + (MYSQL.getJdbcUrl().contains("?") ? "&" : "?")
                    + "connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true";
                var source = new DriverManagerDataSource(url, MYSQL.getUsername(), MYSQL.getPassword());
                Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
                var jdbc = new JdbcTemplate(source);
                assertThat(jdbc.queryForObject("SELECT @@session.time_zone", String.class)).isEqualTo("+00:00");
                var workspace = new WorkspaceService(jdbc, new ObjectMapper(), new RestTemplate());
                Instant expected = Instant.parse("2026-10-30T23:30:00Z");
                for (String value : new String[]{"2026-10-31T07:30:00+08:00", "2026-10-30T23:30:00Z", "2026-10-30 23:30:00"}) {
                    Timestamp parsed = ReflectionTestUtils.invokeMethod(workspace, "parseTimestamp", value);
                    assertThat(parsed.toInstant()).isEqualTo(expected);
                    // Use DATETIME just like review_card.due_at, not a synthetic TIMESTAMP column.
                    jdbc.execute("CREATE TABLE IF NOT EXISTS utc_probe(value DATETIME(6))");
                    jdbc.update("DELETE FROM utc_probe");
                    jdbc.update("INSERT INTO utc_probe(value) VALUES(?)", parsed);
                    assertThat(jdbc.queryForObject("SELECT CAST(value AS CHAR) FROM utc_probe", String.class))
                        .startsWith("2026-10-30 23:30:00");
                    assertThat(jdbc.queryForObject("SELECT value FROM utc_probe", Timestamp.class).toInstant()).isEqualTo(expected);
                }
                assertThat((Object) ReflectionTestUtils.invokeMethod(workspace, "parseTimestamp", "bad")).isNull();
                jdbc.update("INSERT IGNORE INTO user(username,password_hash) VALUES('utc-qa','hash')");
                Long user = jdbc.queryForObject("SELECT id FROM user WHERE username='utc-qa'", Long.class);
                var sessions = new AuthSessionService(jdbc);
                String active = sessions.create(user, LocalDateTime.now(ZoneOffset.UTC).plusHours(1), false);
                String expired = sessions.create(user, LocalDateTime.now(ZoneOffset.UTC).minusMinutes(1), false);
                assertThat(sessions.isActive(active, user)).isTrue();
                assertThat(sessions.isActive(expired, user)).isFalse();
                sessions.revoke(active);
            }
        } finally { TimeZone.setDefault(original); }
    }
}

package com.mneme.service;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.client.RestTemplate;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@Testcontainers(disabledWithoutDocker = true)
class InfrastructureDiagnosticsIntegrationTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("diagnostics-test");
    @Container static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7-alpine")
        .withExposedPorts(6379).withCommand("redis-server", "--requirepass", "diagnostic-test-auth");
    static JdbcTemplate jdbc;
    @BeforeAll static void migrate() {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(source);
    }
    InfrastructureDiagnosticsService service(JdbcTemplate database, StringRedisTemplate redis) {
        return new InfrastructureDiagnosticsService(database, redis, mock(ObjectStorageService.class), mock(PasswordResetDelivery.class), new RestTemplate(), "http://agent", "", "");
    }
    @Test void realRuntimeSqlCrudCleansUpAndReadOnlyPermissionIsNotBusinessSuccess() {
        assertThat(service(jdbc, mock(StringRedisTemplate.class)).check("mysql", 1L))
            .containsEntry("connection", "passed").containsEntry("operation", "passed").containsEntry("cleanup", "passed");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM operations_diagnostic_probe", Long.class)).isZero();
        var admin = new JdbcTemplate(new DriverManagerDataSource(MYSQL.getJdbcUrl(), "root", MYSQL.getPassword()));
        admin.execute("CREATE USER 'diagnostic_reader'@'%' IDENTIFIED BY 'isolated-reader-test'");
        try {
            admin.execute("GRANT SELECT ON mneme.operations_diagnostic_probe TO 'diagnostic_reader'@'%'");
            var reader = new JdbcTemplate(new DriverManagerDataSource(MYSQL.getJdbcUrl(), "diagnostic_reader", "isolated-reader-test"));
            assertThat(service(reader, mock(StringRedisTemplate.class)).check("mysql", 1L))
                .containsEntry("connection", "passed").containsEntry("operation", "failed").containsEntry("cleanup", "failed");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM operations_diagnostic_probe", Long.class)).isZero();
        } finally { admin.execute("DROP USER 'diagnostic_reader'@'%'"); }
    }
    @Test void actualRedisAuthPingReadWriteCleanupAndWrongPassword() {
        for (String password : new String[] { "diagnostic-test-auth", "wrong-test-auth" }) {
            var config = new RedisStandaloneConfiguration(REDIS.getHost(), REDIS.getMappedPort(6379));
            config.setPassword(password);
            var factory = new LettuceConnectionFactory(config); factory.afterPropertiesSet();
            try {
                var redis = new StringRedisTemplate(factory);
                var result = service(jdbc, redis).check("redis", 1L);
                if (password.equals("diagnostic-test-auth")) {
                    assertThat(result).containsEntry("connection", "passed").containsEntry("operation", "passed").containsEntry("cleanup", "passed");
                    assertThat(redis.keys("mneme:diagnostics:probe:*")).isEmpty();
                } else assertThat(result).containsEntry("connection", "failed").containsEntry("operation", "not_run");
            } finally { factory.destroy(); }
        }
    }
}

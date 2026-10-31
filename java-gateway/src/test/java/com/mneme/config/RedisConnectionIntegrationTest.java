package com.mneme.config;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.data.redis.connection.RedisPassword;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers(disabledWithoutDocker = true)
class RedisConnectionIntegrationTest {
    @ParameterizedTest
    @ValueSource(strings = {"", "redis-integration-secret"})
    void springClientConnectsWithTheSameServerPassword(String password) {
        try (var redis = new GenericContainer<>("redis:7-alpine")
                .withExposedPorts(6379)
                .withCommand("redis-server", "--appendonly", "yes", "--appendfsync", "everysec",
                    "--requirepass", password)) {
            redis.start();
            var config = new RedisStandaloneConfiguration(redis.getHost(), redis.getMappedPort(6379));
            if (!password.isEmpty()) config.setPassword(RedisPassword.of(password));
            var factory = new LettuceConnectionFactory(config);
            factory.afterPropertiesSet();
            try (var connection = factory.getConnection()) {
                assertThat(connection.ping()).isEqualTo("PONG");
                assertThat(connection.serverCommands().getConfig("appendonly").get("appendonly")).isEqualTo("yes");
                assertThat(connection.serverCommands().getConfig("appendfsync").get("appendfsync")).isEqualTo("everysec");
            } finally {
                factory.destroy();
            }
        }
    }
}

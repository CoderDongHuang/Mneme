package com.mneme.migration;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.sql.DriverManager;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers(disabledWithoutDocker = true)
class FlywayMigrationTest {
    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme")
        .withUsername("mneme")
        .withPassword("mneme-test-password");

    @Test
    void appliesAllMigrationsToAnEmptyDatabase() throws Exception {
        Flyway.configure()
            .dataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword())
            .locations("classpath:db/migration")
            .load()
            .migrate();

        try (var connection = DriverManager.getConnection(
            MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword()
        ); var statement = connection.createStatement();
             var rows = statement.executeQuery("""
                 SELECT COUNT(*) FROM information_schema.tables
                 WHERE table_schema = DATABASE()
                   AND table_name IN ('learning_plan', 'review_card', 'knowledge_quiz', 'quiz_attempt', 'chat_branch')
                 """)) {
            assertThat(rows.next()).isTrue();
            assertThat(rows.getInt(1)).isEqualTo(5);
        }

        try (var connection = DriverManager.getConnection(
            MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword()
        ); var statement = connection.createStatement();
             var columns = statement.executeQuery("""
                 SELECT COUNT(*) FROM information_schema.columns
                 WHERE table_schema = DATABASE()
                   AND table_name = 'user'
                   AND column_name IN ('nickname', 'email', 'avatar_path')
                 """)) {
            assertThat(columns.next()).isTrue();
            assertThat(columns.getInt(1)).isEqualTo(3);
        }

        try (var connection = DriverManager.getConnection(
            MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword()
        ); var statement = connection.createStatement();
             var securityTables = statement.executeQuery("""
                 SELECT COUNT(*) FROM information_schema.tables
                 WHERE table_schema = DATABASE()
                   AND table_name IN ('password_reset_token', 'audit_log')
                 """)) {
            assertThat(securityTables.next()).isTrue();
            assertThat(securityTables.getInt(1)).isEqualTo(2);
        }
    }
}

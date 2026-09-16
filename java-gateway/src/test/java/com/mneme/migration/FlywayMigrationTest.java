package com.mneme.migration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.service.WorkspaceService;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.RestTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.sql.DriverManager;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;

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

    @Test
    void exportsAndImportsAllWorkspaceRelationships() throws Exception {
        Flyway.configure().dataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword())
            .locations("classpath:db/migration").load().migrate();
        var dataSource = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        var jdbc = new JdbcTemplate(dataSource);
        jdbc.update("INSERT INTO user(username,password_hash) VALUES('export-user','hash'),('import-user','hash')");
        Long sourceUser = jdbc.queryForObject("SELECT id FROM user WHERE username='export-user'", Long.class);
        Long targetUser = jdbc.queryForObject("SELECT id FROM user WHERE username='import-user'", Long.class);
        jdbc.update("INSERT INTO knowledge_base(user_id,name,status) VALUES(?, '课程资料', 'active')", sourceUser);
        Long kb = jdbc.queryForObject("SELECT id FROM knowledge_base WHERE user_id=? AND name='课程资料'", Long.class, sourceUser);
        jdbc.update("INSERT INTO chat_session(user_id,title) VALUES(?, '原会话'),(?, '分支会话')", sourceUser, sourceUser);
        var sessions = jdbc.queryForList("SELECT id FROM chat_session WHERE user_id=? ORDER BY id", Long.class, sourceUser);
        jdbc.update("INSERT INTO chat_message(session_id,role,content) VALUES(?, 'user', '解释链式法则')", sessions.get(0));
        Long message = jdbc.queryForObject("SELECT id FROM chat_message WHERE session_id=?", Long.class, sessions.get(0));
        jdbc.update("INSERT INTO learning_plan(user_id,title,goal) VALUES(?, '学习计划', '掌握反向传播')", sourceUser);
        Long plan = jdbc.queryForObject("SELECT id FROM learning_plan WHERE user_id=?", Long.class, sourceUser);
        jdbc.update("INSERT INTO review_card(user_id,plan_id,prompt,answer) VALUES(?,?, '什么是链式法则', '复合函数求导规则')", sourceUser, plan);
        jdbc.update("INSERT INTO knowledge_quiz(user_id,kb_id,title,topic,questions_json) VALUES(?,?, '测验', '反向传播', JSON_ARRAY())", sourceUser, kb);
        Long quiz = jdbc.queryForObject("SELECT id FROM knowledge_quiz WHERE user_id=?", Long.class, sourceUser);
        jdbc.update("INSERT INTO quiz_attempt(quiz_id,user_id,answers_json,score,feedback_json) VALUES(?,?,JSON_ARRAY(),80,JSON_ARRAY())", quiz, sourceUser);
        jdbc.update("INSERT INTO chat_branch(user_id,source_session_id,source_message_id,branch_session_id,label) VALUES(?,?,?,?, '另一种解释')",
            sourceUser, sessions.get(0), message, sessions.get(1));

        var mapper = new ObjectMapper().findAndRegisterModules();
        var service = new WorkspaceService(jdbc, mapper, new RestTemplate());
        var exported = service.exportData(sourceUser);
        @SuppressWarnings("unchecked") var importPayload = mapper.readValue(mapper.writeValueAsBytes(exported), java.util.Map.class);
        var transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        @SuppressWarnings("unchecked") var result = transaction.execute(status -> {
            try {
                return service.importData(targetUser, importPayload);
            } catch (Exception error) {
                throw new RuntimeException(error);
            }
        });
        @SuppressWarnings("unchecked") var counts = (java.util.Map<String, Integer>) result.get("counts");

        assertThat(exported).containsEntry("schema", "mneme.workspace").containsEntry("version", 2);
        assertThat(counts).containsEntry("knowledge_bases", 1).containsEntry("sessions", 2)
            .containsEntry("messages", 1).containsEntry("plans", 1).containsEntry("reviews", 1)
            .containsEntry("quizzes", 1).containsEntry("quiz_attempts", 1).containsEntry("branches", 1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM chat_branch WHERE user_id=?", Integer.class, targetUser)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM quiz_attempt WHERE user_id=?", Integer.class, targetUser)).isEqualTo(1);
    }

    @Test
    void onlyOneInstanceCanClaimTheSameRecoveryTask() throws Exception {
        Flyway.configure().dataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword())
            .locations("classpath:db/migration").load().migrate();
        var dataSource = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        var jdbc = new JdbcTemplate(dataSource);
        jdbc.update("INSERT INTO user(username,password_hash,status) VALUES('claim-user','hash','deleting')");
        Long userId = jdbc.queryForObject("SELECT id FROM user WHERE username='claim-user'", Long.class);
        jdbc.update("""
            INSERT INTO account_deletion_task(operation_id,user_id,status,next_attempt_at)
            VALUES('claim-op',?,'pending',?)
            """, userId, LocalDateTime.now());
        Long taskId = jdbc.queryForObject(
            "SELECT id FROM account_deletion_task WHERE operation_id='claim-op'", Long.class);
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        var executor = Executors.newFixedThreadPool(2);
        try {
            var first = executor.submit(() -> claim(jdbc, taskId, "instance-a", ready, start));
            var second = executor.submit(() -> claim(jdbc, taskId, "instance-b", ready, start));
            ready.await();
            start.countDown();
            assertThat(first.get() + second.get()).isEqualTo(1);
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void concurrentBranchesRemainIndependent() throws Exception {
        Flyway.configure().dataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword())
            .locations("classpath:db/migration").load().migrate();
        var dataSource = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        var jdbc = new JdbcTemplate(dataSource);
        jdbc.update("INSERT INTO user(username,password_hash) VALUES('branch-user','hash')");
        Long userId = jdbc.queryForObject("SELECT id FROM user WHERE username='branch-user'", Long.class);
        jdbc.update("INSERT INTO chat_session(user_id,title) VALUES(?, 'source')", userId);
        Long sessionId = jdbc.queryForObject("SELECT id FROM chat_session WHERE user_id=?", Long.class, userId);
        jdbc.update("INSERT INTO chat_message(session_id,role,content) VALUES(?, 'user', 'source question')", sessionId);
        Long messageId = jdbc.queryForObject("SELECT id FROM chat_message WHERE session_id=?", Long.class, sessionId);
        WorkspaceService service = new WorkspaceService(
            jdbc, new ObjectMapper().findAndRegisterModules(), new RestTemplate());
        var transactionManager = new DataSourceTransactionManager(dataSource);
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        var executor = Executors.newFixedThreadPool(2);
        try {
            var first = executor.submit(() -> {
                createBranch(service, transactionManager, userId, sessionId, messageId, "branch-a", ready, start);
                return null;
            });
            var second = executor.submit(() -> {
                createBranch(service, transactionManager, userId, sessionId, messageId, "branch-b", ready, start);
                return null;
            });
            ready.await();
            start.countDown();
            first.get();
            second.get();
            assertThat(jdbc.queryForObject(
                "SELECT COUNT(*) FROM chat_branch WHERE user_id=?", Integer.class, userId)).isEqualTo(2);
            assertThat(jdbc.queryForObject("""
                SELECT COUNT(*) FROM chat_message m JOIN chat_branch b ON b.branch_session_id=m.session_id
                WHERE b.user_id=? AND m.content='source question'
                """, Integer.class, userId)).isEqualTo(2);
        } finally {
            executor.shutdownNow();
        }
    }

    private void createBranch(
        WorkspaceService service,
        DataSourceTransactionManager transactionManager,
        Long userId,
        Long sessionId,
        Long messageId,
        String label,
        CountDownLatch ready,
        CountDownLatch start
    ) throws Exception {
        ready.countDown();
        start.await();
        new TransactionTemplate(transactionManager).executeWithoutResult(status -> service.createBranch(userId, Map.of(
            "source_session_id", sessionId,
            "source_message_id", messageId,
            "label", label
        )));
    }

    private int claim(JdbcTemplate jdbc, Long taskId, String instance, CountDownLatch ready, CountDownLatch start)
        throws Exception {
        ready.countDown();
        start.await();
        return jdbc.update("""
            UPDATE account_deletion_task SET status='processing',locked_at=NOW(),locked_by=?
            WHERE id=? AND status IN ('pending','retry')
            """, instance, taskId);
    }
}

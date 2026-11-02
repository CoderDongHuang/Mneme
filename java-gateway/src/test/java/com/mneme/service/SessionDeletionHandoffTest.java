package com.mneme.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.http.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.web.client.RestTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.*;

import java.util.*;
import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@Testcontainers(disabledWithoutDocker = true)
class SessionDeletionHandoffTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("session-delete-test")
        .withCommand("--log-bin-trust-function-creators=1");
    static JdbcTemplate jdbc;
    static DataSourceTransactionManager manager;
    static SqlSessionTemplate template;
    static final ObjectMapper json = new ObjectMapper();
    long user, other, session, keep, message;
    ChatSessionService sessions;
    TaskLeaseService leases;
    RestTemplate http;
    ProcessingTaskService worker;

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
        String name = "session_delete_" + UUID.randomUUID().toString().replace("-", "").substring(0, 20);
        jdbc.update("INSERT INTO user(username,password_hash,status) VALUES(?,'hash','active'),(?,'hash','active')", name, name + "_other");
        user = jdbc.queryForObject("SELECT id FROM user WHERE username=?", Long.class, name);
        other = jdbc.queryForObject("SELECT id FROM user WHERE username=?", Long.class, name + "_other");
        jdbc.update("INSERT INTO chat_session(user_id,title) VALUES(?,'target'),(?,'keep')", user, user);
        session = jdbc.queryForObject("SELECT id FROM chat_session WHERE user_id=? AND title='target'", Long.class, user);
        keep = jdbc.queryForObject("SELECT id FROM chat_session WHERE user_id=? AND title='keep'", Long.class, user);
        jdbc.update("INSERT INTO chat_message(session_id,role,content,status,answer_generation) VALUES(?,'assistant','partial','processing',1)", session);
        message = jdbc.queryForObject("SELECT id FROM chat_message WHERE session_id=?", Long.class, session);
        var target = new ChatSessionService(template.getMapper(ChatSessionMapper.class), template.getMapper(ChatMessageMapper.class), jdbc, json);
        var proxy = new ProxyFactory(target); proxy.setProxyTargetClass(true);
        proxy.addAdvice(new TransactionInterceptor(manager, new AnnotationTransactionAttributeSource()));
        sessions = (ChatSessionService) proxy.getProxy();
        leases = new TaskLeaseService(jdbc, manager, 30); http = mock(RestTemplate.class);
        worker = new ProcessingTaskService(template.getMapper(ProcessingTaskMapper.class), mock(KnowledgeDocumentMapper.class),
            mock(KnowledgeBaseMapper.class), json, http, new SimpleMeterRegistry(), mock(NotificationService.class), jdbc,
            mock(ObjectStorageService.class), leases, new PendingMemoryService(template.getMapper(PendingMemoryMapper.class), mock(MemoryService.class)));
        ReflectionTestUtils.setField(worker, "pythonAgentUrl", "http://agent");
        response(Map.of("deleted", true, "session_id", String.valueOf(session)));
    }

    @AfterEach void cleanup() { leases.close(); jdbc.update("DELETE FROM user WHERE id IN (?,?)", user, other); }
    ProcessingTask task() { return template.getMapper(ProcessingTaskMapper.class).selectOne(
        new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ProcessingTask>()
            .eq(ProcessingTask::getUserId, user).eq(ProcessingTask::getTaskType, "session_delete")); }
    void response(Map<String, Object> receipt) {
        when(http.exchange(eq("http://agent/api/v1/session/" + session + "?user_id=" + user), eq(HttpMethod.DELETE), isNull(), eq(Map.class)))
            .thenReturn(ResponseEntity.ok(receipt));
    }
    void run() {
        var task = task();
        try (var lease = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), false)) {
            assertThat(lease).isNotNull(); ReflectionTestUtils.invokeMethod(worker, "execute", task, lease);
        }
    }
    long count(String table) { return jdbc.queryForObject("SELECT COUNT(*) FROM " + table + " WHERE "
        + (table.equals("chat_session") ? "id" : "session_id") + "=?", Long.class, session); }
    void retry() { new WorkspaceService(jdbc, json, http).retryTask(user, task().getTaskId()); }

    @Test void enqueueIsDurableIdempotentAndBlocksAllLateWritesBeforeAgentRuns() {
        var receipt = sessions.deleteSession(user, session);
        assertThat(receipt).containsEntry("accepted", true).containsEntry("status", "pending").doesNotContainKey("deleted");
        assertThat(sessions.deleteSession(user, session)).isEqualTo(receipt);
        assertThat(count("chat_session")).isEqualTo(1); assertThat(count("chat_message")).isEqualTo(1);
        assertThat(sessions.listSessions(user)).extracting(com.mneme.entity.ChatSession::getId).containsExactly(keep);
        assertThatThrownBy(() -> sessions.getMessages(user, session)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> sessions.renameSession(user, session, "late")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> sessions.appendMessage(user, session, "user", "late")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> sessions.prepareExchange(user, session, "late", "late")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> sessions.finishAnswer(message, 1, "late", "[]")).isInstanceOf(IllegalStateException.class);
        verifyNoInteractions(http);
        run(); assertThat(task().getStatus()).isEqualTo("completed");
        assertThat(count("chat_session")).isZero(); assertThat(count("chat_message")).isZero();
        assertThat(sessions.deleteSession(user, session)).containsEntry("task_id", receipt.get("task_id")).containsEntry("status", "completed");
        assertThat(sessions.getOwnedSession(user, keep).getId()).isEqualTo(keep);
        assertThatThrownBy(() -> sessions.deleteSession(other, keep)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> sessions.deleteSession(other, session)).isInstanceOf(IllegalArgumentException.class);
    }

    @Test void concurrentRequestsReceiveOneDurableTask() throws Exception {
        var pool = Executors.newFixedThreadPool(2); var start = new CountDownLatch(1);
        try {
            var a = pool.submit(() -> { start.await(); return sessions.deleteSession(user, session); });
            var b = pool.submit(() -> { start.await(); return sessions.deleteSession(user, session); });
            start.countDown(); assertThat(a.get(10, TimeUnit.SECONDS)).isEqualTo(b.get(10, TimeUnit.SECONDS));
        } finally { pool.shutdownNow(); }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM processing_task WHERE user_id=?", Long.class, user)).isEqualTo(1);
    }

    @Test void verifiedCleanupErasesCandidatesAndDurablePayloadButProtectsAnotherSession() {
        jdbc.update("INSERT INTO pending_memory(memory_id,user_id,session_id,source_message_id,category,content,confidence) VALUES(?,?,?,?,'preference','private',0.8)",
            "target_" + message, user, session, message);
        jdbc.update("INSERT INTO pending_memory(memory_id,user_id,session_id,category,content,confidence) VALUES(?,?,?,'preference','keep',0.8)",
            "keep_" + message, user, keep);
        jdbc.update("INSERT INTO processing_task(task_id,task_type,user_id,aggregate_id,idempotency_key,payload) VALUES(?,'memory_candidates',?,?,?,'[]')",
            "candidate_" + message, user, message, "candidate:" + message);
        sessions.deleteSession(user, session); run();
        assertThat(task().getStatus()).isEqualTo("completed"); assertThat(count("pending_memory")).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM processing_task WHERE user_id=? AND task_type='memory_candidates'", Long.class, user)).isZero();
        assertThat(jdbc.queryForObject("SELECT content FROM pending_memory WHERE user_id=?", String.class, user)).isEqualTo("keep");
        assertThat(count("chat_message")).isZero();
    }

    @Test void deletingAccountRejectsEnqueueAndManualRetry() {
        sessions.deleteSession(user, session); response(Map.of()); run();
        jdbc.update("UPDATE user SET status='deleting' WHERE id=?", user);
        assertThatThrownBy(() -> sessions.deleteSession(user, keep)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(this::retry).isInstanceOf(IllegalArgumentException.class);
        assertThat(count("chat_session")).isEqualTo(1);
    }

    @Test void invalidReceiptsRetainCanonicalScopeAndRecoveryReusesTask() {
        for (var bad : List.of(Map.<String,Object>of(), Map.<String,Object>of("deleted", "true", "session_id", "" + session),
            Map.<String,Object>of("deleted", true, "session_id", session), Map.<String,Object>of("deleted", true, "session_id", "other"))) {
            sessions.deleteSession(user, session); response(bad); run();
            assertThat(task().getStatus()).isEqualTo("retry");
            assertThat(count("chat_session")).isEqualTo(1); assertThat(count("chat_message")).isEqualTo(1);
            retry();
        }
        String id = task().getTaskId(); response(Map.of("deleted", true, "session_id", "" + session)); run();
        assertThat(task().getStatus()).isEqualTo("completed"); assertThat(task().getTaskId()).isEqualTo(id);
    }

    @Test void remoteFailureNeverDeletesSqlOrLeaksExceptionAndFreshWorkerCanRetry() {
        sessions.deleteSession(user, session);
        when(http.exchange(anyString(), eq(HttpMethod.DELETE), isNull(), eq(Map.class)))
            .thenThrow(new IllegalStateException("private-session-marker"));
        run(); assertThat(task().getStatus()).isEqualTo("retry");
        assertThat(task().getErrorMessage()).doesNotContain("private-session-marker");
        assertThat(count("chat_session")).isEqualTo(1); retry();
        response(Map.of("deleted", true, "session_id", "" + session)); run();
        assertThat(task().getStatus()).isEqualTo("completed");
    }

    @Test void sqlFailureRollsBackAllLocalDeletesAndExpiredLeaseCannotComplete() {
        sessions.deleteSession(user, session);
        jdbc.execute("CREATE TRIGGER fail_session_delete BEFORE DELETE ON chat_session FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='QA SQL failure'");
        try {
            run(); assertThat(task().getStatus()).isEqualTo("retry");
            assertThat(count("chat_session")).isEqualTo(1); assertThat(count("chat_message")).isEqualTo(1);
        } finally { jdbc.execute("DROP TRIGGER fail_session_delete"); }
        retry(); var task = task();
        try (var old = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), false)) {
            jdbc.update("UPDATE processing_task SET lease_until=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP()) WHERE id=?", task.getId());
            leases.recover(TaskLeaseService.Queue.PROCESSING);
            ReflectionTestUtils.invokeMethod(worker, "execute", task, old);
            assertThat(count("chat_session")).isEqualTo(1);
            try (var next = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), false)) {
                ReflectionTestUtils.invokeMethod(worker, "execute", task, next);
            }
        }
        assertThat(task().getStatus()).isEqualTo("completed"); assertThat(count("chat_message")).isZero();
    }
}

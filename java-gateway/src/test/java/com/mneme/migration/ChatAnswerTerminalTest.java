package com.mneme.migration;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.spring.MybatisSqlSessionFactoryBean;
import com.mneme.mapper.ChatMessageMapper;
import com.mneme.mapper.ChatSessionMapper;
import com.mneme.service.ChatSessionService;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

@Testcontainers(disabledWithoutDocker = true)
class ChatAnswerTerminalTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("terminal-test-password");
    static JdbcTemplate jdbc;
    static ChatMessageMapper messages;
    static ChatSessionService service;

    @BeforeAll static void database() throws Exception {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        jdbc = new JdbcTemplate(source);
        Flyway.configure().dataSource(source).locations("classpath:db/migration").target("30").load().migrate();
        jdbc.update("INSERT INTO user(id,username,password_hash) VALUES(1,'terminal','hash')");
        jdbc.update("INSERT INTO chat_session(id,user_id,title) VALUES(1,1,'terminal')");
        jdbc.update("INSERT INTO chat_message(id,session_id,role,content,status,request_id) VALUES(1,1,'assistant','legacy','completed','legacy')");
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
        assertThat(jdbc.queryForObject("SELECT answer_generation FROM chat_message WHERE id=1", Long.class)).isZero();
        var config = new MybatisConfiguration(); config.setMapUnderscoreToCamelCase(true);
        config.addMapper(ChatMessageMapper.class); config.addMapper(ChatSessionMapper.class);
        var factory = new MybatisSqlSessionFactoryBean(); factory.setDataSource(source); factory.setConfiguration(config);
        var template = new SqlSessionTemplate(factory.getObject());
        messages = template.getMapper(ChatMessageMapper.class);
        var proxy = new ProxyFactory(new ChatSessionService(template.getMapper(ChatSessionMapper.class), messages, jdbc));
        proxy.setProxyTargetClass(true);
        proxy.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(source), new AnnotationTransactionAttributeSource()));
        service = (ChatSessionService) proxy.getProxy();
    }

    @BeforeEach void reset() {
        jdbc.update("DELETE FROM chat_message");
        jdbc.update("INSERT INTO chat_message(id,session_id,role,content,status,request_id,answer_generation) VALUES(1,1,'user','question','completed','request',0)");
        jdbc.update("INSERT INTO chat_message(id,session_id,role,content,status,error_code,sources_json,request_id,answer_generation) VALUES(2,1,'assistant','partial','processing','OLD','[]','request',1)");
    }

    @Test void commitsAnswerEvidenceAndClearsErrorAtomicallyAndRejectsLateFailure() {
        var stale = messages.selectById(2L);
        service.finishAnswer(2L, 1L, "verified", "[{\"documentId\":8}]");
        service.failMessage(2L, 1L, "late partial", "DISCONNECTED");
        stale.setContent("stale"); stale.setErrorCode("OLD"); stale.setAnswerGeneration(0L);
        stale.setRole("assistant"); messages.updateById(stale);
        var saved = messages.selectById(2L);
        assertThat(saved.getContent()).isEqualTo("verified");
        assertThat(saved.getStatus()).isEqualTo("completed");
        assertThat(saved.getErrorCode()).isNull();
        assertThat(saved.getSourcesJson()).contains("documentId", "8");
        assertThat(saved.getAnswerGeneration()).isEqualTo(1L);
    }

    @Test void badEvidenceCannotPartiallyCommitAndEmptyAnswerCannotComplete() {
        assertThatThrownBy(() -> service.finishAnswer(2L, 1L, "verified", "invalid-json")).isInstanceOf(RuntimeException.class);
        var saved = messages.selectById(2L);
        assertThat(saved.getStatus()).isEqualTo("processing");
        assertThat(saved.getContent()).isEqualTo("partial");
        assertThat(saved.getErrorCode()).isEqualTo("OLD");
        assertThatThrownBy(() -> service.finishAnswer(2L, 1L, "  ", "[]")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test void retryFencesOldCompletionAndFailureAndClearsPersistedError() {
        service.failMessage(2L, 1L, "partial", "TIMEOUT");
        var retry = service.prepareExchange(1L, 1L, "request", "question");
        assertThat(retry.assistantMessage().getAnswerGeneration()).isEqualTo(2L);
        assertThat(messages.selectById(2L).getErrorCode()).isNull();
        assertThatThrownBy(() -> service.finishAnswer(2L, 1L, "old answer", "[]")).isInstanceOf(IllegalStateException.class);
        service.failMessage(2L, 1L, "old failure", "OLD");
        assertThat(messages.selectById(2L).getStatus()).isEqualTo("processing");
        assertThat(messages.selectById(2L).getContent()).isEmpty();
        service.finishAnswer(2L, 2L, "new answer", "[]");
        assertThat(service.prepareExchange(1L, 1L, "request", "question").completed()).isTrue();
        assertThat(messages.selectById(2L).getContent()).isEqualTo("new answer");
    }

    @Test void competingTerminalCallbacksHaveExactlyOneWinner() throws Exception {
        var pool = Executors.newFixedThreadPool(2); var start = new CountDownLatch(1);
        try {
            var complete = pool.submit(() -> {
                start.await();
                try { service.finishAnswer(2L, 1L, "winner", "[]"); } catch (IllegalStateException lost) { }
                return true;
            });
            var fail = pool.submit(() -> { start.await(); service.failMessage(2L, 1L, "failed partial", "TIMEOUT"); return true; });
            start.countDown(); complete.get(10, TimeUnit.SECONDS); fail.get(10, TimeUnit.SECONDS);
        } finally { pool.shutdownNow(); }
        var saved = messages.selectById(2L);
        if (saved.getStatus().equals("completed")) {
            assertThat(saved.getContent()).isEqualTo("winner"); assertThat(saved.getErrorCode()).isNull();
        } else {
            assertThat(saved.getStatus()).isEqualTo("failed"); assertThat(saved.getContent()).isEqualTo("failed partial");
            assertThat(saved.getErrorCode()).isEqualTo("TIMEOUT");
        }
    }

    @Test void missingMessageCannotPublishSuccess() {
        jdbc.update("DELETE FROM chat_message WHERE id=2");
        assertThatThrownBy(() -> service.finishAnswer(2L, 1L, "answer", "[]")).isInstanceOf(IllegalStateException.class);
    }
}

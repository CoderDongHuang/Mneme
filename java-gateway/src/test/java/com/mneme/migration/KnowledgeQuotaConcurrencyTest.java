package com.mneme.migration;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.KnowledgeDocument;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.KnowledgeBaseMapper;
import com.mneme.mapper.KnowledgeDocumentMapper;
import com.mneme.mapper.ProcessingTaskMapper;
import com.mneme.service.KnowledgeService;
import com.mneme.service.ObjectStorageService;
import com.mneme.service.WorkspaceService;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.web.client.RestTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@Testcontainers(disabledWithoutDocker = true)
class KnowledgeQuotaConcurrencyTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("mneme-test-password");
    static DriverManagerDataSource source;
    static JdbcTemplate jdbc;
    @TempDir Path root;

    @BeforeAll static void database() {
        source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        jdbc = new JdbcTemplate(source);
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
    }

    @Test void twoKnowledgeBasesCannotBothConsumeTheSameRemainingBytesEvenWithOldSnapshots() throws Exception {
        long user = user();
        var first = service(null, 10);
        var second = service(null, 10);
        long a = first.createKb(user, "A", "").getId();
        long b = first.createKb(user, "B", "").getId();
        var results = concurrentlyWithExistingSnapshots(
            () -> first.uploadDocument(user, a, file(600 * 1024)),
            () -> second.uploadDocument(user, b, file(600 * 1024)));
        assertThat(results).containsExactlyInAnyOrder(true, false);
        assertThat(used(user)).isEqualTo(600L * 1024);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM processing_task WHERE user_id=?", Long.class, user)).isEqualTo(1);
        try (var paths = Files.walk(root)) { assertThat(paths.filter(Files::isRegularFile).count()).isEqualTo(1); }
    }

    @Test void knowledgeBaseCountIsAtomicAcrossInstancesAndDeletingUsersCannotAllocate() throws Exception {
        long user = user();
        var first = service(null, 1);
        var second = service(null, 1);
        var results = concurrentlyWithExistingSnapshots(
            () -> first.createKb(user, "A", ""), () -> second.createKb(user, "B", ""));
        assertThat(results).containsExactlyInAnyOrder(true, false);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_base WHERE user_id=?", Long.class, user)).isEqualTo(1);
        jdbc.update("UPDATE user SET status='deleting' WHERE id=?", user);
        assertThatThrownBy(() -> service(null, 10).createKb(user, "C", ""))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("正在删除");
    }

    @Test void allRetainedVersionsCountAndRestoringAnExistingVersionDoesNotAllocateAgain() throws Exception {
        long user = user();
        var service = service(null, 10);
        long kb = service.createKb(user, "History", "").getId();
        var document = service.uploadDocument(user, kb, file(400 * 1024));
        finish(document);
        service.replaceDocument(user, document.getId(), file(400 * 1024));
        finish(document);
        assertThat(used(user)).isEqualTo(800L * 1024);
        assertThatThrownBy(() -> service.replaceDocument(user, document.getId(), file(400 * 1024)))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("配额");
        service.restoreDocumentVersion(user, document.getId(), 1);
        assertThat(used(user)).isEqualTo(800L * 1024);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document_version WHERE document_id=?", Long.class, document.getId())).isEqualTo(2);
        long other = service.createKb(user, "Other", "").getId();
        assertThatThrownBy(() -> service.uploadDocument(user, other, file(300 * 1024)))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("配额");
    }

    @Test void archiveAndNormalCreationShareTheSameQuotaAndOldSnapshotProtection() throws Exception {
        long user = user();
        var knowledge = service(null, 1);
        var workspace = workspace(knowledge);
        var results = concurrentlyWithExistingSnapshots(
            () -> importKnowledgeBases(workspace, user, 1), () -> knowledge.createKb(user, "Concurrent", ""));
        assertThat(results).containsExactlyInAnyOrder(true, false);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_base WHERE user_id=?", Long.class, user)).isEqualTo(1);
    }

    @Test void batchImportRejectsBeforeInsertAndOuterRollbackReleasesTheCapacity() throws Exception {
        long user = user();
        var workspace = workspace(service(null, 1));
        assertThatThrownBy(() -> importKnowledgeBases(workspace, user, 2))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("配额");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_base WHERE user_id=?", Long.class, user)).isZero();
        assertThatThrownBy(() -> new TransactionTemplate(new DataSourceTransactionManager(source)).executeWithoutResult(status -> {
            importKnowledgeBases(workspace, user, 1);
            throw new IllegalStateException("injected failure after archive import");
        })).isInstanceOf(IllegalStateException.class).hasMessageContaining("injected failure");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_base WHERE user_id=?", Long.class, user)).isZero();
        importKnowledgeBases(workspace, user, 1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_base WHERE user_id=?", Long.class, user)).isEqualTo(1);
    }

    private WorkspaceService workspace(KnowledgeService knowledge) {
        var target = new WorkspaceService(jdbc, new ObjectMapper(), new RestTemplate());
        ReflectionTestUtils.setField(target, "knowledgeService", knowledge);
        var proxy = new ProxyFactory(target);
        proxy.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(source), new AnnotationTransactionAttributeSource()));
        return (WorkspaceService) proxy.getProxy();
    }

    private void importKnowledgeBases(WorkspaceService workspace, long user, int count) {
        try {
            workspace.importData(user, Map.of("knowledge_bases", java.util.stream.IntStream.range(0, count)
                .mapToObj(i -> Map.of("id", i + 1, "name", "Imported " + i)).toList()));
        } catch (RuntimeException error) { throw error; }
        catch (Exception error) { throw new IllegalStateException(error); }
    }

    @Test void failureAfterVersionInsertRollsBackBytesAndRemovesFileBeforeRetry() throws Exception {
        long user = user();
        var tasks = mock(ProcessingTaskMapper.class);
        doThrow(new IllegalStateException("injected task persistence failure")).when(tasks).insert(any(ProcessingTask.class));
        var failing = service(tasks, 10);
        long kb = failing.createKb(user, "Rollback", "").getId();
        assertThatThrownBy(() -> failing.uploadDocument(user, kb, file(600 * 1024))).isInstanceOf(IllegalStateException.class);
        assertThat(used(user)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document WHERE kb_id=?", Long.class, kb)).isZero();
        try (var paths = Files.walk(root)) { assertThat(paths.filter(Files::isRegularFile).count()).isZero(); }
        service(null, 10).uploadDocument(user, kb, file(600 * 1024));
        assertThat(used(user)).isEqualTo(600L * 1024);
    }

    private List<Boolean> concurrentlyWithExistingSnapshots(Runnable first, Runnable second) throws Exception {
        var ready = new CountDownLatch(2);
        var pool = Executors.newFixedThreadPool(2);
        try {
            var futures = java.util.stream.Stream.of(first, second).map(action -> pool.submit(() -> {
                try {
                    new TransactionTemplate(new DataSourceTransactionManager(source)).executeWithoutResult(status -> {
                        // Deliberately establish an old MySQL RR snapshot before
                        // either request acquires the shared quota-owner lock.
                        jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document_version", Long.class);
                        ready.countDown();
                        try { assertThat(ready.await(10, TimeUnit.SECONDS)).isTrue(); }
                        catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IllegalStateException(error); }
                        action.run();
                    });
                    return true;
                } catch (IllegalArgumentException error) {
                    assertThat(error).hasMessageContaining("配额");
                    return false;
                }
            })).toList();
            return List.of(futures.get(0).get(30, TimeUnit.SECONDS), futures.get(1).get(30, TimeUnit.SECONDS));
        } finally { pool.shutdownNow(); }
    }

    private KnowledgeService service(ProcessingTaskMapper tasks, int kbLimit) throws Exception {
        var configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.addMapper(KnowledgeBaseMapper.class);
        configuration.addMapper(KnowledgeDocumentMapper.class);
        configuration.addMapper(ProcessingTaskMapper.class);
        var factory = new MybatisSqlSessionFactoryBean();
        factory.setDataSource(source);
        factory.setConfiguration(configuration);
        var session = new SqlSessionTemplate(factory.getObject());
        var target = new KnowledgeService(session.getMapper(KnowledgeBaseMapper.class),
            session.getMapper(KnowledgeDocumentMapper.class), tasks == null ? session.getMapper(ProcessingTaskMapper.class) : tasks,
            new ObjectMapper(), jdbc, new ObjectStorageService("local", root.toString(), "", "", "", "mneme"));
        ReflectionTestUtils.setField(target, "fileStoragePath", root.toString());
        ReflectionTestUtils.setField(target, "tenantStorageQuotaMb", 1L);
        ReflectionTestUtils.setField(target, "tenantKnowledgeBaseQuota", kbLimit);
        var proxy = new ProxyFactory(target);
        proxy.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(source), new AnnotationTransactionAttributeSource()));
        return (KnowledgeService) proxy.getProxy();
    }

    private long user() {
        String username = "quota_" + UUID.randomUUID().toString().replace("-", "");
        jdbc.update("INSERT INTO user(username,password_hash) VALUES(?, 'hash')", username);
        return jdbc.queryForObject("SELECT id FROM user WHERE username=?", Long.class, username);
    }
    private long used(long user) {
        return jdbc.queryForObject("SELECT COALESCE(SUM(v.size_bytes),0) FROM knowledge_document_version v JOIN knowledge_document d ON d.id=v.document_id JOIN knowledge_base k ON k.id=d.kb_id WHERE k.user_id=?", Long.class, user);
    }
    private MockMultipartFile file(int bytes) {
        byte[] content = new byte[bytes]; java.util.Arrays.fill(content, (byte) 'a');
        return new MockMultipartFile("file", "notes.txt", "text/plain", content);
    }
    private void finish(KnowledgeDocument document) {
        jdbc.update("UPDATE processing_task SET status='completed' WHERE aggregate_id=? AND task_type='document_ingest'", document.getId());
        jdbc.update("UPDATE knowledge_document SET status='ready' WHERE id=?", document.getId());
    }
}

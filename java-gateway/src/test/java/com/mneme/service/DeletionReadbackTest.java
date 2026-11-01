package com.mneme.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.KnowledgeBaseMapper;
import com.mneme.mapper.KnowledgeDocumentMapper;
import com.mneme.mapper.ProcessingTaskMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Real Flyway/MySQL transactions and files; independent Agent readback is fault injected. */
@Testcontainers(disabledWithoutDocker = true)
class DeletionReadbackTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("mneme-test-password");
    static JdbcTemplate jdbc;
    static DataSourceTransactionManager manager;
    @TempDir Path root;
    final ObjectMapper json = new ObjectMapper();

    long insert(String sql, Object... args) {
        var keys = new org.springframework.jdbc.support.GeneratedKeyHolder();
        jdbc.update(connection -> {
            var statement = connection.prepareStatement(sql, java.sql.Statement.RETURN_GENERATED_KEYS);
            for (int i = 0; i < args.length; i++) statement.setObject(i + 1, args[i]);
            return statement;
        }, keys);
        return keys.getKey().longValue();
    }

    @BeforeAll static void database() {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        jdbc = new JdbcTemplate(source);
        manager = new DataSourceTransactionManager(source);
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
    }

    final class Fixture implements AutoCloseable {
        final long user, kb, doc, keepUser, keepKb, keepDoc;
        final Path original, version, keep;
        final RestTemplate http = mock(RestTemplate.class);
        final ObjectStorageService storage = spy(new ObjectStorageService("local", root.toString(), "", "", "", "mneme"));
        final KnowledgeDocumentMapper documents = mock(KnowledgeDocumentMapper.class);
        final KnowledgeBaseMapper bases = mock(KnowledgeBaseMapper.class);
        final AtomicReference<Map<String, Object>> agent = new AtomicReference<>(Map.of("qdrant_chunks", 0, "fts_rows", 0, "qdrant_collections", 0));
        final TaskLeaseService leases = new TaskLeaseService(jdbc, manager, 30);
        final ProcessingTaskService service = new ProcessingTaskService(mock(ProcessingTaskMapper.class), documents, bases,
            json, http, new SimpleMeterRegistry(), mock(NotificationService.class), jdbc, storage, leases, mock(PendingMemoryService.class));
        Fixture() throws Exception {
            user = user(); kb = kb(user); keepUser = user(); keepKb = kb(keepUser);
            original = file(user, kb, "current.txt"); version = file(user, kb, "history.txt");
            keep = file(keepUser, keepKb, "keep.txt");
            doc = doc(kb, original); keepDoc = doc(keepKb, keep);
            jdbc.update("INSERT INTO knowledge_document_version(document_id,version_number,file_name,file_path,sha256,size_bytes) VALUES(?,1,'history.txt',?,?,9)", doc, version.toString(), "a".repeat(64));
            jdbc.update("INSERT INTO knowledge_document_tag(document_id,tag) VALUES(?,'keep-until-verified')", doc);
            when(http.getForObject(anyString(), eq(Map.class))).thenAnswer(call -> agent.get());
            when(documents.deleteById(anyLong())).thenAnswer(call -> jdbc.update("DELETE FROM knowledge_document WHERE id=?", call.getArgument(0, Long.class)));
            when(bases.deleteById(anyLong())).thenAnswer(call -> jdbc.update("DELETE FROM knowledge_base WHERE id=?", call.getArgument(0, Long.class)));
            ReflectionTestUtils.setField(service, "pythonAgentUrl", "http://agent");
            ReflectionTestUtils.setField(service, "fileStoragePath", root.toString());
        }
        Path file(long user, long kb, String name) throws Exception {
            var path = root.resolve(user + "/" + kb + "/" + name);
            Files.createDirectories(path.getParent()); Files.writeString(path, "QA fixture"); return path;
        }
        long user() {
            return insert("INSERT INTO user(username,password_hash) VALUES(?,'test')", UUID.randomUUID().toString());
        }
        long kb(long user) {
            return insert("INSERT INTO knowledge_base(user_id,name,status) VALUES(?,'QA','deleting')", user);
        }
        long doc(long kb, Path path) {
            return insert("INSERT INTO knowledge_document(kb_id,file_name,file_path,status) VALUES(?,'QA',?,'deleting')", kb, path.toString());
        }
        ProcessingTask task(boolean wholeKb) throws Exception {
            var task = new ProcessingTask(); task.setTaskId(UUID.randomUUID().toString());
            task.setTaskType(wholeKb ? "knowledge_base_delete" : "document_delete");
            task.setUserId(user); task.setAggregateId(wholeKb ? kb : doc); task.setMaxAttempts(1); task.setAttemptCount(0);
            task.setPayload(json.writeValueAsString(Map.of("user_id", String.valueOf(user), "kb_id", String.valueOf(kb),
                "document_id", "doc_" + doc, "file_path", original.toString())));
            task.setId(insert("INSERT INTO processing_task(task_id,task_type,user_id,aggregate_id,idempotency_key,payload,max_attempts) VALUES(?,?,?,?,?,?,1)",
                task.getTaskId(), task.getTaskType(), user, task.getAggregateId(), task.getTaskId(), task.getPayload()));
            return task;
        }
        void run(ProcessingTask task) {
            try (var lease = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), false)) {
                assertThat(lease).isNotNull(); task.setStatus("processing");
                ReflectionTestUtils.invokeMethod(service, "execute", task, lease);
            }
        }
        void retry(ProcessingTask task) {
            jdbc.update("UPDATE processing_task SET status='pending',attempt_count=0,next_attempt_at=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP()) WHERE id=?", task.getId());
            task.setAttemptCount(0); run(task);
        }
        JsonNode report(ProcessingTask task) throws Exception {
            return json.readTree(jdbc.queryForObject("SELECT cleanup_report FROM processing_task WHERE id=?", String.class, task.getId()));
        }
        void retained(ProcessingTask task) throws Exception {
            assertThat(jdbc.queryForObject("SELECT status FROM processing_task WHERE id=?", String.class, task.getId())).isEqualTo("failed");
            assertThat(report(task).path("status").asText()).isEqualTo("pending");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document WHERE id=?", Integer.class, doc)).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document_version WHERE document_id=?", Integer.class, doc)).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document_tag WHERE document_id=?", Integer.class, doc)).isEqualTo(1);
        }
        void completed(ProcessingTask task) throws Exception {
            assertThat(jdbc.queryForObject("SELECT status FROM processing_task WHERE id=?", String.class, task.getId())).isEqualTo("completed");
            var report = report(task); assertThat(report.path("status").asText()).isEqualTo("verified");
            report.path("counts").forEach(count -> assertThat(count.asLong()).isZero());
            assertThat(report.toString()).doesNotContain("QA fixture", original.toString());
            assertThat(Files.exists(original)).isFalse(); assertThat(Files.exists(version)).isFalse();
            assertThat(Files.readString(keep)).isEqualTo("QA fixture");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document WHERE id=?", Integer.class, keepDoc)).isEqualTo(1);
        }
        public void close() { leases.close(); }
    }

    @Test void positiveResidualOrUnknownAgentReadbackBlocksBothScopesAndRetryRecovers() throws Exception {
        for (boolean wholeKb : new boolean[]{false, true}) {
            for (int residual : new int[]{1, -1}) try (var f = new Fixture()) {
                var task = f.task(wholeKb);
                f.agent.set(Map.of("qdrant_chunks", 0, "fts_rows", residual, "qdrant_collections", 0));
                f.run(task); f.retained(task);
                assertThat(f.report(task).path("counts").path("fts_rows").asLong()).isEqualTo(residual);
                f.agent.set(Map.of("qdrant_chunks", 0, "fts_rows", 0, "qdrant_collections", 0));
                f.retry(task); f.completed(task);
            }
        }
    }

    @Test void missingOrMalformedCountersAreUnknownNotZero() throws Exception {
        for (Object malformed : new Object[]{false, "0", 0.0}) try (var f = new Fixture()) {
            var task = f.task(false); f.agent.set(Map.of("fts_rows", malformed));
            f.run(task); f.retained(task);
            assertThat(f.report(task).path("counts").path("fts_rows").asLong()).isEqualTo(-1);
            assertThat(f.report(task).path("counts").path("qdrant_chunks").asLong()).isEqualTo(-1);
        }
    }

    @Test void agentTransportAndFileReadFailuresRemainIndependentlyVisible() throws Exception {
        try (var f = new Fixture()) {
            when(f.http.getForObject(anyString(), eq(Map.class))).thenThrow(new IllegalStateException("offline"));
            doThrow(new java.io.IOException("denied")).when(f.storage).countLocation(anyString());
            var task = f.task(false); f.run(task); f.retained(task);
            var counts = f.report(task).path("counts");
            assertThat(counts.path("qdrant_chunks").asLong()).isEqualTo(-1);
            assertThat(counts.path("fts_rows").asLong()).isEqualTo(-1);
            assertThat(counts.path("files").asLong()).isEqualTo(-1);
        }
    }

    @Test void successfulFileDeleteCallWithHistoryStillPresentCannotComplete() throws Exception {
        try (var f = new Fixture()) {
            doNothing().when(f.storage).delete(f.version.toString());
            var task = f.task(false); f.run(task); f.retained(task);
            assertThat(f.report(task).path("counts").path("files").asLong()).isEqualTo(1);
            doCallRealMethod().when(f.storage).delete(f.version.toString());
            f.retry(task); f.completed(task);
        }
    }

    @Test void mysqlSilentNoopRollsBackPartialCascadesAndRemainsRetryable() throws Exception {
        for (boolean wholeKb : new boolean[]{false, true}) try (var f = new Fixture()) {
            if (wholeKb) when(f.bases.deleteById(anyLong())).thenAnswer(call -> {
                jdbc.update("DELETE FROM knowledge_document_version WHERE document_id=?", f.doc); return 0;
            });
            else when(f.documents.deleteById(anyLong())).thenAnswer(call -> {
                jdbc.update("DELETE FROM knowledge_document_version WHERE document_id=?", f.doc); return 0;
            });
            var task = f.task(wholeKb); f.run(task); f.retained(task);
            assertThat(f.report(task).path("counts").path("mysql_rows").asLong()).isGreaterThan(0);
            when(f.documents.deleteById(anyLong())).thenAnswer(call -> jdbc.update("DELETE FROM knowledge_document WHERE id=?", f.doc));
            when(f.bases.deleteById(anyLong())).thenAnswer(call -> jdbc.update("DELETE FROM knowledge_base WHERE id=?", f.kb));
            f.retry(task); f.completed(task);
        }
    }

    @Test void knowledgeBaseDeletesAllVersionLocationsEvenOutsideItsDirectory() throws Exception {
        try (var f = new Fixture()) {
            var detached = root.resolve("shared-history.txt"); Files.writeString(detached, "QA fixture");
            jdbc.update("UPDATE knowledge_document_version SET file_path=? WHERE document_id=?", detached.toString(), f.doc);
            var task = f.task(true); f.run(task); f.completed(task);
            assertThat(Files.exists(detached)).isFalse();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_base WHERE id=?", Integer.class, f.kb)).isZero();
            verify(f.storage).delete(detached.toString());
        }
    }
}

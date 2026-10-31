package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.KnowledgeBase;
import com.mneme.entity.KnowledgeDocument;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.KnowledgeBaseMapper;
import com.mneme.mapper.KnowledgeDocumentMapper;
import com.mneme.mapper.ProcessingTaskMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class KnowledgeServiceSecurityTest {
    @TempDir Path root;

    @Test void interruptedCopyClosesStreamAndRemovesPartialFileBeforeAnyDatabaseWrite() throws Exception {
        Fixture fixture = fixture();
        var calls = new java.util.concurrent.atomic.AtomicInteger();
        var closed = new java.util.concurrent.atomic.AtomicBoolean();
        var file = new MockMultipartFile("file", "interrupted.txt", "text/plain", "hello".getBytes()) {
            @Override public java.io.InputStream getInputStream() {
                // Validation reads the header first; copying then fails mid-file.
                if (calls.incrementAndGet() == 1) return new java.io.ByteArrayInputStream("hello".getBytes());
                return new java.io.InputStream() {
                    int count;
                    @Override public int read() throws java.io.IOException {
                        if (count++ >= 2) throw new java.io.IOException("connection interrupted");
                        return 'a';
                    }
                    @Override public void close() { closed.set(true); }
                };
            }
        };
        assertThrows(IllegalStateException.class, () -> fixture.service.uploadDocument(7L, 3L, file));
        assertTrue(closed.get());
        try (var paths = java.nio.file.Files.walk(root)) {
            assertEquals(0, paths.filter(java.nio.file.Files::isRegularFile).count());
        }
        verify(fixture.documents, never()).insert(any(KnowledgeDocument.class));
        verify(fixture.tasks, never()).insert(any(ProcessingTask.class));
    }

    @Test
    void rejectsPdfWhoseContentDoesNotMatchExtension() {
        Fixture fixture = fixture();
        MockMultipartFile file = new MockMultipartFile(
            "file", "attack.pdf", "application/pdf", "MZ executable".getBytes());

        assertThrows(IllegalArgumentException.class, () -> fixture.service.uploadDocument(7L, 3L, file));
        verify(fixture.documents, never()).insert(any(KnowledgeDocument.class));
    }

    @Test
    void uploadCreatesHashAndSizeBackedInitialVersion() {
        Fixture fixture = fixture();
        doAnswer(invocation -> {
            KnowledgeDocument document = invocation.getArgument(0);
            document.setId(42L);
            return 1;
        }).when(fixture.documents).insert(any(KnowledgeDocument.class));
        when(fixture.jdbc.queryForObject(
            contains("MAX(version_number)"), any(org.springframework.jdbc.core.RowMapper.class), eq(42L))).thenReturn(1);
        MockMultipartFile file = new MockMultipartFile(
            "file", "notes.txt", "text/plain", "hello".getBytes());

        KnowledgeDocument document = fixture.service.uploadDocument(7L, 3L, file);

        assertEquals(42L, document.getId());
        assertEquals("parsing", document.getStatus());
        verify(fixture.jdbc).update(
            contains("INSERT INTO knowledge_document_version"),
            eq(42L), eq(1), eq("notes.txt"), anyString(), anyString(), eq(5L));
        verify(fixture.tasks).insert(any(ProcessingTask.class));
    }

    private Fixture fixture() {
        KnowledgeBaseMapper bases = mock(KnowledgeBaseMapper.class);
        KnowledgeDocumentMapper documents = mock(KnowledgeDocumentMapper.class);
        ProcessingTaskMapper tasks = mock(ProcessingTaskMapper.class);
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        KnowledgeBase base = new KnowledgeBase(); base.setId(3L); base.setUserId(7L); base.setStatus("active");
        when(bases.selectById(3L)).thenReturn(base);
        when(jdbc.queryForList("SELECT status FROM user WHERE id=? FOR UPDATE", String.class, 7L)).thenReturn(java.util.List.of("active"));
        ObjectStorageService storage = new ObjectStorageService(
            "local", root.toString(), "", "", "", "mneme");
        KnowledgeService service = new KnowledgeService(
            bases, documents, tasks, new ObjectMapper(), jdbc, storage);
        ReflectionTestUtils.setField(service, "fileStoragePath", root.toString());
        ReflectionTestUtils.setField(service, "tenantStorageQuotaMb", 100L);
        ReflectionTestUtils.setField(service, "tenantKnowledgeBaseQuota", 100);
        return new Fixture(service, documents, tasks, jdbc);
    }

    @Test void indexRepairIsOwnedAndDurableWithoutSourceFile() {
        Fixture f = fixture();
        KnowledgeDocument document = new KnowledgeDocument();
        document.setId(42L); document.setKbId(3L); document.setStatus("index_pending");
        document.setFilePath("missing-source.txt"); document.setFileName("notes.txt");
        document.setParseReport("{\"vector_index_version\":\"" + "a".repeat(64) + "\"}");
        when(f.documents.selectById(42L)).thenReturn(document);
        assertThrows(IllegalArgumentException.class, () -> f.service.repairDocumentIndex(8L, 42L));
        f.service.repairDocumentIndex(7L, 42L);
        verify(f.tasks).insert(argThat((ProcessingTask task) -> "document_index_repair".equals(task.getTaskType())
            && task.getPayload().contains("expected_version") && task.getUserId().equals(7L)));
        assertEquals("index_repairing", document.getStatus());
        assertNotNull(document.getParseTaskId());
        when(f.jdbc.queryForList(contains("task_type IN"), eq(42L))).thenReturn(java.util.List.of(java.util.Map.of("task_id", document.getParseTaskId())));
        assertThrows(IllegalArgumentException.class, () -> f.service.deleteDocument(7L, 42L));
    }

    @Test void indexRepairRejectsMissingOrInvalidReportBeforeCreatingTask() {
        Fixture f = fixture();
        KnowledgeDocument document = new KnowledgeDocument();
        document.setId(42L); document.setKbId(3L); document.setStatus("index_pending");
        when(f.documents.selectById(42L)).thenReturn(document);
        for (String report : java.util.Arrays.asList(null, "", "null", "{}", "{broken")) {
            document.setParseReport(report);
            assertThrows(IllegalArgumentException.class, () -> f.service.repairDocumentIndex(7L, 42L));
        }
        verifyNoInteractions(f.tasks);
        assertEquals("index_pending", document.getStatus());
    }

    private record Fixture(
        KnowledgeService service,
        KnowledgeDocumentMapper documents,
        ProcessingTaskMapper tasks,
        JdbcTemplate jdbc
    ) { }
}

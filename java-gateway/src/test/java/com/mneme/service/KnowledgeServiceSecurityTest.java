package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.KnowledgeBase;
import com.mneme.entity.KnowledgeDocument;
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

    @Test
    void rejectsPdfWhoseContentDoesNotMatchExtension() {
        Fixture fixture = fixture();
        MockMultipartFile file = new MockMultipartFile(
            "file", "attack.pdf", "application/pdf", "MZ executable".getBytes());

        assertThrows(IllegalArgumentException.class, () -> fixture.service.uploadDocument(7L, 3L, file));
        verify(fixture.documents, never()).insert(any());
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
            contains("MAX(version_number)"), eq(Integer.class), eq(42L))).thenReturn(1);
        MockMultipartFile file = new MockMultipartFile(
            "file", "notes.txt", "text/plain", "hello".getBytes());

        KnowledgeDocument document = fixture.service.uploadDocument(7L, 3L, file);

        assertEquals(42L, document.getId());
        assertEquals("parsing", document.getStatus());
        verify(fixture.jdbc).update(
            contains("INSERT INTO knowledge_document_version"),
            eq(42L), eq(1), eq("notes.txt"), anyString(), anyString(), eq(5L));
        verify(fixture.tasks).insert(any());
    }

    private Fixture fixture() {
        KnowledgeBaseMapper bases = mock(KnowledgeBaseMapper.class);
        KnowledgeDocumentMapper documents = mock(KnowledgeDocumentMapper.class);
        ProcessingTaskMapper tasks = mock(ProcessingTaskMapper.class);
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        KnowledgeBase base = new KnowledgeBase(); base.setId(3L); base.setUserId(7L); base.setStatus("active");
        when(bases.selectById(3L)).thenReturn(base);
        when(jdbc.queryForObject(contains("SUM(v.size_bytes)"), eq(Long.class), eq(7L))).thenReturn(0L);
        ObjectStorageService storage = new ObjectStorageService(
            "local", root.toString(), "", "", "", "mneme");
        KnowledgeService service = new KnowledgeService(
            bases, documents, tasks, new ObjectMapper(), jdbc, storage);
        ReflectionTestUtils.setField(service, "fileStoragePath", root.toString());
        ReflectionTestUtils.setField(service, "tenantStorageQuotaMb", 100L);
        ReflectionTestUtils.setField(service, "tenantKnowledgeBaseQuota", 100);
        return new Fixture(service, documents, tasks, jdbc);
    }

    private record Fixture(
        KnowledgeService service,
        KnowledgeDocumentMapper documents,
        ProcessingTaskMapper tasks,
        JdbcTemplate jdbc
    ) { }
}

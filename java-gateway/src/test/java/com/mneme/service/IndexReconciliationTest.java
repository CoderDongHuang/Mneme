package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.internal.IngestionResult;
import com.mneme.entity.KnowledgeDocument;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.KnowledgeBaseMapper;
import com.mneme.mapper.KnowledgeDocumentMapper;
import com.mneme.mapper.ProcessingTaskMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class IndexReconciliationTest {
    static final String VERSION = "a".repeat(64);
    final ObjectMapper json = new ObjectMapper();
    final KnowledgeDocumentMapper documents = mock(KnowledgeDocumentMapper.class);
    final RestTemplate http = mock(RestTemplate.class);
    final ObjectStorageService storage = mock(ObjectStorageService.class);
    final ProcessingTaskService service = new ProcessingTaskService(mock(ProcessingTaskMapper.class), documents,
        mock(KnowledgeBaseMapper.class), json, http, new SimpleMeterRegistry(), mock(NotificationService.class),
        mock(JdbcTemplate.class), storage, mock(TaskLeaseService.class));
    final TaskLeaseService.Lease lease = mock(TaskLeaseService.Lease.class);
    final KnowledgeDocument document = new KnowledgeDocument();
    final ProcessingTask task = new ProcessingTask();

    IndexReconciliationTest() throws Exception {
        ReflectionTestUtils.setField(service, "pythonAgentUrl", "http://agent");
        task.setTaskId("repair-7"); task.setAggregateId(7L); task.setTaskType("document_index_repair");
        task.setPayload(json.writeValueAsString(Map.of("user_id", "1", "kb_id", "2", "document_id", "doc_7", "expected_version", VERSION)));
        document.setId(7L); document.setParseTaskId(task.getTaskId()); document.setChunkCount(3);
        document.setParseReport(json.writeValueAsString(Map.of("vector_index_version", VERSION,
            "warnings", List.of(Map.of("page", 2, "code", "no_text")), "pages", List.of(Map.of("page", 1, "text", "source preview")),
            "content_sha256", "hash", "index_error", "lexical_index_pending")));
        when(documents.selectById(7L)).thenReturn(document);
        when(lease.write(any())).thenAnswer(invocation -> {
            java.util.function.Function<Map<String, Object>, Object> change = invocation.getArgument(0);
            return change.apply(Map.of("status", "processing"));
        });
    }

    @Test void repairPreservesParseWarningsAndPreviewWithoutMaterializingFile() throws Exception {
        when(http.postForObject(anyString(), any(), eq(IngestionResult.class))).thenReturn(new IngestionResult("done", "doc_7", 3,
            Map.of("vector_index_version", VERSION, "lexical_index_version", VERSION, "index_status", "ready")));
        ReflectionTestUtils.invokeMethod(service, "repairIndex", task, lease);
        assertEquals("partial", document.getStatus()); // A lexical repair cannot fix OCR warnings.
        assertEquals(3, document.getChunkCount());
        assertTrue(document.getParseReport().contains("source preview"));
        assertTrue(document.getParseReport().contains("no_text"));
        assertFalse(document.getParseReport().contains("index_error"));
        assertEquals("completed", task.getStatus());
        verifyNoInteractions(storage);
        verify(http).postForObject(eq("http://agent/api/v1/knowledge/internal/reconcile-index"),
            argThat((Object value) -> value instanceof Map<?, ?> request && VERSION.equals(request.get("expected_version"))), eq(IngestionResult.class));
    }

    @Test void mismatchNeverPublishesReady() {
        when(http.postForObject(anyString(), any(), eq(IngestionResult.class))).thenReturn(new IngestionResult("done", "doc_7", 3,
            Map.of("vector_index_version", VERSION, "lexical_index_version", "b".repeat(64), "index_status", "ready")));
        assertThrows(IllegalStateException.class, () -> ReflectionTestUtils.invokeMethod(service, "repairIndex", task, lease));
        verify(documents, never()).updateById(any(KnowledgeDocument.class));
    }

    @Test void failedRepairKeepsVectorAvailabilityAndCanBeRetried() {
        task.setAttemptCount(2); task.setMaxAttempts(3);
        ReflectionTestUtils.invokeMethod(service, "retryOrFailLocked", task, lease, new IllegalStateException("FTS unavailable"));
        assertEquals("failed", task.getStatus());
        assertEquals("index_pending", document.getStatus());
        assertEquals(3, document.getChunkCount());
        assertTrue(document.getErrorMessage().contains("词法索引待修复"));
    }

    @Test void denseOnlyResultCannotBecomeReadyEvenIfAgentSaysDone() throws Exception {
        var result = new IngestionResult("done", "doc_7", 3, Map.of("vector_index_version", VERSION, "index_status", "pending"));
        ReflectionTestUtils.invokeMethod(service, "persistIngestion", task, result, lease);
        assertEquals("index_pending", document.getStatus());
        assertEquals("completed", task.getStatus());
    }

    @Test void obsoleteRepairCannotOverwriteNewTask() {
        document.setParseTaskId("new-task");
        when(http.postForObject(anyString(), any(), eq(IngestionResult.class))).thenReturn(new IngestionResult("done", "doc_7", 3,
            Map.of("vector_index_version", VERSION, "lexical_index_version", VERSION, "index_status", "ready")));
        assertThrows(IllegalStateException.class, () -> ReflectionTestUtils.invokeMethod(service, "repairIndex", task, lease));
        verify(documents, never()).updateById(any(KnowledgeDocument.class));
    }
}

package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.internal.IngestionResult;
import com.mneme.dto.internal.IngestionRequest;
import com.mneme.entity.KnowledgeDocument;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.KnowledgeBaseMapper;
import com.mneme.mapper.KnowledgeDocumentMapper;
import com.mneme.mapper.ProcessingTaskMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ProcessingTaskIngestionTest {
    @Test void cancelledIngestionUsesRetryableCleanupInsteadOfPermanentDocumentDeletion() {
        var http = mock(RestTemplate.class);
        var service = new ProcessingTaskService(mock(ProcessingTaskMapper.class), mock(KnowledgeDocumentMapper.class),
            mock(KnowledgeBaseMapper.class), new ObjectMapper(), http, new SimpleMeterRegistry(),
            mock(NotificationService.class), mock(JdbcTemplate.class), mock(ObjectStorageService.class), mock(TaskLeaseService.class));
        ReflectionTestUtils.setField(service, "pythonAgentUrl", "http://agent");
        var task = new ProcessingTask(); task.setTaskType("document_ingest"); task.setTaskId("cancelled");
        task.setPayload("{\"user_id\":\"1\",\"kb_id\":\"2\",\"document_id\":\"doc_7\"}");
        var lease = mock(TaskLeaseService.Lease.class);
        when(lease.write(any())).thenAnswer(invocation -> {
            java.util.function.Function<Map<String, Object>, Object> change = invocation.getArgument(0);
            return change.apply(Map.of("status", "cancelling"));
        });
        assertEquals(Boolean.TRUE, ReflectionTestUtils.invokeMethod(service, "finishCancelled", task, lease));
        verify(http).delete("http://agent/api/v1/knowledge/internal/cancelled-documents/doc_7?user_id=1&kb_id=2");
        verify(lease).finish("cancelled", null);
    }

    static java.util.stream.Stream<Object> invalidGenerations() {
        return java.util.stream.Stream.of(null, 1L, 3L, "2", true, 2.5, new java.math.BigDecimal("9223372036854775808"));
    }

    @ParameterizedTest @MethodSource("invalidGenerations")
    void obsoleteMissingOrMalformedGenerationNeverPublishes(Object generation) {
        var documents = mock(KnowledgeDocumentMapper.class);
        var tasks = mock(ProcessingTaskMapper.class);
        var jdbc = mock(JdbcTemplate.class);
        var service = new ProcessingTaskService(tasks, documents, mock(KnowledgeBaseMapper.class), new ObjectMapper(),
            mock(RestTemplate.class), new SimpleMeterRegistry(), mock(NotificationService.class), jdbc,
            mock(ObjectStorageService.class), mock(TaskLeaseService.class));
        var task = new ProcessingTask(); task.setAggregateId(7L); task.setTaskId("current");
        var document = new KnowledgeDocument(); document.setIndexGeneration(2L); document.setParseTaskId("current"); document.setStatus("processing");
        when(documents.selectForUpdate(7L)).thenReturn(document);
        var report = new java.util.HashMap<String,Object>(); report.put("index_generation", generation);
        assertThrows(RuntimeException.class, () -> ReflectionTestUtils.invokeMethod(service, "persistIngestion", task,
            new IngestionResult("done", "doc_7", 9, report), mock(TaskLeaseService.Lease.class)));
        assertEquals("processing", document.getStatus());
        verify(documents, never()).updateById(any(KnowledgeDocument.class));
        verifyNoInteractions(tasks, jdbc);
    }

    @Test void deletedWrongDocumentAndReplacedTaskCannotPublishEvenWithMatchingGeneration() {
        for (String state : List.of("absent", "deleting", "wrong_document", "new_task")) {
            var documents = mock(KnowledgeDocumentMapper.class);
            var tasks = mock(ProcessingTaskMapper.class);
            var service = new ProcessingTaskService(tasks, documents, mock(KnowledgeBaseMapper.class), new ObjectMapper(),
                mock(RestTemplate.class), new SimpleMeterRegistry(), mock(NotificationService.class), mock(JdbcTemplate.class),
                mock(ObjectStorageService.class), mock(TaskLeaseService.class));
            var task = new ProcessingTask(); task.setAggregateId(7L); task.setTaskId("current");
            var document = new KnowledgeDocument(); document.setIndexGeneration(2L);
            document.setParseTaskId(state.equals("new_task") ? "successor" : "current");
            document.setStatus(state.equals("deleting") ? "deleting" : "processing");
            when(documents.selectForUpdate(7L)).thenReturn(state.equals("absent") ? null : document);
            var result = new IngestionResult("done", state.equals("wrong_document") ? "doc_8" : "doc_7", 9, Map.of("index_generation", 2));
            assertThrows(RuntimeException.class, () -> ReflectionTestUtils.invokeMethod(service, "persistIngestion", task, result, mock(TaskLeaseService.Lease.class)), state);
            verify(documents, never()).updateById(any(KnowledgeDocument.class));
            verifyNoInteractions(tasks);
        }
    }

    @Test
    void partialIngestionPersistsDiagnosticsInsteadOfReportingReady() throws Exception {
        var documents = mock(KnowledgeDocumentMapper.class);
        var http = mock(RestTemplate.class);
        var storage = mock(ObjectStorageService.class);
        var service = new ProcessingTaskService(mock(ProcessingTaskMapper.class), documents,
            mock(KnowledgeBaseMapper.class), new ObjectMapper(), http, new SimpleMeterRegistry(),
            mock(NotificationService.class), mock(JdbcTemplate.class), storage, mock(TaskLeaseService.class));
        ReflectionTestUtils.setField(service, "pythonAgentUrl", "http://agent");
        var task = new ProcessingTask();
        task.setAggregateId(7L);
        task.setPayload("{\"file_path\":\"source\",\"user_id\":\"1\",\"kb_id\":\"2\",\"document_id\":\"7\",\"source_name\":\"学习资料.pdf\"}");
        when(storage.materialize("source")).thenReturn(Path.of("source.pdf"));
        var document = new KnowledgeDocument();
        when(documents.selectForUpdate(7L)).thenReturn(document);
        when(documents.advanceGeneration(7L, 0L)).thenAnswer(call -> { document.setIndexGeneration(1L); return 1; });
        var report = Map.<String,Object>of("index_generation", 1, "warnings", List.of(Map.of("page", 2, "code", "no_text")));
        when(http.postForObject(anyString(), any(), eq(IngestionResult.class)))
            .thenReturn(new IngestionResult("partial", "doc_7", 3, report));
        var lease = mock(TaskLeaseService.Lease.class);
        when(lease.write(any())).thenAnswer(invocation -> {
            java.util.function.Function<Map<String, Object>, Object> change = invocation.getArgument(0);
            return change.apply(Map.of("status", "processing"));
        });
        ReflectionTestUtils.invokeMethod(service, "ingest", task, lease);
        verify(http).postForObject(anyString(), argThat((Object value) -> value instanceof IngestionRequest request
            && request.indexGeneration() == 1 && "学习资料.pdf".equals(request.sourceName()) && "source.pdf".equals(request.filePath())), eq(IngestionResult.class));
        assertEquals("partial", document.getStatus());
        assertEquals(3, document.getChunkCount());
        assertTrue(document.getParseReport().contains("no_text"));
        assertNotNull(document.getErrorMessage());
        verify(documents).advanceGeneration(7L, 0L);
        verify(documents).updateById(document);
    }
}

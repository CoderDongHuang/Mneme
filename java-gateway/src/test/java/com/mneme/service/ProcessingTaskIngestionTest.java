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
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ProcessingTaskIngestionTest {
    @Test
    void partialIngestionPersistsDiagnosticsInsteadOfReportingReady() throws Exception {
        var documents = mock(KnowledgeDocumentMapper.class);
        var http = mock(RestTemplate.class);
        var storage = mock(ObjectStorageService.class);
        var service = new ProcessingTaskService(mock(ProcessingTaskMapper.class), documents,
            mock(KnowledgeBaseMapper.class), new ObjectMapper(), http, new SimpleMeterRegistry(),
            mock(NotificationService.class), mock(JdbcTemplate.class), storage);
        ReflectionTestUtils.setField(service, "pythonAgentUrl", "http://agent");
        var task = new ProcessingTask();
        task.setAggregateId(7L);
        task.setPayload("{\"file_path\":\"source\",\"user_id\":\"1\",\"kb_id\":\"2\",\"document_id\":\"7\"}");
        when(storage.materialize("source")).thenReturn(Path.of("source.pdf"));
        var document = new KnowledgeDocument();
        when(documents.selectById(7L)).thenReturn(document);
        var report = Map.<String,Object>of("warnings", List.of(Map.of("page", 2, "code", "no_text")));
        when(http.postForObject(anyString(), any(), eq(IngestionResult.class)))
            .thenReturn(new IngestionResult("partial", "7", 3, report));
        ReflectionTestUtils.invokeMethod(service, "ingest", task);
        assertEquals("partial", document.getStatus());
        assertEquals(3, document.getChunkCount());
        assertTrue(document.getParseReport().contains("no_text"));
        assertNotNull(document.getErrorMessage());
        verify(documents).updateById(document);
    }
}

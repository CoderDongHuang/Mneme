package com.mneme.service;

import com.mneme.dto.internal.MemoryContracts;
import com.mneme.exception.RequestInProgressException;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestTemplate;
import java.nio.charset.StandardCharsets;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import com.mneme.controller.MemoryController;
import com.mneme.controller.GlobalExceptionHandler;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class MemoryServiceTest {
    @ParameterizedTest
    @ValueSource(strings = {"read", "write"})
    void storageOutageRemainsRetryableAcrossHttpBoundary(String operation) throws Exception {
        RestTemplate client = new RestTemplate();
        var server = MockRestServiceServer.createServer(client);
        MemoryService service = new MemoryService(client);
        ReflectionTestUtils.setField(service, "pythonAgentUrl", "http://agent");
        server.expect(requestTo("http://agent/api/v1/memory/" + operation))
            .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE).contentType(MediaType.APPLICATION_JSON)
                .body("{\"detail\":\"PRIVATE_MEMORY_STORAGE_CANARY\"}"));
        var mvc = MockMvcBuilders.standaloneSetup(new MemoryController(service, mock(PendingMemoryService.class)))
            .setControllerAdvice(new GlobalExceptionHandler()).build();
        var request = operation.equals("read") ? get("/api/v1/memory")
            : post("/api/v1/memory/write").contentType(MediaType.APPLICATION_JSON)
                .content("{\"category\":\"progress\",\"content\":\"chapter/section\"}");
        mvc.perform(request.requestAttr("userId", 7L)).andExpect(status().isServiceUnavailable())
            .andExpect(jsonPath("$.code").value(503))
            .andExpect(jsonPath("$.message").value("长期记忆暂时无法读取，请稍后重试"));
        server.verify();
    }

    @Test
    void indexConflictHasActionableMessageWithoutInternalResponseDetails() {
        RestTemplate client = mock(RestTemplate.class);
        MemoryService service = new MemoryService(client);
        ReflectionTestUtils.setField(service, "pythonAgentUrl", "http://agent");
        when(client.postForObject(anyString(), any(), eq(MemoryContracts.OperationResult.class)))
            .thenThrow(HttpClientErrorException.create(HttpStatus.CONFLICT, "Conflict", new HttpHeaders(),
                "private upstream details".getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8));
        var error = assertThrows(RequestInProgressException.class,
            () -> service.writeMemory("7", "preference", "资料优先", ""));
        assertTrue(error.getMessage().contains("索引需要迁移"));
        assertFalse(error.getMessage().contains("private"));
    }
}

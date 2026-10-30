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

class MemoryServiceTest {
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

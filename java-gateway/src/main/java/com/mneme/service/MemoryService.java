package com.mneme.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.client.HttpClientErrorException;
import com.mneme.exception.RequestInProgressException;
import com.mneme.dto.internal.MemoryContracts;

import java.util.List;

@Service
public class MemoryService {
    private final RestTemplate restTemplate;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    public MemoryService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public MemoryContracts.ReadResult readMemory(String userId, List<String> memoryTypes) {
        return post(
            "/api/v1/memory/read",
            new MemoryContracts.ReadRequest(userId, memoryTypes),
            MemoryContracts.ReadResult.class
        );
    }

    public MemoryContracts.OperationResult writeMemory(
        String userId, String category, String content, String topic
    ) {
        if (category == null || content == null || content.isBlank()) {
            throw new IllegalArgumentException("记忆类别和内容不能为空");
        }
        MemoryContracts.Entry entry = new MemoryContracts.Entry(
            category, content.trim(), topic == null ? "" : topic.trim()
        );
        return post(
            "/api/v1/memory/write",
            new MemoryContracts.WriteRequest(userId, entry),
            MemoryContracts.OperationResult.class
        );
    }

    public MemoryContracts.OperationResult confirmMemory(MemoryContracts.ConfirmRequest request) {
        return post("/api/v1/memory/confirm", request, MemoryContracts.OperationResult.class);
    }

    private <T> T post(String path, Object body, Class<T> responseType) {
        T response;
        try {
            response = restTemplate.postForObject(pythonAgentUrl + path, body, responseType);
        } catch (HttpClientErrorException.Conflict exception) {
            throw new RequestInProgressException("长期记忆索引需要迁移，请联系管理员重建索引；仍可查看、导出或删除记忆");
        }
        if (response == null) {
            throw new IllegalStateException("Python Agent 返回空响应");
        }
        return response;
    }
}

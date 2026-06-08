package com.mneme.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

@Service
public class MemoryService {

    private final RestTemplate restTemplate;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    public MemoryService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public Map<String, Object> readMemory(String userId, String[] memoryTypes) {
        return restTemplate.postForObject(
            pythonAgentUrl + "/api/v1/memory/read",
            Map.of("user_id", userId, "memory_types", memoryTypes),
            Map.class
        );
    }

    public Map<String, Object> writeMemory(String userId, String category, String content) {
        return restTemplate.postForObject(
            pythonAgentUrl + "/api/v1/memory/write",
            Map.of("user_id", userId, "entry", Map.of("category", category, "content", content)),
            Map.class
        );
    }
}

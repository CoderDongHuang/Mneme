package com.mneme.service;

import com.mneme.dto.ChatRequest;
import com.mneme.dto.ChatResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class ChatService {

    private final RestTemplate restTemplate;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    public ChatService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public ChatResponse chat(ChatRequest request) {
        int maxRetries = 2;
        for (int i = 0; i <= maxRetries; i++) {
            try {
                return restTemplate.postForObject(
                    pythonAgentUrl + "/api/v1/chat",
                    request,
                    ChatResponse.class
                );
            } catch (Exception e) {
                if (i == maxRetries) {
                    throw new RuntimeException("Python Agent 调用失败，已重试 " + maxRetries + " 次", e);
                }
                // 重试前等待
                try { Thread.sleep(1000 * (i + 1)); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); }
            }
        }
        throw new RuntimeException("Python Agent 调用失败");
    }
}
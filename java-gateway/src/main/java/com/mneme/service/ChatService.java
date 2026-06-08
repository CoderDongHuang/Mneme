package com.mneme.service;

import com.mneme.dto.ChatRequest;
import com.mneme.dto.ChatResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.concurrent.TimeUnit;

@Service
public class ChatService {

    private final RestTemplate restTemplate;
    private final RedisTemplate<String, Object> redisTemplate;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    public ChatService(RestTemplate restTemplate, RedisTemplate<String, Object> redisTemplate) {
        this.restTemplate = restTemplate;
        this.redisTemplate = redisTemplate;
    }

    public ChatResponse chat(ChatRequest request) {
        // 缓存用户画像（热点记忆）
        String cacheKey = "user_profile:" + request.getUserId();
        Object cached = redisTemplate.opsForValue().get(cacheKey);
        if (cached != null) {
            // 使用缓存的用户画像（阶段四可优化为直接返回缓存结果）
        }

        int maxRetries = 2;
        for (int i = 0; i <= maxRetries; i++) {
            try {
                ChatResponse response = restTemplate.postForObject(
                    pythonAgentUrl + "/api/v1/chat",
                    request,
                    ChatResponse.class
                );
                // 缓存用户画像（30 分钟过期）
                if (response != null) {
                    redisTemplate.opsForValue().set(cacheKey, response.getAnswer(), 30, TimeUnit.MINUTES);
                }
                return response;
            } catch (Exception e) {
                if (i == maxRetries) {
                    throw new RuntimeException("Python Agent 调用失败，已重试 " + maxRetries + " 次", e);
                }
                try { Thread.sleep(1000 * (i + 1)); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); }
            }
        }
        throw new RuntimeException("Python Agent 调用失败");
    }
}

package com.mneme.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.ChatRequest;
import com.mneme.dto.ChatResponse;
import com.mneme.entity.ChatMessage;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

@Service
public class ChatService {
    private static final Logger log = LoggerFactory.getLogger(ChatService.class);

    private final RestTemplate restTemplate;
    private final RedisTemplate<String, Object> redisTemplate;
    private final ObjectMapper objectMapper;
    private final ChatSessionService sessionService;
    private final PendingMemoryService pendingMemoryService;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    @Value("${mneme.internal-service-token}")
    private String internalServiceToken;

    public ChatService(
        RestTemplate restTemplate,
        RedisTemplate<String, Object> redisTemplate,
        ObjectMapper objectMapper,
        ChatSessionService sessionService,
        PendingMemoryService pendingMemoryService
    ) {
        this.restTemplate = restTemplate;
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.sessionService = sessionService;
        this.pendingMemoryService = pendingMemoryService;
    }

    public ChatResponse chat(Long userId, ChatRequest request) {
        Long sessionId = parseSessionId(request.getSessionId());
        sessionService.appendMessage(userId, sessionId, request.getRequestId(), "user", request.getMessage(), "completed");
        ChatMessage assistant = sessionService.appendMessage(
            userId, sessionId, request.getRequestId(), "assistant", "", "processing"
        );
        ChatResponse response;
        try {
            response = restTemplate.postForObject(
                pythonAgentUrl + "/api/v1/chat", request, ChatResponse.class
            );
            if (response == null) throw new IllegalStateException("Python Agent 返回空响应");
            sessionService.finishMessage(assistant.getId(), response.getAnswer());
            pendingMemoryService.store(userId, sessionId, assistant.getId(), response.getPendingMemories());
        } catch (Exception error) {
            sessionService.failMessage(assistant.getId(), "", error.getClass().getSimpleName());
            throw error;
        }
        try {
            redisTemplate.opsForValue().set(
                "mneme:last-answer:" + userId, response.getAnswer(), 30, TimeUnit.MINUTES
            );
        } catch (Exception error) {
            log.debug("Redis 缓存不可用: {}", error.getMessage());
        }
        return response;
    }

    public StreamingResponseBody stream(Long userId, ChatRequest request) {
        Long sessionId = parseSessionId(request.getSessionId());
        sessionService.appendMessage(userId, sessionId, request.getRequestId(), "user", request.getMessage(), "completed");
        ChatMessage assistant = sessionService.appendMessage(
            userId, sessionId, request.getRequestId(), "assistant", "", "processing"
        );
        return output -> proxyStream(userId, sessionId, assistant.getId(), request, output);
    }

    private void proxyStream(Long userId, Long sessionId, Long assistantMessageId, ChatRequest request, OutputStream output) {
        HttpURLConnection connection = null;
        StringBuilder answer = new StringBuilder();
        try {
            connection = (HttpURLConnection) URI.create(
                pythonAgentUrl + "/api/v1/chat/stream"
            ).toURL().openConnection();
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("X-Internal-Service-Token", internalServiceToken);
            connection.setConnectTimeout(10_000);
            connection.setReadTimeout(180_000);
            try (OutputStream requestBody = connection.getOutputStream()) {
                objectMapper.writeValue(requestBody, request);
            }
            if (connection.getResponseCode() != 200) {
                throw new IllegalStateException("Python Agent 返回 " + connection.getResponseCode());
            }

            String eventType = "message";
            try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8)
            )) {
                String line;
                while ((line = reader.readLine()) != null) {
                    output.write((line + "\n").getBytes(StandardCharsets.UTF_8));
                    output.flush();
                    if (line.startsWith("event: ")) {
                        eventType = line.substring(7).trim();
                    } else if (line.startsWith("data: ") && "token".equals(eventType)) {
                        JsonNode payload = objectMapper.readTree(line.substring(6));
                        answer.append(payload.path("content").asText(""));
                    } else if (line.startsWith("data: ") && "memory".equals(eventType)) {
                        JsonNode payload = objectMapper.readTree(line.substring(6));
                        java.util.List<ChatResponse.PendingMemory> pending = objectMapper.convertValue(
                            payload.path("pending"),
                            objectMapper.getTypeFactory().constructCollectionType(
                                java.util.List.class, ChatResponse.PendingMemory.class
                            )
                        );
                        pendingMemoryService.store(userId, sessionId, assistantMessageId, pending);
                    }
                }
            }
            if (!answer.isEmpty()) {
                sessionService.finishMessage(assistantMessageId, answer.toString());
            } else {
                sessionService.failMessage(assistantMessageId, "", "EMPTY_RESPONSE");
            }
        } catch (Exception error) {
            sessionService.failMessage(assistantMessageId, answer.toString(), error.getClass().getSimpleName());
            log.error("SSE 转发失败: userId={}, sessionId={}", userId, sessionId, error);
            try {
                String payload = objectMapper.writeValueAsString(
                    java.util.Map.of("message", "Agent 服务暂时不可用")
                );
                output.write(("event: error\ndata: " + payload + "\n\n").getBytes(StandardCharsets.UTF_8));
                output.flush();
            } catch (Exception ignored) {
                // Client connection may already be closed.
            }
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private Long parseSessionId(String value) {
        try {
            return Long.valueOf(value);
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException("session_id 必须来自 Java 会话接口");
        }
    }
}

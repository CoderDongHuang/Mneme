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
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private RetrievalScopeService retrievalScope;
    @org.springframework.beans.factory.annotation.Autowired
    private UserSettingsService userSettings;

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
        if (retrievalScope != null) retrievalScope.apply(userId, request);
        Long sessionId = parseSessionId(request.getSessionId());
        ChatSessionService.Exchange exchange = sessionService.prepareExchange(
            userId, sessionId, request.getRequestId(), request.getMessage()
        );
        ChatMessage assistant = exchange.assistantMessage();
        if (exchange.completed()) {
            ChatResponse replay = new ChatResponse();
            replay.setAnswer(assistant.getContent());
            replay.setSources(readSources(assistant.getSourcesJson()));
            return replay;
        }
        ChatResponse response;
        try {
            response = restTemplate.postForObject(
                pythonAgentUrl + "/api/v1/chat", request, ChatResponse.class
            );
            if (response == null) throw new IllegalStateException("Python Agent 返回空响应");
            pendingMemoryService.store(userId, sessionId, assistant.getId(), response.getPendingMemories());
            sessionService.finishAnswer(assistant.getId(), assistant.getAnswerGeneration(), response.getAnswer(), serializeSources(response.getSources()));
        } catch (Exception error) {
            sessionService.failMessage(assistant.getId(), assistant.getAnswerGeneration(), "", error.getClass().getSimpleName());
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
        if (retrievalScope != null) retrievalScope.apply(userId, request);
        Long sessionId = parseSessionId(request.getSessionId());
        ChatSessionService.Exchange exchange = sessionService.prepareExchange(
            userId, sessionId, request.getRequestId(), request.getMessage()
        );
        ChatMessage assistant = exchange.assistantMessage();
        if (exchange.completed()) {
            return output -> replayStream(assistant, output);
        }
        return output -> proxyStream(userId, sessionId, assistant.getId(), assistant.getAnswerGeneration(), request, output);
    }

    private java.util.List<ChatResponse.Source> readSources(String value) {
        if (value == null || value.isBlank()) return java.util.List.of();
        try { return objectMapper.readValue(value, objectMapper.getTypeFactory().constructCollectionType(java.util.List.class, ChatResponse.Source.class)); }
        catch (Exception ignored) { return java.util.List.of(); }
    }

    private String serializeSources(java.util.List<ChatResponse.Source> sources) {
        try { return objectMapper.writeValueAsString(sources == null ? java.util.List.of() : sources); }
        catch (Exception error) { throw new IllegalStateException("引用保存失败", error); }
    }

    private void replayStream(ChatMessage assistant, OutputStream output) throws java.io.IOException {
        String answer = assistant.getContent();
        String meta = objectMapper.writeValueAsString(java.util.Map.of("sources", readSources(assistant.getSourcesJson())));
        output.write(("event: meta\ndata: " + meta + "\n\n").getBytes(StandardCharsets.UTF_8));
        String token = objectMapper.writeValueAsString(java.util.Map.of("content", answer));
        output.write(("event: token\ndata: " + token + "\n\n").getBytes(StandardCharsets.UTF_8));
        output.write("event: done\ndata: {\"ok\":true,\"replayed\":true}\n\n".getBytes(StandardCharsets.UTF_8));
        output.flush();
    }

    private void proxyStream(Long userId, Long sessionId, Long assistantMessageId, long generation, ChatRequest request, OutputStream output) {
        HttpURLConnection connection = null;
        StringBuilder answer = new StringBuilder();
        boolean completed = false;
        boolean failed = false;
        try {
            connection = (HttpURLConnection) URI.create(
                pythonAgentUrl + "/api/v1/chat/stream"
            ).toURL().openConnection();
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("X-Internal-Service-Token", internalServiceToken);
            if (userSettings != null) {
                String model = userSettings.modelHeader(userId);
                if (!model.isEmpty()) connection.setRequestProperty("X-Mneme-Model", model);
            }
            connection.setConnectTimeout(10_000);
            connection.setReadTimeout(180_000);
            try (OutputStream requestBody = connection.getOutputStream()) {
                objectMapper.writeValue(requestBody, request);
            }
            if (connection.getResponseCode() != 200) {
                throw new IllegalStateException("Python Agent 返回 " + connection.getResponseCode());
            }

            String sourcesJson = "[]";
            try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8)
            )) {
                SseEvent event;
                while ((event = readEvent(reader)) != null) {
                    JsonNode payload = objectMapper.readTree(event.data());
                    switch (event.type()) {
                        case "token" -> answer.append(payload.path("content").asText(""));
                        case "meta" -> sourcesJson = payload.path("sources").isArray() ? payload.path("sources").toString() : "[]";
                        case "memory" -> pendingMemoryService.store(userId, sessionId, assistantMessageId,
                            objectMapper.convertValue(payload.path("pending"), objectMapper.getTypeFactory()
                                .constructCollectionType(java.util.List.class, ChatResponse.PendingMemory.class)));
                        case "done" -> {
                            sessionService.finishAnswer(assistantMessageId, generation, answer.toString(), sourcesJson);
                            completed = true;
                        }
                        case "error" -> {
                            sessionService.failMessage(assistantMessageId, generation, answer.toString(), "AGENT_ERROR");
                            failed = true;
                        }
                        default -> { }
                    }
                    output.write(("event: " + event.type() + "\ndata: " + objectMapper.writeValueAsString(payload) + "\n\n").getBytes(StandardCharsets.UTF_8));
                    output.flush();
                    // Browser stops reading on done. Never wait for provider EOF to persist.
                    if (completed || failed) break;
                }
            }
            if (!completed && !failed) throw new IllegalStateException("INCOMPLETE_RESPONSE");
        } catch (Exception error) {
            if (completed) return; // Delivery failure cannot roll back a committed answer.
            try { sessionService.failMessage(assistantMessageId, generation, answer.toString(), error.getClass().getSimpleName()); }
            catch (Exception persistenceError) { log.error("SSE 失败状态保存异常: messageId={}", assistantMessageId, persistenceError); }
            log.error("SSE 转发失败: userId={}, sessionId={}, errorType={}", userId, sessionId, error.getClass().getSimpleName());
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

    private record SseEvent(String type, String data) { }

    private SseEvent readEvent(BufferedReader reader) throws java.io.IOException {
        String type = "message";
        StringBuilder data = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            if (line.isEmpty()) {
                if (!data.isEmpty()) return new SseEvent(type, data.substring(0, data.length() - 1));
                type = "message";
            } else if (line.startsWith("event:")) type = line.substring(6).trim();
            else if (line.startsWith("data:")) {
                String value = line.substring(5);
                data.append(value.startsWith(" ") ? value.substring(1) : value).append('\n');
                if (data.length() > 2_000_000) throw new java.io.IOException("SSE event too large");
            }
        }
        return null; // An incomplete frame must not publish a terminal event.
    }

    private Long parseSessionId(String value) {
        try {
            return Long.valueOf(value);
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException("session_id 必须来自 Java 会话接口");
        }
    }
}

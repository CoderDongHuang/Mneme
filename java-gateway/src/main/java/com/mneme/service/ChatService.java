package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.ChatRequest;
import com.mneme.dto.ChatResponse;
import com.mneme.websocket.ChatWebSocketHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

@Service
public class ChatService {

    private static final Logger log = LoggerFactory.getLogger(ChatService.class);

    private final RestTemplate restTemplate;
    private final RedisTemplate<String, Object> redisTemplate;
    private final ChatWebSocketHandler webSocketHandler;
    private final ObjectMapper objectMapper;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    public ChatService(RestTemplate restTemplate,
                       RedisTemplate<String, Object> redisTemplate,
                       ChatWebSocketHandler webSocketHandler,
                       ObjectMapper objectMapper) {
        this.restTemplate = restTemplate;
        this.redisTemplate = redisTemplate;
        this.webSocketHandler = webSocketHandler;
        this.objectMapper = objectMapper;
    }

    /**
     * 同步对话：阻塞等待完整结果后返回。
     * 用于 HTTP REST 调用场景。
     */
    public ChatResponse chat(ChatRequest request) {
        String cacheKey = "user_profile:" + request.getUserId();

        int maxRetries = 2;
        for (int i = 0; i <= maxRetries; i++) {
            try {
                ChatResponse response = restTemplate.postForObject(
                    pythonAgentUrl + "/api/v1/chat",
                    request,
                    ChatResponse.class
                );
                if (response != null) {
                    redisTemplate.opsForValue().set(cacheKey, response.getAnswer(), 30, TimeUnit.MINUTES);
                }
                return response;
            } catch (Exception e) {
                if (i == maxRetries) {
                    throw new RuntimeException("Python Agent 调用失败，已重试 " + maxRetries + " 次", e);
                }
                try {
                    Thread.sleep(1000L * (i + 1));
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                }
            }
        }
        throw new RuntimeException("Python Agent 调用失败");
    }

    /**
     * 异步流式对话：通过 HTTP 连接到 Python Agent 的 SSE 流式端点，
     * 将 LLM 回复逐 token 推送到用户的 WebSocket 连接。
     *
     * 设计：
     * 1. 建立到 Python /api/v1/chat/stream 的 HTTP 连接
     * 2. 异步读取 SSE 事件流
     * 3. 每个 token 通过 WebSocket 实时推送给用户
     * 4. [DONE] 信号表示流结束
     * 5. [PENDING] 信号携带待确认记忆
     */
    public void chatAsync(ChatRequest request) {
        String userId = request.getUserId();
        log.info("异步流式对话: user_id={}, session_id={}", userId, request.getSessionId());

        CompletableFuture.runAsync(() -> {
            HttpURLConnection conn = null;
            try {
                URL url = URI.create(pythonAgentUrl + "/api/v1/chat/stream").toURL();
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setConnectTimeout(10_000);
                conn.setReadTimeout(120_000);

                // 发送请求体
                String requestBody = objectMapper.writeValueAsString(request);
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(requestBody.getBytes(StandardCharsets.UTF_8));
                    os.flush();
                }

                // 读取 SSE 流式响应
                int responseCode = conn.getResponseCode();
                if (responseCode != 200) {
                    webSocketHandler.sendMessage(userId,
                        "{\"error\":\"Python Agent 返回状态码: " + responseCode + "\"}");
                    return;
                }

                try (BufferedReader reader = new BufferedReader(
                        new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    StringBuilder fullAnswer = new StringBuilder();

                    while ((line = reader.readLine()) != null) {
                        if (!line.startsWith("data: ")) {
                            continue;
                        }

                        String data = line.substring(6);

                        if ("[DONE]".equals(data)) {
                            // 流结束
                            webSocketHandler.sendMessage(userId,
                                "{\"type\":\"done\",\"session_id\":\"" + request.getSessionId() + "\"}");
                            break;
                        }

                        if (data.startsWith("[PENDING]")) {
                            // 待确认记忆 — 透传给前端
                            String pendingJson = data.substring(10);
                            webSocketHandler.sendMessage(userId,
                                "{\"type\":\"pending_memories\",\"data\":" + pendingJson + "}");
                            continue;
                        }

                        if (data.startsWith("[ERROR]")) {
                            String errorMsg = data.substring(8);
                            webSocketHandler.sendMessage(userId,
                                "{\"type\":\"error\",\"message\":\"" + escapeJson(errorMsg) + "\"}");
                            continue;
                        }

                        // 普通 token 内容
                        fullAnswer.append(data);
                        webSocketHandler.sendMessage(userId,
                            "{\"type\":\"token\",\"content\":\"" + escapeJson(data) + "\"}");
                    }
                }

            } catch (Exception e) {
                log.error("异步流式对话失败: user_id={}, error={}", userId, e.getMessage());
                webSocketHandler.sendMessage(userId,
                    "{\"type\":\"error\",\"message\":\"" + escapeJson(e.getMessage()) + "\"}");
            } finally {
                if (conn != null) {
                    conn.disconnect();
                }
            }
        });
    }

    /**
     * 简单的 JSON 字符串转义（避免引入额外依赖）
     */
    private String escapeJson(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}

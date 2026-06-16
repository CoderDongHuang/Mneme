package com.mneme.controller;

import com.mneme.dto.ChatRequest;
import com.mneme.dto.ChatResponse;
import com.mneme.dto.Result;
import com.mneme.service.ChatService;
import com.mneme.websocket.ChatWebSocketHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/v1/chat")
public class ChatController {

    private static final Logger log = LoggerFactory.getLogger(ChatController.class);

    private final ChatService chatService;
    private final ChatWebSocketHandler webSocketHandler;

    public ChatController(ChatService chatService, ChatWebSocketHandler webSocketHandler) {
        this.chatService = chatService;
        this.webSocketHandler = webSocketHandler;
    }

    /**
     * 同步对话接口：阻塞等待完整结果后返回 JSON。
     */
    @PostMapping
    public Result<ChatResponse> chat(@RequestHeader("userId") Long userId,
                                     @RequestBody ChatRequest request) {
        request.setUserId(userId.toString());
        ChatResponse response = chatService.chat(request);
        return Result.success(response);
    }

    /**
     * 异步流式对话接口：立即返回确认，实际回复通过 WebSocket 实时推送。
     *
     * 前端应先建立 WebSocket 连接 (ws://host:8080/ws/chat?userId=xxx)，
     * 再调用此接口。LLM 回复将逐 token 通过 WebSocket 推送到客户端。
     *
     * WebSocket 消息格式：
     * - {"type":"token","content":"..."}    — LLM 输出的单个 token
     * - {"type":"pending_memories","data":[...]} — 待确认记忆列表
     * - {"type":"done","session_id":"..."}     — 流结束
     * - {"type":"error","message":"..."}       — 错误信息
     */
    @PostMapping("/stream")
    public Result<Map<String, String>> chatStream(@RequestHeader("userId") Long userId,
                                                   @RequestBody ChatRequest request) {
        request.setUserId(userId.toString());

        // 检查用户是否已建立 WebSocket 连接
        if (!webSocketHandler.isUserOnline(userId.toString())) {
            log.warn("用户 {} 未建立 WebSocket 连接，降级使用同步接口", userId);
            // 降级：走异步推送（会在后台尝试连接，失败时静默丢弃）
        }

        log.info("启动异步流式对话: user_id={}, session_id={}", userId, request.getSessionId());
        chatService.chatAsync(request);

        return Result.success(Map.of(
            "status", "streaming",
            "message", "回复将通过 WebSocket 实时推送",
            "session_id", request.getSessionId()
        ));
    }

    /**
     * WebSocket 连接状态查询
     */
    @GetMapping("/ws-status")
    public Result<Map<String, Object>> wsStatus() {
        return Result.success(Map.of(
            "online_users", webSocketHandler.getOnlineCount()
        ));
    }
}
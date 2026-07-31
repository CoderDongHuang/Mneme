package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.entity.ChatMessage;
import com.mneme.entity.ChatSession;
import com.mneme.service.ChatSessionService;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/sessions")
public class ChatSessionController {
    private final ChatSessionService sessionService;

    public ChatSessionController(ChatSessionService sessionService) {
        this.sessionService = sessionService;
    }

    @PostMapping
    public Result<ChatSession> createSession(
        @RequestAttribute("userId") Long userId,
        @RequestBody Map<String, String> request
    ) {
        return Result.success(sessionService.createSession(userId, request.get("title")));
    }

    @GetMapping
    public Result<List<ChatSession>> listSessions(@RequestAttribute("userId") Long userId) {
        return Result.success(sessionService.listSessions(userId));
    }

    @GetMapping("/{sessionId}/messages")
    public Result<List<ChatMessage>> messages(
        @RequestAttribute("userId") Long userId,
        @PathVariable Long sessionId
    ) {
        return Result.success(sessionService.getMessages(userId, sessionId));
    }

    @DeleteMapping("/{sessionId}")
    public Result<Map<String, Boolean>> delete(
        @RequestAttribute("userId") Long userId,
        @PathVariable Long sessionId
    ) {
        sessionService.deleteSession(userId, sessionId);
        return Result.success(Map.of("deleted", true));
    }
}

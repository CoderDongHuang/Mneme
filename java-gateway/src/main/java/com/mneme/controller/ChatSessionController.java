package com.mneme.controller;

import com.mneme.dto.Result;
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
    public Result<ChatSession> createSession(@RequestHeader("userId") Long userId,
                                             @RequestBody Map<String, String> request) {
        ChatSession session = sessionService.createSession(userId, request.get("title"));
        return Result.success(session);
    }

    @GetMapping
    public Result<List<ChatSession>> listSessions(@RequestHeader("userId") Long userId) {
        return Result.success(sessionService.listSessions(userId));
    }
}

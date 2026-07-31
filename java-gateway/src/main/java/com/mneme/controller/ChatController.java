package com.mneme.controller;

import com.mneme.dto.ChatRequest;
import com.mneme.dto.ChatResponse;
import com.mneme.dto.Result;
import com.mneme.service.ChatService;
import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
@RequestMapping("/api/v1/chat")
public class ChatController {
    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    @PostMapping
    public Result<ChatResponse> chat(
        @RequestAttribute("userId") Long userId,
        @Valid @RequestBody ChatRequest request
    ) {
        request.setUserId(userId.toString());
        ensureRequestId(request);
        return Result.success(chatService.chat(userId, request));
    }

    @PostMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<StreamingResponseBody> chatStream(
        @RequestAttribute("userId") Long userId,
        @Valid @RequestBody ChatRequest request
    ) {
        request.setUserId(userId.toString());
        ensureRequestId(request);
        return ResponseEntity.ok()
            .contentType(MediaType.TEXT_EVENT_STREAM)
            .header("Cache-Control", "no-cache")
            .header("X-Accel-Buffering", "no")
            .body(chatService.stream(userId, request));
    }

    private void ensureRequestId(ChatRequest request) {
        if (request.getRequestId() == null || request.getRequestId().isBlank()) {
            request.setRequestId(java.util.UUID.randomUUID().toString());
        }
    }
}

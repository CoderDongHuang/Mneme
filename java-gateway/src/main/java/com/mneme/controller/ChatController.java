package com.mneme.controller;

import com.mneme.dto.ChatRequest;
import com.mneme.dto.ChatResponse;
import com.mneme.dto.Result;
import com.mneme.service.ChatService;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/chat")
public class ChatController {

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    @PostMapping
    public Result<ChatResponse> chat(@RequestHeader("userId") Long userId,
                                     @RequestBody ChatRequest request) {
        request.setUserId(userId.toString());
        ChatResponse response = chatService.chat(request);
        return Result.success(response);
    }
}
package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.mneme.entity.ChatMessage;
import com.mneme.entity.ChatSession;
import com.mneme.mapper.ChatMessageMapper;
import com.mneme.mapper.ChatSessionMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class ChatSessionService {
    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;

    public ChatSessionService(ChatSessionMapper sessionMapper, ChatMessageMapper messageMapper) {
        this.sessionMapper = sessionMapper;
        this.messageMapper = messageMapper;
    }

    public ChatSession createSession(Long userId, String title) {
        ChatSession session = new ChatSession();
        session.setUserId(userId);
        session.setTitle(title == null || title.isBlank() ? "新对话" : title.trim());
        sessionMapper.insert(session);
        return session;
    }

    public List<ChatSession> listSessions(Long userId) {
        return sessionMapper.selectList(new LambdaQueryWrapper<ChatSession>()
            .eq(ChatSession::getUserId, userId)
            .orderByDesc(ChatSession::getUpdatedAt));
    }

    public ChatSession getOwnedSession(Long userId, Long sessionId) {
        ChatSession session = sessionMapper.selectById(sessionId);
        if (session == null || !userId.equals(session.getUserId())) {
            throw new IllegalArgumentException("会话不存在");
        }
        return session;
    }

    public List<ChatMessage> getMessages(Long userId, Long sessionId) {
        getOwnedSession(userId, sessionId);
        return messageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
            .eq(ChatMessage::getSessionId, sessionId)
            .orderByAsc(ChatMessage::getCreatedAt));
    }

    @Transactional
    public ChatMessage appendMessage(Long userId, Long sessionId, String role, String content) {
        return appendMessage(userId, sessionId, null, role, content, "completed");
    }

    @Transactional
    public ChatMessage appendMessage(
        Long userId, Long sessionId, String requestId, String role, String content, String status
    ) {
        ChatSession session = getOwnedSession(userId, sessionId);
        if (requestId != null) {
            ChatMessage existing = messageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getRequestId, requestId)
                .eq(ChatMessage::getRole, role));
            if (existing != null) return existing;
        }
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRequestId(requestId);
        message.setRole(role);
        message.setContent(content);
        message.setStatus(status);
        messageMapper.insert(message);
        if ("user".equals(role) && ("新对话".equals(session.getTitle()) || session.getTitle() == null)) {
            session.setTitle(content.substring(0, Math.min(content.length(), 40)));
        }
        sessionMapper.updateById(session);
        return message;
    }

    public void finishMessage(Long messageId, String content) {
        ChatMessage message = messageMapper.selectById(messageId);
        if (message == null) return;
        message.setContent(content);
        message.setStatus("completed");
        message.setErrorCode(null);
        messageMapper.updateById(message);
    }

    public void failMessage(Long messageId, String content, String errorCode) {
        ChatMessage message = messageMapper.selectById(messageId);
        if (message == null) return;
        message.setContent(content == null ? "" : content);
        message.setStatus("failed");
        message.setErrorCode(errorCode);
        messageMapper.updateById(message);
    }

    @Transactional
    public void deleteSession(Long userId, Long sessionId) {
        getOwnedSession(userId, sessionId);
        messageMapper.delete(new LambdaQueryWrapper<ChatMessage>().eq(ChatMessage::getSessionId, sessionId));
        sessionMapper.deleteById(sessionId);
    }
}

package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.mneme.entity.ChatMessage;
import com.mneme.entity.ChatSession;
import com.mneme.exception.RequestInProgressException;
import com.mneme.mapper.ChatMessageMapper;
import com.mneme.mapper.ChatSessionMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class ChatSessionService {
    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;
    private final JdbcTemplate jdbc;

    public ChatSessionService(
        ChatSessionMapper sessionMapper,
        ChatMessageMapper messageMapper,
        JdbcTemplate jdbc
    ) {
        this.sessionMapper = sessionMapper;
        this.messageMapper = messageMapper;
        this.jdbc = jdbc;
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
            .orderByAsc(ChatMessage::getCreatedAt, ChatMessage::getId));
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
                .eq(ChatMessage::getSessionId, sessionId)
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

    @Transactional
    public Exchange prepareExchange(Long userId, Long sessionId, String requestId, String content) {
        List<Long> locked = jdbc.queryForList(
            "SELECT id FROM chat_session WHERE id=? AND user_id=? FOR UPDATE",
            Long.class,
            sessionId,
            userId
        );
        if (locked.isEmpty()) throw new IllegalArgumentException("会话不存在");

        ChatMessage userMessage = findByRequest(sessionId, requestId, "user");
        ChatMessage assistant = findByRequest(sessionId, requestId, "assistant");
        if (userMessage != null && !content.equals(userMessage.getContent())) {
            throw new IllegalArgumentException("request_id 已用于不同的消息内容");
        }
        if (assistant != null) {
            if ("completed".equals(assistant.getStatus())) {
                return new Exchange(userMessage, assistant, true);
            }
            if ("processing".equals(assistant.getStatus())) {
                throw new RequestInProgressException("相同请求正在处理中");
            }
            long generation = assistant.getAnswerGeneration() + 1;
            if (jdbc.update("UPDATE chat_message SET content='',sources_json='[]',status='processing',"
                + "error_code=NULL,answer_generation=? WHERE id=? AND answer_generation=? AND status IN ('failed','stopped')",
                generation, assistant.getId(), assistant.getAnswerGeneration()) != 1)
                throw new RequestInProgressException("请求状态已变化，请刷新后重试");
            assistant.setAnswerGeneration(generation);
            assistant.setContent("");
            assistant.setSourcesJson("[]");
            assistant.setStatus("processing");
            assistant.setErrorCode(null);
            return new Exchange(userMessage, assistant, false);
        }

        ChatSession session = sessionMapper.selectById(sessionId);
        if (userMessage == null) {
            userMessage = newMessage(sessionId, requestId, "user", content, "completed");
            messageMapper.insert(userMessage);
            if (session != null && ("新对话".equals(session.getTitle()) || session.getTitle() == null)) {
                session.setTitle(content.substring(0, Math.min(content.length(), 40)));
            }
        }
        assistant = newMessage(sessionId, requestId, "assistant", "", "processing");
        messageMapper.insert(assistant);
        if (session != null) sessionMapper.updateById(session);
        return new Exchange(userMessage, assistant, false);
    }

    private ChatMessage findByRequest(Long sessionId, String requestId, String role) {
        return messageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
            .eq(ChatMessage::getSessionId, sessionId)
            .eq(ChatMessage::getRequestId, requestId)
            .eq(ChatMessage::getRole, role));
    }

    private ChatMessage newMessage(
        Long sessionId, String requestId, String role, String content, String status
    ) {
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRequestId(requestId);
        message.setRole(role);
        message.setContent(content);
        message.setStatus(status);
        if ("assistant".equals(role)) message.setAnswerGeneration(1L);
        return message;
    }

    public record Exchange(ChatMessage userMessage, ChatMessage assistantMessage, boolean completed) { }

    public ChatSession renameSession(Long userId, Long sessionId, String title) {
        if (title == null || title.isBlank() || title.trim().length() > 120) {
            throw new IllegalArgumentException("标题不能为空，最多 120 个字符");
        }
        ChatSession session = getOwnedSession(userId, sessionId);
        session.setTitle(title.trim());
        sessionMapper.updateById(session);
        return session;
    }

    /** Commit verified text, evidence and terminal state before exposing done. */
    @Transactional
    public void finishAnswer(Long messageId, long generation, String content, String sourcesJson) {
        if (content == null || content.isBlank()) throw new IllegalArgumentException("回答内容为空");
        if (jdbc.update("UPDATE chat_message SET content=?,sources_json=?,status='completed',error_code=NULL"
            + " WHERE id=? AND role='assistant' AND status='processing' AND answer_generation=?",
            content, sourcesJson, messageId, generation) != 1)
            throw new IllegalStateException("回答执行权已失效，拒绝发布完成状态");
    }

    public void failMessage(Long messageId, long generation, String content, String errorCode) {
        // Late failures, old retries and client disconnect after done cannot undo success.
        jdbc.update("UPDATE chat_message SET content=?,status='failed',error_code=?"
            + " WHERE id=? AND role='assistant' AND status='processing' AND answer_generation=?",
            content == null ? "" : content, errorCode, messageId, generation);
    }

    @Transactional
    public void deleteSession(Long userId, Long sessionId) {
        getOwnedSession(userId, sessionId);
        messageMapper.delete(new LambdaQueryWrapper<ChatMessage>().eq(ChatMessage::getSessionId, sessionId));
        sessionMapper.deleteById(sessionId);
    }
}

package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.mneme.entity.ChatSession;
import com.mneme.mapper.ChatSessionMapper;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ChatSessionService {

    private final ChatSessionMapper sessionMapper;

    public ChatSessionService(ChatSessionMapper sessionMapper) {
        this.sessionMapper = sessionMapper;
    }

    public ChatSession createSession(Long userId, String title) {
        ChatSession session = new ChatSession();
        session.setUserId(userId);
        session.setTitle(title);
        sessionMapper.insert(session);
        return session;
    }

    public List<ChatSession> listSessions(Long userId) {
        return sessionMapper.selectList(new QueryWrapper<ChatSession>().eq("user_id", userId));
    }

    public ChatSession getSession(Long sessionId) {
        return sessionMapper.selectById(sessionId);
    }
}

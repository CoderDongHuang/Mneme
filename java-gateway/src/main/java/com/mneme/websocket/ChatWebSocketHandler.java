package com.mneme.websocket;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class ChatWebSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(ChatWebSocketHandler.class);

    /** userId → WebSocketSession */
    private static final Map<String, WebSocketSession> sessions = new ConcurrentHashMap<>();

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        String userId = (String) session.getAttributes().get("userId");
        if (userId != null) {
            // 关闭旧连接（同一用户重复连接）
            WebSocketSession oldSession = sessions.put(userId, session);
            if (oldSession != null && oldSession.isOpen()) {
                try {
                    oldSession.close(CloseStatus.NORMAL);
                } catch (Exception e) {
                    log.warn("关闭旧 WebSocket 连接失败: userId={}", userId);
                }
            }
            log.info("WebSocket 连接建立: userId={}, sessionId={}", userId, session.getId());
        } else {
            log.warn("WebSocket 连接缺少 userId 参数: sessionId={}", session.getId());
        }
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        sessions.values().remove(session);
        log.info("WebSocket 连接关闭: sessionId={}, status={}", session.getId(), status);
    }

    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) {
        log.error("WebSocket 传输错误: sessionId={}, error={}", session.getId(), exception.getMessage());
        sessions.values().remove(session);
    }

    /**
     * 向指定用户推送消息
     *
     * @param userId  用户 ID
     * @param message 消息内容（JSON 字符串）
     * @return true 发送成功，false 用户未连接或发送失败
     */
    public boolean sendMessage(String userId, String message) {
        WebSocketSession session = sessions.get(userId);
        if (session == null) {
            return false;
        }
        if (!session.isOpen()) {
            sessions.remove(userId);
            return false;
        }
        try {
            synchronized (session) {
                session.sendMessage(new TextMessage(message));
            }
            return true;
        } catch (Exception e) {
            log.warn("WebSocket 推送失败: userId={}, error={}", userId, e.getMessage());
            sessions.remove(userId);
            return false;
        }
    }

    /**
     * 获取当前在线用户数
     */
    public int getOnlineCount() {
        return sessions.size();
    }

    /**
     * 检查用户是否在线
     */
    public boolean isUserOnline(String userId) {
        WebSocketSession session = sessions.get(userId);
        return session != null && session.isOpen();
    }
}

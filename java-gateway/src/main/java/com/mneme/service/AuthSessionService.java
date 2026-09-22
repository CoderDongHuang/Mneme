package com.mneme.service;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.UUID;

@Service
public class AuthSessionService {
    private final JdbcTemplate jdbc;

    public AuthSessionService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public String create(Long userId, LocalDateTime expiresAt, boolean remembered) {
        String sessionId = UUID.randomUUID().toString();
        jdbc.update("""
            INSERT INTO auth_session(session_id,user_id,remembered,expires_at)
            VALUES(?,?,?,?)
            """, sessionId, userId, remembered, expiresAt);
        return sessionId;
    }

    public boolean isActive(String sessionId, Long userId) {
        if (sessionId == null || sessionId.isBlank()) return false;
        Long count = jdbc.queryForObject("""
            SELECT COUNT(*) FROM auth_session
            WHERE session_id=? AND user_id=? AND revoked_at IS NULL AND expires_at>NOW()
            """, Long.class, sessionId, userId);
        if (count != null && count == 1) {
            jdbc.update("UPDATE auth_session SET last_seen_at=NOW() WHERE session_id=?", sessionId);
            return true;
        }
        return false;
    }

    public void revoke(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) return;
        jdbc.update("UPDATE auth_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE session_id=?", sessionId);
    }

    public void revokeAll(Long userId) {
        jdbc.update("UPDATE auth_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE user_id=?", userId);
    }

    @Scheduled(cron = "${mneme.auth-session-cleanup-cron:0 37 3 * * *}")
    public void cleanupExpired() {
        jdbc.update("DELETE FROM auth_session WHERE expires_at<DATE_SUB(NOW(), INTERVAL 7 DAY)");
    }
}

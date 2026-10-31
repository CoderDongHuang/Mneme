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
        Long activity = jdbc.queryForObject("""
            SELECT COALESCE(MAX(CASE WHEN last_seen_at IS NULL
                OR last_seen_at<=DATE_SUB(NOW(), INTERVAL 2 MINUTE) THEN 2 ELSE 1 END),0)
            FROM auth_session
            WHERE session_id=? AND user_id=? AND revoked_at IS NULL AND expires_at>NOW()
            """, (rs, rowNum) -> rs.getLong(1), sessionId, userId);
        if (activity == null || activity == 0) return false;
        if (activity == 2) {
            // Keep every authorization read authoritative. Only activity writes
            // are throttled; the DB clock and predicate work across instances.
            jdbc.update("""
                UPDATE auth_session SET last_seen_at=NOW()
                WHERE session_id=? AND user_id=? AND revoked_at IS NULL AND expires_at>NOW()
                    AND (last_seen_at IS NULL OR last_seen_at<=DATE_SUB(NOW(), INTERVAL 2 MINUTE))
                """, sessionId, userId);
        }
        return true;
    }

    public void revoke(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) return;
        jdbc.update("UPDATE auth_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE session_id=?", sessionId);
    }

    public void revokeAll(Long userId) {
        jdbc.update("UPDATE auth_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE user_id=?", userId);
    }

    public java.util.List<java.util.Map<String,Object>> list(Long userId) {
        return jdbc.queryForList("SELECT session_id,remembered,created_at,last_seen_at,expires_at FROM auth_session WHERE user_id=? AND revoked_at IS NULL AND expires_at>NOW() ORDER BY last_seen_at DESC", userId);
    }

    public void revokeOwned(Long userId, String sessionId) {
        jdbc.update("UPDATE auth_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE session_id=? AND user_id=?", sessionId, userId);
    }

    @Scheduled(cron = "${mneme.auth-session-cleanup-cron:0 37 3 * * *}")
    public void cleanupExpired() {
        jdbc.update("DELETE FROM auth_session WHERE expires_at<DATE_SUB(NOW(), INTERVAL 7 DAY)");
    }
}

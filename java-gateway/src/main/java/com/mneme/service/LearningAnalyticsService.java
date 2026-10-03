package com.mneme.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class LearningAnalyticsService {
    private final JdbcTemplate jdbc;
    private final RestTemplate agent;
    private final String agentUrl;
    public LearningAnalyticsService(JdbcTemplate jdbc, @Qualifier("healthHttp") RestTemplate agent,
        @Value("${mneme.python-agent-url}") String agentUrl) {
        this.jdbc = jdbc; this.agent = agent; this.agentUrl = agentUrl;
    }

    public Map<String, Object> summary(Long user, int days) {
        int window = Math.max(7, Math.min(90, days));
        var result = new LinkedHashMap<String, Object>();
        result.put("window_days", window);
        result.put("topics", jdbc.queryForList("""
            SELECT topic,COUNT(*) AS observations,AVG(score) AS average_score,
                AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate,
                AVG(CASE WHEN created_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL ? DAY) THEN score END) AS early_score,
                AVG(CASE WHEN created_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL ? DAY) THEN score END) AS recent_score
            FROM learning_outcome_event WHERE user_id=? AND created_at>=DATE_SUB(UTC_TIMESTAMP(), INTERVAL ? DAY)
            GROUP BY topic ORDER BY success_rate ASC,observations DESC LIMIT 100
            """, window / 2, window / 2, user, window));
        result.put("daily", jdbc.queryForList("""
            SELECT DATE(created_at) AS day,event_type,COUNT(*) AS observations,AVG(score) AS average_score,
                AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate
            FROM learning_outcome_event WHERE user_id=? AND created_at>=DATE_SUB(UTC_TIMESTAMP(), INTERVAL ? DAY)
            GROUP BY DATE(created_at),event_type ORDER BY day ASC
            """, user, window));
        result.put("feedback_summary", jdbc.queryForList("""
            SELECT outcome,citation_rating,reason,COUNT(*) AS observations FROM rag_quality_feedback
            WHERE user_id=? AND updated_at>=DATE_SUB(UTC_TIMESTAMP(), INTERVAL ? DAY)
            GROUP BY outcome,citation_rating,reason
            """, user, window));
        result.put("feedback", jdbc.queryForList("""
            SELECT id,message_id,outcome,citation_rating,reason,note,updated_at FROM rag_quality_feedback
            WHERE user_id=? ORDER BY updated_at DESC,id DESC LIMIT 100
            """, user));
        result.put("answers", jdbc.queryForList("""
            SELECT m.id,m.session_id,LEFT(m.content,240) AS excerpt,m.created_at FROM chat_message m
            JOIN chat_session s ON s.id=m.session_id
            WHERE s.user_id=? AND m.role='assistant' AND m.status='completed'
            ORDER BY m.created_at DESC,m.id DESC LIMIT 50
            """, user));
        try {
            Object quality = agent.getForObject(agentUrl + "/api/v1/agent/quality/" + user + "?days=" + window, Object.class);
            result.put("trace_quality", quality == null ? Map.of("status", "unavailable") : quality);
        } catch (Exception ignored) { result.put("trace_quality", Map.of("status", "unavailable")); }
        return result;
    }

    @Transactional
    public void feedback(Long user, long message, String outcome, String citation, String reason, String note) {
        if (message <= 0 || !List.of("helpful", "incorrect", "low_confidence", "refusal").contains(outcome)
            || !List.of("correct", "incorrect", "unclear", "not_applicable").contains(citation)
            || !List.of("none", "no_evidence", "irrelevant_sources", "unsafe_content", "other").contains(reason)
            || note == null || note.length() > 1000) throw new IllegalArgumentException("反馈参数无效");
        // The ownership predicate is part of the write, not a separate race-prone check.
        int changed = jdbc.update("""
            INSERT INTO rag_quality_feedback(user_id,message_id,outcome,citation_rating,reason,note)
            SELECT ?,m.id,?,?,?,? FROM chat_message m JOIN chat_session s ON s.id=m.session_id
            WHERE m.id=? AND s.user_id=? AND m.role='assistant' AND m.status='completed'
            ON DUPLICATE KEY UPDATE outcome=VALUES(outcome),citation_rating=VALUES(citation_rating),
                reason=VALUES(reason),note=VALUES(note),updated_at=UTC_TIMESTAMP()
            """, user, outcome, citation, reason, note.trim(), message, user);
        // MySQL may return zero for an identical upsert with useAffectedRows enabled.
        if (changed == 0 && !Boolean.TRUE.equals(jdbc.queryForObject("""
            SELECT EXISTS(SELECT 1 FROM rag_quality_feedback f
            JOIN chat_message m ON m.id=f.message_id JOIN chat_session s ON s.id=m.session_id
            WHERE f.user_id=? AND f.message_id=? AND s.user_id=? AND m.role='assistant' AND m.status='completed')
            """, Boolean.class, user, message, user)))
            throw new IllegalArgumentException("回答不存在、未完成或不属于当前用户");
    }

    public void deleteFeedback(Long user, long id) {
        if (jdbc.update("DELETE FROM rag_quality_feedback WHERE id=? AND user_id=?", id, user) == 0)
            throw new IllegalArgumentException("反馈不存在");
    }
}

package com.mneme.service;

import com.mneme.entity.User;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestTemplate;
import java.nio.file.Path;
import java.util.List;

/** Independent final reads. Audit, operation receipts and durable fences have separate retention. */
final class AccountCleanupVerification {
    private static final List<String> AGENT_STORES = List.of(
        "qdrant_chunks", "qdrant_collections", "fts_rows", "account_fence",
        "long_term_memories", "memory_versions", "traces", "privacy_rows", "tool_governance",
        "session_manifest", "sql_session_histories", "redis_scoped_sessions", "reflection_keys", "reflection_queue_entries");
    private static final List<String> OWNED_TABLES = List.of(
        "knowledge_base", "chat_session", "processing_task", "pending_memory", "learning_plan",
        "review_card", "knowledge_quiz", "quiz_attempt", "chat_branch", "password_reset_token",
        "notification_event", "learning_metric_snapshot", "learning_outcome_event", "auth_session",
        "rag_quality_feedback", "user_preference", "user_model_config", "quiz_draft", "quiz_question_report",
        "email_verification_token", "upload_submission");
    private final JdbcTemplate jdbc;
    private final RestTemplate http;
    private final String agentUrl;
    private final AccountFileCleanup files;

    AccountCleanupVerification(JdbcTemplate jdbc, RestTemplate http, String agentUrl, AccountFileCleanup files) {
        this.jdbc = jdbc; this.http = http; this.agentUrl = agentUrl; this.files = files;
    }

    CleanupReport read(long userId, User snapshot) {
        var report = new CleanupReport();
        report.agent(http, agentUrl + "/api/v1/admin/user/" + userId + "/deletion-report", AGENT_STORES);
        files.readReport(userId, report);
        report.read("avatars", () -> snapshot == null ? -1 : snapshot.getAvatarPath() == null ? 0
            : ObjectStorageService.countPath(Path.of(snapshot.getAvatarPath())));
        readSql(userId, report);
        return report;
    }

    void readSql(long userId, CleanupReport report) {
        report.read("mysql_rows", () -> {
            long total = jdbc.queryForObject("SELECT COUNT(*) FROM user WHERE id=?", Long.class, userId);
            for (String table : OWNED_TABLES) {
                total = Math.addExact(total, jdbc.queryForObject("SELECT COUNT(*) FROM " + table + " WHERE user_id=?", Long.class, userId));
            }
            return total;
        });
    }
}

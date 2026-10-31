package com.mneme.service;

import com.mneme.entity.KnowledgeDocument;
import com.mneme.exception.RequestInProgressException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Durable receipt serializes cancellation and submission across gateway instances. */
@Service
public class UploadSubmissionService {
    private final JdbcTemplate jdbc;
    private final KnowledgeService knowledge;

    public UploadSubmissionService(JdbcTemplate jdbc, KnowledgeService knowledge) {
        this.jdbc = jdbc;
        this.knowledge = knowledge;
    }

    @Transactional
    public KnowledgeDocument upload(Long user, Long kb, String requestId, MultipartFile file) {
        if (requestId == null) return knowledge.uploadDocument(user, kb, file); // legacy clients
        lock(user, kb, requestId);
        var rows = receipt(user, kb, requestId);
        if (!rows.isEmpty()) {
            if ("cancelled".equals(rows.get(0).get("status"))) {
                throw new RequestInProgressException("上传已取消，请重新选择文件");
            }
            // Return the existing receipt even if the original response was lost.
            var documents = jdbc.query("SELECT * FROM knowledge_document WHERE id=? AND kb_id=? FOR UPDATE",
                org.springframework.jdbc.core.BeanPropertyRowMapper.newInstance(KnowledgeDocument.class),
                rows.get(0).get("document_id"), kb);
            if (documents.isEmpty()) throw new RequestInProgressException("上传已提交，原文档已删除");
            return documents.get(0);
        }
        var document = knowledge.uploadDocument(user, kb, file);
        jdbc.update("""
            INSERT INTO upload_submission(user_id,request_id,kb_id,status,document_id,task_id)
            VALUES(?,?,?,'submitted',?,?)
            """, user, requestId, kb, document.getId(), document.getParseTaskId());
        return document;
    }

    @Transactional
    public Map<String, Object> cancel(Long user, Long kb, String requestId) {
        lock(user, kb, requestId);
        var rows = receipt(user, kb, requestId);
        if (!rows.isEmpty()) return rows.get(0);
        // A tombstone also rejects a multipart body that finishes arriving later.
        jdbc.update("INSERT INTO upload_submission(user_id,request_id,kb_id,status) VALUES(?,?,?,'cancelled')",
            user, requestId, kb);
        return Map.of("status", "cancelled");
    }

    private void lock(Long user, Long kb, String requestId) {
        if (requestId == null || !requestId.equals(UUID.fromString(requestId).toString())) {
            throw new IllegalArgumentException("上传请求编号无效");
        }
        var states = jdbc.queryForList("SELECT status FROM user WHERE id=? FOR UPDATE", String.class, user);
        if (states.isEmpty() || !"active".equals(states.get(0))) throw new IllegalArgumentException("账户不可用");
        knowledge.getOwnedKb(user, kb);
    }

    private List<Map<String, Object>> receipt(Long user, Long kb, String requestId) {
        // Current read: an outer REPEATABLE READ snapshot must not hide a cancellation.
        var rows = jdbc.queryForList("SELECT kb_id,status,document_id,task_id FROM upload_submission WHERE user_id=? AND request_id=? FOR UPDATE",
            user, requestId);
        if (!rows.isEmpty() && ((Number) rows.get(0).get("kb_id")).longValue() != kb.longValue()) {
            throw new IllegalArgumentException("上传请求不属于此资料库");
        }
        return rows;
    }
}

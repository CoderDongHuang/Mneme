package com.mneme.service;

import com.mneme.dto.ChatRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.annotation.Isolation;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

/** Resolve untrusted UI filters against the live tenant catalog before either retrieval channel. */
@Service
public class RetrievalScopeService {
    private final JdbcTemplate jdbc;
    public RetrievalScopeService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public void apply(Long userId, ChatRequest request) {
        request.setDocumentIds(resolve(userId, request.getKnowledgeBaseIds(), request.getSelectedDocumentIds(),
            request.getTags(), request.getDateFrom(), request.getDateTo()));
    }

    public List<String> resolve(Long userId, List<String> kbIds, List<String> documentIds,
                                List<String> tags, String from, String to) {
        if (kbIds == null || kbIds.isEmpty()) return List.of();
        if (tags != null && tags.size() > 20) throw new IllegalArgumentException("最多筛选 20 个标签");
        List<Object> args = new ArrayList<>();
        args.add(userId);
        StringBuilder sql = new StringBuilder("SELECT d.id FROM knowledge_document d JOIN knowledge_base k ON k.id=d.kb_id WHERE k.user_id=? AND d.status IN ('ready','partial','index_pending','index_repairing') AND k.status='active'");
        appendIn(sql, args, "d.kb_id", kbIds);
        if (documentIds != null && !documentIds.isEmpty()) appendIn(sql, args, "d.id", documentIds);
        if (tags != null) for (String tag : tags) {
            if (tag == null || tag.isBlank() || tag.length() > 80) throw new IllegalArgumentException("标签长度须为 1–80 字");
            sql.append(" AND EXISTS (SELECT 1 FROM knowledge_document_tag t WHERE t.document_id=d.id AND t.tag=?)");
            args.add(tag.trim());
        }
        LocalDate start = parseDate(from);
        LocalDate end = parseDate(to);
        if (start != null && end != null && start.isAfter(end)) throw new IllegalArgumentException("起始日期不能晚于结束日期");
        if (start != null) { sql.append(" AND d.created_at>=?"); args.add(start.atStartOfDay()); }
        if (end != null) { sql.append(" AND d.created_at<?"); args.add(end.plusDays(1).atStartOfDay()); }
        sql.append(" ORDER BY d.id LIMIT 10001");
        List<String> ids = jdbc.query(sql.toString(), (rs, row) -> "doc_" + rs.getLong(1), args.toArray());
        if (ids.size() > 10000) throw new IllegalArgumentException("请缩小检索范围至 10000 份资料以内");
        return ids;
    }

    private LocalDate parseDate(String value) {
        try {
            LocalDate date = value == null || value.isBlank() ? null : LocalDate.parse(value);
            if (date != null && (date.getYear() < 1000 || date.getYear() > 9998)) throw new IllegalArgumentException("日期超出支持范围");
            return date;
        } catch (java.time.format.DateTimeParseException error) {
            throw new IllegalArgumentException("日期须使用 YYYY-MM-DD 格式", error);
        }
    }

    private void appendIn(StringBuilder sql, List<Object> args, String column, List<String> values) {
        if (values.size() > 10000) throw new IllegalArgumentException("筛选项过多");
        sql.append(" AND ").append(column).append(" IN (")
            .append(String.join(",", java.util.Collections.nCopies(values.size(), "?"))).append(")");
        for (String value : values) {
            if (value == null || !value.matches("[0-9]+")) throw new IllegalArgumentException("资料编号无效");
            args.add(value);
        }
    }

    public List<String> tags(Long userId, Long documentId) {
        requireDocument(userId, documentId);
        return jdbc.query("SELECT tag FROM knowledge_document_tag WHERE document_id=? ORDER BY tag", (rs, row) -> rs.getString(1), documentId);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public List<String> setTags(Long userId, Long documentId, List<String> tags) {
        if (tags == null || tags.size() > 20 || tags.stream().anyMatch(t -> t == null || t.isBlank() || t.length() > 80))
            throw new IllegalArgumentException("最多设置 20 个标签，每个 1–80 字");
        // Match catalog mutation lock order and serialize edits of the same document.
        // READ_COMMITTED avoids empty tag-range gap locks across unrelated documents.
        List<Long> parents = jdbc.query("SELECT kb_id FROM knowledge_document WHERE id=?",
            (rs, row) -> rs.getLong(1), documentId);
        if (parents.isEmpty() || jdbc.queryForList(
            "SELECT id FROM knowledge_base WHERE id=? AND user_id=? AND status='active' FOR UPDATE",
            parents.get(0), userId).isEmpty()) throw new IllegalArgumentException("文档不存在或不可访问");
        if (jdbc.queryForList("SELECT id FROM knowledge_document WHERE id=? AND status NOT IN ('deleting','delete_failed') FOR UPDATE",
            documentId).isEmpty()) throw new IllegalArgumentException("文档不存在或不可访问");
        jdbc.update("DELETE FROM knowledge_document_tag WHERE document_id=?", documentId);
        for (String tag : tags.stream().map(String::trim).distinct().toList())
            jdbc.update("INSERT INTO knowledge_document_tag(document_id,tag) VALUES(?,?)", documentId, tag);
        return tags(userId, documentId);
    }

    private void requireDocument(Long userId, Long id) {
        Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document d JOIN knowledge_base k ON k.id=d.kb_id WHERE d.id=? AND k.user_id=? AND k.status='active' AND d.status NOT IN ('deleting','delete_failed')", Integer.class, id, userId);
        if (count == null || count != 1) throw new IllegalArgumentException("文档不存在或不可访问");
    }
}

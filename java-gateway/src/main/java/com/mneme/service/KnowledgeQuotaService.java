package com.mneme.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/** Current reads and the owner lock must share the catalog mutation's transaction. */
@Service
@Transactional(propagation = Propagation.MANDATORY)
public class KnowledgeQuotaService {
    private final JdbcTemplate jdbc;
    private final long storageQuotaMb;
    private final int knowledgeBaseQuota;

    public KnowledgeQuotaService(JdbcTemplate jdbc,
        @Value("${mneme.tenant-storage-quota-mb:2048}") long storageQuotaMb,
        @Value("${mneme.tenant-knowledge-base-quota:100}") int knowledgeBaseQuota) {
        this.jdbc = jdbc;
        this.storageQuotaMb = storageQuotaMb;
        this.knowledgeBaseQuota = knowledgeBaseQuota;
    }

    public void lockActiveOwner(Long userId) {
        var states = jdbc.queryForList("SELECT status FROM user WHERE id=? FOR UPDATE", String.class, userId);
        if (states.isEmpty() || !"active".equals(states.get(0))) {
            throw new IllegalArgumentException("用户不存在或正在删除");
        }
    }

    public void requireKnowledgeBaseCapacity(Long userId, int incoming) {
        if (incoming < 0) throw new IllegalArgumentException("新增知识库数量不合法");
        lockActiveOwner(userId);
        // A locking read bypasses snapshots established earlier by archive import.
        int count = jdbc.queryForList("SELECT id FROM knowledge_base WHERE user_id=? FOR UPDATE",
            Long.class, userId).size();
        if ((long) count + incoming > knowledgeBaseQuota) {
            throw new IllegalArgumentException("知识库数量已达到租户配额");
        }
    }

    /** Caller locks the owner before parent/document rows; preserve that lock order. */
    public void requireStorageCapacity(Long userId, long incomingBytes) {
        // Include inactive versions and documents awaiting deletion in the budget.
        var sizes = jdbc.queryForList("""
            SELECT v.size_bytes
            FROM knowledge_document_version v
            JOIN knowledge_document d ON d.id=v.document_id
            JOIN knowledge_base k ON k.id=d.kb_id
            WHERE k.user_id=? FOR UPDATE
            """, Long.class, userId);
        long remaining = Math.max(1, storageQuotaMb) * 1024L * 1024L;
        for (long size : sizes) remaining -= Math.min(remaining, Math.max(0, size));
        if (incomingBytes < 0 || incomingBytes > remaining) {
            throw new IllegalArgumentException("文档存储量已达到租户配额");
        }
    }
}

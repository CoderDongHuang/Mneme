package com.mneme.dto.internal;

import com.fasterxml.jackson.annotation.JsonProperty;

public record IngestionRequest(
    @JsonProperty("user_id") String userId,
    @JsonProperty("kb_id") String knowledgeBaseId,
    @JsonProperty("file_path") String filePath,
    @JsonProperty("document_id") String documentId,
    @JsonProperty("task_id") String taskId,
    @JsonProperty("source_name") String sourceName
) {
    public IngestionRequest(String userId, String knowledgeBaseId, String filePath, String documentId, String taskId) {
        this(userId, knowledgeBaseId, filePath, documentId, taskId, null);
    }
    public IngestionRequest(String userId, String knowledgeBaseId, String filePath, String documentId) {
        this(userId, knowledgeBaseId, filePath, documentId, null, null);
    }
}

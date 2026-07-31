package com.mneme.dto.internal;

import com.fasterxml.jackson.annotation.JsonProperty;

public record IngestionRequest(
    @JsonProperty("user_id") String userId,
    @JsonProperty("kb_id") String knowledgeBaseId,
    @JsonProperty("file_path") String filePath,
    @JsonProperty("document_id") String documentId
) {}

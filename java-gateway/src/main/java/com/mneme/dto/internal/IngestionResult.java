package com.mneme.dto.internal;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

public record IngestionResult(
    String status,
    @JsonProperty("document_id") String documentId,
    int chunks,
    Map<String, Object> report
) {
    public IngestionResult(String status, String documentId, int chunks) {
        this(status, documentId, chunks, Map.of());
    }
}

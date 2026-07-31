package com.mneme.dto.internal;

import com.fasterxml.jackson.annotation.JsonProperty;

public record IngestionResult(
    String status,
    @JsonProperty("document_id") String documentId,
    int chunks
) {}

package com.mneme.dto.internal;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

public final class MemoryContracts {
    private MemoryContracts() {}

    public record ReadRequest(
        @JsonProperty("user_id") String userId,
        @JsonProperty("memory_types") List<String> memoryTypes
    ) {}

    public record Entry(String category, String content, String topic) {}

    public record WriteRequest(@JsonProperty("user_id") String userId, Entry entry) {}

    public record ConfirmRequest(
        @JsonProperty("user_id") String userId,
        @JsonProperty("temp_id") String memoryId,
        String action,
        String category,
        String content,
        String topic
    ) {}

    public record ReadResult(
        @JsonProperty("user_id") String userId,
        List<Map<String, Object>> preferences,
        @JsonProperty("weak_points") List<Map<String, Object>> weakPoints,
        Map<String, Object> progress
    ) {}

    public record OperationResult(String status, String action, String message) {}
}

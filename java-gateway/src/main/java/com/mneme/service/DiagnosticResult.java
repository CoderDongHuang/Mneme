package com.mneme.service;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/** Only fixed codes and stage outcomes may cross the administrator API. */
public final class DiagnosticResult {
    private final long started = System.nanoTime();
    private final Map<String, Object> fields = new LinkedHashMap<>();

    public DiagnosticResult(boolean configured) {
        fields.put("configuration", configured ? "present" : "missing");
        fields.put("connection", "not_checked");
        fields.put("operation", "not_run");
        fields.put("cleanup", "not_required");
        fields.put("code", configured ? "NOT_RUN" : "NOT_CONFIGURED");
    }

    public DiagnosticResult stage(String name, String value) { fields.put(name, value); return this; }
    public DiagnosticResult code(String code) { fields.put("code", code); return this; }
    public Map<String, Object> finish() {
        fields.put("checked_at", Instant.now().toString());
        fields.put("latency_ms", (System.nanoTime() - started) / 1_000_000);
        return Map.copyOf(fields);
    }

    public static Map<String, Object> unavailable(String code) {
        return new DiagnosticResult(true).code(code).finish();
    }

    /** Reject arbitrary remote JSON, including error text or credentials. */
    public static Map<String, Object> remote(Map<?, ?> value) {
        if (value == null || !(value.get("configuration") instanceof String configuration)
            || !java.util.Set.of("present", "missing").contains(configuration))
            return unavailable("INVALID_DIAGNOSTIC_RESPONSE");
        var result = new DiagnosticResult("present".equals(value.get("configuration")));
        for (String key : java.util.List.of("connection", "operation", "cleanup")) {
            Object stage = value.get(key);
            if (!(stage instanceof String) || !java.util.Set.of("passed", "failed", "not_checked", "not_run", "not_required", "not_applicable").contains(stage))
                return unavailable("INVALID_DIAGNOSTIC_RESPONSE");
            result.stage(key, (String) stage);
        }
        Object code = value.get("code");
        if (!(code instanceof String) || !java.util.Set.of("OK", "NOT_CONFIGURED", "CONNECTION_FAILED",
            "OPERATION_FAILED", "CLEANUP_FAILED", "KEY_CHECK_FAILED", "BUSY").contains(code))
            return unavailable("INVALID_DIAGNOSTIC_RESPONSE");
        return result.code((String) code).finish();
    }
}

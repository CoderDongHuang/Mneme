package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.web.client.RestTemplate;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** A missing/failed read is -1, not proof of absence. Stores contain logical live data. */
final class CleanupReport {
    @FunctionalInterface interface Counter { long count() throws Exception; }
    private final Map<String, Long> counts = new LinkedHashMap<>();
    private final Map<String, Exception> failures = new LinkedHashMap<>();
    private final Instant checkedAt = Instant.now();

    void read(String store, Counter counter) {
        try { counts.put(store, counter.count()); failures.remove(store); }
        catch (Exception unavailable) { counts.put(store, -1L); failures.put(store, unavailable); }
    }

    void agent(RestTemplate http, String url, List<String> expected) {
        expected.forEach(key -> { counts.put(key, -1L); failures.remove(key); });
        try {
            Map<?, ?> result = http.getForObject(url, Map.class);
            for (String key : expected) {
                Object value = result == null ? null : result.get(key);
                // Do not accept null, strings, false or fractional values as zero.
                if (value instanceof Integer || value instanceof Long) counts.put(key, ((Number) value).longValue());
            }
        } catch (Exception unavailable) { expected.forEach(key -> failures.put(key, unavailable)); }
    }

    void requireZeroExcept(String except) {
        var remaining = counts.entrySet().stream().filter(e -> !e.getKey().equals(except) && e.getValue() != 0).toList();
        if (!remaining.isEmpty()) {
            // Only a purely throttled read is allowed to defer without consuming the
            // fault budget. Real residues or other unreadable stores remain failures.
            Exception cause = remaining.stream().allMatch(e -> failures.containsKey(e.getKey())
                && TaskRetryPolicy.decide(failures.get(e.getKey()), 0, 1, 300, Instant.now()).rateLimited())
                ? failures.get(remaining.get(0).getKey()) : null;
            throw new IllegalStateException("删除核验未通过，存在残留或无法读取的存储；请查看清理清单后重试", cause);
        }
    }

    String json(ObjectMapper mapper) {
        try {
            return mapper.writeValueAsString(Map.of("checked_at", checkedAt.toString(), "counts", counts,
                "status", counts.values().stream().allMatch(count -> count == 0) ? "verified" : "pending",
                "scope", "logical_live_data"));
        } catch (Exception error) { throw new IllegalStateException("无法保存删除核验清单", error); }
    }
}

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
    private final Instant checkedAt = Instant.now();

    void read(String store, Counter counter) {
        try { counts.put(store, counter.count()); }
        catch (Exception unavailable) { counts.put(store, -1L); }
    }

    void agent(RestTemplate http, String url, List<String> expected) {
        expected.forEach(key -> counts.put(key, -1L));
        try {
            Map<?, ?> result = http.getForObject(url, Map.class);
            for (String key : expected) {
                Object value = result == null ? null : result.get(key);
                // Do not accept null, strings, false or fractional values as zero.
                if (value instanceof Integer || value instanceof Long) counts.put(key, ((Number) value).longValue());
            }
        } catch (Exception unavailable) { /* Unknown remains visible and blocks completion. */ }
    }

    void requireZeroExcept(String except) {
        if (counts.entrySet().stream().anyMatch(e -> !e.getKey().equals(except) && e.getValue() != 0))
            throw new IllegalStateException("删除核验未通过，存在残留或无法读取的存储；请查看清理清单后重试");
    }

    String json(ObjectMapper mapper) {
        try {
            return mapper.writeValueAsString(Map.of("checked_at", checkedAt.toString(), "counts", counts,
                "status", counts.values().stream().allMatch(count -> count == 0) ? "verified" : "pending",
                "scope", "logical_live_data"));
        } catch (Exception error) { throw new IllegalStateException("无法保存删除核验清单", error); }
    }
}

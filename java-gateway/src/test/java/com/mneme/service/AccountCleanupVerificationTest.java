package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestTemplate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AccountCleanupVerificationTest {
    @Test void missingUserSnapshotCannotProveAvatarAbsence() {
        var jdbc = mock(org.springframework.jdbc.core.JdbcTemplate.class);
        var http = mock(RestTemplate.class);
        when(http.getForObject("http://agent/api/v1/admin/user/1/deletion-report", Map.class)).thenReturn(healthyAgent());
        when(jdbc.queryForObject(anyString(), eq(Long.class), eq(1L))).thenReturn(0L);
        var verification = new AccountCleanupVerification(jdbc, http, "http://agent", mock(AccountFileCleanup.class));
        var report = verification.read(1L, null);
        assertThat(report.json(new ObjectMapper())).contains("\"avatars\":-1");
        assertThatThrownBy(() -> report.requireZeroExcept(null)).isInstanceOf(IllegalStateException.class);
    }

    static Map<String, Object> healthyAgent() {
        var counts = new LinkedHashMap<String, Object>();
        for (String name : List.of("qdrant_chunks", "qdrant_collections", "fts_rows", "account_fence",
            "long_term_memories", "memory_versions", "traces", "privacy_rows", "tool_governance",
            "session_manifest", "redis_scoped_sessions", "reflection_keys", "reflection_queue_entries")) counts.put(name, 0);
        return counts;
    }

    @Test void malformedMissingAndUnknownCountsNeverBecomeZero() throws Exception {
        var http = mock(RestTemplate.class);
        for (Object bad : new Object[] {false, "0", 0.0, -1, 1}) {
            when(http.getForObject("http://agent/report", Map.class)).thenReturn(Map.of("store", bad));
            var report = new CleanupReport();
            report.agent(http, "http://agent/report", List.of("store"));
            assertThatThrownBy(() -> report.requireZeroExcept(null)).isInstanceOf(IllegalStateException.class);
            assertThat(new ObjectMapper().readTree(report.json(new ObjectMapper())).get("status").asText()).isEqualTo("pending");
        }
        when(http.getForObject("http://agent/report", Map.class)).thenReturn(Map.of());
        var missing = new CleanupReport();
        missing.agent(http, "http://agent/report", List.of("required"));
        assertThat(missing.json(new ObjectMapper())).contains("\"required\":-1");
    }
}

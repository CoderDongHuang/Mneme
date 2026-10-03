package com.mneme.service;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestTemplate;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class LearningAnalyticsTest {
    @Test void rejectedValuesNeverReachDatabase() {
        var jdbc = mock(JdbcTemplate.class);
        var service = new LearningAnalyticsService(jdbc, mock(RestTemplate.class), "http://agent");
        assertThrows(IllegalArgumentException.class, () -> service.feedback(2L, 1, "bad", "correct", "none", ""));
        assertThrows(IllegalArgumentException.class, () -> service.feedback(2L, 1, "helpful", "bad", "none", ""));
        assertThrows(IllegalArgumentException.class, () -> service.feedback(2L, 1, "helpful", "correct", "none", "x".repeat(1001)));
        verifyNoInteractions(jdbc);
    }
    @Test void ownershipIsEnforcedInFeedbackWriteAndDelete() {
        var jdbc = mock(JdbcTemplate.class);
        var service = new LearningAnalyticsService(jdbc, mock(RestTemplate.class), "http://agent");
        assertThrows(IllegalArgumentException.class, () -> service.feedback(2L, 44, "refusal", "unclear", "no_evidence", ""));
        verify(jdbc).update(argThat(sql -> sql.contains("s.user_id=?") && sql.contains("m.status='completed'")),
            eq(2L), eq("refusal"), eq("unclear"), eq("no_evidence"), eq(""), eq(44L), eq(2L));
        assertThrows(IllegalArgumentException.class, () -> service.deleteFeedback(2L, 7));
        verify(jdbc).update("DELETE FROM rag_quality_feedback WHERE id=? AND user_id=?", 7L, 2L);
    }
    @Test void summaryClampsWindowAndDoesNotInventUnavailableTraceData() {
        var jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(anyString(), any(Object[].class))).thenReturn(List.of());
        var service = new LearningAnalyticsService(jdbc, mock(RestTemplate.class), "http://agent");
        var result = service.summary(2L, 9999);
        assertEquals(90, result.get("window_days"));
        assertEquals(java.util.Map.of("status", "unavailable"), result.get("trace_quality"));
        verify(jdbc).queryForList(contains("GROUP BY topic"), eq(45), eq(45), eq(2L), eq(90));
    }
}

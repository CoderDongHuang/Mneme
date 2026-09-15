package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class WorkspaceMetricsTest {
    @Test
    void returnsUserScopedLearningMetricsAndEmptyDefaults() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        List<String> queries = new ArrayList<>();
        when(jdbc.queryForObject(anyString(), eq(Long.class), any(Object[].class)))
            .thenAnswer(invocation -> {
                String sql = invocation.getArgument(0);
                queries.add(sql);
                if (sql.contains("status='completed'")) return 1L;
                if (sql.contains("review_count>0")) return 2L;
                if (sql.contains("due_at")) return 0L;
                if (sql.contains("quiz_mistake")) return 1L;
                return 3L;
            });
        when(jdbc.queryForObject(anyString(), eq(Double.class), any(Object[].class)))
            .thenAnswer(invocation -> {
                queries.add(invocation.getArgument(0));
                return 2.5;
            });

        WorkspaceService service = new WorkspaceService(
            jdbc, new ObjectMapper().findAndRegisterModules(), new RestTemplate());
        Map<String, Object> metrics = service.metrics(7L);

        @SuppressWarnings("unchecked")
        Map<String, Object> plans = (Map<String, Object>) metrics.get("plans");
        @SuppressWarnings("unchecked")
        Map<String, Object> mistakes = (Map<String, Object>) metrics.get("mistakes");
        assertThat(plans).containsEntry("total", 3L)
            .containsEntry("completed", 1L)
            .containsEntry("completion_rate", 0.3333);
        assertThat(mistakes).containsEntry("cards_created", 1L);
        assertThat(queries).allMatch(sql -> sql.contains("user_id=?"));
    }
}

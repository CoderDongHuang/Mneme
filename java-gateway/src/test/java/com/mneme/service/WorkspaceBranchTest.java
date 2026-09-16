package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class WorkspaceBranchTest {
    @Test
    void rejectsSourceMessageThatDoesNotBelongToSourceSession() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(anyString(), any(Object[].class))).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            return sql.contains("chat_session") ? List.of(Map.of("id", 4L)) : List.of();
        });
        WorkspaceService service = new WorkspaceService(
            jdbc, new ObjectMapper().findAndRegisterModules(), new RestTemplate());

        assertThatThrownBy(() -> service.createBranch(7L, Map.of(
            "source_session_id", 4L,
            "source_message_id", 99L,
            "label", "invalid branch"
        ))).isInstanceOf(IllegalArgumentException.class).hasMessageContaining("不存在");
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }
}

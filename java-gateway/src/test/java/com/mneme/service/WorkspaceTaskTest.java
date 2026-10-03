package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class WorkspaceTaskTest {
    @Test void cancellationIsUserScopedAndCannotRaceClaim() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.update(contains("UPDATE processing_task"), eq(7L), eq("task_1"))).thenReturn(1);
        WorkspaceService service = new WorkspaceService(jdbc, new ObjectMapper(), new RestTemplate());
        assertThat(service.cancelTask(7L, "task_1")).containsEntry("status", "cancelled");
        verify(jdbc).update(contains("status IN ('pending','retry')"), eq(7L), eq("task_1"));
        verify(jdbc).update(contains("d.parse_task_id=t.task_id"), eq(7L), eq("task_1"), eq(7L));
    }
    @Test void refusesMissingForeignRunningAndDeletionTasks() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        WorkspaceService service = new WorkspaceService(jdbc, new ObjectMapper(), new RestTemplate());
        assertThatThrownBy(() -> service.cancelTask(8L, "task_1")).isInstanceOf(IllegalArgumentException.class);
        verify(jdbc).update(contains("task_type='document_ingest'"), eq(8L), eq("task_1"));
        verifyNoMoreInteractions(jdbc);
    }
}

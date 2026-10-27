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
        when(jdbc.queryForList(contains("FOR UPDATE"), eq(7L), eq("task_1")))
            .thenReturn(java.util.List.of(java.util.Map.of("status", "pending")));
        when(jdbc.update(contains("UPDATE processing_task"), eq(7L), eq("task_1"))).thenReturn(1);
        WorkspaceService service = new WorkspaceService(jdbc, new ObjectMapper(), new RestTemplate());
        var redis = mock(org.springframework.data.redis.core.StringRedisTemplate.class);
        when(redis.opsForValue()).thenReturn(mock(org.springframework.data.redis.core.ValueOperations.class));
        org.springframework.test.util.ReflectionTestUtils.setField(service, "cancellationRedis", redis);
        assertThat(service.cancelTask(7L, "task_1")).containsEntry("status", "cancelled");
        verify(jdbc).update(contains("status IN ('pending','retry')"), eq(7L), eq("task_1"));
        verify(jdbc).update(contains("d.parse_task_id=t.task_id"), eq(7L), eq("task_1"), eq(7L));
    }
    @Test void refusesMissingForeignAndDeletionTasks() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        WorkspaceService service = new WorkspaceService(jdbc, new ObjectMapper(), new RestTemplate());
        assertThatThrownBy(() -> service.cancelTask(8L, "task_1")).isInstanceOf(IllegalArgumentException.class);
        verify(jdbc).queryForList(contains("task_type='document_ingest' FOR UPDATE"), eq(8L), eq("task_1"));
        verifyNoMoreInteractions(jdbc);
    }

    @Test void retryCannotRemoveAnInFlightCancellation() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        var redis = mock(org.springframework.data.redis.core.StringRedisTemplate.class);
        when(jdbc.queryForList(contains("FOR UPDATE"), eq(7L), eq("task_1")))
            .thenReturn(java.util.List.of(java.util.Map.of("status", "cancelling")));
        WorkspaceService service = new WorkspaceService(jdbc, new ObjectMapper(), new RestTemplate());
        org.springframework.test.util.ReflectionTestUtils.setField(service, "cancellationRedis", redis);
        assertThatThrownBy(() -> service.retryTask(7L, "task_1")).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(redis);
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test void runningCancellationIsDurableAndIdempotent() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        var redis = mock(org.springframework.data.redis.core.StringRedisTemplate.class);
        org.springframework.data.redis.core.ValueOperations<String, String> values = mock(org.springframework.data.redis.core.ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(jdbc.queryForList(contains("FOR UPDATE"), eq(7L), eq("task_1")))
            .thenReturn(java.util.List.of(java.util.Map.of("status", "processing")))
            .thenReturn(java.util.List.of(java.util.Map.of("status", "cancelling")));
        WorkspaceService service = new WorkspaceService(jdbc, new ObjectMapper(), new RestTemplate());
        org.springframework.test.util.ReflectionTestUtils.setField(service, "cancellationRedis", redis);
        assertThat(service.cancelTask(7L, "task_1")).containsEntry("status", "cancelling");
        assertThat(service.cancelTask(7L, "task_1")).containsEntry("status", "cancelling");
        verify(values).set(eq("mneme:ingestion:cancel:7:task_1"), eq("1"), any(java.time.Duration.class));
        verify(jdbc).update(contains("status='cancelling'"), eq(7L), eq("task_1"));
    }
}

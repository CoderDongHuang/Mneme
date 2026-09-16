package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.ProcessingTask;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class NotificationServiceTest {
    @Test
    void readsPersistedNotificationEvents() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(anyString(), eq(7L))).thenReturn(List.of(Map.of(
            "id", 9L,
            "event_type", "task",
            "aggregate_id", "3",
            "severity", "warning",
            "payload_json", "{\"task_id\":\"task_1\",\"status\":\"retry\"}",
            "created_at", "2026-09-16 10:00:00"
        )));
        NotificationService service = new NotificationService(jdbc, new ObjectMapper());

        List<Map<String, Object>> events = service.recent(7L);

        assertThat(events).hasSize(1);
        assertThat(events.get(0)).containsEntry("task_id", "task_1")
            .containsEntry("status", "retry")
            .containsEntry("event_type", "task")
            .containsEntry("severity", "warning");
    }

    @Test
    void cleanupUsesConfiguredRetentionWindow() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        NotificationService service = new NotificationService(jdbc, new ObjectMapper());
        ReflectionTestUtils.setField(service, "retentionDays", 30);

        service.cleanupHistory();

        verify(jdbc).update(anyString(), eq(30));
    }

    @Test
    void publishPersistsTaskPayloadEvenWithoutSubscribers() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), eq(Long.class), anyLong())).thenReturn(0L);
        ProcessingTask task = new ProcessingTask();
        task.setUserId(7L);
        task.setTaskId("task_1");
        task.setTaskType("document_ingest");
        task.setAggregateId(3L);
        task.setStatus("failed");
        task.setAttemptCount(2);
        task.setMaxAttempts(3);
        NotificationService service = new NotificationService(jdbc, new ObjectMapper());

        service.publish(task);

        verify(jdbc).update(any(org.springframework.jdbc.core.PreparedStatementCreator.class), any(org.springframework.jdbc.support.KeyHolder.class));
    }

    @Test
    void publishBroadcastsPersistedEventWhenRedisIsEnabled() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), eq(Long.class), anyLong())).thenReturn(12L);
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        NotificationService service = new NotificationService(jdbc, new ObjectMapper());
        ReflectionTestUtils.setField(service, "redisEnabled", true);
        ReflectionTestUtils.setField(service, "redis", redis);
        ProcessingTask task = new ProcessingTask();
        task.setUserId(7L);
        task.setTaskId("task_redis");
        task.setAggregateId(3L);
        task.setStatus("completed");

        service.publish(task);

        verify(redis).convertAndSend(eq("mneme:notifications"), contains("task_redis"));
    }
}

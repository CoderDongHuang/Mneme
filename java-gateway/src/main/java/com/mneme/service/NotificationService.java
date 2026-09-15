package com.mneme.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.ProcessingTaskMapper;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

@Service
public class NotificationService {
    private final ProcessingTaskMapper taskMapper;
    private final ObjectMapper mapper;
    private final Map<Long, CopyOnWriteArrayList<SseEmitter>> subscribers = new ConcurrentHashMap<>();

    public NotificationService(ProcessingTaskMapper taskMapper, ObjectMapper mapper) {
        this.taskMapper = taskMapper;
        this.mapper = mapper;
    }

    public List<Map<String, Object>> recent(Long userId) {
        return taskMapper.selectList(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ProcessingTask>()
            .eq(ProcessingTask::getUserId, userId)
            .orderByDesc(ProcessingTask::getCreatedAt)
            .last("LIMIT 100"))
            .stream().map(this::payload).toList();
    }

    public SseEmitter subscribe(Long userId) {
        SseEmitter emitter = new SseEmitter(0L);
        subscribers.computeIfAbsent(userId, ignored -> new CopyOnWriteArrayList<>()).add(emitter);
        emitter.onCompletion(() -> remove(userId, emitter));
        emitter.onTimeout(() -> remove(userId, emitter));
        emitter.onError(ignored -> remove(userId, emitter));
        try {
            emitter.send(SseEmitter.event().name("ready").data(Map.of("status", "connected")));
        } catch (IOException error) {
            remove(userId, emitter);
        }
        return emitter;
    }

    public void publish(ProcessingTask task) {
        List<SseEmitter> current = subscribers.get(task.getUserId());
        if (current == null) return;
        Map<String, Object> event = payload(task);
        for (SseEmitter emitter : current) {
            try {
                emitter.send(SseEmitter.event().name("task").data(event));
            } catch (IOException error) {
                remove(task.getUserId(), emitter);
            }
        }
    }

    private Map<String, Object> payload(ProcessingTask task) {
        return Map.ofEntries(
            Map.entry("task_id", task.getTaskId() == null ? "" : task.getTaskId()),
            Map.entry("task_type", task.getTaskType() == null ? "" : task.getTaskType()),
            Map.entry("aggregate_id", task.getAggregateId() == null ? "" : task.getAggregateId()),
            Map.entry("status", task.getStatus() == null ? "" : task.getStatus()),
            Map.entry("attempt_count", task.getAttemptCount() == null ? 0 : task.getAttemptCount()),
            Map.entry("max_attempts", task.getMaxAttempts() == null ? 0 : task.getMaxAttempts()),
            Map.entry("error_code", task.getErrorCode() == null ? "" : task.getErrorCode()),
            Map.entry("error_message", task.getErrorMessage() == null ? "" : task.getErrorMessage()),
            Map.entry("created_at", task.getCreatedAt() == null ? "" : task.getCreatedAt().toString()),
            Map.entry("updated_at", task.getUpdatedAt() == null ? "" : task.getUpdatedAt().toString())
        );
    }

    private void remove(Long userId, SseEmitter emitter) {
        List<SseEmitter> current = subscribers.get(userId);
        if (current != null) {
            current.remove(emitter);
            if (current.isEmpty()) subscribers.remove(userId, (CopyOnWriteArrayList<SseEmitter>) current);
        }
    }
}

package com.mneme.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.ProcessingTask;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.sql.Statement;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicLong;
import java.util.UUID;

@Service
public class NotificationService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final Map<Long, CopyOnWriteArrayList<Subscriber>> subscribers = new ConcurrentHashMap<>();
    private final String instanceId = UUID.randomUUID().toString();

    @Autowired(required = false)
    private StringRedisTemplate redis;

    @Value("${mneme.notification-redis-enabled:false}")
    private boolean redisEnabled;

    @Value("${mneme.notification-retention-days:30}")
    private int retentionDays;

    public NotificationService(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    public List<Map<String, Object>> recent(Long userId) {
        return jdbc.queryForList("""
            SELECT id,event_type,aggregate_id,severity,payload_json,read_at,created_at
            FROM notification_event
            WHERE user_id=?
            ORDER BY created_at DESC
            LIMIT 100
            """, userId).stream().map(this::decode).toList();
    }

    public SseEmitter subscribe(Long userId) {
        SseEmitter emitter = new SseEmitter(0L);
        Subscriber subscriber = new Subscriber(emitter, latestId(userId));
        subscribers.computeIfAbsent(userId, ignored -> new CopyOnWriteArrayList<>()).add(subscriber);
        emitter.onCompletion(() -> remove(userId, subscriber));
        emitter.onTimeout(() -> remove(userId, subscriber));
        emitter.onError(ignored -> remove(userId, subscriber));
        try {
            emitter.send(SseEmitter.event().name("ready").data(Map.of("status", "connected")));
            for (Map<String, Object> event : recent(userId).stream().limit(10).toList()) {
                emitter.send(SseEmitter.event().name("task").data(event));
            }
        } catch (IOException error) {
            remove(userId, subscriber);
        }
        return emitter;
    }

    public void publish(ProcessingTask task) {
        Map<String, Object> event = payload(task);
        long eventId = persist(task.getUserId(), "task", String.valueOf(task.getAggregateId()), severity(task), event);
        event = withEventFields(event, eventId, "task", severity(task));
        for (Subscriber subscriber : subscribers.getOrDefault(task.getUserId(), new CopyOnWriteArrayList<>())) {
            send(task.getUserId(), subscriber, event);
        }
        publishToRedis(task.getUserId(), event);
    }

    private void publishToRedis(Long userId, Map<String, Object> event) {
        if (!redisEnabled || redis == null) return;
        try {
            redis.convertAndSend("mneme:notifications", mapper.writeValueAsString(Map.of(
                "origin", instanceId,
                "user_id", userId,
                "event", event
            )));
        } catch (Exception ignored) {
            // The persisted-event pump remains the delivery fallback.
        }
    }

    public void receiveRedisMessage(String message) {
        try {
            Map<String, Object> envelope = mapper.readValue(message, new TypeReference<>() {});
            if (instanceId.equals(String.valueOf(envelope.get("origin")))) return;
            Long userId = Long.valueOf(String.valueOf(envelope.get("user_id")));
            Map<String, Object> event = mapper.convertValue(envelope.get("event"), new TypeReference<>() {});
            for (Subscriber subscriber : subscribers.getOrDefault(userId, new CopyOnWriteArrayList<>())) {
                if (((Number) event.getOrDefault("id", 0)).longValue() > subscriber.lastSeen.get()) {
                    send(userId, subscriber, event);
                }
            }
        } catch (Exception ignored) {
            // Invalid broadcasts are ignored; the database remains authoritative.
        }
    }

    @Scheduled(fixedDelayString = "${mneme.notification-poll-delay-ms:2000}")
    public void pumpPersistedEvents() {
        for (Map.Entry<Long, CopyOnWriteArrayList<Subscriber>> entry : subscribers.entrySet()) {
            Long userId = entry.getKey();
            long minSeen = entry.getValue().stream()
                .mapToLong(subscriber -> subscriber.lastSeen.get())
                .min()
                .orElse(latestId(userId));
            List<Map<String, Object>> events = jdbc.queryForList("""
                SELECT id,event_type,aggregate_id,severity,payload_json,read_at,created_at
                FROM notification_event
                WHERE user_id=? AND id>?
                ORDER BY id ASC
                LIMIT 100
                """, userId, minSeen).stream().map(this::decode).toList();
            for (Map<String, Object> event : events) {
                for (Subscriber subscriber : entry.getValue()) {
                    if (((Number) event.get("id")).longValue() > subscriber.lastSeen.get()) {
                        send(userId, subscriber, event);
                    }
                }
            }
        }
    }

    @Scheduled(cron = "${mneme.notification-cleanup-cron:0 17 3 * * *}")
    public void cleanupHistory() {
        int days = Math.max(1, retentionDays);
        jdbc.update("DELETE FROM notification_event WHERE created_at < DATE_SUB(NOW(), INTERVAL ? DAY)", days);
    }

    private void send(Long userId, Subscriber subscriber, Map<String, Object> event) {
        try {
            subscriber.emitter.send(SseEmitter.event().name("task").data(event));
            long deliveredId = ((Number) event.getOrDefault("id", subscriber.lastSeen.get())).longValue();
            subscriber.lastSeen.accumulateAndGet(deliveredId, Math::max);
        } catch (IOException error) {
            remove(userId, subscriber);
        }
    }

    private long persist(Long userId, String eventType, String aggregateId, String severity, Map<String, Object> payload) {
        try {
            String payloadJson = mapper.writeValueAsString(payload);
            GeneratedKeyHolder keyHolder = new GeneratedKeyHolder();
            jdbc.update(connection -> {
                var statement = connection.prepareStatement("""
                    INSERT INTO notification_event(user_id,event_type,aggregate_id,severity,payload_json)
                    VALUES(?,?,?,?,CAST(? AS JSON))
                    """, Statement.RETURN_GENERATED_KEYS);
                statement.setLong(1, userId);
                statement.setString(2, eventType);
                statement.setString(3, aggregateId);
                statement.setString(4, severity);
                statement.setString(5, payloadJson);
                return statement;
            }, keyHolder);
            Number key = keyHolder.getKey();
            return key == null ? latestId(userId) : key.longValue();
        } catch (Exception ignored) {
            return latestId(userId);
        }
    }

    private long latestId(Long userId) {
        Long id = jdbc.queryForObject(
            "SELECT COALESCE(MAX(id),0) FROM notification_event WHERE user_id=?",
            Long.class,
            userId
        );
        return id == null ? 0L : id;
    }

    private Map<String, Object> decode(Map<String, Object> row) {
        try {
            Map<String, Object> payload = mapper.readValue(jsonText(row.get("payload_json")), new TypeReference<>() {});
            return withEventFields(
                payload,
                ((Number) row.get("id")).longValue(),
                String.valueOf(row.get("event_type")),
                String.valueOf(row.get("severity"))
            );
        } catch (Exception error) {
            return Map.of(
                "id", row.get("id"),
                "event_type", row.getOrDefault("event_type", "unknown"),
                "severity", row.getOrDefault("severity", "warning"),
                "error_message", "通知事件解析失败"
            );
        }
    }

    private Map<String, Object> withEventFields(Map<String, Object> event, long id, String eventType, String severity) {
        LinkedHashMap<String, Object> copy = new LinkedHashMap<>(event);
        copy.put("id", id);
        copy.put("event_type", eventType);
        copy.put("severity", severity);
        return copy;
    }

    private String severity(ProcessingTask task) {
        if ("failed".equals(task.getStatus())) return "error";
        if ("retry".equals(task.getStatus())) return "warning";
        return "info";
    }

    private String jsonText(Object value) {
        return value instanceof byte[] bytes ? new String(bytes, StandardCharsets.UTF_8) : String.valueOf(value);
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

    private void remove(Long userId, Subscriber subscriber) {
        List<Subscriber> current = subscribers.get(userId);
        if (current != null) {
            current.remove(subscriber);
            if (current.isEmpty()) subscribers.remove(userId, current);
        }
    }

    private record Subscriber(SseEmitter emitter, AtomicLong lastSeen) {
        Subscriber(SseEmitter emitter, long lastSeen) {
            this(emitter, new AtomicLong(lastSeen));
        }
    }
}

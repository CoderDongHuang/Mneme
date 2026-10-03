package com.mneme.service;

import com.mneme.config.RateLimitInterceptor;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.util.UriComponentsBuilder;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.*;

@Service
public class OperationsCenterService {
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    private final RestTemplate internal;
    private final RestTemplate metrics;
    private final StorageDiagnosticsService storage;
    private final String agentUrl;
    private final String prometheusUrl;
    private final Path fileRoot;
    public OperationsCenterService(JdbcTemplate jdbc, StringRedisTemplate redis, @Qualifier("healthHttp") RestTemplate internal,
        @Qualifier("monitoringHttp") RestTemplate metrics, StorageDiagnosticsService storage,
        @Value("${mneme.python-agent-url}") String agentUrl,
        @Value("${mneme.prometheus-url:}") String prometheusUrl,
        @Value("${mneme.file-storage-path:../data/files}") String fileRoot) {
        this.jdbc = jdbc; this.redis = redis; this.internal = internal; this.metrics = metrics;
        this.storage = storage; this.agentUrl = agentUrl; this.prometheusUrl = prometheusUrl;
        this.fileRoot = Path.of(fileRoot).toAbsolutePath().normalize();
    }
    public Map<String, Object> snapshot() {
        Map<String, Object> result = new LinkedHashMap<>();
        Map<String, Object> health = new LinkedHashMap<>();
        try { health.put("mysql", jdbc.queryForObject("SELECT 1", Integer.class) == 1 ? "up" : "down"); }
        catch (Exception ignored) { health.put("mysql", "down"); }
        try (var conn = redis.getConnectionFactory().getConnection()) { health.put("redis", "PONG".equals(conn.ping()) ? "up" : "down"); }
        catch (Exception ignored) { health.put("redis", "down"); }
        try { health.put("agent", internal.getForObject(agentUrl + "/health/ready", Map.class)); }
        catch (HttpStatusCodeException e) {
            try { health.put("agent", new ObjectMapper().readValue(e.getResponseBodyAsString(), Map.class)); }
            catch (Exception ignored) { health.put("agent", Map.of("status", "down")); }
        } catch (Exception ignored) { health.put("agent", Map.of("status", "down")); }
        result.put("health", health);
        result.put("storage", storage.status());
        result.put("capacity", capacity());
        result.put("rate_limits", Map.of("window_seconds", 60, "scope", "trusted-proxy validated client IP", "limits", RateLimitInterceptor.LIMITS));
        result.put("monitoring", monitoring());
        try {
            result.put("queue", jdbc.queryForList("SELECT task_type,status,COUNT(*) AS total FROM processing_task GROUP BY task_type,status"));
            result.put("sagas", jdbc.queryForList("""
                SELECT operation_id,user_id,status,current_step,attempt_count,next_attempt_at,completed_at,updated_at
                FROM account_deletion_task ORDER BY updated_at DESC LIMIT 100
                """));
            result.put("deletion_tasks", jdbc.queryForList("""
                SELECT task_id,task_type,user_id,status,attempt_count,max_attempts,error_code,next_attempt_at,updated_at
                FROM processing_task WHERE task_type IN ('document_delete','knowledge_base_delete')
                ORDER BY updated_at DESC LIMIT 100
                """));
            result.put("task_alerts", jdbc.queryForList("""
                SELECT task_id,task_type,status,error_code,attempt_count,updated_at FROM processing_task
                WHERE status IN ('failed','retry') ORDER BY updated_at DESC LIMIT 100
                """));
            result.put("task_data_status", "available");
        } catch (Exception ignored) { result.put("task_data_status", "unavailable"); }
        result.put("checked_at", Instant.now().toString());
        return result;
    }
    private Map<String, Object> capacity() {
        try {
            Path path = fileRoot;
            while (path != null && !Files.exists(path)) path = path.getParent();
            var disk = Files.getFileStore(Objects.requireNonNull(path));
            return Map.of("status", "available", "disk_total_bytes", disk.getTotalSpace(),
                "disk_usable_bytes", disk.getUsableSpace(), "scope", "gateway local volume; not object-storage bucket quota");
        } catch (Exception ignored) { return Map.of("status", "unavailable"); }
    }
    public Map<String, Object> monitoring() {
        if (prometheusUrl.isBlank()) return Map.of("status", "not_configured");
        try {
            var origin = java.net.URI.create(prometheusUrl);
            if (!List.of("http", "https").contains(origin.getScheme()) || origin.getHost() == null || origin.getUserInfo() != null)
                throw new IllegalArgumentException("invalid monitoring origin");
            Map<String, Object> values = new LinkedHashMap<>();
            values.put("status", "available"); values.put("window_seconds", 300);
            values.put("availability_target", 0.995); values.put("p95_target_seconds", 2);
            for (String metric : List.of("mneme:gateway_availability:rate5m", "mneme:gateway_latency_p95:rate5m",
                "mneme:http_availability:rate5m", "mneme:http_latency_p95:rate5m")) {
                var uri = UriComponentsBuilder.fromUriString(prometheusUrl).path("/api/v1/query").queryParam("query", metric).build().encode().toUri();
                Map<?, ?> body = metrics.getForObject(uri, Map.class);
                if (body == null || !"success".equals(body.get("status"))) throw new IllegalStateException("metrics unavailable");
                Map<?, ?> data = (Map<?, ?>) body.get("data");
                List<?> rows = (List<?>) data.get("result");
                Double value = null;
                if (rows.size() == 1) {
                    List<?> pair = (List<?>) ((Map<?, ?>) rows.get(0)).get("value");
                    double parsed = Double.parseDouble(String.valueOf(pair.get(1)));
                    if (Double.isFinite(parsed)) value = parsed;
                }
                values.put(metric, value);
            }
            Map<?, ?> alerts = metrics.getForObject(prometheusUrl + "/api/v1/alerts", Map.class);
            if (alerts == null || !"success".equals(alerts.get("status"))) throw new IllegalStateException("alerts unavailable");
            values.put("alerts", ((Map<?, ?>) alerts.get("data")).get("alerts"));
            return values;
        } catch (Exception ignored) { return Map.of("status", "unavailable"); }
    }
}

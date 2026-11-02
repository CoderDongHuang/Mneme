package com.mneme.service;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.util.Map;
import java.util.UUID;

/** Explicit administrator actions, synthetic payloads, no user-selected target. */
@Service
public class InfrastructureDiagnosticsService {
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    private final ObjectStorageService storage;
    private final PasswordResetDelivery mail;
    private final RestTemplate http;
    private final String agentUrl;
    private final String workerUrl;
    private final String workerToken;

    public InfrastructureDiagnosticsService(JdbcTemplate jdbc, StringRedisTemplate redis,
        ObjectStorageService storage, PasswordResetDelivery mail,
        @Qualifier("diagnosticHttp") RestTemplate http,
        @Value("${mneme.python-agent-url}") String agentUrl,
        @Value("${mneme.recovery-worker-url:}") String workerUrl,
        @Value("${mneme.recovery-worker-token:}") String workerToken) {
        this.jdbc = jdbc; this.redis = redis; this.storage = storage; this.mail = mail;
        this.http = http; this.agentUrl = agentUrl; this.workerUrl = workerUrl; this.workerToken = workerToken;
    }

    public Map<String, Object> check(String component, Long administrator) {
        return switch (component) {
            case "mysql" -> mysql();
            case "redis" -> redis();
            case "object_storage" -> storage.diagnose();
            case "qdrant" -> remote(agentUrl + "/health/storage/check", false);
            case "backup_keys" -> workerUrl.isBlank() || workerToken.length() < 32
                ? new DiagnosticResult(false).finish()
                : remote(workerUrl.replaceAll("/+$", "") + "/site/keys/check", true);
            case "smtp" -> smtp(administrator);
            default -> throw new IllegalArgumentException("不支持的诊断类型");
        };
    }

    Map<String, Object> mysql() {
        var result = new DiagnosticResult(jdbc.getDataSource() != null);
        String id = UUID.randomUUID().toString();
        boolean connected = false, attempted = false;
        try {
            if (!Integer.valueOf(1).equals(jdbc.queryForObject("SELECT 1", Integer.class))) throw new IllegalStateException();
            connected = true;
            result.stage("connection", "passed");
            attempted = true;
            if (jdbc.update("INSERT INTO operations_diagnostic_probe(probe_id,probe_value) VALUES (?,?)", id, "initial") != 1)
                throw new IllegalStateException();
            if (!"initial".equals(jdbc.queryForObject("SELECT probe_value FROM operations_diagnostic_probe WHERE probe_id=?", String.class, id)))
                throw new IllegalStateException();
            if (jdbc.update("UPDATE operations_diagnostic_probe SET probe_value=? WHERE probe_id=?", "updated", id) != 1
                || !"updated".equals(jdbc.queryForObject("SELECT probe_value FROM operations_diagnostic_probe WHERE probe_id=?", String.class, id)))
                throw new IllegalStateException();
            if (jdbc.update("DELETE FROM operations_diagnostic_probe WHERE probe_id=?", id) != 1) throw new IllegalStateException();
            result.stage("operation", "passed").code("OK");
        } catch (Exception ignored) {
            result.stage(connected ? "operation" : "connection", "failed")
                .code(connected ? "OPERATION_FAILED" : "CONNECTION_FAILED");
        } finally {
            if (attempted) {
                try {
                    jdbc.update("DELETE FROM operations_diagnostic_probe WHERE probe_id=?", id);
                    if (!Long.valueOf(0).equals(jdbc.queryForObject("SELECT COUNT(*) FROM operations_diagnostic_probe WHERE probe_id=?", Long.class, id)))
                        throw new IllegalStateException();
                    result.stage("cleanup", "passed");
                } catch (Exception ignored) { result.stage("cleanup", "failed").code("CLEANUP_FAILED"); }
            }
        }
        return result.finish();
    }

    Map<String, Object> redis() {
        var result = new DiagnosticResult(redis.getConnectionFactory() != null);
        String key = "mneme:diagnostics:probe:" + UUID.randomUUID();
        boolean connected = false, attempted = false;
        try {
            try (var connection = redis.getConnectionFactory().getConnection()) {
                if (!"PONG".equals(connection.ping())) throw new IllegalStateException();
            }
            connected = true;
            result.stage("connection", "passed");
            attempted = true;
            if (!Boolean.TRUE.equals(redis.opsForValue().setIfAbsent(key, "synthetic", Duration.ofSeconds(60)))
                || !"synthetic".equals(redis.opsForValue().get(key))) throw new IllegalStateException();
            if (!Boolean.TRUE.equals(redis.delete(key))) throw new IllegalStateException();
            result.stage("operation", "passed").code("OK");
        } catch (Exception ignored) {
            result.stage(connected ? "operation" : "connection", "failed")
                .code(connected ? "OPERATION_FAILED" : "CONNECTION_FAILED");
        } finally {
            if (attempted) {
                try {
                    redis.delete(key);
                    if (!Boolean.FALSE.equals(redis.hasKey(key))) throw new IllegalStateException();
                    result.stage("cleanup", "passed");
                } catch (Exception ignored) { result.stage("cleanup", "failed").code("CLEANUP_FAILED"); }
            }
        }
        return result.finish();
    }

    private Map<String, Object> remote(String url, boolean recovery) {
        var result = new DiagnosticResult(true);
        try {
            var headers = new HttpHeaders();
            if (recovery) headers.setBearerAuth(workerToken);
            Map<?, ?> body = http.exchange(url, HttpMethod.POST, new HttpEntity<>(headers), Map.class).getBody();
            return DiagnosticResult.remote(body);
        } catch (Exception ignored) { return result.stage("connection", "failed").code("CONNECTION_FAILED").finish(); }
    }

    private Map<String, Object> smtp(Long administrator) {
        var result = new DiagnosticResult(mail.configured());
        if (!mail.configured()) return result.finish();
        try {
            var users = jdbc.queryForList("SELECT email FROM user WHERE id=? AND status='active' AND email_verified_at IS NOT NULL", administrator);
            if (users.size() != 1 || !(users.get(0).get("email") instanceof String email) || email.isBlank())
                return result.code("VERIFIED_EMAIL_REQUIRED").finish();
            // Distributed throttle; a diagnostic never sends to a browser-supplied address.
            if (!Boolean.TRUE.equals(redis.opsForValue().setIfAbsent("mneme:diagnostics:smtp:" + administrator,
                "reserved", Duration.ofSeconds(60)))) return result.code("RATE_LIMITED").finish();
            mail.checkConnection();
            result.stage("connection", "passed");
            try {
                mail.sendDiagnostic(email);
                result.stage("operation", "passed").code("SMTP_ACCEPTED");
            } catch (Exception ignored) { result.stage("operation", "failed").code("OPERATION_FAILED"); }
        } catch (Exception ignored) { result.stage("connection", "failed").code("CONNECTION_FAILED"); }
        return result.finish();
    }
}

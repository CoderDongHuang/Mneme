package com.mneme.controller;

import com.mneme.service.StorageDiagnosticsService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/health")
public class HealthController {
    private final JdbcTemplate jdbcTemplate;
    private final RestTemplate restTemplate;
    private final StorageDiagnosticsService storageDiagnostics;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    public HealthController(
        JdbcTemplate jdbcTemplate,
        RestTemplate restTemplate,
        StorageDiagnosticsService storageDiagnostics
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.restTemplate = restTemplate;
        this.storageDiagnostics = storageDiagnostics;
    }

    @GetMapping
    public Map<String, Object> health() {
        Map<String, Object> components = new LinkedHashMap<>();
        boolean databaseUp = false;
        boolean agentUp = false;
        try {
            databaseUp = jdbcTemplate.queryForObject("SELECT 1", Integer.class) == 1;
        } catch (Exception ignored) {
            components.put("database", "down");
        }
        try {
            Map<?, ?> agent = restTemplate.getForObject(pythonAgentUrl + "/health", Map.class);
            agentUp = agent != null && "ok".equals(agent.get("status"));
        } catch (Exception ignored) {
            components.put("pythonAgent", "down");
        }
        components.putIfAbsent("database", databaseUp ? "up" : "down");
        components.putIfAbsent("pythonAgent", agentUp ? "up" : "down");
        return Map.of(
            "status", databaseUp && agentUp ? "ok" : "degraded",
            "service", "mneme-java-gateway",
            "components", components
        );
    }

    @GetMapping("/config")
    public Map<String, Object> config(@org.springframework.web.bind.annotation.RequestAttribute("userId") Long userId) {
        try {
            Map<?, ?> python = restTemplate.getForObject(pythonAgentUrl + "/health/config", Map.class);
            if (python == null) return Map.of("status", "unavailable");
            Map<String, Object> result = new LinkedHashMap<>();
            python.forEach((key, value) -> result.put(String.valueOf(key), value));
            result.put("storage", storageDiagnostics.status());
            result.put("tenant_isolation", Map.of(
                "relational_user_filters", true,
                "vector_collections_scoped", true,
                "memory_metadata_scoped", true
            ));
            return result;
        } catch (Exception ignored) {
            return Map.of(
                "status", "unavailable",
                "service", "mneme-java-gateway",
                "storage", storageDiagnostics.status()
            );
        }
    }
}

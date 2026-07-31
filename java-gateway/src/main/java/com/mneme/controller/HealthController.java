package com.mneme.controller;

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

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    public HealthController(JdbcTemplate jdbcTemplate, RestTemplate restTemplate) {
        this.jdbcTemplate = jdbcTemplate;
        this.restTemplate = restTemplate;
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
}

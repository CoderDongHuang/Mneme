package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.service.OperationLogService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/privacy")
public class PrivacyController {
    private final RestTemplate client;
    private final OperationLogService logs;
    private final String agentUrl;
    public PrivacyController(RestTemplate client, OperationLogService logs,
        @Value("${mneme.python-agent-url}") String agentUrl) {
        this.client = client; this.logs = logs; this.agentUrl = agentUrl;
    }
    public record Policy(@NotNull Boolean cloud_allowed, @Min(1) @Max(365) int trace_days) {}
    private String path(Long userId) { return agentUrl + "/api/v1/agent/privacy/" + userId; }
    @GetMapping public Result<Object> get(@RequestAttribute("userId") Long userId) {
        return Result.success(client.getForObject(path(userId), Object.class));
    }
    @PutMapping public Result<Object> save(@RequestAttribute("userId") Long userId, @Valid @RequestBody Policy policy) {
        Object result = client.exchange(path(userId), HttpMethod.PUT, new HttpEntity<>(policy), Object.class).getBody();
        logs.record(logs.newOperationId(), userId, "privacy_policy", userId.toString(), "saved", "completed",
            Map.of("cloud_allowed", policy.cloud_allowed(), "trace_days", policy.trace_days()), null);
        return Result.success(result);
    }
    @DeleteMapping("/traces") public Result<Object> delete(@RequestAttribute("userId") Long userId,
        @RequestParam String confirmation) {
        if (!"DELETE TRACES".equals(confirmation)) throw new IllegalArgumentException("需要确认删除 Trace");
        Object result = client.exchange(path(userId) + "/traces", HttpMethod.DELETE, HttpEntity.EMPTY, Object.class).getBody();
        logs.record(logs.newOperationId(), userId, "privacy_trace_delete", userId.toString(), "deleted", "completed", Map.of(), null);
        return Result.success(result);
    }
}

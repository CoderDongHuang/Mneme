package com.mneme.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.mneme.dto.Result;
import com.mneme.entity.AuditLog;
import com.mneme.mapper.AuditLogMapper;
import com.mneme.service.AdminAuthorizationService;
import com.mneme.service.InternalServiceTokenProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.bind.annotation.*;
import java.util.List;
import java.util.Map;

@RestController @RequestMapping("/api/v1/admin")
public class AdminController {
    private final AuditLogMapper logs;
    private final AdminAuthorizationService admins;
    private final InternalServiceTokenProvider internalTokens;
    private final RestTemplate restTemplate;
    private final String pythonAgentUrl;
    public AdminController(
        AuditLogMapper logs,
        AdminAuthorizationService admins,
        InternalServiceTokenProvider internalTokens,
        RestTemplate restTemplate,
        @Value("${mneme.python-agent-url}") String pythonAgentUrl
    ) {
        this.logs = logs;
        this.admins = admins;
        this.internalTokens = internalTokens;
        this.restTemplate = restTemplate;
        this.pythonAgentUrl = pythonAgentUrl;
    }
    @GetMapping("/audit") public Result<List<AuditLog>> audit(
        @RequestAttribute("userId") Long userId,
        @RequestHeader(value = "X-Admin-Token", required = false) String token
    ) {
        admins.requireAdmin(userId, token);
        return Result.success(logs.selectList(new LambdaQueryWrapper<AuditLog>().orderByDesc(AuditLog::getCreatedAt).last("LIMIT 200")));
    }

    @PostMapping("/secrets/internal-token/rotate")
    public Result<Map<String, Object>> rotateInternalToken(
        @RequestAttribute("userId") Long userId,
        @RequestHeader(value = "X-Admin-Token", required = false) String token,
        @RequestBody Map<String, String> request
    ) {
        admins.requireAdmin(userId, token);
        String next = request.getOrDefault("new_token", "");
        if (next.length() < 32) throw new IllegalArgumentException("新令牌至少需要 32 个字符");
        restTemplate.postForObject(
            pythonAgentUrl + "/api/v1/agent/secrets/internal-token/rotate",
            Map.of("new_token", next),
            Map.class
        );
        internalTokens.rotate(next);
        return Result.success(internalTokens.status());
    }

    @GetMapping("/secrets/internal-token")
    public Result<Map<String, Object>> internalTokenStatus(
        @RequestAttribute("userId") Long userId,
        @RequestHeader(value = "X-Admin-Token", required = false) String token
    ) {
        admins.requireAdmin(userId, token);
        return Result.success(internalTokens.status());
    }
}

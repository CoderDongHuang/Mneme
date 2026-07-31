package com.mneme.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.mneme.dto.Result;
import com.mneme.entity.AuditLog;
import com.mneme.mapper.AuditLogMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;

@RestController @RequestMapping("/api/v1/admin")
public class AdminController {
    private final AuditLogMapper logs;
    @Value("${mneme.admin-api-token:}") private String adminToken;
    public AdminController(AuditLogMapper logs) { this.logs = logs; }
    @GetMapping("/audit") public Result<List<AuditLog>> audit(@RequestHeader("X-Admin-Token") String token) {
        if (adminToken.length() < 32 || !MessageDigest.isEqual(adminToken.getBytes(StandardCharsets.UTF_8), token.getBytes(StandardCharsets.UTF_8))) throw new SecurityException("管理员凭证无效");
        return Result.success(logs.selectList(new LambdaQueryWrapper<AuditLog>().orderByDesc(AuditLog::getCreatedAt).last("LIMIT 200")));
    }
}

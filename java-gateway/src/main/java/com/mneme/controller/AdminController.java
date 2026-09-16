package com.mneme.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.mneme.dto.Result;
import com.mneme.entity.AuditLog;
import com.mneme.mapper.AuditLogMapper;
import com.mneme.service.AdminAuthorizationService;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController @RequestMapping("/api/v1/admin")
public class AdminController {
    private final AuditLogMapper logs;
    private final AdminAuthorizationService admins;
    public AdminController(AuditLogMapper logs, AdminAuthorizationService admins) {
        this.logs = logs;
        this.admins = admins;
    }
    @GetMapping("/audit") public Result<List<AuditLog>> audit(
        @RequestAttribute("userId") Long userId,
        @RequestHeader(value = "X-Admin-Token", required = false) String token
    ) {
        admins.requireAdmin(userId, token);
        return Result.success(logs.selectList(new LambdaQueryWrapper<AuditLog>().orderByDesc(AuditLog::getCreatedAt).last("LIMIT 200")));
    }
}

package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.service.AdminAuthorizationService;
import com.mneme.service.InfrastructureDiagnosticsService;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/admin/operations/check")
public class InfrastructureDiagnosticsController {
    private final AdminAuthorizationService admins;
    private final InfrastructureDiagnosticsService diagnostics;
    public InfrastructureDiagnosticsController(AdminAuthorizationService admins, InfrastructureDiagnosticsService diagnostics) {
        this.admins = admins; this.diagnostics = diagnostics;
    }
    @PostMapping("/{component}")
    public Result<Map<String, Object>> check(@RequestAttribute("userId") Long user,
        @RequestHeader(value="X-Admin-Token", required=false) String token, @PathVariable String component) {
        admins.requireAdmin(user, token);
        return Result.success(diagnostics.check(component, user));
    }
}

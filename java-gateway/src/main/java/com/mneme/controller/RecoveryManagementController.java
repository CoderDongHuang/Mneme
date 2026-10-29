package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.service.AdminAuthorizationService;
import com.mneme.service.RecoveryManagementService;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/admin/recovery")
public class RecoveryManagementController {
    @org.springframework.beans.factory.annotation.Autowired
    private com.mneme.service.SiteRecoveryService site;
    private final AdminAuthorizationService admins;
    private final RecoveryManagementService recovery;
    public RecoveryManagementController(AdminAuthorizationService admins, RecoveryManagementService recovery) {
        this.admins = admins; this.recovery = recovery;
    }
    @GetMapping("/site") public Result<?> siteHistory(@RequestAttribute("userId") Long user,
        @RequestHeader(value="X-Admin-Token", required=false) String token) {
        admins.requireAdmin(user, token); return Result.success(site.history());
    }
    @PostMapping("/site/preview") public Result<?> sitePreview(@RequestAttribute("userId") Long user,
        @RequestHeader(value="X-Admin-Token", required=false) String token, @RequestBody Map<String,String> body) {
        admins.requireAdmin(user, token); return Result.success(site.preview(body.getOrDefault("archive", "")));
    }
    @PostMapping("/site/jobs") public Result<?> siteSubmit(@RequestAttribute("userId") Long user,
        @RequestHeader(value="X-Admin-Token", required=false) String token, @RequestBody Map<String,String> body) {
        admins.requireAdmin(user, token); return Result.success(site.submit(user, body));
    }
    @GetMapping public Result<Map<String, Object>> history(@RequestAttribute("userId") Long user,
        @RequestHeader(value="X-Admin-Token", required=false) String token) {
        admins.requireAdmin(user, token); return Result.success(recovery.history());
    }
    @GetMapping("/{runId}") public Result<Map<String, Object>> evidence(@RequestAttribute("userId") Long user,
        @RequestHeader(value="X-Admin-Token", required=false) String token, @PathVariable long runId) {
        admins.requireAdmin(user, token); return Result.success(recovery.evidence(runId));
    }
    @PostMapping public Result<Map<String, Object>> dispatch(@RequestAttribute("userId") Long user,
        @RequestHeader(value="X-Admin-Token", required=false) String token, @RequestBody Map<String, String> body) {
        admins.requireAdmin(user, token); return Result.success(recovery.dispatch(user, body.get("confirmation")));
    }
}

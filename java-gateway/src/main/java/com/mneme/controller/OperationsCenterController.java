package com.mneme.controller;
import com.mneme.dto.Result;
import com.mneme.service.AdminAuthorizationService;
import com.mneme.service.OperationsCenterService;
import org.springframework.web.bind.annotation.*;
import java.util.Map;
@RestController
@RequestMapping("/api/v1/admin/operations")
public class OperationsCenterController {
    private final AdminAuthorizationService admins;
    private final OperationsCenterService operations;
    public OperationsCenterController(AdminAuthorizationService admins, OperationsCenterService operations) {
        this.admins = admins; this.operations = operations;
    }
    @GetMapping public Result<Map<String, Object>> snapshot(@RequestAttribute("userId") Long user,
        @RequestHeader(value="X-Admin-Token", required=false) String token) {
        admins.requireAdmin(user, token); return Result.success(operations.snapshot());
    }
}

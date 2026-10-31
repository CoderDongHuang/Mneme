package com.mneme.controller;
import com.mneme.dto.Result;
import com.mneme.service.AdminAuthorizationService;
import com.mneme.service.UserSettingsService;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/admin/model-keys")
public class ModelKeyRotationController {
    private final AdminAuthorizationService admins;
    private final UserSettingsService settings;
    public ModelKeyRotationController(AdminAuthorizationService admins, UserSettingsService settings) {
        this.admins = admins; this.settings = settings;
    }
    @PostMapping("/rotate")
    public Result<Map<String, Object>> rotate(@RequestAttribute("userId") Long user,
        @RequestHeader(value="X-Admin-Token", required=false) String token, @RequestBody Map<String, String> body) {
        admins.requireAdmin(user, token);
        return Result.success(settings.rotateModelKeys(body.get("expected_version")));
    }
}

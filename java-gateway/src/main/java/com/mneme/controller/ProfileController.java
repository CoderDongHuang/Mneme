package com.mneme.controller;

import com.mneme.dto.PasswordChangeRequest;
import com.mneme.dto.ProfileUpdateRequest;
import com.mneme.dto.Result;
import com.mneme.service.ProfileService;
import com.mneme.service.EmailVerificationService;
import com.mneme.dto.EmailVerificationRequest;
import com.mneme.dto.EmailVerificationConfirmRequest;
import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/profile")
public class ProfileController {
    private final ProfileService profiles;
    private final EmailVerificationService verification;
    public ProfileController(ProfileService profiles, EmailVerificationService verification) {
        this.profiles = profiles;
        this.verification = verification;
    }

    @PostMapping("/email-verification/request")
    public Result<Map<String, Object>> requestEmail(@RequestAttribute("userId") Long userId, @Valid @RequestBody EmailVerificationRequest request) {
        verification.request(userId, request.email());
        return Result.success(Map.of("expiresInSeconds", 900, "resendAfterSeconds", 60));
    }

    @PostMapping("/email-verification/confirm")
    public Result<Map<String, Object>> confirmEmail(@RequestAttribute("userId") Long userId, @Valid @RequestBody EmailVerificationConfirmRequest request) {
        verification.confirm(userId, request.token());
        return Result.success(profiles.profile(userId));
    }

    @GetMapping public Result<Map<String, Object>> get(@RequestAttribute("userId") Long userId) { return Result.success(profiles.profile(userId)); }
    @GetMapping("/sessions") public Result<?> sessions(@RequestAttribute("userId") Long userId) { return Result.success(profiles.sessions(userId)); }
    @DeleteMapping("/sessions/{sessionId}") public Result<?> revoke(@RequestAttribute("userId") Long userId, @PathVariable String sessionId) { profiles.revokeSession(userId, sessionId); return Result.success(null); }
    @PatchMapping public Result<Map<String, Object>> update(@RequestAttribute("userId") Long userId, @Valid @RequestBody ProfileUpdateRequest request) { return Result.success(profiles.update(userId, request)); }
    @PostMapping("/avatar") public Result<Map<String, Object>> avatar(@RequestAttribute("userId") Long userId, @RequestParam("file") MultipartFile file) throws IOException { return Result.success(profiles.uploadAvatar(userId, file)); }
    @GetMapping("/avatar") public ResponseEntity<byte[]> avatar(@RequestAttribute("userId") Long userId) throws IOException { return ResponseEntity.ok().contentType(MediaType.parseMediaType(profiles.avatarType(userId))).body(profiles.avatar(userId)); }
    @PostMapping("/password") public Result<Void> password(@RequestAttribute("userId") Long userId, @Valid @RequestBody PasswordChangeRequest request) { profiles.changePassword(userId, request); return Result.success(null); }
    @DeleteMapping("/account") public Result<Map<String, String>> delete(@RequestAttribute("userId") Long userId) { return Result.success(Map.of("operation_id", profiles.deleteAccount(userId), "status", "queued")); }
}

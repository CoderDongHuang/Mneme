package com.mneme.controller;

import com.mneme.dto.PasswordChangeRequest;
import com.mneme.dto.ProfileUpdateRequest;
import com.mneme.dto.Result;
import com.mneme.service.ProfileService;
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
    public ProfileController(ProfileService profiles) { this.profiles = profiles; }

    @GetMapping public Result<Map<String, Object>> get(@RequestAttribute("userId") Long userId) { return Result.success(profiles.profile(userId)); }
    @PatchMapping public Result<Map<String, Object>> update(@RequestAttribute("userId") Long userId, @Valid @RequestBody ProfileUpdateRequest request) { return Result.success(profiles.update(userId, request)); }
    @PostMapping("/avatar") public Result<Map<String, Object>> avatar(@RequestAttribute("userId") Long userId, @RequestParam("file") MultipartFile file) throws IOException { return Result.success(profiles.uploadAvatar(userId, file)); }
    @GetMapping("/avatar") public ResponseEntity<byte[]> avatar(@RequestAttribute("userId") Long userId) throws IOException { return ResponseEntity.ok().contentType(MediaType.parseMediaType(profiles.avatarType(userId))).body(profiles.avatar(userId)); }
    @PostMapping("/password") public Result<Void> password(@RequestAttribute("userId") Long userId, @Valid @RequestBody PasswordChangeRequest request) { profiles.changePassword(userId, request); return Result.success(null); }
    @DeleteMapping("/account") public Result<Void> delete(@RequestAttribute("userId") Long userId) { profiles.deleteAccount(userId); return Result.success(null); }
}

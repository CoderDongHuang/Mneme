package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.service.AuthService;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/register")
    public Result<Map<String, String>> register(@RequestBody Map<String, String> request) {
        String token = authService.register(request.get("username"), request.get("password"));
        return Result.success(Map.of("token", token));
    }

    @PostMapping("/login")
    public Result<Map<String, String>> login(@RequestBody Map<String, String> request) {
        String token = authService.login(request.get("username"), request.get("password"));
        return Result.success(Map.of("token", token));
    }
}
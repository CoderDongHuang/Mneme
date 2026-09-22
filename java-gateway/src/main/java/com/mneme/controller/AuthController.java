package com.mneme.controller;

import com.mneme.dto.AuthRequest;
import com.mneme.dto.AuthResponse;
import com.mneme.dto.PasswordResetRequest;
import com.mneme.dto.PasswordResetConfirmRequest;
import com.mneme.dto.PasswordResetStartRequest;
import com.mneme.dto.Result;
import com.mneme.service.AuthService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.beans.factory.annotation.Value;
import com.mneme.service.ProfileService;
import com.mneme.service.PasswordResetDelivery;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {
    private final AuthService authService;
    private final ProfileService profileService;
    private final PasswordResetDelivery resetDelivery;

    @Value("${mneme.secure-cookies:false}")
    private boolean secureCookies;

    public AuthController(AuthService authService, ProfileService profileService, PasswordResetDelivery resetDelivery) {
        this.authService = authService;
        this.profileService = profileService;
        this.resetDelivery = resetDelivery;
    }

    @PostMapping("/register")
    public ResponseEntity<Result<AuthResponse>> register(@Valid @RequestBody AuthRequest request) {
        return authenticated(authService.register(request.getUsername(), request.getPassword()), false);
    }

    @PostMapping("/login")
    public ResponseEntity<Result<AuthResponse>> login(@Valid @RequestBody AuthRequest request) {
        boolean remember = Boolean.TRUE.equals(request.getRemember());
        return authenticated(authService.login(request.getUsername(), request.getPassword(), remember), remember);
    }

    @PostMapping("/reset-password")
    public Result<Void> resetPassword(@Valid @RequestBody PasswordResetRequest request) {
        throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.GONE, "请使用邮箱验证码重置密码");
    }

    @PostMapping("/password-reset/request")
    public Result<java.util.Map<String, Object>> requestReset(@Valid @RequestBody PasswordResetStartRequest request) {
        try {
            String token = authService.issuePasswordResetToken(request.username(), request.email());
            resetDelivery.send(request.email(), token);
        } catch (IllegalArgumentException ignored) { }
        return Result.success(java.util.Map.of("message", "如果账号信息匹配，重置验证码已发送", "expiresInSeconds", 900));
    }

    @PostMapping("/password-reset/confirm")
    public Result<Void> confirmReset(@Valid @RequestBody PasswordResetConfirmRequest request) {
        authService.confirmPasswordReset(request.token(), request.newPassword()); return Result.success(null);
    }

    @PostMapping("/logout")
    public ResponseEntity<Result<Void>> logout(HttpServletRequest request) {
        authService.revokeToken(token(request));
        ResponseCookie cookie = ResponseCookie.from("mneme_session", "")
            .httpOnly(true).secure(secureCookies).sameSite("Strict").path("/").maxAge(0).build();
        return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE, cookie.toString()).body(Result.success(null));
    }

    private ResponseEntity<Result<AuthResponse>> authenticated(AuthResponse session, boolean remember) {
        ResponseCookie.ResponseCookieBuilder builder = ResponseCookie.from("mneme_session", session.token())
            .httpOnly(true).secure(secureCookies).sameSite("Strict").path("/");
        if (remember) builder.maxAge(java.time.Duration.ofSeconds(session.maxAgeSeconds()));
        ResponseCookie cookie = builder.build();
        return ResponseEntity.ok()
            .header(HttpHeaders.SET_COOKIE, cookie.toString())
            .body(Result.success(session));
    }

    private String token(HttpServletRequest request) {
        String authorization = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (authorization != null && authorization.startsWith("Bearer ")) return authorization.substring(7);
        if (request.getCookies() == null) return null;
        for (Cookie cookie : request.getCookies()) {
            if ("mneme_session".equals(cookie.getName())) return cookie.getValue();
        }
        return null;
    }
}

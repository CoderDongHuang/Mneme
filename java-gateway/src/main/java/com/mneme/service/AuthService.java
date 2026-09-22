package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.mneme.dto.AuthResponse;
import com.mneme.entity.User;
import com.mneme.entity.PasswordResetToken;
import com.mneme.mapper.UserMapper;
import com.mneme.mapper.PasswordResetTokenMapper;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import io.jsonwebtoken.JwtException;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.HexFormat;
import jakarta.annotation.PostConstruct;

@Service
public class AuthService {
    private final UserMapper userMapper;
    private final PasswordResetTokenMapper resetTokens;
    private final AuthSessionService sessions;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Value("${mneme.jwt-secret}")
    private String jwtSecret;

    @Value("${mneme.jwt-expiration}")
    private Long jwtExpiration;

    @Value("${mneme.jwt-remember-expiration:2592000000}")
    private Long jwtRememberExpiration;

    public AuthService(UserMapper userMapper, PasswordResetTokenMapper resetTokens, AuthSessionService sessions) {
        this.userMapper = userMapper;
        this.resetTokens = resetTokens;
        this.sessions = sessions;
    }

    public String issuePasswordResetToken(String username, String email) {
        User user = userMapper.selectOne(new LambdaQueryWrapper<User>()
            .eq(User::getUsername, username.trim()).eq(User::getEmail, email.trim().toLowerCase()));
        if (user == null) throw new IllegalArgumentException("用户名与绑定邮箱不匹配");
        requireActive(user);
        resetTokens.delete(new LambdaQueryWrapper<PasswordResetToken>().eq(PasswordResetToken::getUserId, user.getId()));
        byte[] raw = new byte[32]; new SecureRandom().nextBytes(raw);
        String token = HexFormat.of().formatHex(raw);
        PasswordResetToken record = new PasswordResetToken();
        record.setUserId(user.getId()); record.setTokenHash(hash(token));
        record.setExpiresAt(LocalDateTime.now().plusMinutes(15)); resetTokens.insert(record);
        return token;
    }

    @Transactional
    public void confirmPasswordReset(String token, String password) {
        LocalDateTime now = LocalDateTime.now();
        PasswordResetToken record = resetTokens.selectOne(new LambdaQueryWrapper<PasswordResetToken>()
            .eq(PasswordResetToken::getTokenHash, hash(token)));
        if (record == null || record.getUsedAt() != null || !record.getExpiresAt().isAfter(now)) {
            throw new IllegalArgumentException("重置链接无效或已过期");
        }
        int claimed = resetTokens.update(null, new UpdateWrapper<PasswordResetToken>()
            .eq("id", record.getId())
            .isNull("used_at")
            .gt("expires_at", now)
            .set("used_at", now));
        if (claimed != 1) throw new IllegalArgumentException("重置链接无效或已过期");
        User user = userMapper.selectById(record.getUserId());
        if (user == null) throw new IllegalArgumentException("用户不存在");
        requireActive(user);
        user.setPasswordHash(passwordEncoder.encode(password)); userMapper.updateById(user);
        sessions.revokeAll(user.getId());
    }

    private String hash(String value) { try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); } catch (Exception e) { throw new IllegalStateException(e); } }

    @PostConstruct
    void validateSecrets() {
        if (jwtSecret == null || jwtSecret.length() < 32 || jwtSecret.contains("change-in-production")) {
            throw new IllegalStateException("JWT_SECRET 必须是至少 32 字节的随机字符串");
        }
        if (jwtExpiration == null || jwtExpiration < 300_000L) {
            throw new IllegalStateException("JWT_EXPIRATION 不能短于 5 分钟");
        }
        if (jwtRememberExpiration == null || jwtRememberExpiration < jwtExpiration) {
            throw new IllegalStateException("JWT_REMEMBER_EXPIRATION 不能短于普通会话");
        }
    }

    @Transactional
    public AuthResponse register(String username, String password) {
        String normalized = username.trim();
        User existing = userMapper.selectOne(
            new LambdaQueryWrapper<User>().eq(User::getUsername, normalized)
        );
        if (existing != null) {
            throw new IllegalArgumentException("用户名已存在");
        }
        User user = new User();
        user.setUsername(normalized);
        user.setPasswordHash(passwordEncoder.encode(password));
        user.setRole("user");
        user.setStatus("active");
        userMapper.insert(user);
        return payload(user, false);
    }

    @Transactional
    public AuthResponse login(String username, String password, boolean remember) {
        User user = userMapper.selectOne(
            new LambdaQueryWrapper<User>().eq(User::getUsername, username.trim())
        );
        if (user == null || !passwordEncoder.matches(password, user.getPasswordHash())) {
            throw new IllegalArgumentException("用户名或密码错误");
        }
        requireActive(user);
        return payload(user, remember);
    }

    public Long parseUserId(String token) {
        Claims claims = Jwts.parser().verifyWith(signingKey()).build()
            .parseSignedClaims(token).getPayload();
        Long userId = claims.get("userId", Long.class);
        String sessionId = claims.get("sessionId", String.class);
        if (!sessions.isActive(sessionId, userId)) return null;
        User user = userMapper.selectById(userId);
        if (user == null || !"active".equals(user.getStatus())) {
            return null;
        }
        return userId;
    }

    private void requireActive(User user) {
        if (!"active".equals(user.getStatus())) {
            throw new IllegalArgumentException("账号当前不可用");
        }
    }

    public void revokeToken(String token) {
        if (token == null || token.isBlank()) return;
        try {
            Claims claims = Jwts.parser().verifyWith(signingKey()).build()
                .parseSignedClaims(token).getPayload();
            sessions.revoke(claims.get("sessionId", String.class));
        } catch (JwtException ignored) {
            // Logout remains idempotent for expired or malformed credentials.
        }
    }

    private AuthResponse payload(User user, boolean remember) {
        long lifetime = remember ? jwtRememberExpiration : jwtExpiration;
        LocalDateTime expiresAt = LocalDateTime.now().plusNanos(lifetime * 1_000_000L);
        String sessionId = sessions.create(user.getId(), expiresAt, remember);
        return new AuthResponse(
            generateToken(user, sessionId, lifetime),
            user.getId(),
            user.getUsername(),
            Math.max(1, lifetime / 1000L)
        );
    }

    private String generateToken(User user, String sessionId, long lifetime) {
        return Jwts.builder()
            .subject(user.getUsername())
            .claim("userId", user.getId())
            .claim("sessionId", sessionId)
            .issuedAt(new Date())
            .expiration(new Date(System.currentTimeMillis() + lifetime))
            .signWith(signingKey())
            .compact();
    }

    private SecretKey signingKey() {
        return Keys.hmacShaKeyFor(jwtSecret.getBytes(StandardCharsets.UTF_8));
    }
}

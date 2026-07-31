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

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.HexFormat;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import jakarta.annotation.PostConstruct;

@Service
public class AuthService {
    private final UserMapper userMapper;
    private final PasswordResetTokenMapper resetTokens;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Value("${mneme.jwt-secret}")
    private String jwtSecret;

    @Value("${mneme.jwt-expiration}")
    private Long jwtExpiration;

    public AuthService(UserMapper userMapper, PasswordResetTokenMapper resetTokens) {
        this.userMapper = userMapper;
        this.resetTokens = resetTokens;
    }

    public String issuePasswordResetToken(String username, String email) {
        User user = userMapper.selectOne(new LambdaQueryWrapper<User>()
            .eq(User::getUsername, username.trim()).eq(User::getEmail, email.trim().toLowerCase()));
        if (user == null) throw new IllegalArgumentException("用户名与绑定邮箱不匹配");
        resetTokens.delete(new LambdaQueryWrapper<PasswordResetToken>().eq(PasswordResetToken::getUserId, user.getId()));
        byte[] raw = new byte[32]; new SecureRandom().nextBytes(raw);
        String token = HexFormat.of().formatHex(raw);
        PasswordResetToken record = new PasswordResetToken();
        record.setUserId(user.getId()); record.setTokenHash(hash(token));
        record.setExpiresAt(LocalDateTime.now().plusMinutes(15)); resetTokens.insert(record);
        return token;
    }

    public void confirmPasswordReset(String token, String password) {
        PasswordResetToken record = resetTokens.selectOne(new LambdaQueryWrapper<PasswordResetToken>()
            .eq(PasswordResetToken::getTokenHash, hash(token)).isNull(PasswordResetToken::getUsedAt));
        if (record == null || record.getExpiresAt().isBefore(LocalDateTime.now())) throw new IllegalArgumentException("重置链接无效或已过期");
        User user = userMapper.selectById(record.getUserId());
        if (user == null) throw new IllegalArgumentException("用户不存在");
        user.setPasswordHash(passwordEncoder.encode(password)); userMapper.updateById(user);
        record.setUsedAt(LocalDateTime.now()); resetTokens.updateById(record);
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
    }

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
        userMapper.insert(user);
        return payload(user);
    }

    public AuthResponse login(String username, String password) {
        User user = userMapper.selectOne(
            new LambdaQueryWrapper<User>().eq(User::getUsername, username.trim())
        );
        if (user == null || !passwordEncoder.matches(password, user.getPasswordHash())) {
            throw new IllegalArgumentException("用户名或密码错误");
        }
        return payload(user);
    }

    public Long parseUserId(String token) {
        Claims claims = Jwts.parser().verifyWith(signingKey()).build()
            .parseSignedClaims(token).getPayload();
        return claims.get("userId", Long.class);
    }

    private AuthResponse payload(User user) {
        return new AuthResponse(generateToken(user), user.getId(), user.getUsername());
    }

    private String generateToken(User user) {
        return Jwts.builder()
            .subject(user.getUsername())
            .claim("userId", user.getId())
            .issuedAt(new Date())
            .expiration(new Date(System.currentTimeMillis() + jwtExpiration))
            .signWith(signingKey())
            .compact();
    }

    private SecretKey signingKey() {
        return Keys.hmacShaKeyFor(jwtSecret.getBytes(StandardCharsets.UTF_8));
    }
}

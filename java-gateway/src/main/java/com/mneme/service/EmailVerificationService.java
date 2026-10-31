package com.mneme.service;

import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;

/** Every email/reset mutation locks the same user row before touching tokens. */
@Service
public class EmailVerificationService {
    private final JdbcTemplate jdbc;
    private final PasswordResetDelivery mail;
    private final SecureRandom random = new SecureRandom();

    public EmailVerificationService(JdbcTemplate jdbc, PasswordResetDelivery mail) {
        this.jdbc = jdbc;
        this.mail = mail;
    }

    @Transactional
    public void updateProfile(Long userId, String nickname, String email) {
        var user = lockUser(userId);
        String next = normalizeEmail(email);
        boolean changed = !Objects.equals(normalizeEmail((String) user.get("email")), next);
        if (changed) {
            // An empty email must explicitly set SQL NULL (MyBatis skips null fields).
            try {
                jdbc.update("UPDATE user SET nickname=?,email=?,email_verified_at=NULL WHERE id=?", nickname, next, userId);
            } catch (org.springframework.dao.DuplicateKeyException duplicate) {
                throw new IllegalArgumentException("该邮箱已被绑定");
            }
            jdbc.update("DELETE FROM email_verification_token WHERE user_id=?", userId);
            jdbc.update("DELETE FROM password_reset_token WHERE user_id=?", userId);
        } else {
            jdbc.update("UPDATE user SET nickname=? WHERE id=?", nickname, userId);
        }
    }

    @Transactional
    public void request(Long userId, String expectedEmail) {
        var user = lockUser(userId);
        String email = normalizeEmail((String) user.get("email"));
        if (email == null || !email.equals(normalizeEmail(expectedEmail))) {
            throw new IllegalArgumentException("请先保存需要验证的邮箱");
        }
        if (user.get("email_verified_at") != null) throw new IllegalArgumentException("当前邮箱已验证");
        Long recent = jdbc.queryForObject("SELECT COUNT(*) FROM email_verification_token WHERE user_id=?"
            + " AND created_at>TIMESTAMPADD(SECOND,-60,UTC_TIMESTAMP(6))", Long.class, userId);
        if (recent != null && recent > 0) {
            throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "请在 60 秒后重新发送验证码");
        }
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String token = HexFormat.of().formatHex(bytes);
        jdbc.update("DELETE FROM email_verification_token WHERE user_id=?", userId);
        jdbc.update("INSERT INTO email_verification_token(user_id,email,token_hash,created_at,expires_at)"
            + " VALUES(?,?,?,UTC_TIMESTAMP(6),TIMESTAMPADD(MINUTE,15,UTC_TIMESTAMP(6)))", userId, email, hash(token));
        // A delivery failure rolls back token replacement. The raw token never leaves SMTP.
        mail.sendVerification(email, token);
    }

    @Transactional
    public void confirm(Long userId, String token) {
        var user = lockUser(userId);
        String email = normalizeEmail((String) user.get("email"));
        int consumed = jdbc.update("DELETE FROM email_verification_token WHERE user_id=? AND email=?"
            + " AND token_hash=? AND expires_at>UTC_TIMESTAMP(6)", userId, email, hash(token));
        if (consumed != 1 || email == null) throw new IllegalArgumentException("邮箱验证码无效或已过期");
        jdbc.update("UPDATE user SET email_verified_at=UTC_TIMESTAMP(6) WHERE id=?", userId);
    }

    private Map<String, Object> lockUser(Long userId) {
        var rows = jdbc.queryForList("SELECT email,email_verified_at,status FROM user WHERE id=? FOR UPDATE", userId);
        if (rows.size() != 1 || !"active".equals(rows.get(0).get("status"))) {
            throw new IllegalArgumentException("账号当前不可用");
        }
        return rows.get(0);
    }

    static String normalizeEmail(String value) {
        return value == null || value.isBlank() ? null : value.trim().toLowerCase(Locale.ROOT);
    }

    static String hash(String token) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
    }
}

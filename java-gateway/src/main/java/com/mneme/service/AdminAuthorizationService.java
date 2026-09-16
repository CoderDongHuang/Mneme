package com.mneme.service;

import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Service
public class AdminAuthorizationService {
    private final UserMapper users;

    @Value("${mneme.admin-api-token:}")
    private String adminToken;

    public AdminAuthorizationService(UserMapper users) {
        this.users = users;
    }

    public void requireAdmin(Long userId, String suppliedToken) {
        User user = users.selectById(userId);
        if (user == null || !"admin".equals(user.getRole()) || !"active".equals(user.getStatus())) {
            throw new SecurityException("需要管理员权限");
        }
        if (adminToken.length() < 32 || suppliedToken == null || !MessageDigest.isEqual(
            adminToken.getBytes(StandardCharsets.UTF_8),
            suppliedToken.getBytes(StandardCharsets.UTF_8)
        )) {
            throw new SecurityException("管理员凭证无效");
        }
    }

    public boolean configured() {
        return adminToken != null && adminToken.length() >= 32;
    }
}

package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;

@Service
public class AuthService {

    private final UserMapper userMapper;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Value("${mneme.jwt-secret}")
    private String jwtSecret;

    @Value("${mneme.jwt-expiration}")
    private Long jwtExpiration;

    public AuthService(UserMapper userMapper) {
        this.userMapper = userMapper;
    }

    public String register(String username, String password) {
        if (userMapper.selectOne(new QueryWrapper<User>().eq("username", username)) != null) {
            throw new RuntimeException("用户名已存在");
        }
        User user = new User();
        user.setUsername(username);
        user.setPasswordHash(passwordEncoder.encode(password));
        userMapper.insert(user);
        return generateToken(user.getId(), username);
    }

    public String login(String username, String password) {
        User user = userMapper.selectOne(new QueryWrapper<User>().eq("username", username));
        if (user == null || !passwordEncoder.matches(password, user.getPasswordHash())) {
            throw new RuntimeException("用户名或密码错误");
        }
        return generateToken(user.getId(), username);
    }

    private String generateToken(Long userId, String username) {
        SecretKey key = Keys.hmacShaKeyFor(jwtSecret.getBytes(StandardCharsets.UTF_8));
        return Jwts.builder()
                .subject(username)
                .claim("userId", userId)
                .issuedAt(new Date())
                .expiration(new Date(System.currentTimeMillis() + jwtExpiration))
                .signWith(key)
                .compact();
    }
}
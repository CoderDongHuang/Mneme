package com.mneme.config;

import com.mneme.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;
import jakarta.servlet.http.Cookie;

@Component
public class JwtAuthInterceptor implements HandlerInterceptor {
    private final AuthService authService;

    public JwtAuthInterceptor(AuthService authService) {
        this.authService = authService;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }
        String authorization = request.getHeader("Authorization");
        String token = authorization != null && authorization.startsWith("Bearer ")
            ? authorization.substring(7)
            : cookieToken(request.getCookies());
        if (token == null || token.isBlank()) {
            throw new SecurityException("请先登录");
        }
        Long userId = authService.parseUserId(token);
        if (userId == null) {
            throw new SecurityException("登录凭证无效");
        }
        request.setAttribute("userId", userId);
        return true;
    }

    private String cookieToken(Cookie[] cookies) {
        if (cookies == null) return null;
        for (Cookie cookie : cookies) {
            if ("mneme_session".equals(cookie.getName())) return cookie.getValue();
        }
        return null;
    }
}

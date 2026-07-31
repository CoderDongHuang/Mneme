package com.mneme.config;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;
import java.time.Duration;

@Component
public class RateLimitInterceptor implements HandlerInterceptor {
    private final StringRedisTemplate redis;
    public RateLimitInterceptor(StringRedisTemplate redis) { this.redis = redis; }

    @Override public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String path = request.getRequestURI();
        if (!path.startsWith("/api/v1/") || "OPTIONS".equalsIgnoreCase(request.getMethod())) return true;
        String bucket = path.startsWith("/api/v1/auth/") ? "auth" : path.contains("/document/upload") ? "upload" : path.contains("/chat") ? "chat" : "api";
        int limit = bucket.equals("auth") ? 12 : bucket.equals("upload") ? 20 : bucket.equals("chat") ? 60 : 240;
        String key = "mneme:rate:" + bucket + ":" + clientIp(request) + ":" + (System.currentTimeMillis() / 60_000L);
        Long count = redis.opsForValue().increment(key);
        if (count != null && count == 1) redis.expire(key, Duration.ofSeconds(70));
        if (count != null && count > limit) {
            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
            response.setHeader("Retry-After", "60");
            return false;
        }
        return true;
    }
    private String clientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        return forwarded == null || forwarded.isBlank() ? request.getRemoteAddr() : forwarded.split(",")[0].trim();
    }
}

package com.mneme.config;

import com.mneme.entity.AuditLog;
import com.mneme.mapper.AuditLogMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

@Component
public class AuditInterceptor implements HandlerInterceptor {
    private final AuditLogMapper logs;
    public AuditInterceptor(AuditLogMapper logs) { this.logs = logs; }
    @Override public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception error) {
        if ("GET".equalsIgnoreCase(request.getMethod()) || "OPTIONS".equalsIgnoreCase(request.getMethod())) return;
        try {
            AuditLog log = new AuditLog();
            Object userId = request.getAttribute("userId"); if (userId instanceof Long id) log.setUserId(id);
            log.setAction(request.getMethod()); log.setResource(request.getRequestURI()); log.setStatusCode(response.getStatus());
            String forwarded = request.getHeader("X-Forwarded-For"); log.setClientIp(forwarded == null ? request.getRemoteAddr() : forwarded.split(",")[0].trim());
            log.setTraceId(response.getHeader("X-Trace-Id")); logs.insert(log);
        } catch (Exception ignored) { }
    }
}

package com.mneme.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
import org.springframework.beans.factory.annotation.Value;
import java.util.Arrays;

@Configuration
public class WebMvcConfig implements WebMvcConfigurer {
    private final TraceIdInterceptor traceIdInterceptor;
    private final JwtAuthInterceptor jwtAuthInterceptor;
    private final RateLimitInterceptor rateLimitInterceptor;
    private final AuditInterceptor auditInterceptor;

    @Value("${mneme.cors-origins:http://localhost:5173}")
    private String corsOrigins;

    public WebMvcConfig(TraceIdInterceptor traceIdInterceptor, JwtAuthInterceptor jwtAuthInterceptor, RateLimitInterceptor rateLimitInterceptor, AuditInterceptor auditInterceptor) {
        this.traceIdInterceptor = traceIdInterceptor;
        this.jwtAuthInterceptor = jwtAuthInterceptor;
        this.rateLimitInterceptor = rateLimitInterceptor;
        this.auditInterceptor = auditInterceptor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(traceIdInterceptor);
        registry.addInterceptor(rateLimitInterceptor).addPathPatterns("/api/v1/**");
        registry.addInterceptor(jwtAuthInterceptor)
            .addPathPatterns("/api/v1/**")
            .excludePathPatterns("/api/v1/auth/**", "/api/v1/health/**", "/api/v1/admin/**");
        registry.addInterceptor(auditInterceptor).addPathPatterns("/api/v1/**");
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
            .allowedOrigins(Arrays.stream(corsOrigins.split(",")).map(String::trim).toArray(String[]::new))
            .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
            .allowedHeaders("*")
            .allowCredentials(true);
    }
}

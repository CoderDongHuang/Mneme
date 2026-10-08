package com.mneme.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.Result;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.net.InetAddress;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

@Component
public class RateLimitInterceptor implements HandlerInterceptor {
    public static final java.util.Map<String, Integer> LIMITS = java.util.Map.of("auth", 12, "upload", 20, "chat", 60, "api", 240);
    private final StringRedisTemplate redis;
    private final List<CidrBlock> trustedProxies;
    private final ObjectMapper objectMapper;

    public RateLimitInterceptor(
        StringRedisTemplate redis,
        @Value("${mneme.trusted-proxies:}") String trustedProxies,
        ObjectMapper objectMapper
    ) {
        this.redis = redis;
        this.trustedProxies = parseTrustedProxies(trustedProxies);
        this.objectMapper = objectMapper;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws IOException {
        String path = request.getRequestURI();
        if (!path.startsWith("/api/v1/") || "OPTIONS".equalsIgnoreCase(request.getMethod())) return true;
        String bucket = path.startsWith("/api/v1/auth/") ? "auth"
            : path.contains("/document/upload") ? "upload"
            : path.contains("/chat") ? "chat" : "api";
        int limit = LIMITS.get(bucket);
        long now = System.currentTimeMillis();
        String key = "mneme:rate:" + bucket + ":" + clientIp(request) + ":" + (now / 60_000L);
        Long count = redis.opsForValue().increment(key);
        if (count != null && count == 1) redis.expire(key, Duration.ofSeconds(70));
        if (count != null && count > limit) {
            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
            long retryAfter = (60_000L - now % 60_000L + 999L) / 1000L;
            response.setHeader("Retry-After", Long.toString(retryAfter));
            response.setContentType("application/json");
            response.setCharacterEncoding(StandardCharsets.UTF_8.name());
            objectMapper.writeValue(response.getWriter(), Result.error(429,
                "请求过于频繁，请在 " + retryAfter + " 秒后重试"));
            return false;
        }
        return true;
    }

    String clientIp(HttpServletRequest request) {
        String remote = request.getRemoteAddr();
        InetAddress remoteAddress = parseAddress(remote);
        if (remoteAddress == null || !isTrusted(remoteAddress)) return remote;

        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded == null || forwarded.isBlank()) return remote;
        List<String> hops = Arrays.stream(forwarded.split(",", -1))
            .map(String::trim)
            .toList();
        if (hops.isEmpty() || hops.stream().anyMatch(String::isBlank)) return remote;

        List<InetAddress> addresses = new ArrayList<>(hops.size());
        for (String hop : hops) {
            InetAddress address = parseAddress(hop);
            if (address == null) return remote;
            addresses.add(address);
        }
        for (int index = addresses.size() - 1; index >= 0; index--) {
            if (!isTrusted(addresses.get(index))) return hops.get(index);
        }
        return hops.get(0);
    }

    private boolean isTrusted(InetAddress address) {
        return trustedProxies.stream().anyMatch(block -> block.contains(address));
    }

    private static List<CidrBlock> parseTrustedProxies(String configured) {
        if (configured == null || configured.isBlank()) return List.of();
        return Arrays.stream(configured.split(","))
            .map(String::trim)
            .filter(value -> !value.isEmpty())
            .map(CidrBlock::parse)
            .toList();
    }

    private static InetAddress parseAddress(String value) {
        if (value == null || value.isBlank() || !value.matches("[0-9a-fA-F:.]+")) return null;
        try {
            return InetAddress.getByName(value);
        } catch (Exception ignored) {
            return null;
        }
    }

    private record CidrBlock(byte[] network, int prefixLength) {
        static CidrBlock parse(String value) {
            String[] parts = value.split("/", -1);
            InetAddress address = parseAddress(parts[0]);
            if (address == null || parts.length > 2) {
                throw new IllegalArgumentException("无效的可信代理网段: " + value);
            }
            int bits = address.getAddress().length * 8;
            int prefix;
            try {
                prefix = parts.length == 2 ? Integer.parseInt(parts[1]) : bits;
            } catch (NumberFormatException error) {
                throw new IllegalArgumentException("无效的可信代理网段: " + value, error);
            }
            if (prefix < 0 || prefix > bits) {
                throw new IllegalArgumentException("无效的可信代理网段: " + value);
            }
            return new CidrBlock(address.getAddress(), prefix);
        }

        boolean contains(InetAddress address) {
            byte[] candidate = address.getAddress();
            if (candidate.length != network.length) return false;
            int completeBytes = prefixLength / 8;
            int remainingBits = prefixLength % 8;
            for (int index = 0; index < completeBytes; index++) {
                if (candidate[index] != network[index]) return false;
            }
            if (remainingBits == 0) return true;
            int mask = 0xff << (8 - remainingBits);
            return (candidate[completeBytes] & mask) == (network[completeBytes] & mask);
        }
    }
}

package com.mneme.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

@Service
public class InternalServiceTokenProvider {
    private final AtomicReference<String> current;
    private final AtomicReference<String> previous;
    private volatile Instant rotatedAt;

    public InternalServiceTokenProvider(
        @Value("${mneme.internal-service-token}") String current,
        @Value("${mneme.internal-service-token-previous:}") String previous
    ) {
        validate(current);
        this.current = new AtomicReference<>(current);
        this.previous = new AtomicReference<>(previous == null ? "" : previous);
    }

    public String current() { return current.get(); }

    public void rotate(String next) {
        validate(next);
        previous.set(current.getAndSet(next));
        rotatedAt = Instant.now();
    }

    public Map<String, Object> status() {
        return Map.of(
            "current_fingerprint", fingerprint(current.get()),
            "previous_configured", !previous.get().isBlank(),
            "rotated_at", rotatedAt == null ? "" : rotatedAt.toString()
        );
    }

    private void validate(String token) {
        if (token == null || token.length() < 32) {
            throw new IllegalArgumentException("内部服务令牌至少需要 32 个字符");
        }
    }

    private String fingerprint(String token) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                .digest(token.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest).substring(0, 16);
        } catch (Exception error) {
            throw new IllegalStateException(error);
        }
    }
}

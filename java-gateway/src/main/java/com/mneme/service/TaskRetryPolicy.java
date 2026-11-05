package com.mneme.service;

import java.time.Duration;
import java.time.Instant;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Collections;
import java.util.IdentityHashMap;
import org.springframework.web.client.RestClientResponseException;

/** Persist a future retry instead of sleeping while holding a worker or lease. */
final class TaskRetryPolicy {
    static final String RATE_LIMIT_MESSAGE = "服务请求受限，任务已保留，将在退避后自动重试";
    record Decision(int attempts, boolean exhausted, long delaySeconds, boolean rateLimited) {}

    static Decision decide(Exception error, int attempts, int maxAttempts, long failureDelayCap, Instant now) {
        var seen = Collections.newSetFromMap(new IdentityHashMap<Throwable, Boolean>());
        Throwable cause = error;
        for (int depth = 0; cause != null && depth < 32 && seen.add(cause); depth++, cause = cause.getCause()) {
            if (cause instanceof RestClientResponseException response && response.getStatusCode().value() == 429) {
                String header = response.getResponseHeaders() == null ? null : response.getResponseHeaders().getFirst("Retry-After");
                return new Decision(attempts, false, retryAfter(header, now), true);
            }
        }
        int next = attempts + 1;
        return new Decision(next, next >= maxAttempts, Math.min(failureDelayCap, 1L << Math.min(next, 10)), false);
    }

    private static long retryAfter(String value, Instant now) {
        long delay = 60;
        if (value != null) {
            try { delay = Long.parseLong(value.trim()); }
            catch (NumberFormatException invalidSeconds) {
                try {
                    delay = (long) Math.ceil(Duration.between(now,
                        ZonedDateTime.parse(value.trim(), DateTimeFormatter.RFC_1123_DATE_TIME).toInstant()).toMillis() / 1000.0);
                } catch (RuntimeException invalidDate) { /* Use the conservative default. */ }
            }
        }
        return Math.max(30, Math.min(86400, delay));
    }
}

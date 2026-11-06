package com.mneme.maintenance;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.service.ObjectStorageService;
import com.mneme.service.StorageRetention;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

import java.time.Instant;
import java.util.HashSet;
import java.util.Arrays;

/** Dedicated entrypoint: no web server, Flyway, schedulers or application writers. */
public final class RetentionMain {
    public static void main(String[] args) {
        var json = new ObjectMapper();
        try {
            if (Arrays.stream(args).anyMatch(value -> !java.util.Set.of("--apply", "--offline").contains(value)))
                throw new IllegalArgumentException();
            boolean apply = Arrays.asList(args).contains("--apply");
            if (apply && !Arrays.asList(args).contains("--offline")) throw new IllegalArgumentException();
            var input = json.readTree(System.in);
            if (input == null || !input.isObject()) throw new IllegalArgumentException();
            var allowed = java.util.Set.of("versions", "version_days", "task_days", "orphan_hours", "cache_hours", "cache_bytes", "pinned_locations");
            input.fieldNames().forEachRemaining(name -> { if (!allowed.contains(name)) throw new IllegalArgumentException(); });
            var pins = new HashSet<String>();
            if (input.has("pinned_locations")) {
                if (!input.get("pinned_locations").isArray()) throw new IllegalArgumentException();
                for (var value : input.get("pinned_locations")) {
                    if (!value.isTextual() || value.textValue().isBlank()) throw new IllegalArgumentException();
                    pins.add(value.textValue());
                }
            }
            var policy = new StorageRetention.Policy(
                number(input, "versions", 10), number(input, "version_days", 30),
                number(input, "task_days", 30), number(input, "orphan_hours", 24),
                number(input, "cache_hours", 24), longNumber(input, "cache_bytes", 1073741824L), pins);
            var source = new DriverManagerDataSource(env("SPRING_DATASOURCE_URL", ""),
                env("SPRING_DATASOURCE_USERNAME", "mneme_gateway"), env("SPRING_DATASOURCE_PASSWORD", ""));
            var storage = new ObjectStorageService(env("STORAGE_BACKEND", "local"),
                env("FILE_STORAGE_PATH", "../data/files"), env("OBJECT_STORAGE_ENDPOINT", ""),
                env("OBJECT_STORAGE_ACCESS_KEY", ""), env("OBJECT_STORAGE_SECRET_KEY", ""),
                env("OBJECT_STORAGE_BUCKET", "mneme"), false);
            // DATETIME values share the application's UTC session convention.
            try (var connection = source.getConnection()) {
                var jdbc = new JdbcTemplate(new SingleConnectionDataSource(connection, true));
                jdbc.execute("SET time_zone = '+00:00'");
                System.out.println(json.writeValueAsString(new StorageRetention(jdbc, storage).run(policy, apply, Instant.now())));
            }
        } catch (Exception error) {
            // Paths, database URLs, task bodies and credentials must not enter operator logs.
            System.out.println("{\"status\":\"failed\",\"code\":\"retention_failed\"}");
            System.exit(1);
        }
    }

    private static long longNumber(com.fasterxml.jackson.databind.JsonNode input, String name, long fallback) {
        var value = input.get(name);
        if (value == null) return fallback;
        if (!value.isIntegralNumber() || !value.canConvertToLong()) throw new IllegalArgumentException();
        return value.longValue();
    }
    private static int number(com.fasterxml.jackson.databind.JsonNode input, String name, int fallback) {
        long value = longNumber(input, name, fallback);
        if (value > Integer.MAX_VALUE || value < Integer.MIN_VALUE) throw new IllegalArgumentException();
        return (int) value;
    }
    private static String env(String name, String fallback) {
        return System.getenv().getOrDefault(name, fallback);
    }
}

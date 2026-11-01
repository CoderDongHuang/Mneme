package com.mneme.service;

import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

@Service
public class AccountDeletionService {
    private static final Logger log = LoggerFactory.getLogger(AccountDeletionService.class);
    private static final List<String> STEPS = List.of(
        "queued", "knowledge_cleanup", "memory_cleanup", "session_cleanup",
        "file_cleanup", "avatar_cleanup", "user_delete"
    );
    private final UserMapper users;
    private final JdbcTemplate jdbc;
    private final RestTemplate restTemplate;
    private final OperationLogService operations;
    private final String pythonAgentUrl;
    private final Path fileRoot;
    private final int maxAttempts;
    private final ObjectStorageService storage;
    private final TaskLeaseService leases;

    public AccountDeletionService(
        UserMapper users,
        JdbcTemplate jdbc,
        RestTemplate restTemplate,
        OperationLogService operations,
        @Value("${mneme.python-agent-url}") String pythonAgentUrl,
        @Value("${mneme.file-storage-path:../data/files}") String fileStoragePath,
        @Value("${mneme.account-deletion-max-attempts:8}") int maxAttempts,
        ObjectStorageService storage,
        TaskLeaseService leases
    ) {
        this.users = users;
        this.jdbc = jdbc;
        this.restTemplate = restTemplate;
        this.operations = operations;
        this.pythonAgentUrl = pythonAgentUrl;
        this.fileRoot = Path.of(fileStoragePath).toAbsolutePath().normalize();
        this.maxAttempts = Math.max(1, maxAttempts);
        this.storage = storage;
        this.leases = leases;
    }

    @Transactional
    public String enqueue(Long userId) {
        List<Long> locked = jdbc.queryForList(
            "SELECT id FROM user WHERE id=? FOR UPDATE", Long.class, userId);
        if (locked.isEmpty()) return "";
        User user = users.selectById(userId);
        if (user == null) return "";
        List<Map<String, Object>> existing = jdbc.queryForList("""
            SELECT operation_id FROM account_deletion_task
            WHERE user_id=?
            ORDER BY id DESC LIMIT 1
            """, userId);
        if (!existing.isEmpty()) return String.valueOf(existing.get(0).get("operation_id"));

        String operationId = operations.newOperationId();
        jdbc.update("UPDATE user SET status='deleting' WHERE id=?", userId);
        jdbc.update("""
            INSERT INTO account_deletion_task(
                operation_id,user_id,status,current_step,attempt_count,next_attempt_at
            ) VALUES(?,?,'pending','queued',0,NOW())
            """, operationId, userId);
        operations.record(operationId, userId, "account_delete", userId.toString(),
            "queued", "pending", Map.of(), null);
        return operationId;
    }

    @Scheduled(fixedDelayString = "${mneme.account-deletion-poll-delay-ms:3000}")
    public void poll() {
        recoverAbandoned();
        List<Map<String, Object>> candidates = jdbc.queryForList("""
            SELECT id FROM account_deletion_task
            WHERE status IN ('pending','retry') AND next_attempt_at<=NOW()
            ORDER BY created_at LIMIT 5
            """);
        for (Map<String, Object> candidate : candidates) {
            long id = ((Number) candidate.get("id")).longValue();
            var lease = leases.claim(TaskLeaseService.Queue.ACCOUNT_DELETION, id, false);
            if (lease != null) try (lease) {
                lease.startHeartbeat();
                try { execute(lease); }
                catch (TaskLeaseService.LostLease lost) { log.info("账号删除执行权已转移: taskId={}", id); }
            }
        }
    }

    void execute(TaskLeaseService.Lease lease) {
        long taskId = lease.id();
        Map<String, Object> task = lease.write(row -> row);
        String operationId = String.valueOf(task.get("operation_id"));
        Long userId = ((Number) task.get("user_id")).longValue();
        int attempts = ((Number) task.get("attempt_count")).intValue();
        String currentStep = String.valueOf(task.get("current_step"));
        try {
            User user = users.selectById(userId);
            for (int index = Math.max(0, STEPS.indexOf(currentStep) + 1); index < STEPS.size(); index++) {
                String step = STEPS.get(index);
                lease.renew();
                // Slow HTTP/object operations run outside MySQL transactions; the next
                // fenced commit refuses their result if another owner took over.
                if (!"user_delete".equals(step)) runStep(step, userId, user);
                lease.write(row -> {
                    if ("user_delete".equals(step)) users.deleteById(userId);
                    jdbc.update("UPDATE account_deletion_task SET current_step=?,error_message=NULL WHERE id=? AND owner_token=? AND lease_fence=?",
                        step, taskId, lease.owner(), lease.fence());
                    operations.record(operationId, userId, "account_delete", userId.toString(),
                        step, "completed", Map.of("attempts", attempts), null);
                    return null;
                });
            }
            lease.write(row -> {
                jdbc.update("UPDATE account_deletion_task SET completed_at=UTC_TIMESTAMP(6) WHERE id=? AND owner_token=? AND lease_fence=?",
                    taskId, lease.owner(), lease.fence());
                lease.finish("completed", null);
                return null;
            });
        } catch (TaskLeaseService.LostLease lost) {
            log.info("账号删除执行权已转移: operationId={}", operationId);
        } catch (Exception error) {
            int nextAttempt = attempts + 1;
            boolean exhausted = nextAttempt >= maxAttempts;
            long delay = Math.min(3600, 1L << Math.min(nextAttempt, 10));
            try {
                lease.write(row -> {
                    jdbc.update("UPDATE account_deletion_task SET attempt_count=?,next_attempt_at=TIMESTAMPADD(SECOND,?,UTC_TIMESTAMP(6))"
                        + " WHERE id=? AND owner_token=? AND lease_fence=?", nextAttempt, delay, taskId, lease.owner(), lease.fence());
                    jdbc.update("UPDATE user SET status=? WHERE id=? AND status IN ('deleting','deletion_failed')",
                        exhausted ? "deletion_failed" : "deleting", userId);
                    operations.record(operationId, userId, "account_delete", userId.toString(),
                        String.valueOf(row.get("current_step")), exhausted ? "failed" : "retry", Map.of("attempts", nextAttempt), error);
                    lease.finish(exhausted ? "failed" : "retry", safeError(error));
                    return null;
                });
            } catch (TaskLeaseService.LostLease lost) {
                return; // A stale owner must not publish failure over its successor.
            }
            log.warn("账号删除任务失败: operationId={}, attempt={}/{}", operationId, nextAttempt, maxAttempts, error);
        }
    }

    private void runStep(String step, Long userId, User snapshot) throws Exception {
        String id = userId.toString();
        switch (step) {
            case "knowledge_cleanup" -> restTemplate.delete(pythonAgentUrl + "/api/v1/knowledge/admin/user/" + id);
            case "memory_cleanup" -> restTemplate.delete(pythonAgentUrl + "/api/v1/memory/admin/user/" + id);
            case "session_cleanup" -> cleanupSessions(userId);
            case "file_cleanup" -> {
                storage.deleteUserPrefix(userId);
                deleteDirectory(fileRoot.resolve(id).normalize());
            }
            case "avatar_cleanup" -> {
                if (snapshot != null && snapshot.getAvatarPath() != null) {
                    Files.deleteIfExists(Path.of(snapshot.getAvatarPath()));
                }
            }
            default -> throw new IllegalArgumentException("未知删除步骤: " + step);
        }
    }

    private void cleanupSessions(Long userId) {
        // The Agent's UI list prunes old entries and may be missing entirely.
        // Keep MySQL rows until all cache batches and the local manifest succeed.
        long after = 0;
        while (true) {
            List<Long> batch = jdbc.queryForList("SELECT id FROM chat_session WHERE user_id=? AND id>? ORDER BY id LIMIT 1000",
                Long.class, userId, after);
            if (batch.isEmpty()) break;
            Map<?, ?> receipt = restTemplate.postForObject(pythonAgentUrl + "/api/v1/admin/user/" + userId + "/session-cache",
                Map.of("session_ids", batch.stream().map(String::valueOf).toList()), Map.class);
            if (receipt == null || !"verified".equals(receipt.get("status"))
                || !integerEquals(receipt.get("redis_sessions"), 0)
                || !integerEquals(receipt.get("checked_sessions"), batch.size())) {
                throw new IllegalStateException("会话缓存清理未通过读回核验");
            }
            after = batch.get(batch.size() - 1);
        }
        restTemplate.delete(pythonAgentUrl + "/api/v1/admin/user/" + userId);
    }

    private static boolean integerEquals(Object value, long expected) {
        return (value instanceof Integer || value instanceof Long) && ((Number) value).longValue() == expected;
    }

    private void deleteDirectory(Path directory) throws Exception {
        if (!directory.startsWith(fileRoot) || !Files.exists(directory)) return;
        try (var paths = Files.walk(directory)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) {
                Files.deleteIfExists(path);
            }
        }
    }

    private void recoverAbandoned() {
        leases.recover(TaskLeaseService.Queue.ACCOUNT_DELETION);
    }

    private String safeError(Exception error) {
        String message = error.getMessage();
        return (message == null ? error.getClass().getSimpleName() : message).substring(
            0, Math.min(message == null ? error.getClass().getSimpleName().length() : message.length(), 2000));
    }
}

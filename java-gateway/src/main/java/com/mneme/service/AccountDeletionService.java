package com.mneme.service;

import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.UUID;

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

    public AccountDeletionService(
        UserMapper users,
        JdbcTemplate jdbc,
        RestTemplate restTemplate,
        OperationLogService operations,
        @Value("${mneme.python-agent-url}") String pythonAgentUrl,
        @Value("${mneme.file-storage-path:../data/files}") String fileStoragePath,
        @Value("${mneme.account-deletion-max-attempts:8}") int maxAttempts,
        ObjectStorageService storage
    ) {
        this.users = users;
        this.jdbc = jdbc;
        this.restTemplate = restTemplate;
        this.operations = operations;
        this.pythonAgentUrl = pythonAgentUrl;
        this.fileRoot = Path.of(fileStoragePath).toAbsolutePath().normalize();
        this.maxAttempts = Math.max(1, maxAttempts);
        this.storage = storage;
    }

    public String enqueue(Long userId) {
        User user = users.selectById(userId);
        if (user == null) return "";
        List<Map<String, Object>> existing = jdbc.queryForList("""
            SELECT operation_id FROM account_deletion_task
            WHERE user_id=? AND status IN ('pending','retry','processing')
            ORDER BY id DESC LIMIT 1
            """, userId);
        if (!existing.isEmpty()) return String.valueOf(existing.get(0).get("operation_id"));

        String operationId = operations.newOperationId();
        user.setStatus("deleting");
        users.updateById(user);
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
            if (claim(id)) execute(id);
        }
    }

    private boolean claim(long id) {
        return jdbc.update("""
            UPDATE account_deletion_task
            SET status='processing',locked_at=NOW(),locked_by=?
            WHERE id=? AND status IN ('pending','retry') AND next_attempt_at<=NOW()
            """, workerId(), id) == 1;
    }

    void execute(long taskId) {
        Map<String, Object> task = jdbc.queryForMap(
            "SELECT * FROM account_deletion_task WHERE id=?", taskId);
        String operationId = String.valueOf(task.get("operation_id"));
        Long userId = ((Number) task.get("user_id")).longValue();
        int attempts = ((Number) task.get("attempt_count")).intValue();
        String currentStep = String.valueOf(task.get("current_step"));
        try {
            User user = users.selectById(userId);
            for (int index = Math.max(0, STEPS.indexOf(currentStep) + 1); index < STEPS.size(); index++) {
                String step = STEPS.get(index);
                runStep(step, userId, user);
                jdbc.update("""
                    UPDATE account_deletion_task
                    SET current_step=?,error_message=NULL,updated_at=NOW()
                    WHERE id=?
                    """, step, taskId);
                operations.record(operationId, userId, "account_delete", userId.toString(),
                    step, "completed", Map.of("attempts", attempts), null);
            }
            jdbc.update("""
                UPDATE account_deletion_task
                SET status='completed',locked_at=NULL,locked_by=NULL,completed_at=NOW(),error_message=NULL
                WHERE id=?
                """, taskId);
        } catch (Exception error) {
            int nextAttempt = attempts + 1;
            boolean exhausted = nextAttempt >= maxAttempts;
            long delay = Math.min(3600, 1L << Math.min(nextAttempt, 10));
            jdbc.update("""
                UPDATE account_deletion_task
                SET status=?,attempt_count=?,next_attempt_at=DATE_ADD(NOW(), INTERVAL ? SECOND),
                    locked_at=NULL,locked_by=NULL,error_message=?
                WHERE id=?
                """, exhausted ? "failed" : "retry", nextAttempt, delay,
                safeError(error), taskId);
            User user = users.selectById(userId);
            if (user != null) {
                user.setStatus(exhausted ? "deletion_failed" : "deleting");
                users.updateById(user);
            }
            operations.record(operationId, userId, "account_delete", userId.toString(),
                currentStep, exhausted ? "failed" : "retry", Map.of("attempts", nextAttempt), error);
            log.warn("账号删除任务失败: operationId={}, attempt={}/{}", operationId, nextAttempt, maxAttempts, error);
        }
    }

    private void runStep(String step, Long userId, User snapshot) throws Exception {
        String id = userId.toString();
        switch (step) {
            case "knowledge_cleanup" -> restTemplate.delete(pythonAgentUrl + "/api/v1/knowledge/admin/user/" + id);
            case "memory_cleanup" -> restTemplate.delete(pythonAgentUrl + "/api/v1/memory/admin/user/" + id);
            case "session_cleanup" -> restTemplate.delete(pythonAgentUrl + "/api/v1/admin/user/" + id);
            case "file_cleanup" -> {
                storage.deleteUserPrefix(userId);
                deleteDirectory(fileRoot.resolve(id).normalize());
            }
            case "avatar_cleanup" -> {
                if (snapshot != null && snapshot.getAvatarPath() != null) {
                    Files.deleteIfExists(Path.of(snapshot.getAvatarPath()));
                }
            }
            case "user_delete" -> users.deleteById(userId);
            default -> throw new IllegalArgumentException("未知删除步骤: " + step);
        }
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
        jdbc.update("""
            UPDATE account_deletion_task
            SET status='retry',next_attempt_at=NOW(),locked_at=NULL,locked_by=NULL
            WHERE status='processing' AND locked_at < DATE_SUB(NOW(), INTERVAL 5 MINUTE)
            """);
    }

    private String workerId() {
        return System.getenv().getOrDefault("HOSTNAME", "local") + ":" + UUID.randomUUID().toString().substring(0, 8);
    }

    private String safeError(Exception error) {
        String message = error.getMessage();
        return (message == null ? error.getClass().getSimpleName() : message).substring(
            0, Math.min(message == null ? error.getClass().getSimpleName().length() : message.length(), 2000));
    }
}

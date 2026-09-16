package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.internal.IngestionRequest;
import com.mneme.dto.internal.IngestionResult;
import com.mneme.entity.KnowledgeDocument;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.KnowledgeBaseMapper;
import com.mneme.mapper.KnowledgeDocumentMapper;
import com.mneme.mapper.ProcessingTaskMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestTemplate;
import io.micrometer.core.instrument.MeterRegistry;

import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

@Service
public class ProcessingTaskService {
    private static final Logger log = LoggerFactory.getLogger(ProcessingTaskService.class);
    private final ProcessingTaskMapper taskMapper;
    private final KnowledgeDocumentMapper documentMapper;
    private final KnowledgeBaseMapper knowledgeBaseMapper;
    private final ObjectMapper objectMapper;
    private final RestTemplate restTemplate;
    private final MeterRegistry meterRegistry;
    private final NotificationService notificationService;
    private final JdbcTemplate jdbc;
    private final ObjectStorageService storage;

    @Autowired(required = false)
    private OperationLogService operationLog;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    @Value("${mneme.file-storage-path:./data/files}")
    private String fileStoragePath;

    public ProcessingTaskService(
        ProcessingTaskMapper taskMapper,
        KnowledgeDocumentMapper documentMapper,
        KnowledgeBaseMapper knowledgeBaseMapper,
        ObjectMapper objectMapper,
        RestTemplate restTemplate,
        MeterRegistry meterRegistry,
        NotificationService notificationService,
        JdbcTemplate jdbc,
        ObjectStorageService storage
    ) {
        this.taskMapper = taskMapper;
        this.documentMapper = documentMapper;
        this.knowledgeBaseMapper = knowledgeBaseMapper;
        this.objectMapper = objectMapper;
        this.restTemplate = restTemplate;
        this.meterRegistry = meterRegistry;
        this.notificationService = notificationService;
        this.jdbc = jdbc;
        this.storage = storage;
    }

    @Scheduled(fixedDelayString = "${mneme.task-poll-delay-ms:2000}")
    public void poll() {
        recoverAbandonedTasks();
        List<ProcessingTask> tasks = taskMapper.selectList(
            new LambdaQueryWrapper<ProcessingTask>()
                .in(ProcessingTask::getStatus, "pending", "retry")
                .le(ProcessingTask::getNextAttemptAt, LocalDateTime.now())
                .orderByAsc(ProcessingTask::getCreatedAt)
                .last("LIMIT 5")
        );
        for (ProcessingTask task : tasks) {
            if (claim(task)) {
                ProcessingTask claimed = taskMapper.selectById(task.getId());
                if (claimed == null) continue;
                notificationService.publish(claimed);
                execute(claimed);
            }
        }
    }

    private boolean claim(ProcessingTask task) {
        boolean claimed = taskMapper.update(null, new LambdaUpdateWrapper<ProcessingTask>()
            .eq(ProcessingTask::getId, task.getId())
            .in(ProcessingTask::getStatus, "pending", "retry")
            .set(ProcessingTask::getStatus, "processing")
            .set(ProcessingTask::getLockedAt, LocalDateTime.now())
            .set(ProcessingTask::getLockedBy, hostName())) == 1;
        if (claimed) record(task, "claim", "processing", Map.of("locked_by", hostName()), null);
        return claimed;
    }

    private void execute(ProcessingTask task) {
        try {
            if ("document_ingest".equals(task.getTaskType())) {
                ingest(task);
            } else if ("document_delete".equals(task.getTaskType())) {
                deleteDocument(task);
            } else if ("knowledge_base_delete".equals(task.getTaskType())) {
                deleteKnowledgeBase(task);
            } else {
                throw new IllegalArgumentException("未知任务类型: " + task.getTaskType());
            }
            complete(task);
            record(task, "complete", "completed", Map.of(), null);
            meterRegistry.counter("mneme.processing.tasks", "type", task.getTaskType(), "outcome", "completed").increment();
        } catch (Exception error) {
            retryOrFail(task, error);
        }
    }

    private void ingest(ProcessingTask task) throws Exception {
        JsonNode payload = objectMapper.readTree(task.getPayload());
        Path localFile = storage.materialize(payload.path("file_path").asText());
        IngestionRequest request = new IngestionRequest(
            payload.path("user_id").asText(),
            payload.path("kb_id").asText(),
            localFile.toString(),
            payload.path("document_id").asText()
        );
        IngestionResult result = restTemplate.postForObject(
            pythonAgentUrl + "/api/v1/knowledge/internal/ingest", request, IngestionResult.class
        );
        if (result == null || !"done".equals(result.status())) {
            throw new IllegalStateException("Python Agent 未完成解析任务");
        }
        KnowledgeDocument document = documentMapper.selectById(task.getAggregateId());
        if (document != null) {
            document.setStatus("ready");
            document.setChunkCount(result.chunks());
            document.setErrorMessage(null);
            documentMapper.updateById(document);
        }
    }

    private void deleteDocument(ProcessingTask task) throws Exception {
        JsonNode payload = objectMapper.readTree(task.getPayload());
        String userId = payload.path("user_id").asText();
        String kbId = payload.path("kb_id").asText();
        String documentId = payload.path("document_id").asText();
        restTemplate.delete(pythonAgentUrl + "/api/v1/knowledge/admin/documents/" + documentId
            + "?user_id=" + userId + "&kb_id=" + kbId);
        List<Map<String, Object>> versions = jdbc.queryForList(
            "SELECT file_path FROM knowledge_document_version WHERE document_id=?", task.getAggregateId());
        if (versions.isEmpty()) versions = List.of(Map.of("file_path", payload.path("file_path").asText()));
        for (Map<String, Object> version : versions) {
            storage.delete(String.valueOf(version.get("file_path")));
        }
        documentMapper.deleteById(task.getAggregateId());
    }

    @Transactional
    protected void deleteKnowledgeBase(ProcessingTask task) throws Exception {
        JsonNode payload = objectMapper.readTree(task.getPayload());
        String userId = payload.path("user_id").asText();
        String knowledgeBaseId = payload.path("kb_id").asText();
        restTemplate.delete(
            pythonAgentUrl + "/api/v1/knowledge/admin/collections/" + knowledgeBaseId + "?user_id=" + userId
        );
        storage.deleteKnowledgeBasePrefix(Long.valueOf(userId), Long.valueOf(knowledgeBaseId));
        Path root = Path.of(fileStoragePath).toAbsolutePath().normalize();
        Path directory = root.resolve(userId).resolve(knowledgeBaseId).normalize();
        if (directory.startsWith(root) && Files.exists(directory)) {
            Path checkedDirectory = checkedStoragePath(directory.toString(), false);
            try (var paths = Files.walk(checkedDirectory)) {
                paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                    try { Files.deleteIfExists(path); }
                    catch (Exception error) { throw new IllegalStateException(error); }
                });
            }
        }
        knowledgeBaseMapper.deleteById(task.getAggregateId());
    }

    private Path checkedStoragePath(String rawPath, boolean requireRegularFile) {
        Path root = Path.of(fileStoragePath).toAbsolutePath().normalize();
        Path path = Path.of(rawPath).toAbsolutePath().normalize();
        if (!path.startsWith(root)
            || (requireRegularFile && !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS))) {
            throw new IllegalStateException("文档原文件路径无效");
        }
        Path current = root;
        for (Path part : root.relativize(path)) {
            current = current.resolve(part);
            if (Files.isSymbolicLink(current)) {
                throw new IllegalStateException("文档原文件路径无效");
            }
        }
        return path;
    }

    private void complete(ProcessingTask task) {
        task.setStatus("completed");
        task.setLockedAt(null);
        task.setLockedBy(null);
        task.setErrorCode(null);
        task.setErrorMessage(null);
        taskMapper.updateById(task);
        notificationService.publish(task);
    }

    private void retryOrFail(ProcessingTask task, Exception error) {
        int attempts = (task.getAttemptCount() == null ? 0 : task.getAttemptCount()) + 1;
        int maxAttempts = task.getMaxAttempts() == null ? 3 : task.getMaxAttempts();
        boolean exhausted = attempts >= maxAttempts;
        task.setAttemptCount(attempts);
        task.setStatus(exhausted ? "failed" : "retry");
        task.setNextAttemptAt(LocalDateTime.now().plusSeconds(Math.min(300, 1L << attempts)));
        task.setLockedAt(null);
        task.setLockedBy(null);
        task.setErrorCode(error.getClass().getSimpleName());
        task.setErrorMessage(error.getMessage());
        taskMapper.updateById(task);
        notificationService.publish(task);
        record(task, "retry_or_fail", task.getStatus(), Map.of("attempts", attempts), error);
        meterRegistry.counter(
            "mneme.processing.tasks", "type", task.getTaskType(), "outcome", exhausted ? "failed" : "retry"
        ).increment();
        if ("document_ingest".equals(task.getTaskType())) {
            KnowledgeDocument document = documentMapper.selectById(task.getAggregateId());
            if (document != null) {
                document.setStatus(exhausted ? "failed" : "parsing");
                document.setErrorMessage(error.getMessage());
                documentMapper.updateById(document);
            }
        }
        if ("document_delete".equals(task.getTaskType())) {
            KnowledgeDocument document = documentMapper.selectById(task.getAggregateId());
            if (document != null) {
                document.setStatus("delete_failed");
                document.setErrorMessage(error.getMessage());
                documentMapper.updateById(document);
            }
        }
        log.warn("任务执行失败: taskId={}, attempt={}/{}", task.getTaskId(), attempts, task.getMaxAttempts(), error);
    }

    private void recoverAbandonedTasks() {
        taskMapper.update(null, new LambdaUpdateWrapper<ProcessingTask>()
            .eq(ProcessingTask::getStatus, "processing")
            .lt(ProcessingTask::getLockedAt, LocalDateTime.now().minusMinutes(5))
            .set(ProcessingTask::getStatus, "retry")
            .set(ProcessingTask::getNextAttemptAt, LocalDateTime.now())
            .set(ProcessingTask::getLockedAt, null)
            .set(ProcessingTask::getLockedBy, null));
    }

    private String hostName() {
        return System.getenv().getOrDefault("HOSTNAME", "local-worker");
    }

    private void record(
        ProcessingTask task,
        String step,
        String status,
        Map<String, ?> payload,
        Exception error
    ) {
        if (operationLog != null) {
            operationLog.record(
                task.getTaskId(),
                task.getUserId(),
                task.getTaskType(),
                String.valueOf(task.getAggregateId()),
                step,
                status,
                payload,
                error
            );
        }
    }
}

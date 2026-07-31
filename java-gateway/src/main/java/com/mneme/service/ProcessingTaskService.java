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
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;
import io.micrometer.core.instrument.MeterRegistry;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;

@Service
public class ProcessingTaskService {
    private static final Logger log = LoggerFactory.getLogger(ProcessingTaskService.class);
    private final ProcessingTaskMapper taskMapper;
    private final KnowledgeDocumentMapper documentMapper;
    private final KnowledgeBaseMapper knowledgeBaseMapper;
    private final ObjectMapper objectMapper;
    private final RestTemplate restTemplate;
    private final MeterRegistry meterRegistry;

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
        MeterRegistry meterRegistry
    ) {
        this.taskMapper = taskMapper;
        this.documentMapper = documentMapper;
        this.knowledgeBaseMapper = knowledgeBaseMapper;
        this.objectMapper = objectMapper;
        this.restTemplate = restTemplate;
        this.meterRegistry = meterRegistry;
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
                execute(taskMapper.selectById(task.getId()));
            }
        }
    }

    private boolean claim(ProcessingTask task) {
        return taskMapper.update(null, new LambdaUpdateWrapper<ProcessingTask>()
            .eq(ProcessingTask::getId, task.getId())
            .in(ProcessingTask::getStatus, "pending", "retry")
            .set(ProcessingTask::getStatus, "processing")
            .set(ProcessingTask::getLockedAt, LocalDateTime.now())
            .set(ProcessingTask::getLockedBy, hostName())) == 1;
    }

    private void execute(ProcessingTask task) {
        try {
            if ("document_ingest".equals(task.getTaskType())) {
                ingest(task);
            } else if ("knowledge_base_delete".equals(task.getTaskType())) {
                deleteKnowledgeBase(task);
            } else {
                throw new IllegalArgumentException("未知任务类型: " + task.getTaskType());
            }
            complete(task);
            meterRegistry.counter("mneme.processing.tasks", "type", task.getTaskType(), "outcome", "completed").increment();
        } catch (Exception error) {
            retryOrFail(task, error);
        }
    }

    private void ingest(ProcessingTask task) throws Exception {
        JsonNode payload = objectMapper.readTree(task.getPayload());
        IngestionRequest request = new IngestionRequest(
            payload.path("user_id").asText(),
            payload.path("kb_id").asText(),
            payload.path("file_path").asText(),
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

    @Transactional
    protected void deleteKnowledgeBase(ProcessingTask task) throws Exception {
        JsonNode payload = objectMapper.readTree(task.getPayload());
        String userId = payload.path("user_id").asText();
        String knowledgeBaseId = payload.path("kb_id").asText();
        restTemplate.delete(
            pythonAgentUrl + "/api/v1/knowledge/admin/collections/" + knowledgeBaseId + "?user_id=" + userId
        );
        Path directory = Path.of(fileStoragePath, userId, knowledgeBaseId).normalize();
        Path root = Path.of(fileStoragePath).normalize();
        if (directory.startsWith(root) && Files.exists(directory)) {
            try (var paths = Files.walk(directory)) {
                paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                    try { Files.deleteIfExists(path); }
                    catch (Exception error) { throw new IllegalStateException(error); }
                });
            }
        }
        knowledgeBaseMapper.deleteById(task.getAggregateId());
    }

    private void complete(ProcessingTask task) {
        task.setStatus("completed");
        task.setLockedAt(null);
        task.setLockedBy(null);
        task.setErrorCode(null);
        task.setErrorMessage(null);
        taskMapper.updateById(task);
    }

    private void retryOrFail(ProcessingTask task, Exception error) {
        int attempts = task.getAttemptCount() + 1;
        boolean exhausted = attempts >= task.getMaxAttempts();
        task.setAttemptCount(attempts);
        task.setStatus(exhausted ? "failed" : "retry");
        task.setNextAttemptAt(LocalDateTime.now().plusSeconds(Math.min(300, 1L << attempts)));
        task.setLockedAt(null);
        task.setLockedBy(null);
        task.setErrorCode(error.getClass().getSimpleName());
        task.setErrorMessage(error.getMessage());
        taskMapper.updateById(task);
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
}

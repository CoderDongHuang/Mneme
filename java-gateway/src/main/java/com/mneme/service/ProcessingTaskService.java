package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
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
    private final TaskLeaseService leases;

    @Autowired(required = false)
    private OperationLogService operationLog;
    @Autowired(required = false)
    private org.springframework.data.redis.core.StringRedisTemplate cancellationRedis;

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
        ObjectStorageService storage,
        TaskLeaseService leases
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
        this.leases = leases;
    }

    @Scheduled(fixedDelayString = "${mneme.task-poll-delay-ms:2000}")
    public void poll() {
        recoverAbandonedTasks();
        List<ProcessingTask> tasks = taskMapper.selectList(
            new LambdaQueryWrapper<ProcessingTask>()
                .in(ProcessingTask::getStatus, "pending", "retry")
                .le(ProcessingTask::getNextAttemptAt, LocalDateTime.now(java.time.ZoneOffset.UTC))
                .orderByAsc(ProcessingTask::getCreatedAt)
                .last("LIMIT 5")
        );
        for (ProcessingTask task : tasks) {
            run(task, false);
        }
    }

    private void run(ProcessingTask task, boolean cleanup) {
        if (List.of("document_ingest", "document_index_repair").contains(task.getTaskType()) && ingestionActive(task)) return;
        var lease = leases.claim(TaskLeaseService.Queue.PROCESSING, task.getId(), cleanup);
        if (lease == null) return;
        try (lease) {
            lease.startHeartbeat();
            // Keep the claimed attempt, not a subsequent owner's mutable row snapshot.
            lease.write(row -> {
                task.setStatus(String.valueOf(row.get("status")));
                task.setAttemptCount(((Number) row.get("attempt_count")).intValue());
                record(task, "claim", task.getStatus(), Map.of("owner", lease.owner(), "fence", lease.fence()), null);
                notificationService.publish(task);
                return null;
            });
            if (cleanup) finishCancelled(task, lease);
            else execute(task, lease);
        } catch (TaskLeaseService.LostLease lost) {
            log.info("任务执行权已转移: {}", task.getTaskId());
        } catch (Exception error) {
            log.warn("任务等待恢复清理: {}", task.getTaskId());
        }
    }

    private void execute(ProcessingTask task, TaskLeaseService.Lease lease) {
        try {
            lease.renew();
            if ("document_ingest".equals(task.getTaskType())) {
                ingest(task, lease);
            } else if ("document_index_repair".equals(task.getTaskType())) {
                repairIndex(task, lease);
            } else if ("document_delete".equals(task.getTaskType())) {
                deleteDocument(task, lease);
            } else if ("knowledge_base_delete".equals(task.getTaskType())) {
                deleteKnowledgeBase(task, lease);
            } else {
                throw new IllegalArgumentException("未知任务类型: " + task.getTaskType());
            }
            if ("cancelled".equals(task.getStatus()) || "cancelling".equals(task.getStatus())) return;
            if (!"completed".equals(task.getStatus()) && finishCancelled(task, lease)) return;
            if ("completed".equals(task.getStatus())) {
                record(task, "complete", "completed", Map.of(), null);
                meterRegistry.counter("mneme.processing.tasks", "type", task.getTaskType(), "outcome", "completed").increment();
            }
        } catch (TaskLeaseService.LostLease lost) {
            log.info("任务结果因执行权转移而丢弃: {}", task.getTaskId());
        } catch (Exception error) {
            try { retryOrFail(task, lease, error); }
            catch (Exception cleanupError) { log.warn("任务等待恢复清理: {}", task.getTaskId(), cleanupError); }
        }
    }

    private void ingest(ProcessingTask task, TaskLeaseService.Lease lease) throws Exception {
        JsonNode payload = objectMapper.readTree(task.getPayload());
        Path localFile = storage.materialize(payload.path("file_path").asText());
        lease.renew();
        long generation = lease.write(row -> {
            if (!"processing".equals(row.get("status"))) throw new TaskLeaseService.LostLease();
            KnowledgeDocument document = documentMapper.selectForUpdate(task.getAggregateId());
            if (document == null || !java.util.Objects.equals(document.getParseTaskId(), task.getTaskId())
                || "deleting".equals(document.getStatus())) throw new IllegalStateException("文档已变更，拒绝解析");
            long next = Math.addExact(document.getIndexGeneration(), 1);
            if (documentMapper.advanceGeneration(task.getAggregateId(), document.getIndexGeneration()) != 1)
                throw new IllegalStateException("解析代已变化，拒绝分配");
            record(task, "source_ready", "processing", Map.of("index_generation", next), null);
            return next;
        });
        IngestionRequest request = new IngestionRequest(
            payload.path("user_id").asText(),
            payload.path("kb_id").asText(),
            localFile.toString(),
            payload.path("document_id").asText(), task.getTaskId(), payload.path("source_name").asText(null), generation
        );
        IngestionResult result = restTemplate.postForObject(
            pythonAgentUrl + "/api/v1/knowledge/internal/ingest", request, IngestionResult.class
        );
        if (finishCancelled(task, lease)) return;
        if (result == null || !("done".equals(result.status()) || "partial".equals(result.status()))) {
            throw new IllegalStateException("Python Agent 未完成解析任务");
        }
        boolean persisted = lease.write(row -> {
            if (!"processing".equals(row.get("status"))) return false;
            try { persistIngestion(task, result, lease); }
            catch (TaskLeaseService.LostLease lost) { throw lost; }
            catch (Exception error) { throw new IllegalStateException(error); }
            return true;
        });
        if (!persisted) finishCancelled(task, lease);
    }

    private void persistIngestion(ProcessingTask task, IngestionResult result, TaskLeaseService.Lease lease) throws Exception {
        KnowledgeDocument document = documentMapper.selectForUpdate(task.getAggregateId());
        if (document == null) throw new IllegalStateException("文档已删除，拒绝发布索引");
        if (!java.util.Objects.equals(document.getParseTaskId(), task.getTaskId()) || "deleting".equals(document.getStatus())
            || !("doc_" + task.getAggregateId()).equals(result.documentId())) {
            throw new IllegalStateException("文档已转入其他解析任务，拒绝覆盖结果");
        }
        Map<String, Object> report = result.report() == null ? Map.of() : result.report();
        Object rawGeneration = report.get("index_generation");
        if (!(rawGeneration instanceof Number) || new java.math.BigDecimal(rawGeneration.toString()).longValueExact() != document.getIndexGeneration())
            throw new IllegalStateException("解析代不匹配，拒绝旧 worker 结果");
        record(task, "index_ready", "processing", Map.of("chunks", result.chunks(), "index_generation", document.getIndexGeneration()), null);
        boolean indexPending = report.containsKey("vector_index_version") &&
            (!java.util.Objects.equals(report.get("vector_index_version"), report.get("lexical_index_version"))
            || !"ready".equals(report.get("index_status")));
        boolean partial = "partial".equals(result.status());
        document.setStatus(indexPending ? "index_pending" : partial ? "partial" : "ready");
        document.setChunkCount(result.chunks());
        document.setErrorMessage(indexPending ? "向量索引可用，词法索引待修复" : partial ? "部分页面或解析步骤未完成，请查看解析报告后重试" : null);
        document.setParseReport(objectMapper.writeValueAsString(report));
        documentMapper.updateById(document);
        Object hash = report.get("content_sha256");
        if (hash != null) jdbc.update("UPDATE knowledge_document_version SET parse_report=? WHERE document_id=? AND sha256=?",
            document.getParseReport(), document.getId(), String.valueOf(hash));
        // Publish document readiness and task completion under the same cancellation lock.
        completeLocked(task, lease);
    }

    private void repairIndex(ProcessingTask task, TaskLeaseService.Lease lease) throws Exception {
        JsonNode payload = objectMapper.readTree(task.getPayload());
        String expected = payload.path("expected_version").asText();
        IngestionResult result = restTemplate.postForObject(pythonAgentUrl + "/api/v1/knowledge/internal/reconcile-index",
            Map.of("user_id", payload.path("user_id").asText(), "kb_id", payload.path("kb_id").asText(),
                "document_id", payload.path("document_id").asText(), "task_id", task.getTaskId(), "expected_version", expected),
            IngestionResult.class);
        if (result == null || !"done".equals(result.status()) || result.report() == null
            || !expected.equals(result.report().get("vector_index_version"))
            || !expected.equals(result.report().get("lexical_index_version"))
            || !"ready".equals(result.report().get("index_status"))) {
            throw new IllegalStateException("词法索引修复未通过版本核验");
        }
        lease.write(row -> {
            if (!"processing".equals(row.get("status"))) throw new TaskLeaseService.LostLease();
            KnowledgeDocument document = documentMapper.selectById(task.getAggregateId());
            if (document == null || !task.getTaskId().equals(document.getParseTaskId()))
                throw new IllegalStateException("文档已变更，拒绝覆盖索引状态");
            try {
                var report = objectMapper.readValue(document.getParseReport(), new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {});
                if (!expected.equals(report.get("vector_index_version"))) throw new IllegalStateException("文档索引版本已变化");
                report.putAll(result.report());
                report.remove("index_error");
                boolean partial = report.get("warnings") instanceof List<?> warnings && !warnings.isEmpty();
                report.put("status", partial ? "partial" : "done");
                persistIngestion(task, new IngestionResult(partial ? "partial" : "done", result.documentId(), result.chunks(), report), lease);
            } catch (TaskLeaseService.LostLease lost) { throw lost; }
            catch (Exception error) { throw new IllegalStateException(error); }
            return null;
        });
    }

    private void deleteDocument(ProcessingTask task, TaskLeaseService.Lease lease) throws Exception {
        JsonNode payload = objectMapper.readTree(task.getPayload());
        String userId = payload.path("user_id").asText();
        String kbId = payload.path("kb_id").asText();
        String documentId = payload.path("document_id").asText();
        List<Map<String, Object>> versions = jdbc.queryForList(
            "SELECT file_path FROM knowledge_document_version WHERE document_id=?", task.getAggregateId());
        var locations = new java.util.LinkedHashSet<String>();
        versions.forEach(version -> locations.add(String.valueOf(version.get("file_path"))));
        locations.add(payload.path("file_path").asText());
        Exception failure = null;
        try {
            restTemplate.delete(pythonAgentUrl + "/api/v1/knowledge/admin/documents/" + documentId
                + "?user_id=" + userId + "&kb_id=" + kbId);
            for (String location : locations) {
                lease.renew();
                storage.delete(location);
            }
        } catch (TaskLeaseService.LostLease lost) { throw lost; }
        catch (Exception error) { failure = error; }
        var report = new CleanupReport();
        report.agent(restTemplate, pythonAgentUrl + "/api/v1/knowledge/admin/deletion-report?user_id=" + userId
            + "&kb_id=" + kbId + "&document_id=" + documentId, List.of("qdrant_chunks", "fts_rows"));
        report.read("files", () -> {
            long count = 0;
            for (String location : locations) count += storage.countLocation(location);
            return count;
        });
        report.read("mysql_rows", () -> documentRowCount(task.getAggregateId()));
        saveCleanupReport(task, lease, report);
        if (failure != null) throw failure;
        report.requireZeroExcept("mysql_rows");
        lease.write(row -> {
            documentMapper.deleteById(task.getAggregateId());
            report.read("mysql_rows", () -> documentRowCount(task.getAggregateId()));
            report.requireZeroExcept("");
            saveCleanupReportLocked(task, lease, report);
            completeLocked(task, lease);
            return null;
        });
    }

    private long documentRowCount(Long documentId) {
        return jdbc.queryForObject("""
            SELECT (SELECT COUNT(*) FROM knowledge_document WHERE id=?)
                +(SELECT COUNT(*) FROM knowledge_document_version WHERE document_id=?)
                +(SELECT COUNT(*) FROM knowledge_document_tag WHERE document_id=?)
            """, Long.class, documentId, documentId, documentId);
    }

    private long knowledgeBaseRowCount(Long kbId, List<Long> documentIds) {
        long count = jdbc.queryForObject("""
            SELECT (SELECT COUNT(*) FROM knowledge_base WHERE id=?)
                +(SELECT COUNT(*) FROM knowledge_document WHERE kb_id=?)
            """, Long.class, kbId, kbId);
        for (Long documentId : documentIds) count += documentRowCount(documentId);
        return count;
    }

    private void saveCleanupReport(ProcessingTask task, TaskLeaseService.Lease lease, CleanupReport report) {
        lease.write(row -> { saveCleanupReportLocked(task, lease, report); return null; });
    }

    private void saveCleanupReportLocked(ProcessingTask task, TaskLeaseService.Lease lease, CleanupReport report) {
        jdbc.update("UPDATE processing_task SET cleanup_report=? WHERE id=? AND owner_token=? AND lease_fence=?",
            report.json(objectMapper), task.getId(), lease.owner(), lease.fence());
    }

    private void deleteKnowledgeBase(ProcessingTask task, TaskLeaseService.Lease lease) throws Exception {
        JsonNode payload = objectMapper.readTree(task.getPayload());
        String userId = payload.path("user_id").asText();
        String knowledgeBaseId = payload.path("kb_id").asText();
        List<Long> documentIds = jdbc.queryForList("SELECT id FROM knowledge_document WHERE kb_id=?", Long.class, knowledgeBaseId);
        // Keep every version until all external stores pass readback. This is also
        // the deletion manifest for caches whose S3 object was already removed.
        List<String> locations = jdbc.queryForList("""
            SELECT file_path FROM knowledge_document WHERE kb_id=?
            UNION SELECT v.file_path FROM knowledge_document_version v
                JOIN knowledge_document d ON d.id=v.document_id WHERE d.kb_id=?
            """, String.class, knowledgeBaseId, knowledgeBaseId);
        Path root = Path.of(fileStoragePath).toAbsolutePath().normalize();
        Path directory = checkedStoragePath(root.resolve(userId).resolve(knowledgeBaseId).toString(), false);
        Exception failure = null;
        try {
            restTemplate.delete(pythonAgentUrl + "/api/v1/knowledge/admin/collections/" + knowledgeBaseId + "?user_id=" + userId);
            lease.renew();
            for (String location : locations) { lease.renew(); storage.delete(location); }
            storage.deleteKnowledgeBasePrefix(Long.valueOf(userId), Long.valueOf(knowledgeBaseId));
            if (ObjectStorageService.countPath(directory) > 0) try (var paths = Files.walk(directory)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) { lease.renew(); Files.deleteIfExists(path); }
            }
        } catch (TaskLeaseService.LostLease lost) { throw lost; }
        catch (Exception error) { failure = error; }
        var report = new CleanupReport();
        report.agent(restTemplate, pythonAgentUrl + "/api/v1/knowledge/admin/deletion-report?user_id=" + userId
            + "&kb_id=" + knowledgeBaseId, List.of("qdrant_chunks", "fts_rows", "qdrant_collections"));
        report.read("files", () -> {
            long count = ObjectStorageService.countPath(directory);
            for (String location : locations) count += storage.countLocation(location);
            return count;
        });
        report.read("object_prefix", () -> storage.countKnowledgeBasePrefix(Long.valueOf(userId), Long.valueOf(knowledgeBaseId)));
        report.read("mysql_rows", () -> knowledgeBaseRowCount(task.getAggregateId(), documentIds));
        saveCleanupReport(task, lease, report);
        if (failure != null) throw failure;
        report.requireZeroExcept("mysql_rows");
        lease.write(row -> {
            knowledgeBaseMapper.deleteById(task.getAggregateId());
            report.read("mysql_rows", () -> knowledgeBaseRowCount(task.getAggregateId(), documentIds));
            report.requireZeroExcept("");
            saveCleanupReportLocked(task, lease, report);
            completeLocked(task, lease);
            return null;
        });
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

    private void completeLocked(ProcessingTask task, TaskLeaseService.Lease lease) {
        jdbc.update("UPDATE processing_task SET error_code=NULL WHERE id=? AND owner_token=? AND lease_fence=?",
            task.getId(), lease.owner(), lease.fence());
        lease.finish("completed", null);
        task.setStatus("completed");
        task.setLockedAt(null);
        task.setLockedBy(null);
        task.setErrorCode(null);
        task.setErrorMessage(null);
        notificationService.publish(task);
    }

    private void retryOrFail(ProcessingTask task, TaskLeaseService.Lease lease, Exception error) {
        if (finishCancelled(task, lease)) return;
        boolean updated = lease.write(row -> {
            if (!"processing".equals(row.get("status"))) return false;
            retryOrFailLocked(task, lease, error);
            return true;
        });
        if (!updated) finishCancelled(task, lease);
    }

    private void retryOrFailLocked(ProcessingTask task, TaskLeaseService.Lease lease, Exception error) {
        int attempts = (task.getAttemptCount() == null ? 0 : task.getAttemptCount()) + 1;
        int maxAttempts = task.getMaxAttempts() == null ? 3 : task.getMaxAttempts();
        boolean exhausted = attempts >= maxAttempts;
        task.setAttemptCount(attempts);
        task.setStatus(exhausted ? "failed" : "retry");
        task.setNextAttemptAt(LocalDateTime.now(java.time.ZoneOffset.UTC).plusSeconds(Math.min(300, 1L << Math.min(attempts, 10))));
        task.setLockedAt(null);
        task.setLockedBy(null);
        task.setErrorCode(error.getClass().getSimpleName());
        task.setErrorMessage(error.getMessage());
        jdbc.update("UPDATE processing_task SET attempt_count=?,next_attempt_at=TIMESTAMPADD(SECOND,?,UTC_TIMESTAMP(6)),error_code=?"
            + " WHERE id=? AND owner_token=? AND lease_fence=?", attempts, Math.min(300, 1L << Math.min(attempts, 10)),
            task.getErrorCode(), task.getId(), lease.owner(), lease.fence());
        lease.finish(task.getStatus(), error.getMessage());
        record(task, "retry_or_fail", task.getStatus(), Map.of("attempts", attempts), error);
        meterRegistry.counter(
            "mneme.processing.tasks", "type", task.getTaskType(), "outcome", exhausted ? "failed" : "retry"
        ).increment();
        if ("document_ingest".equals(task.getTaskType())) {
            KnowledgeDocument document = documentMapper.selectById(task.getAggregateId());
            if (document != null && task.getTaskId().equals(document.getParseTaskId())) {
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
        if ("document_index_repair".equals(task.getTaskType())) {
            KnowledgeDocument document = documentMapper.selectById(task.getAggregateId());
            if (document != null && task.getTaskId().equals(document.getParseTaskId())) {
                document.setStatus("index_pending");
                document.setErrorMessage("向量索引可用，词法索引待修复；请在任务中心重试");
                documentMapper.updateById(document);
            }
        }
        log.warn("任务执行失败: taskId={}, attempt={}/{}", task.getTaskId(), attempts, task.getMaxAttempts(), error);
        notificationService.publish(task);
    }

    private void recoverAbandonedTasks() {
        leases.recover(TaskLeaseService.Queue.PROCESSING);
        List<ProcessingTask> cancelled = taskMapper.selectList(new LambdaQueryWrapper<ProcessingTask>()
            .eq(ProcessingTask::getStatus, "cancelling")
            .last("AND (owner_token IS NULL OR lease_until<=UTC_TIMESTAMP(6)) LIMIT 10"));
        for (ProcessingTask task : cancelled) {
            run(task, true);
        }
    }

    private boolean finishCancelled(ProcessingTask task, TaskLeaseService.Lease lease) {
        if (!"document_ingest".equals(task.getTaskType()) || task.getTaskId() == null) return false;
        String status = lease.write(row -> String.valueOf(row.get("status")));
        if (!"cancelling".equals(status)) return false;
        task.setStatus("cancelling");
        if (ingestionActive(task)) return true;
        try {
            JsonNode payload = objectMapper.readTree(task.getPayload());
            restTemplate.delete(pythonAgentUrl + "/api/v1/knowledge/internal/cancelled-documents/" + payload.path("document_id").asText()
                + "?user_id=" + payload.path("user_id").asText() + "&kb_id=" + payload.path("kb_id").asText());
            lease.write(row -> {
                jdbc.update("UPDATE knowledge_document SET status='failed',chunk_count=0,error_message='任务已由用户取消' WHERE id=? AND parse_task_id=?", task.getAggregateId(), task.getTaskId());
                lease.finish("cancelled", null);
                record(task, "cancel", "cancelled", Map.of(), null);
                task.setStatus("cancelled");
                notificationService.publish(task);
                return null;
            });
            task.setStatus("cancelled");
            return true;
        } catch (TaskLeaseService.LostLease lost) { throw lost;
        } catch (Exception error) {
            throw new IllegalStateException("取消后的索引清理尚未完成", error);
        }
    }

    private boolean ingestionActive(ProcessingTask task) {
        return cancellationRedis != null && Boolean.TRUE.equals(cancellationRedis.hasKey(
            "mneme:ingestion:active:" + task.getUserId() + ":" + task.getTaskId()));
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

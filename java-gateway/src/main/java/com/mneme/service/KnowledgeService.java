package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.mneme.entity.KnowledgeBase;
import com.mneme.entity.KnowledgeDocument;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.KnowledgeBaseMapper;
import com.mneme.mapper.KnowledgeDocumentMapper;
import com.mneme.mapper.ProcessingTaskMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.Set;

@Service
public class KnowledgeService {
    private static final Set<String> SUPPORTED_EXTENSIONS = Set.of(
        ".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".csv", ".md", ".txt", ".html", ".htm"
    );
    private final KnowledgeBaseMapper kbMapper;
    private final KnowledgeDocumentMapper docMapper;
    private final ProcessingTaskMapper taskMapper;
    private final ObjectMapper objectMapper;

    @Value("${mneme.file-storage-path:./data/files}")
    private String fileStoragePath;

    public KnowledgeService(
        KnowledgeBaseMapper kbMapper,
        KnowledgeDocumentMapper docMapper,
        ProcessingTaskMapper taskMapper,
        ObjectMapper objectMapper
    ) {
        this.kbMapper = kbMapper;
        this.docMapper = docMapper;
        this.taskMapper = taskMapper;
        this.objectMapper = objectMapper;
    }

    public KnowledgeBase createKb(Long userId, String name, String description) {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("知识库名称不能为空");
        }
        KnowledgeBase kb = new KnowledgeBase();
        kb.setUserId(userId);
        kb.setName(name.trim());
        kb.setDescription(description == null ? "" : description.trim());
        kb.setStatus("active");
        kbMapper.insert(kb);
        kb.setChromaCollectionId("user_" + userId + "_kb_" + kb.getId());
        kbMapper.updateById(kb);
        return kb;
    }

    public List<KnowledgeBase> listKb(Long userId) {
        return kbMapper.selectList(new LambdaQueryWrapper<KnowledgeBase>()
            .eq(KnowledgeBase::getUserId, userId)
            .eq(KnowledgeBase::getStatus, "active")
            .orderByDesc(KnowledgeBase::getUpdatedAt));
    }

    public KnowledgeBase getOwnedKb(Long userId, Long kbId) {
        KnowledgeBase kb = kbMapper.selectById(kbId);
        if (kb == null || !userId.equals(kb.getUserId())) {
            throw new IllegalArgumentException("知识库不存在");
        }
        return kb;
    }

    @Transactional
    public KnowledgeDocument uploadDocument(Long userId, Long kbId, MultipartFile file) {
        KnowledgeBase kb = getOwnedKb(userId, kbId);
        if (file.isEmpty()) {
            throw new IllegalArgumentException("上传文件为空");
        }
        String originalName = file.getOriginalFilename() == null ? "document" : file.getOriginalFilename();
        String safeName = Path.of(originalName).getFileName().toString();
        String lowerName = safeName.toLowerCase(java.util.Locale.ROOT);
        if (SUPPORTED_EXTENSIONS.stream().noneMatch(lowerName::endsWith)) {
            throw new IllegalArgumentException("不支持的文件格式");
        }
        if (file.getSize() > 30L * 1024 * 1024) throw new IllegalArgumentException("文件不能超过 30MB");
        try (var input = file.getInputStream()) {
            byte[] header = input.readNBytes(16);
            if (isExecutable(header) || (lowerName.endsWith(".pdf") && !startsWith(header, "%PDF"))) {
                throw new IllegalArgumentException("文件内容校验失败");
            }
        } catch (java.io.IOException error) { throw new IllegalStateException("文件校验失败", error); }
        Path targetDirectory = Path.of(fileStoragePath, userId.toString(), kbId.toString()).normalize();
        Path targetPath = targetDirectory.resolve(UUID.randomUUID() + "-" + safeName).normalize();
        if (!targetPath.startsWith(targetDirectory)) {
            throw new IllegalArgumentException("文件名不合法");
        }
        try {
            Files.createDirectories(targetDirectory);
            Files.copy(file.getInputStream(), targetPath, StandardCopyOption.REPLACE_EXISTING);
        } catch (Exception error) {
            throw new IllegalStateException("文件保存失败", error);
        }

        KnowledgeDocument document = new KnowledgeDocument();
        document.setKbId(kbId);
        document.setFileName(safeName);
        document.setFilePath(targetPath.toAbsolutePath().toString());
        document.setStatus("parsing");
        document.setChunkCount(0);
        docMapper.insert(document);
        try {
            ProcessingTask task = new ProcessingTask();
            String taskId = "task_" + UUID.randomUUID().toString().replace("-", "");
            task.setTaskId(taskId);
            task.setTaskType("document_ingest");
            task.setUserId(userId);
            task.setAggregateId(document.getId());
            task.setIdempotencyKey("document:" + document.getId());
            task.setStatus("pending");
            task.setPayload(objectMapper.writeValueAsString(Map.of(
                "user_id", userId.toString(),
                "kb_id", kbId.toString(),
                "file_path", targetPath.toAbsolutePath().toString(),
                "document_id", "doc_" + document.getId()
            )));
            task.setAttemptCount(0);
            task.setMaxAttempts(3);
            task.setNextAttemptAt(java.time.LocalDateTime.now());
            taskMapper.insert(task);
            document.setParseTaskId(taskId);
        } catch (Exception error) {
            try { Files.deleteIfExists(targetPath); } catch (Exception ignored) { }
            throw new IllegalStateException("解析任务创建失败", error);
        }
        docMapper.updateById(document);
        return document;
    }

    private boolean startsWith(byte[] bytes, String value) { byte[] expected = value.getBytes(java.nio.charset.StandardCharsets.US_ASCII); if (bytes.length < expected.length) return false; for (int i=0;i<expected.length;i++) if (bytes[i] != expected[i]) return false; return true; }
    private boolean isExecutable(byte[] bytes) { return startsWith(bytes, "MZ") || startsWith(bytes, "#!"); }

    public List<KnowledgeDocument> listDocuments(Long userId, Long kbId) {
        getOwnedKb(userId, kbId);
        return docMapper.selectList(new LambdaQueryWrapper<KnowledgeDocument>()
            .eq(KnowledgeDocument::getKbId, kbId)
            .orderByDesc(KnowledgeDocument::getCreatedAt));
    }

    public KnowledgeDocument refreshDocumentStatus(Long userId, Long documentId) {
        KnowledgeDocument document = docMapper.selectById(documentId);
        if (document == null) {
            throw new IllegalArgumentException("文档不存在");
        }
        getOwnedKb(userId, document.getKbId());
        return document;
    }

    @Transactional
    public void deleteKb(Long userId, Long kbId) {
        getOwnedKb(userId, kbId);
        try {
            KnowledgeBase kb = getOwnedKb(userId, kbId);
            kb.setStatus("deleting");
            kbMapper.updateById(kb);
            ProcessingTask task = new ProcessingTask();
            task.setTaskId("task_" + UUID.randomUUID().toString().replace("-", ""));
            task.setTaskType("knowledge_base_delete");
            task.setUserId(userId);
            task.setAggregateId(kbId);
            task.setIdempotencyKey("knowledge-base-delete:" + kbId);
            task.setStatus("pending");
            task.setPayload(objectMapper.writeValueAsString(Map.of("user_id", userId.toString(), "kb_id", kbId.toString())));
            task.setAttemptCount(0);
            task.setMaxAttempts(5);
            task.setNextAttemptAt(java.time.LocalDateTime.now());
            taskMapper.insert(task);
        } catch (Exception error) {
            throw new IllegalStateException("删除任务创建失败", error);
        }
    }
}

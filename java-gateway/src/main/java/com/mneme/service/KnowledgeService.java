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
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.Set;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.zip.ZipInputStream;
import java.io.ByteArrayInputStream;
import java.io.InputStream;

@Service
public class KnowledgeService {
    private static final Set<String> SUPPORTED_EXTENSIONS = Set.of(
        ".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".csv", ".md", ".markdown", ".txt", ".html", ".htm"
    );
    private final KnowledgeBaseMapper kbMapper;
    private final KnowledgeDocumentMapper docMapper;
    private final ProcessingTaskMapper taskMapper;
    private final ObjectMapper objectMapper;
    private final JdbcTemplate jdbc;
    private final ObjectStorageService storage;

    @Autowired(required = false)
    private MaliciousContentScanner maliciousContentScanner;

    @Value("${mneme.file-storage-path:./data/files}")
    private String fileStoragePath;

    @Value("${mneme.tenant-storage-quota-mb:2048}")
    private long tenantStorageQuotaMb;

    @Value("${mneme.tenant-knowledge-base-quota:100}")
    private int tenantKnowledgeBaseQuota;

    public KnowledgeService(
        KnowledgeBaseMapper kbMapper,
        KnowledgeDocumentMapper docMapper,
        ProcessingTaskMapper taskMapper,
        ObjectMapper objectMapper,
        JdbcTemplate jdbc,
        ObjectStorageService storage
    ) {
        this.kbMapper = kbMapper;
        this.docMapper = docMapper;
        this.taskMapper = taskMapper;
        this.objectMapper = objectMapper;
        this.jdbc = jdbc;
        this.storage = storage;
    }

    public KnowledgeBase createKb(Long userId, String name, String description) {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("知识库名称不能为空");
        }
        Long count = jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_base WHERE user_id=?", Long.class, userId);
        if (count != null && count >= tenantKnowledgeBaseQuota) {
            throw new IllegalArgumentException("知识库数量已达到租户配额");
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
        requireStorageQuota(userId, file.getSize());
        validateUpload(file, lowerName);
        scanUpload(file);
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

        String location = null;
        try {
            location = storage.persist(targetPath, userId, kbId, safeName);
            KnowledgeDocument document = new KnowledgeDocument();
            document.setKbId(kbId);
            document.setFileName(safeName);
            document.setFilePath(location);
            document.setStatus("parsing");
            document.setChunkCount(0);
            docMapper.insert(document);
            saveVersion(document, location, targetPath);
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
                "file_path", location,
                "document_id", "doc_" + document.getId()
            )));
            task.setAttemptCount(0);
            task.setMaxAttempts(3);
            task.setNextAttemptAt(java.time.LocalDateTime.now());
            taskMapper.insert(task);
            document.setParseTaskId(taskId);
            docMapper.updateById(document);
            if ("s3".equals(storage.backend())) Files.deleteIfExists(targetPath);
            return document;
        } catch (Exception error) {
            if (location != null) try { storage.delete(location); } catch (Exception ignored) { }
            try { Files.deleteIfExists(targetPath); } catch (Exception ignored) { }
            throw new IllegalStateException("文档入库或解析任务创建失败", error);
        }
    }

    private boolean startsWith(byte[] bytes, String value) { byte[] expected = value.getBytes(java.nio.charset.StandardCharsets.US_ASCII); if (bytes.length < expected.length) return false; for (int i=0;i<expected.length;i++) if (bytes[i] != expected[i]) return false; return true; }
    private boolean isExecutable(byte[] bytes) { return startsWith(bytes, "MZ") || startsWith(bytes, "#!"); }

    private void validateUpload(MultipartFile file, String lowerName) {
        try (var input = file.getInputStream()) {
            byte[] header = input.readNBytes(16);
            boolean zipOffice = lowerName.endsWith(".docx") || lowerName.endsWith(".pptx")
                || lowerName.endsWith(".xlsx") || lowerName.endsWith(".xlsm");
            if (isExecutable(header)
                || (lowerName.endsWith(".pdf") && !startsWith(header, "%PDF"))
                || (zipOffice && !(header.length >= 4 && header[0] == 'P' && header[1] == 'K'))) {
                throw new IllegalArgumentException("文件扩展名与内容签名不匹配");
            }
            String contentType = file.getContentType() == null ? "" : file.getContentType().toLowerCase();
            if (!contentType.isBlank() && !"application/octet-stream".equals(contentType)
                && !contentType.startsWith("text/") && !contentType.contains("pdf")
                && !contentType.contains("word") && !contentType.contains("presentation")
                && !contentType.contains("sheet") && !contentType.contains("excel")
                && !contentType.contains("office") && !contentType.contains("zip")) {
                throw new IllegalArgumentException("文件 MIME 类型不受支持");
            }
        } catch (java.io.IOException error) {
            throw new IllegalStateException("文件校验失败", error);
        }
        if (lowerName.endsWith(".docx") || lowerName.endsWith(".pptx")
            || lowerName.endsWith(".xlsx") || lowerName.endsWith(".xlsm")) {
            validateOfficeArchive(file);
        }
    }

    private void validateOfficeArchive(MultipartFile file) {
        long expanded = 0;
        int entries = 0;
        boolean contentTypes = false;
        try (ZipInputStream zip = new ZipInputStream(file.getInputStream())) {
            for (var entry = zip.getNextEntry(); entry != null; entry = zip.getNextEntry()) {
                entries++;
                if (entries > 10_000) throw new IllegalArgumentException("Office 文档条目过多");
                String name = entry.getName().replace('\\', '/').toLowerCase();
                if (name.equals("[content_types].xml")) contentTypes = true;
                if (name.startsWith("/") || name.contains("../")
                    || name.matches(".*\\.(exe|dll|com|bat|cmd|ps1|vbs|js)$")) {
                    throw new IllegalArgumentException("Office 文档包含危险条目");
                }
                byte[] buffer = new byte[8192];
                for (int read = zip.read(buffer); read >= 0; read = zip.read(buffer)) {
                    expanded += read;
                    if (expanded > 200L * 1024 * 1024) {
                        throw new IllegalArgumentException("Office 文档展开后体积过大");
                    }
                }
            }
        } catch (java.io.IOException error) {
            throw new IllegalArgumentException("Office 文档压缩结构无效", error);
        }
        if (!contentTypes) throw new IllegalArgumentException("Office 文档缺少内容类型清单");
    }

    private void saveVersion(KnowledgeDocument document, String location, Path localPath) {
        try {
            Integer next = jdbc.queryForObject(
                "SELECT COALESCE(MAX(version_number),0)+1 FROM knowledge_document_version WHERE document_id=?",
                Integer.class, document.getId());
            jdbc.update("""
                INSERT INTO knowledge_document_version(document_id,version_number,file_name,file_path,sha256,size_bytes)
                VALUES(?,?,?,?,?,?)
                """, document.getId(), next, document.getFileName(), location,
                sha256(localPath), Files.size(localPath));
        } catch (Exception error) {
            throw new IllegalStateException("文档版本记录失败", error);
        }
    }

    private String sha256(Path path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (var input = Files.newInputStream(path)) {
            byte[] buffer = new byte[8192];
            for (int read = input.read(buffer); read >= 0; read = input.read(buffer)) {
                digest.update(buffer, 0, read);
            }
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    @Transactional
    public KnowledgeDocument replaceDocument(Long userId, Long documentId, MultipartFile file) {
        KnowledgeDocument document = ownedDocument(userId, documentId);
        String originalName = file.getOriginalFilename() == null ? "document" : file.getOriginalFilename();
        String safeName = Path.of(originalName).getFileName().toString();
        String lowerName = safeName.toLowerCase(java.util.Locale.ROOT);
        if (SUPPORTED_EXTENSIONS.stream().noneMatch(lowerName::endsWith)) throw new IllegalArgumentException("不支持的文件格式");
        if (file.isEmpty() || file.getSize() > 30L * 1024 * 1024) throw new IllegalArgumentException("文件大小必须在 30MB 以内");
        requireStorageQuota(userId, file.getSize());
        validateUpload(file, lowerName);
        scanUpload(file);
        Path directory = Path.of(fileStoragePath, userId.toString(), document.getKbId().toString()).normalize();
        Path target = directory.resolve(UUID.randomUUID() + "-" + safeName).normalize();
        if (!target.startsWith(directory)) throw new IllegalArgumentException("文件名不合法");
        String newLocation = null;
        try {
            Files.createDirectories(directory);
            Files.copy(file.getInputStream(), target, StandardCopyOption.REPLACE_EXISTING);
            newLocation = storage.persist(target, userId, document.getKbId(), safeName);
            document.setFileName(safeName);
            document.setFilePath(newLocation);
            document.setStatus("parsing");
            document.setChunkCount(0);
            document.setErrorMessage(null);
            docMapper.updateById(document);
            saveVersion(document, newLocation, target);
            createDocumentTask(userId, document, "document_ingest");
            if ("s3".equals(storage.backend())) Files.deleteIfExists(target);
            return document;
        } catch (Exception error) {
            if (newLocation != null) try { storage.delete(newLocation); } catch (Exception ignored) { }
            try { Files.deleteIfExists(target); } catch (Exception ignored) { }
            throw error instanceof RuntimeException runtime ? runtime : new IllegalStateException("文档替换失败", error);
        }
    }

    public List<Map<String, Object>> documentVersions(Long userId, Long documentId) {
        ownedDocument(userId, documentId);
        return jdbc.queryForList("""
            SELECT version_number,file_name,sha256,size_bytes,created_at,
                CASE WHEN file_path=(SELECT file_path FROM knowledge_document WHERE id=?) THEN TRUE ELSE FALSE END AS active
            FROM knowledge_document_version WHERE document_id=? ORDER BY version_number DESC
            """, documentId, documentId);
    }

    private void requireStorageQuota(Long userId, long incomingBytes) {
        Long used = jdbc.queryForObject("""
            SELECT COALESCE(SUM(v.size_bytes),0)
            FROM knowledge_document_version v
            JOIN knowledge_document d ON d.id=v.document_id
            JOIN knowledge_base k ON k.id=d.kb_id
            WHERE k.user_id=?
            """, Long.class, userId);
        long limit = Math.max(1, tenantStorageQuotaMb) * 1024L * 1024L;
        if ((used == null ? 0 : used) + incomingBytes > limit) {
            throw new IllegalArgumentException("文档存储量已达到租户配额");
        }
    }

    @Transactional
    public KnowledgeDocument restoreDocumentVersion(Long userId, Long documentId, int version) {
        KnowledgeDocument document = ownedDocument(userId, documentId);
        List<Map<String, Object>> rows = jdbc.queryForList("""
            SELECT file_name,file_path FROM knowledge_document_version
            WHERE document_id=? AND version_number=?
            """, documentId, version);
        if (rows.isEmpty()) throw new IllegalArgumentException("文档版本不存在");
        String location = String.valueOf(rows.get(0).get("file_path"));
        storage.materialize(location);
        document.setFileName(String.valueOf(rows.get(0).get("file_name")));
        document.setFilePath(location);
        document.setStatus("parsing");
        document.setChunkCount(0);
        document.setErrorMessage(null);
        docMapper.updateById(document);
        createDocumentTask(userId, document, "document_ingest");
        return document;
    }

    public KnowledgeDocument importArchivedDocument(Long userId, Long kbId, String fileName, byte[] content) {
        return uploadDocument(userId, kbId, new ArchivedMultipartFile(fileName, content));
    }

    public void discardImportedDocument(KnowledgeDocument document) {
        if (document != null && document.getFilePath() != null) storage.delete(document.getFilePath());
    }

    private void scanUpload(MultipartFile file) {
        if (maliciousContentScanner == null) return;
        try (InputStream input = file.getInputStream()) {
            maliciousContentScanner.scan(input);
        } catch (IllegalArgumentException | IllegalStateException error) {
            throw error;
        } catch (Exception error) {
            throw new IllegalStateException("文件扫描失败", error);
        }
    }

    private record ArchivedMultipartFile(String fileName, byte[] content) implements MultipartFile {
        @Override public String getName() { return "file"; }
        @Override public String getOriginalFilename() { return fileName; }
        @Override public String getContentType() { return null; }
        @Override public boolean isEmpty() { return content.length == 0; }
        @Override public long getSize() { return content.length; }
        @Override public byte[] getBytes() { return content.clone(); }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(content); }
        @Override public void transferTo(java.io.File destination) throws java.io.IOException {
            Files.write(destination.toPath(), content);
        }
    }

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
    public void deleteDocument(Long userId, Long documentId) {
        KnowledgeDocument document = ownedDocument(userId, documentId);
        if ("deleting".equals(document.getStatus())) return;
        document.setStatus("deleting");
        document.setErrorMessage(null);
        docMapper.updateById(document);
        createDocumentTask(userId, document, "document_delete");
    }

    @Transactional
    public void reparseDocument(Long userId, Long documentId) {
        KnowledgeDocument document = ownedDocument(userId, documentId);
        if ("parsing".equals(document.getStatus())) return;
        if ("deleting".equals(document.getStatus())) {
            throw new IllegalArgumentException("文档正在删除，无法重新解析");
        }
        storage.materialize(document.getFilePath());
        document.setStatus("parsing");
        document.setChunkCount(0);
        document.setErrorMessage(null);
        docMapper.updateById(document);
        createDocumentTask(userId, document, "document_ingest");
    }

    private KnowledgeDocument ownedDocument(Long userId, Long documentId) {
        KnowledgeDocument document = docMapper.selectById(documentId);
        if (document == null) throw new IllegalArgumentException("文档不存在");
        getOwnedKb(userId, document.getKbId());
        return document;
    }

    private void createDocumentTask(Long userId, KnowledgeDocument document, String type) {
        try {
            ProcessingTask task = new ProcessingTask();
            String taskId = "task_" + UUID.randomUUID().toString().replace("-", "");
            task.setTaskId(taskId);
            task.setTaskType(type);
            task.setUserId(userId);
            task.setAggregateId(document.getId());
            task.setIdempotencyKey(type + ":" + document.getId() + ":" + UUID.randomUUID());
            task.setStatus("pending");
            task.setPayload(objectMapper.writeValueAsString(Map.of(
                "user_id", userId.toString(), "kb_id", document.getKbId().toString(),
                "file_path", document.getFilePath(), "document_id", "doc_" + document.getId()
            )));
            task.setAttemptCount(0); task.setMaxAttempts(3);
            task.setNextAttemptAt(java.time.LocalDateTime.now());
            taskMapper.insert(task);
            document.setParseTaskId(taskId);
            docMapper.updateById(document);
        } catch (Exception error) {
            throw new IllegalStateException("文档任务创建失败", error);
        }
    }

    @Transactional
    public void deleteKb(Long userId, Long kbId) {
        KnowledgeBase kb = getOwnedKb(userId, kbId);
        if ("deleting".equals(kb.getStatus())) return;
        try {
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

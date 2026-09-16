package com.mneme.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.security.MessageDigest;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;
import java.sql.Date;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;

@Service
public class WorkspaceService {
    private static final int IMPORT_MAX_ITEMS = 10_000;
    private static final int IMPORT_MAX_TEXT_LENGTH = 1_000_000;
    private static final int ARCHIVE_MAX_BYTES = 50 * 1024 * 1024;
    private static final int ARCHIVE_MAX_ENTRIES = 500;
    private static final long ARCHIVE_MAX_UNCOMPRESSED_BYTES = 200L * 1024 * 1024;
    private static final int ARCHIVE_MAX_ENTRY_BYTES = 20 * 1024 * 1024;
    private static final Pattern KEY_POINT_SPLIT = Pattern.compile("[。！？!?；;\\n]");
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final RestTemplate restTemplate;

    @Autowired(required = false)
    private OperationLogService operationLog;

    @Value("${mneme.file-storage-path:./data/files}")
    private String fileStoragePath;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    public WorkspaceService(JdbcTemplate jdbc, ObjectMapper mapper, RestTemplate restTemplate) {
        this.jdbc = jdbc;
        this.mapper = mapper;
        this.restTemplate = restTemplate;
    }

    public Map<String, Object> preview(Long userId, Long documentId) throws Exception {
        Map<String, Object> document = one("""
            SELECT d.id,d.kb_id,d.file_name,d.file_path,d.status,d.chunk_count
            FROM knowledge_document d JOIN knowledge_base k ON k.id=d.kb_id
            WHERE d.id=? AND k.user_id=?
            """, documentId, userId);
        Path path = checkedDocumentPath(document);
        String fileName = String.valueOf(document.get("file_name"));
        String extension = fileName.contains(".") ? fileName.substring(fileName.lastIndexOf('.') + 1).toLowerCase() : "";
        String content;
        if (List.of("txt", "md", "csv", "html").contains(extension) && Files.isRegularFile(path)) {
            byte[] bytes = Files.readAllBytes(path);
            content = new String(bytes, 0, Math.min(bytes.length, 250_000), StandardCharsets.UTF_8);
        } else {
            content = "该格式使用语义片段定位。请从回答引用或检索调试器查看对应页码、章节和片段。";
        }
        Map<String, Object> publicDocument = new LinkedHashMap<>(document);
        publicDocument.remove("file_path");
        return Map.of("document", publicDocument, "content", content, "extension", extension);
    }

    public Path documentPath(Long userId, Long documentId) {
        Map<String, Object> document = one("""
            SELECT d.file_path FROM knowledge_document d JOIN knowledge_base k ON k.id=d.kb_id
            WHERE d.id=? AND k.user_id=?
            """, documentId, userId);
        return checkedDocumentPath(document);
    }

    private Path checkedDocumentPath(Map<String, Object> document) {
        return checkedStoragePath(String.valueOf(document.get("file_path")), true);
    }

    private Path checkedStoragePath(String rawPath, boolean requireRegularFile) {
        Path root = Path.of(fileStoragePath).toAbsolutePath().normalize();
        Path path = Path.of(rawPath).toAbsolutePath().normalize();
        if (!path.startsWith(root)
            || (requireRegularFile && !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS))) {
            throw new IllegalArgumentException("文档原文件不存在或路径无效");
        }
        Path current = root;
        for (Path part : root.relativize(path)) {
            current = current.resolve(part);
            if (Files.isSymbolicLink(current)) {
                throw new IllegalArgumentException("文档原文件不存在或路径无效");
            }
        }
        return path;
    }

    public List<Map<String, Object>> tasks(Long userId) {
        return rows("""
            SELECT t.id,t.task_id,t.task_type,t.aggregate_id,t.status,t.attempt_count,t.max_attempts,
                   t.error_code,t.error_message,t.created_at,t.updated_at,d.file_name
            FROM processing_task t LEFT JOIN knowledge_document d ON d.id=t.aggregate_id
            WHERE t.user_id=? ORDER BY t.created_at DESC LIMIT 100
            """, userId);
    }

    @Transactional
    public Map<String, Object> retryTask(Long userId, String taskId) {
        int updated = jdbc.update("""
            UPDATE processing_task SET status='retry',attempt_count=0,next_attempt_at=NOW(),
              locked_at=NULL,locked_by=NULL,error_code=NULL,error_message=NULL
            WHERE user_id=? AND task_id=? AND status IN ('failed','retry')
            """, userId, taskId);
        if (updated == 0) throw new IllegalArgumentException("任务不存在或当前状态不可重试");
        jdbc.update("""
            UPDATE knowledge_document d JOIN processing_task t ON t.aggregate_id=d.id
            SET d.status=CASE WHEN t.task_type='document_delete' THEN 'deleting' ELSE 'parsing' END,
                d.error_message=NULL WHERE t.user_id=? AND t.task_id=?
            """, userId, taskId);
        return Map.of("task_id", taskId, "status", "retry");
    }

    public Map<String, Object> debugRetrieval(Long userId, Long kbId, String query, int topK) {
        requireKb(userId, kbId);
        String url = UriComponentsBuilder.fromHttpUrl(pythonAgentUrl + "/api/v1/knowledge/search")
            .queryParam("user_id", userId).queryParam("kb_id", kbId)
            .queryParam("query", query).queryParam("top_k", Math.max(1, Math.min(topK, 20)))
            .build().encode().toUriString();
        @SuppressWarnings("unchecked") Map<String, Object> result = restTemplate.getForObject(url, Map.class);
        return result == null ? Map.of("query", query, "chunks", List.of()) : result;
    }

    public List<Map<String, Object>> plans(Long userId) {
        return rows("SELECT * FROM learning_plan WHERE user_id=? ORDER BY status,created_at DESC", userId);
    }

    public Map<String, Object> metrics(Long userId) {
        long planTotal = count("SELECT COUNT(*) FROM learning_plan WHERE user_id=?", userId);
        long planCompleted = count(
            "SELECT COUNT(*) FROM learning_plan WHERE user_id=? AND status='completed'", userId);
        long reviewTotal = count("SELECT COUNT(*) FROM review_card WHERE user_id=?", userId);
        long reviewCompleted = count(
            "SELECT COUNT(*) FROM review_card WHERE user_id=? AND review_count>0", userId);
        long reviewDue = count(
            "SELECT COUNT(*) FROM review_card WHERE user_id=? AND due_at<=NOW()", userId);
        long quizTotal = count("SELECT COUNT(*) FROM knowledge_quiz WHERE user_id=?", userId);
        long attemptTotal = count("SELECT COUNT(*) FROM quiz_attempt WHERE user_id=?", userId);
        long mistakeCards = count(
            "SELECT COUNT(*) FROM review_card WHERE user_id=? AND origin='quiz_mistake'", userId);
        long pendingWeakPoints = count(
            "SELECT COUNT(*) FROM pending_memory WHERE user_id=? AND category='weak_point' AND status='pending'",
            userId);
        Map<String, Object> planMetrics = new LinkedHashMap<>();
        planMetrics.put("total", planTotal);
        planMetrics.put("completed", planCompleted);
        planMetrics.put("completion_rate", ratio(planCompleted, planTotal));
        Map<String, Object> reviewMetrics = new LinkedHashMap<>();
        reviewMetrics.put("total", reviewTotal);
        reviewMetrics.put("reviewed", reviewCompleted);
        reviewMetrics.put("due", reviewDue);
        reviewMetrics.put("average_interval_days", average(
            "SELECT AVG(interval_days) FROM review_card WHERE user_id=?", userId));
        Map<String, Object> quizMetrics = new LinkedHashMap<>();
        quizMetrics.put("total", quizTotal);
        quizMetrics.put("attempts", attemptTotal);
        quizMetrics.put("average_score", average(
            "SELECT AVG(score) FROM quiz_attempt WHERE user_id=?", userId));
        Map<String, Object> mistakeMetrics = new LinkedHashMap<>();
        mistakeMetrics.put("cards_created", mistakeCards);
        mistakeMetrics.put("conversion_rate_proxy", ratio(mistakeCards, attemptTotal));
        mistakeMetrics.put("pending_weak_points", pendingWeakPoints);
        return Map.of(
            "plans", planMetrics,
            "reviews", reviewMetrics,
            "quizzes", quizMetrics,
            "mistakes", mistakeMetrics
        );
    }

    @Transactional
    public Map<String, Object> createPlan(Long userId, Map<String, Object> body) {
        String title = required(body, "title");
        String goal = required(body, "goal");
        LocalDate target = body.get("target_date") == null || String.valueOf(body.get("target_date")).isBlank()
            ? null : LocalDate.parse(String.valueOf(body.get("target_date")));
        jdbc.update("INSERT INTO learning_plan(user_id,title,goal,target_date) VALUES(?,?,?,?)",
            userId, title, goal, target == null ? null : Date.valueOf(target));
        Long id = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);
        String[] prompts = {"用自己的话说明：" + goal, "列出核心概念：" + goal, "举一个实际例子：" + goal};
        for (int index = 0; index < prompts.length; index++) {
            jdbc.update("INSERT INTO review_card(user_id,plan_id,prompt,answer,due_at,origin) VALUES(?,?,?,?,?,?)",
                userId, id, prompts[index], "完成学习后补充你的答案",
                Timestamp.valueOf(LocalDateTime.now().plusDays(index)), "plan");
        }
        return one("SELECT * FROM learning_plan WHERE id=? AND user_id=?", id, userId);
    }

    public List<Map<String, Object>> reviews(Long userId) {
        return rows("SELECT * FROM review_card WHERE user_id=? ORDER BY due_at ASC", userId);
    }

    @Transactional
    public Map<String, Object> review(Long userId, Long cardId, int rating) {
        Map<String, Object> card = one("SELECT * FROM review_card WHERE id=? AND user_id=?", cardId, userId);
        int oldInterval = ((Number) card.get("interval_days")).intValue();
        double oldEase = ((Number) card.get("ease_factor")).doubleValue();
        int normalized = Math.max(0, Math.min(rating, 5));
        int interval = normalized < 3 ? 1 : Math.max(1, (int) Math.round(oldInterval * oldEase));
        double ease = Math.max(1.3, oldEase + (0.1 - (5 - normalized) * (0.08 + (5 - normalized) * 0.02)));
        jdbc.update("""
            UPDATE review_card SET interval_days=?,ease_factor=?,due_at=?,last_rating=?,review_count=review_count+1
            WHERE id=? AND user_id=?
            """, interval, ease, Timestamp.valueOf(LocalDateTime.now().plusDays(interval)), normalized, cardId, userId);
        return one("SELECT * FROM review_card WHERE id=?", cardId);
    }

    public List<Map<String, Object>> quizzes(Long userId) {
        return rows("SELECT id,kb_id,title,topic,questions_json,created_at FROM knowledge_quiz WHERE user_id=? ORDER BY created_at DESC", userId);
    }

    @Transactional
    public Map<String, Object> generateQuiz(Long userId, Map<String, Object> body) throws Exception {
        Long kbId = Long.valueOf(String.valueOf(body.get("kb_id")));
        String topic = required(body, "topic");
        Map<String, Object> result = debugRetrieval(userId, kbId, topic, 3);
        List<Map<String, Object>> chunks = mapper.convertValue(result.getOrDefault("chunks", List.of()), new TypeReference<>() {});
        if (chunks.isEmpty()) {
            List<Map<String, Object>> documents = rows("""
                SELECT d.id FROM knowledge_document d JOIN knowledge_base k ON k.id=d.kb_id
                WHERE d.kb_id=? AND k.user_id=? AND d.status='ready' ORDER BY d.created_at DESC LIMIT 1
                """, kbId, userId);
            if (documents.isEmpty()) throw new IllegalArgumentException("该资料库暂无可用于生成测验的内容");
            Map<String, Object> fallback = preview(userId, ((Number) documents.get(0).get("id")).longValue());
            String content = String.valueOf(fallback.getOrDefault("content", "")).trim();
            if (content.isBlank()) throw new IllegalArgumentException("该资料库暂无可用于生成测验的文本内容");
            @SuppressWarnings("unchecked") Map<String, Object> document = (Map<String, Object>) fallback.get("document");
            chunks = List.of(Map.of(
                "content", content,
                "score", 0,
                "metadata", Map.of("source", document.get("file_name"), "page", 1, "section", "原文回退")
            ));
        }
        List<Map<String, Object>> questions = generateQuestions(topic, chunks);
        String title = topic + " · 知识测验";
        jdbc.update("INSERT INTO knowledge_quiz(user_id,kb_id,title,topic,questions_json) VALUES(?,?,?,?,CAST(? AS JSON))",
            userId, kbId, title, topic, mapper.writeValueAsString(questions));
        Long id = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);
        return one("SELECT * FROM knowledge_quiz WHERE id=?", id);
    }

    @Transactional
    public Map<String, Object> submitQuiz(Long userId, Long quizId, Map<String, Object> body) throws Exception {
        Map<String, Object> quiz = one("SELECT * FROM knowledge_quiz WHERE id=? AND user_id=?", quizId, userId);
        List<Map<String, Object>> questions = mapper.readValue(jsonText(quiz.get("questions_json")), new TypeReference<>() {});
        List<String> answers = mapper.convertValue(body.getOrDefault("answers", List.of()), new TypeReference<>() {});
        List<Map<String, Object>> feedback = new ArrayList<>();
        int correct = 0;
        for (int index = 0; index < questions.size(); index++) {
            String expected = String.valueOf(questions.get(index).get("answer"));
            String actual = index < answers.size() ? answers.get(index).trim() : "";
            Map<String, Object> question = questions.get(index);
            List<String> keyPoints = stringList(question.get("key_points"));
            int covered = "short".equals(question.get("type")) ? countCoveredKeyPoints(actual, keyPoints) : 0;
            boolean ok = "short".equals(question.get("type"))
                ? !keyPoints.isEmpty() && covered >= Math.max(1, (keyPoints.size() + 1) / 2)
                : expected.equals(actual);
            if (ok) correct++;
            Map<String, Object> itemFeedback = new LinkedHashMap<>();
            itemFeedback.put("question_id", index + 1);
            itemFeedback.put("correct", ok);
            itemFeedback.put("expected", expected);
            itemFeedback.put("covered_key_points", covered);
            itemFeedback.put("key_point_count", keyPoints.size());
            itemFeedback.put("evidence", question.getOrDefault("evidence", expected));
            itemFeedback.put("source", question.getOrDefault("source", Map.of()));
            feedback.add(itemFeedback);
            if (!ok) createMistakeReview(userId, String.valueOf(question.get("prompt")), expected, String.valueOf(quiz.get("topic")));
        }
        int score = questions.isEmpty() ? 0 : correct * 100 / questions.size();
        jdbc.update("INSERT INTO quiz_attempt(quiz_id,user_id,answers_json,score,feedback_json) VALUES(?,?,CAST(? AS JSON),?,CAST(? AS JSON))",
            quizId, userId, mapper.writeValueAsString(answers), score, mapper.writeValueAsString(feedback));
        return Map.of("score", score, "feedback", feedback);
    }

    public List<Map<String, Object>> branches(Long userId) {
        return rows("""
            SELECT b.*,s.title AS source_title,bs.title AS branch_title FROM chat_branch b
            JOIN chat_session s ON s.id=b.source_session_id JOIN chat_session bs ON bs.id=b.branch_session_id
            WHERE b.user_id=? ORDER BY b.created_at DESC
            """, userId);
    }

    @Transactional
    public Map<String, Object> createBranch(Long userId, Map<String, Object> body) {
        Long sourceSessionId = Long.valueOf(String.valueOf(body.get("source_session_id")));
        Long sourceMessageId = body.get("source_message_id") == null ? null : Long.valueOf(String.valueOf(body.get("source_message_id")));
        String label = required(body, "label");
        one("SELECT id FROM chat_session WHERE id=? AND user_id=?", sourceSessionId, userId);
        jdbc.update("INSERT INTO chat_session(user_id,title) VALUES(?,?)", userId, label);
        Long branchSessionId = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);
        String copySql = """
            INSERT INTO chat_message(session_id,request_id,role,content,status,error_code,created_at)
            SELECT ?,NULL,role,content,status,error_code,created_at FROM chat_message
            WHERE session_id=? %s ORDER BY created_at
            """.formatted(sourceMessageId == null ? "" : "AND id <= ?");
        if (sourceMessageId == null) jdbc.update(copySql, branchSessionId, sourceSessionId);
        else jdbc.update(copySql, branchSessionId, sourceSessionId, sourceMessageId);
        jdbc.update("INSERT INTO chat_branch(user_id,source_session_id,source_message_id,branch_session_id,label) VALUES(?,?,?,?,?)",
            userId, sourceSessionId, sourceMessageId, branchSessionId, label);
        Long id = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);
        return one("SELECT * FROM chat_branch WHERE id=?", id);
    }

    public Map<String, Object> compareBranch(Long userId, Long branchId) {
        Map<String, Object> branch = one("SELECT * FROM chat_branch WHERE id=? AND user_id=?", branchId, userId);
        return Map.of(
            "branch", branch,
            "source_messages", rows("SELECT id,role,content,created_at FROM chat_message WHERE session_id=? ORDER BY created_at", branch.get("source_session_id")),
            "branch_messages", rows("SELECT id,role,content,created_at FROM chat_message WHERE session_id=? ORDER BY created_at", branch.get("branch_session_id"))
        );
    }

    public Map<String, Object> exportData(Long userId) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("schema", "mneme.workspace");
        data.put("version", 2);
        data.put("exported_at", LocalDateTime.now().toString());
        data.put("knowledge_bases", rows("SELECT id,name,description,status,created_at FROM knowledge_base WHERE user_id=?", userId));
        data.put("sessions", rows("SELECT id,title,created_at,updated_at FROM chat_session WHERE user_id=?", userId));
        data.put("messages", rows("SELECT m.id,m.session_id,m.role,m.content,m.status,m.created_at FROM chat_message m JOIN chat_session s ON s.id=m.session_id WHERE s.user_id=?", userId));
        data.put("plans", plans(userId));
        data.put("reviews", reviews(userId));
        data.put("quizzes", quizzes(userId));
        data.put("quiz_attempts", rows("SELECT a.id,a.quiz_id,a.answers_json,a.score,a.feedback_json,a.created_at FROM quiz_attempt a WHERE a.user_id=? ORDER BY a.created_at", userId));
        data.put("branches", branches(userId));
        data.put("scope", Map.of("relational_data", true, "original_files", false, "vector_index", false));
        return data;
    }

    public byte[] exportArchive(Long userId) throws Exception {
        String operationId = operationId();
        record(operationId, userId, "workspace_archive_export", null, "start", "started", Map.of(), null);
        Map<String, Object> workspace = exportData(userId);
        workspace.put("documents", rows("""
            SELECT d.id,d.kb_id,d.file_name,d.file_path,d.status,d.chunk_count,d.created_at,d.updated_at
            FROM knowledge_document d JOIN knowledge_base k ON k.id=d.kb_id WHERE k.user_id=?
            """, userId));
        @SuppressWarnings("unchecked") List<Map<String, Object>> documents = (List<Map<String, Object>>) workspace.get("documents");
        List<Map<String, Object>> manifestDocuments = documents.stream().map(document -> {
            Map<String, Object> manifest = new LinkedHashMap<>();
            manifest.put("id", document.get("id"));
            manifest.put("kb_id", document.get("kb_id"));
            manifest.put("file_name", document.get("file_name"));
            manifest.put("status", document.get("status"));
            manifest.put("chunk_count", document.get("chunk_count"));
            manifest.put("created_at", document.get("created_at"));
            manifest.put("updated_at", document.get("updated_at"));
            try {
                Path file = checkedStoragePath(String.valueOf(document.getOrDefault("file_path", "")), true);
                manifest.put("sha256", sha256(file));
            } catch (Exception ignored) {
                manifest.put("sha256", "");
            }
            return manifest;
        }).toList();
        workspace.put("documents", manifestDocuments);
        workspace.put("scope", Map.of("relational_data", true, "original_files", true, "vector_index", false));
        byte[] workspaceJson = mapper.writeValueAsBytes(workspace);
        if (workspaceJson.length > ARCHIVE_MAX_ENTRY_BYTES) {
            throw new IllegalArgumentException("工作区数据超过归档单文件大小限制");
        }
        if (documents.size() + 1 > ARCHIVE_MAX_ENTRIES) {
            throw new IllegalArgumentException("归档包文件数量超限");
        }
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            zip.putNextEntry(new ZipEntry("workspace.json"));
            zip.write(workspaceJson);
            zip.closeEntry();
            long total = workspaceJson.length;
            for (Map<String, Object> document : documents) {
                Path file;
                try {
                    file = checkedStoragePath(
                        String.valueOf(document.getOrDefault("file_path", "")), true
                    );
                } catch (IllegalArgumentException error) {
                    continue;
                }
                long fileSize = Files.size(file);
                if (fileSize > ARCHIVE_MAX_ENTRY_BYTES) {
                    throw new IllegalArgumentException("归档文件超过单文件大小限制: " + document.get("file_name"));
                }
                total += fileSize;
                if (total > ARCHIVE_MAX_UNCOMPRESSED_BYTES) {
                    throw new IllegalArgumentException("归档包解压大小超限");
                }
                String name = safeArchiveName(String.valueOf(document.get("file_name")));
                zip.putNextEntry(new ZipEntry("files/" + document.get("id") + "/" + name));
                Files.copy(file, zip);
                zip.closeEntry();
            }
        }
        byte[] archive = output.toByteArray();
        if (archive.length > ARCHIVE_MAX_BYTES) {
            throw new IllegalArgumentException("归档包压缩后超过 50MB 限制");
        }
        record(operationId, userId, "workspace_archive_export", null, "complete", "completed",
            Map.of("bytes", archive.length, "documents", manifestDocuments.size()), null);
        return archive;
    }

    public Map<String, Object> importArchive(Long userId, byte[] archive) throws Exception {
        String operationId = operationId();
        record(operationId, userId, "workspace_archive_import", null, "start", "started",
            Map.of("bytes", archive.length), null);
        if (archive.length == 0 || archive.length > ARCHIVE_MAX_BYTES) {
            throw new IllegalArgumentException("归档包大小必须在 1B 至 50MB 之间");
        }
        if (archive.length < 4 || archive[0] != 'P' || archive[1] != 'K') {
            throw new IllegalArgumentException("归档包不是有效的 ZIP 文件");
        }
        byte[] workspaceJson = null;
        int entries = 0;
        long total = 0;
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(archive))) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                if (++entries > ARCHIVE_MAX_ENTRIES) throw new IllegalArgumentException("归档包文件数量超限");
                validateArchiveEntry(entry);
                ByteArrayOutputStream content = new ByteArrayOutputStream();
                byte[] buffer = new byte[8192];
                int read;
                long entryTotal = 0;
                while ((read = zip.read(buffer)) != -1) {
                    entryTotal += read;
                    total += read;
                    if (entryTotal > ARCHIVE_MAX_ENTRY_BYTES || total > ARCHIVE_MAX_UNCOMPRESSED_BYTES) {
                        throw new IllegalArgumentException("归档包解压大小超限");
                    }
                    content.write(buffer, 0, read);
                }
                if ("workspace.json".equals(entry.getName())) workspaceJson = content.toByteArray();
                zip.closeEntry();
            }
        } catch (java.util.zip.ZipException error) {
            throw new IllegalArgumentException("归档包不是有效的 ZIP 文件", error);
        }
        if (workspaceJson == null) throw new IllegalArgumentException("归档包缺少 workspace.json");
        Map<String, Object> workspace = mapper.readValue(workspaceJson, new TypeReference<>() {});
        Map<String, Object> imported = importData(userId, workspace);
        Map<String, Object> result = Map.of("status", "imported", "workspace", imported, "original_files", "not_restored",
            "message", "关系数据已导入；原始文件需重新上传以建立向量索引");
        record(operationId, userId, "workspace_archive_import", null, "complete", "completed",
            Map.of("entries", entries), null);
        return result;
    }

    public List<Map<String, Object>> operationLogs(Long userId, int limit) {
        if (operationLog == null) return List.of();
        return operationLog.list(userId, limit);
    }

    private void validateArchiveEntry(ZipEntry entry) {
        String name = entry.getName().replace('\\', '/');
        Path normalized = Path.of(name).normalize();
        String normalizedName = normalized.toString().replace('\\', '/');
        if (entry.isDirectory() || name.startsWith("/") || name.matches("^[A-Za-z]:.*")
            || normalized.isAbsolute() || normalized.startsWith("..") || !normalizedName.equals(name)) {
            throw new IllegalArgumentException("归档包包含非法路径: " + name);
        }
        if (!name.equals("workspace.json") && !name.startsWith("files/")) {
            throw new IllegalArgumentException("归档包包含未知文件: " + name);
        }
    }

    private String safeArchiveName(String fileName) {
        String clean = Path.of(fileName == null ? "file" : fileName).getFileName().toString();
        clean = clean.replaceAll("[^\\p{L}\\p{N}._-]", "_");
        return clean.isBlank() ? "file" : clean;
    }

    private String sha256(Path file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (var input = Files.newInputStream(file)) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = input.read(buffer)) != -1) {
                digest.update(buffer, 0, read);
            }
        }
        StringBuilder builder = new StringBuilder();
        for (byte value : digest.digest()) {
            builder.append(String.format("%02x", value));
        }
        return builder.toString();
    }

    @Transactional
    public Map<String, Object> importData(Long userId, Map<String, Object> payload) throws Exception {
        int version = integer(payload.getOrDefault("version", 1), 1);
        if (version < 1 || version > 2) throw new IllegalArgumentException("不支持的导出版本: " + version);
        if (version == 2 && !"mneme.workspace".equals(payload.get("schema"))) {
            throw new IllegalArgumentException("导入文件 schema 不正确");
        }
        Map<String, Integer> counts = new LinkedHashMap<>();
        Map<Long, Long> kbIds = importKnowledgeBases(userId, items(payload, "knowledge_bases"), counts);
        Map<Long, Long> sessionIds = importSessions(userId, items(payload, "sessions"), counts);
        Map<Long, Long> messageIds = importMessages(items(payload, "messages"), sessionIds, counts);
        Map<Long, Long> planIds = importPlans(userId, items(payload, "plans"), counts);
        importReviews(userId, items(payload, "reviews"), planIds, counts);
        Map<Long, Long> quizIds = importQuizzes(userId, items(payload, "quizzes"), kbIds, counts);
        importAttempts(userId, items(payload, "quiz_attempts"), quizIds, counts);
        importBranches(userId, items(payload, "branches"), sessionIds, messageIds, counts);
        return Map.of("status", "imported", "version", version, "counts", counts);
    }

    private void validateQuestion(Map<String, Object> question) {
        String type = String.valueOf(question.get("type"));
        if (!List.of("choice", "short").contains(type) || required(question, "prompt").length() > 500) {
            throw new IllegalArgumentException("生成的题目结构不合法");
        }
        if ("choice".equals(type) && stringList(question.get("options")).size() < 2) {
            throw new IllegalArgumentException("选择题至少需要两个选项");
        }
    }

    private List<Map<String, Object>> generateQuestions(String topic, List<Map<String, Object>> chunks) {
        try {
            @SuppressWarnings("unchecked") Map<String, Object> response = restTemplate.postForObject(
                pythonAgentUrl + "/api/v1/knowledge/quiz/generate", Map.of("topic", topic, "chunks", chunks), Map.class);
            List<Map<String, Object>> generated = mapper.convertValue(
                response == null ? List.of() : response.getOrDefault("questions", List.of()), new TypeReference<>() {});
            if (generated.isEmpty() || generated.size() > 5) throw new IllegalArgumentException("模型返回题目数量不合法");
            generated.forEach(this::validateQuestion);
            return generated;
        } catch (Exception ignored) {
            List<Map<String, Object>> fallback = new ArrayList<>();
            int count = Math.max(1, Math.min(3, chunks.size()));
            for (int index = 0; index < count; index++) {
                Map<String, Object> chunk = chunks.get(index);
                String content = String.valueOf(chunk.getOrDefault("content", topic));
                String excerpt = abbreviate(content, 240);
                List<String> keyPoints = extractKeyPoints(content, 3);
                Map<String, Object> question = new LinkedHashMap<>();
                question.put("id", index + 1);
                question.put("type", index == 2 ? "short" : "choice");
                question.put("prompt", index == 2 ? "请根据资料说明“" + topic + "”的关键内容" : "以下哪项有资料证据支持？");
                question.put("options", index == 2 ? List.of() : List.of(excerpt, "资料未提及该主题", "资料明确否定上述内容"));
                question.put("answer", index == 2 ? String.join("；", keyPoints) : "0");
                question.put("key_points", keyPoints);
                question.put("evidence", excerpt);
                question.put("source", chunk.getOrDefault("metadata", Map.of()));
                validateQuestion(question);
                fallback.add(question);
            }
            return fallback;
        }
    }

    private List<String> extractKeyPoints(String content, int maximum) {
        List<String> points = new ArrayList<>();
        for (String part : KEY_POINT_SPLIT.split(content)) {
            String point = part.replaceAll("\\s+", " ").trim();
            if (point.length() >= 4 && points.stream().noneMatch(point::equals)) {
                points.add(abbreviate(point, 80));
                if (points.size() >= maximum) break;
            }
        }
        if (points.isEmpty() && !content.isBlank()) points.add(abbreviate(content.trim(), 80));
        return points;
    }

    private int countCoveredKeyPoints(String answer, List<String> keyPoints) {
        String normalizedAnswer = normalizeText(answer);
        int covered = 0;
        for (String point : keyPoints) {
            List<String> tokens = meaningfulTokens(point);
            long matches = tokens.stream().filter(normalizedAnswer::contains).count();
            if (!tokens.isEmpty() && matches * 2 >= tokens.size()) covered++;
        }
        return covered;
    }

    private List<String> meaningfulTokens(String text) {
        String normalized = normalizeText(text);
        List<String> tokens = new ArrayList<>();
        for (String word : normalized.split(" ")) if (word.length() >= 2) tokens.add(word);
        if (tokens.size() <= 1 && normalized.length() >= 2) {
            tokens.clear();
            for (int index = 0; index < normalized.length() - 1; index += 2) {
                tokens.add(normalized.substring(index, Math.min(index + 2, normalized.length())));
            }
        }
        return tokens;
    }

    private String normalizeText(String text) {
        return text.toLowerCase().replaceAll("[^a-z0-9\\u4e00-\\u9fff]+", " ").trim();
    }

    private void createMistakeReview(Long userId, String prompt, String answer, String topic) {
        jdbc.update("INSERT INTO review_card(user_id,prompt,answer,due_at,origin) VALUES(?,?,?,NOW(),?)",
            userId, prompt, answer, "quiz_mistake");
        jdbc.update("""
            INSERT INTO pending_memory(memory_id,user_id,category,content,topic,confidence,status)
            VALUES(?,?, 'weak_point', ?, ?, 0.8500, 'pending')
            """, UUID.randomUUID().toString(), userId, "测验错题：" + prompt, abbreviate(topic, 255));
    }

    private Map<Long, Long> importKnowledgeBases(Long userId, List<Map<String, Object>> source, Map<String, Integer> counts) {
        Map<Long, Long> ids = new HashMap<>();
        for (Map<String, Object> item : source) {
            jdbc.update("INSERT INTO knowledge_base(user_id,name,description,status) VALUES(?,?,?,?)", userId,
                limited(item, "name", "导入资料库", 100), limited(item, "description", "", 10_000), safeStatus(item, "status", "active"));
            ids.put(longValue(item.get("id")), lastId());
        }
        counts.put("knowledge_bases", source.size());
        return ids;
    }

    private Map<Long, Long> importSessions(Long userId, List<Map<String, Object>> source, Map<String, Integer> counts) {
        Map<Long, Long> ids = new HashMap<>();
        for (Map<String, Object> item : source) {
            jdbc.update("INSERT INTO chat_session(user_id,title) VALUES(?,?)", userId, limited(item, "title", "导入会话", 200));
            ids.put(longValue(item.get("id")), lastId());
        }
        counts.put("sessions", source.size());
        return ids;
    }

    private Map<Long, Long> importMessages(List<Map<String, Object>> source, Map<Long, Long> sessions, Map<String, Integer> counts) {
        Map<Long, Long> ids = new HashMap<>();
        int imported = 0;
        for (Map<String, Object> item : source) {
            Long sessionId = sessions.get(longValue(item.get("session_id")));
            if (sessionId == null) continue;
            String role = String.valueOf(item.getOrDefault("role", "user"));
            if (!List.of("user", "assistant", "system").contains(role)) role = "user";
            jdbc.update("INSERT INTO chat_message(session_id,role,content,status) VALUES(?,?,?,?)", sessionId, role,
                limited(item, "content", "", IMPORT_MAX_TEXT_LENGTH), safeStatus(item, "status", "completed"));
            ids.put(longValue(item.get("id")), lastId());
            imported++;
        }
        counts.put("messages", imported);
        return ids;
    }

    private Map<Long, Long> importPlans(Long userId, List<Map<String, Object>> source, Map<String, Integer> counts) {
        Map<Long, Long> ids = new HashMap<>();
        for (Map<String, Object> item : source) {
            Date target = parseDate(item.get("target_date"));
            jdbc.update("INSERT INTO learning_plan(user_id,title,goal,target_date,status) VALUES(?,?,?,?,?)", userId,
                limited(item, "title", "导入计划", 200), limited(item, "goal", "", IMPORT_MAX_TEXT_LENGTH), target,
                safeStatus(item, "status", "active"));
            ids.put(longValue(item.get("id")), lastId());
        }
        counts.put("plans", source.size());
        return ids;
    }

    private void importReviews(Long userId, List<Map<String, Object>> source, Map<Long, Long> plans, Map<String, Integer> counts) {
        for (Map<String, Object> item : source) {
            jdbc.update("""
                INSERT INTO review_card(user_id,plan_id,prompt,answer,interval_days,ease_factor,due_at,last_rating,review_count)
                VALUES(?,?,?,?,?,?,COALESCE(?,NOW()),?,?,?)
                """, userId, nullableMappedId(item.get("plan_id"), plans), limited(item, "prompt", "导入复习题", IMPORT_MAX_TEXT_LENGTH),
                limited(item, "answer", "", IMPORT_MAX_TEXT_LENGTH), positiveInteger(item.get("interval_days"), 1),
                decimal(item.get("ease_factor"), 2.5), parseTimestamp(item.get("due_at")), nullableInteger(item.get("last_rating")),
                positiveInteger(item.get("review_count"), 0), "imported");
        }
        counts.put("reviews", source.size());
    }

    private Map<Long, Long> importQuizzes(Long userId, List<Map<String, Object>> source, Map<Long, Long> kbs, Map<String, Integer> counts) throws Exception {
        Map<Long, Long> ids = new HashMap<>();
        for (Map<String, Object> item : source) {
            Object questions = item.getOrDefault("questions_json", List.of());
            String questionsJson = questions instanceof String ? String.valueOf(questions) : mapper.writeValueAsString(questions);
            mapper.readTree(questionsJson);
            jdbc.update("INSERT INTO knowledge_quiz(user_id,kb_id,title,topic,questions_json) VALUES(?,?,?,?,CAST(? AS JSON))", userId,
                nullableMappedId(item.get("kb_id"), kbs), limited(item, "title", "导入测验", 200), limited(item, "topic", "导入主题", 200), questionsJson);
            ids.put(longValue(item.get("id")), lastId());
        }
        counts.put("quizzes", source.size());
        return ids;
    }

    private void importAttempts(Long userId, List<Map<String, Object>> source, Map<Long, Long> quizzes, Map<String, Integer> counts) throws Exception {
        int imported = 0;
        for (Map<String, Object> item : source) {
            Long quizId = quizzes.get(longValue(item.get("quiz_id")));
            if (quizId == null) continue;
            String answers = validJson(item.get("answers_json"), List.of());
            String feedback = validJson(item.get("feedback_json"), List.of());
            jdbc.update("INSERT INTO quiz_attempt(quiz_id,user_id,answers_json,score,feedback_json) VALUES(?,?,CAST(? AS JSON),?,CAST(? AS JSON))",
                quizId, userId, answers, Math.max(0, Math.min(100, integer(item.get("score"), 0))), feedback);
            imported++;
        }
        counts.put("quiz_attempts", imported);
    }

    private void importBranches(Long userId, List<Map<String, Object>> source, Map<Long, Long> sessions,
                                Map<Long, Long> messages, Map<String, Integer> counts) {
        int imported = 0;
        for (Map<String, Object> item : source) {
            Long sourceSession = sessions.get(longValue(item.get("source_session_id")));
            Long branchSession = sessions.get(longValue(item.get("branch_session_id")));
            if (sourceSession == null || branchSession == null) continue;
            jdbc.update("INSERT INTO chat_branch(user_id,source_session_id,source_message_id,branch_session_id,label) VALUES(?,?,?,?,?)",
                userId, sourceSession, nullableMappedId(item.get("source_message_id"), messages), branchSession,
                limited(item, "label", "导入分支", 120));
            imported++;
        }
        counts.put("branches", imported);
    }

    private List<Map<String, Object>> items(Map<String, Object> payload, String key) {
        List<Map<String, Object>> result = mapper.convertValue(payload.getOrDefault(key, List.of()), new TypeReference<>() {});
        if (result.size() > IMPORT_MAX_ITEMS) throw new IllegalArgumentException(key + " 超过单次导入上限 " + IMPORT_MAX_ITEMS);
        return result;
    }

    private String validJson(Object value, Object fallback) throws Exception {
        String json = value == null ? mapper.writeValueAsString(fallback) : value instanceof String ? String.valueOf(value) : mapper.writeValueAsString(value);
        mapper.readTree(json);
        return json;
    }

    private Long lastId() { return jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class); }
    private long longValue(Object value) { return value == null ? Long.MIN_VALUE : Long.parseLong(String.valueOf(value)); }
    private Long nullableMappedId(Object value, Map<Long, Long> ids) { return value == null ? null : ids.get(longValue(value)); }
    private int integer(Object value, int fallback) { try { return value == null ? fallback : Integer.parseInt(String.valueOf(value)); } catch (NumberFormatException ignored) { return fallback; } }
    private Integer nullableInteger(Object value) { return value == null ? null : integer(value, 0); }
    private int positiveInteger(Object value, int fallback) { return Math.max(0, integer(value, fallback)); }
    private double decimal(Object value, double fallback) { try { return value == null ? fallback : Double.parseDouble(String.valueOf(value)); } catch (NumberFormatException ignored) { return fallback; } }
    private String abbreviate(String value, int maximum) { return value.length() <= maximum ? value : value.substring(0, maximum); }
    private String limited(Map<String, Object> item, String key, String fallback, int maximum) { return abbreviate(String.valueOf(item.getOrDefault(key, fallback)), maximum); }
    private String safeStatus(Map<String, Object> item, String key, String fallback) { String value = limited(item, key, fallback, 20); return value.matches("[a-z_]{1,20}") ? value : fallback; }
    private Date parseDate(Object value) { try { return value == null ? null : Date.valueOf(String.valueOf(value).substring(0, 10)); } catch (RuntimeException ignored) { return null; } }
    private Timestamp parseTimestamp(Object value) { try { return value == null ? null : Timestamp.valueOf(String.valueOf(value).replace('T', ' ').substring(0, 19)); } catch (RuntimeException ignored) { return null; } }
    private List<String> stringList(Object value) { return mapper.convertValue(value == null ? List.of() : value, new TypeReference<>() {}); }

    private void requireKb(Long userId, Long kbId) { one("SELECT id FROM knowledge_base WHERE id=? AND user_id=?", kbId, userId); }
    private String required(Map<String, Object> body, String key) {
        String value = String.valueOf(body.getOrDefault(key, "")).trim();
        if (value.isBlank()) throw new IllegalArgumentException(key + " 不能为空");
        return value;
    }
    private List<Map<String, Object>> rows(String sql, Object... args) { return jdbc.queryForList(sql, args); }
    private long count(String sql, Object... args) {
        Long value = jdbc.queryForObject(sql, Long.class, args);
        return value == null ? 0 : value;
    }
    private double average(String sql, Object... args) {
        Double value = jdbc.queryForObject(sql, Double.class, args);
        return value == null ? 0.0 : Math.round(value * 100.0) / 100.0;
    }
    private double ratio(long numerator, long denominator) {
        return denominator == 0 ? 0.0 : Math.round((double) numerator / denominator * 10000.0) / 10000.0;
    }
    private String operationId() {
        return operationLog == null ? UUID.randomUUID().toString() : operationLog.newOperationId();
    }
    private void record(
        String operationId,
        Long userId,
        String type,
        String aggregateId,
        String step,
        String status,
        Map<String, ?> payload,
        Exception error
    ) {
        if (operationLog != null) {
            operationLog.record(operationId, userId, type, aggregateId, step, status, payload, error);
        }
    }
    private String jsonText(Object value) {
        return value instanceof byte[] bytes ? new String(bytes, StandardCharsets.UTF_8) : String.valueOf(value);
    }
    private Map<String, Object> one(String sql, Object... args) {
        List<Map<String, Object>> values = rows(sql, args);
        if (values.isEmpty()) throw new IllegalArgumentException("资源不存在或无权访问");
        return values.get(0);
    }
}

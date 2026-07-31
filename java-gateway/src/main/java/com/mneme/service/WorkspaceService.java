package com.mneme.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Date;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class WorkspaceService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final RestTemplate restTemplate;

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
        Path path = Path.of(String.valueOf(document.get("file_path"))).normalize();
        String fileName = String.valueOf(document.get("file_name"));
        String extension = fileName.contains(".") ? fileName.substring(fileName.lastIndexOf('.') + 1).toLowerCase() : "";
        String content;
        if (List.of("txt", "md", "csv", "html").contains(extension) && Files.isRegularFile(path)) {
            byte[] bytes = Files.readAllBytes(path);
            content = new String(bytes, 0, Math.min(bytes.length, 250_000), StandardCharsets.UTF_8);
        } else {
            content = "该格式使用语义片段定位。请从回答引用或检索调试器查看对应页码、章节和片段。";
        }
        return Map.of("document", document, "content", content, "extension", extension);
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
            SET d.status='parsing',d.error_message=NULL WHERE t.user_id=? AND t.task_id=?
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
            jdbc.update("INSERT INTO review_card(user_id,plan_id,prompt,answer,due_at) VALUES(?,?,?,?,?)",
                userId, id, prompts[index], "完成学习后补充你的答案", Timestamp.valueOf(LocalDateTime.now().plusDays(index)));
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
        List<Map<String, Object>> questions = new ArrayList<>();
        int count = Math.max(1, Math.min(3, chunks.size()));
        for (int index = 0; index < count; index++) {
            Map<String, Object> chunk = chunks.get(index);
            String content = String.valueOf(chunk.getOrDefault("content", topic));
            String excerpt = content.length() > 120 ? content.substring(0, 120) + "…" : content;
            questions.add(Map.of(
                "id", index + 1,
                "type", index == 2 ? "short" : "choice",
                "prompt", index == 2 ? "请简述该主题的核心含义" : "以下哪项最符合检索资料中的内容？",
                "options", index == 2 ? List.of() : List.of(excerpt, "与资料无关的陈述", "资料明确否定该内容"),
                "answer", index == 2 ? excerpt : "0",
                "source", chunk.getOrDefault("metadata", Map.of())
            ));
        }
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
            boolean ok = "short".equals(questions.get(index).get("type")) ? actual.length() >= 8 : expected.equals(actual);
            if (ok) correct++;
            feedback.add(Map.of("question_id", index + 1, "correct", ok, "expected", expected));
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
        data.put("version", 1);
        data.put("exported_at", LocalDateTime.now().toString());
        data.put("knowledge_bases", rows("SELECT id,name,description,status,created_at FROM knowledge_base WHERE user_id=?", userId));
        data.put("sessions", rows("SELECT id,title,created_at,updated_at FROM chat_session WHERE user_id=?", userId));
        data.put("messages", rows("SELECT m.id,m.session_id,m.role,m.content,m.status,m.created_at FROM chat_message m JOIN chat_session s ON s.id=m.session_id WHERE s.user_id=?", userId));
        data.put("plans", plans(userId));
        data.put("reviews", reviews(userId));
        data.put("quizzes", quizzes(userId));
        data.put("branches", branches(userId));
        return data;
    }

    @Transactional
    public Map<String, Object> importData(Long userId, Map<String, Object> payload) {
        List<Map<String, Object>> plans = mapper.convertValue(payload.getOrDefault("plans", List.of()), new TypeReference<>() {});
        int imported = 0;
        for (Map<String, Object> plan : plans) {
            jdbc.update("INSERT INTO learning_plan(user_id,title,goal,status) VALUES(?,?,?,?)", userId,
                String.valueOf(plan.getOrDefault("title", "导入计划")), String.valueOf(plan.getOrDefault("goal", "")), "active");
            imported++;
        }
        return Map.of("status", "imported", "plans", imported);
    }

    private void requireKb(Long userId, Long kbId) { one("SELECT id FROM knowledge_base WHERE id=? AND user_id=?", kbId, userId); }
    private String required(Map<String, Object> body, String key) {
        String value = String.valueOf(body.getOrDefault(key, "")).trim();
        if (value.isBlank()) throw new IllegalArgumentException(key + " 不能为空");
        return value;
    }
    private List<Map<String, Object>> rows(String sql, Object... args) { return jdbc.queryForList(sql, args); }
    private String jsonText(Object value) {
        return value instanceof byte[] bytes ? new String(bytes, StandardCharsets.UTF_8) : String.valueOf(value);
    }
    private Map<String, Object> one(String sql, Object... args) {
        List<Map<String, Object>> values = rows(sql, args);
        if (values.isEmpty()) throw new IllegalArgumentException("资源不存在或无权访问");
        return values.get(0);
    }
}

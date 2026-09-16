package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.service.WorkspaceService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.http.MediaTypeFactory;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;

@RestController
@RequestMapping("/api/v1/workspace")
public class WorkspaceController {
    private final WorkspaceService workspace;
    private final RestTemplate restTemplate;

    @Value("${mneme.python-agent-url}") private String pythonAgentUrl;

    public WorkspaceController(WorkspaceService workspace, RestTemplate restTemplate) {
        this.workspace = workspace;
        this.restTemplate = restTemplate;
    }

    @GetMapping("/documents/{id}/preview") public Result<Map<String, Object>> preview(@RequestAttribute("userId") Long userId, @PathVariable Long id) throws Exception { return Result.success(workspace.preview(userId, id)); }
    @GetMapping("/documents/{id}/file")
    public ResponseEntity<Resource> documentFile(@RequestAttribute("userId") Long userId, @PathVariable Long id) {
        Path path = workspace.documentPath(userId, id);
        Resource resource = new FileSystemResource(path);
        MediaType contentType = MediaTypeFactory.getMediaType(path.getFileName().toString())
            .orElse(MediaType.APPLICATION_OCTET_STREAM);
        return ResponseEntity.ok()
            .contentType(contentType)
            .header("Content-Disposition", ContentDisposition.inline()
                .filename(path.getFileName().toString(), StandardCharsets.UTF_8).build().toString())
            .body(resource);
    }
    @GetMapping("/tasks") public Result<List<Map<String, Object>>> tasks(@RequestAttribute("userId") Long userId) { return Result.success(workspace.tasks(userId)); }
    @PostMapping("/tasks/{taskId}/retry") public Result<Map<String, Object>> retry(@RequestAttribute("userId") Long userId, @PathVariable String taskId) { return Result.success(workspace.retryTask(userId, taskId)); }
    @GetMapping("/operations") public Result<List<Map<String, Object>>> operations(@RequestAttribute("userId") Long userId, @RequestParam(defaultValue="100") int limit) { return Result.success(workspace.operationLogs(userId, limit)); }
    @GetMapping("/retrieval/debug") public Result<Map<String, Object>> debug(@RequestAttribute("userId") Long userId, @RequestParam Long kbId, @RequestParam String query, @RequestParam(defaultValue="6") int topK) { return Result.success(workspace.debugRetrieval(userId, kbId, query, topK)); }
    @GetMapping("/plans") public Result<List<Map<String, Object>>> plans(@RequestAttribute("userId") Long userId) { return Result.success(workspace.plans(userId)); }
    @GetMapping("/metrics") public Result<Map<String, Object>> metrics(@RequestAttribute("userId") Long userId) { return Result.success(workspace.metrics(userId)); }
    @GetMapping("/metrics/history") public Result<List<Map<String, Object>>> metricHistory(
        @RequestAttribute("userId") Long userId,
        @RequestParam(defaultValue = "30") int days
    ) { return Result.success(workspace.metricHistory(userId, days)); }
    @PostMapping("/plans") public Result<Map<String, Object>> plan(@RequestAttribute("userId") Long userId, @RequestBody Map<String, Object> body) { return Result.success(workspace.createPlan(userId, body)); }
    @GetMapping("/reviews") public Result<List<Map<String, Object>>> reviews(@RequestAttribute("userId") Long userId) { return Result.success(workspace.reviews(userId)); }
    @PostMapping("/reviews/{id}") public Result<Map<String, Object>> review(@RequestAttribute("userId") Long userId, @PathVariable Long id, @RequestBody Map<String, Object> body) { return Result.success(workspace.review(userId, id, Integer.parseInt(String.valueOf(body.getOrDefault("rating", 3))))); }
    @GetMapping("/quizzes") public Result<List<Map<String, Object>>> quizzes(@RequestAttribute("userId") Long userId) { return Result.success(workspace.quizzes(userId)); }
    @PostMapping("/quizzes/generate") public Result<Map<String, Object>> generateQuiz(@RequestAttribute("userId") Long userId, @RequestBody Map<String, Object> body) throws Exception { return Result.success(workspace.generateQuiz(userId, body)); }
    @PostMapping("/quizzes/{id}/submit") public Result<Map<String, Object>> submitQuiz(@RequestAttribute("userId") Long userId, @PathVariable Long id, @RequestBody Map<String, Object> body) throws Exception { return Result.success(workspace.submitQuiz(userId, id, body)); }
    @GetMapping("/branches") public Result<List<Map<String, Object>>> branches(@RequestAttribute("userId") Long userId) { return Result.success(workspace.branches(userId)); }
    @PostMapping("/branches") public Result<Map<String, Object>> branch(@RequestAttribute("userId") Long userId, @RequestBody Map<String, Object> body) { return Result.success(workspace.createBranch(userId, body)); }
    @GetMapping("/branches/{id}/compare") public Result<Map<String, Object>> compare(@RequestAttribute("userId") Long userId, @PathVariable Long id) { return Result.success(workspace.compareBranch(userId, id)); }

    @GetMapping("/memories") public Result<Object> memories(@RequestAttribute("userId") Long userId) { return Result.success(restTemplate.getForObject(pythonAgentUrl + "/api/v1/memory/admin/" + userId, Object.class)); }
    @PatchMapping("/memories/{id}") public Result<Object> updateMemory(@RequestAttribute("userId") Long userId, @PathVariable String id, @RequestBody Map<String, Object> body) {
        body.put("user_id", userId.toString());
        restTemplate.exchange(
            pythonAgentUrl + "/api/v1/memory/admin/" + id,
            HttpMethod.PATCH,
            new HttpEntity<>(body),
            Object.class
        );
        return memories(userId);
    }
    @DeleteMapping("/memories/{id}") public Result<Object> deleteMemory(@RequestAttribute("userId") Long userId, @PathVariable String id) {
        restTemplate.delete(pythonAgentUrl + "/api/v1/memory/admin/" + id + "?user_id=" + userId);
        return memories(userId);
    }
    @GetMapping("/memories/{id}/versions") public Result<Object> memoryVersions(@RequestAttribute("userId") Long userId, @PathVariable String id) {
        return Result.success(restTemplate.getForObject(
            pythonAgentUrl + "/api/v1/memory/admin/" + id + "/versions?user_id=" + userId,
            Object.class
        ));
    }
    @PostMapping("/memories/{id}/restore") public Result<Object> restoreMemory(@RequestAttribute("userId") Long userId, @PathVariable String id, @RequestBody Map<String, Object> body) {
        body.put("user_id", userId.toString());
        restTemplate.postForObject(
            pythonAgentUrl + "/api/v1/memory/admin/" + id + "/restore",
            body,
            Object.class
        );
        return memories(userId);
    }

    @GetMapping(value="/export", produces=MediaType.APPLICATION_JSON_VALUE) public ResponseEntity<Map<String, Object>> exportData(@RequestAttribute("userId") Long userId) {
        return ResponseEntity.ok().header("Content-Disposition", "attachment; filename=mneme-export.json").body(workspace.exportData(userId));
    }
    @GetMapping(value="/export/archive", produces="application/zip") public ResponseEntity<byte[]> exportArchive(@RequestAttribute("userId") Long userId) throws Exception {
        return ResponseEntity.ok().header("Content-Disposition", "attachment; filename=mneme-workspace.zip").body(workspace.exportArchive(userId));
    }
    @PostMapping(value="/import/archive", consumes=MediaType.MULTIPART_FORM_DATA_VALUE)
    public Result<Map<String, Object>> importArchive(@RequestAttribute("userId") Long userId, @RequestParam("archive") MultipartFile archive) throws Exception {
        return Result.success(workspace.importArchive(userId, archive.getBytes()));
    }
    @PostMapping("/import") public Result<Map<String, Object>> importData(@RequestAttribute("userId") Long userId, @RequestBody Map<String, Object> body) throws Exception { return Result.success(workspace.importData(userId, body)); }
}

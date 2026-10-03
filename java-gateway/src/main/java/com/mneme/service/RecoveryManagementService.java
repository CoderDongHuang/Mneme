package com.mneme.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import java.util.*;

@Service
public class RecoveryManagementService {
    private final RestTemplate http;
    private final String repository;
    private final String token;
    private final OperationLogService operations;
    private static final String WORKFLOW = "disaster-recovery.yml";
    public RecoveryManagementService(RestTemplate http, OperationLogService operations,
        @Value("${mneme.recovery-github-repository:}") String repository,
        @Value("${mneme.recovery-github-token:}") String token) {
        this.http = http; this.operations = operations; this.repository = repository; this.token = token;
    }
    private String url(String suffix) {
        if (!repository.matches("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+") || token.isBlank())
            throw new IllegalArgumentException("恢复工作流未配置");
        return "https://api.github.com/repos/" + repository + "/actions/" + suffix;
    }
    private HttpHeaders headers() {
        HttpHeaders headers = new HttpHeaders();
        headers.setBearerAuth(token); headers.setAccept(List.of(MediaType.APPLICATION_JSON));
        headers.set("X-GitHub-Api-Version", "2022-11-28");
        return headers;
    }
    @SuppressWarnings("unchecked")
    private Map<String, Object> get(String suffix) {
        Map<String, Object> body = http.exchange(url(suffix), HttpMethod.GET, new HttpEntity<>(headers()), Map.class).getBody();
        return body == null ? Map.of() : body;
    }
    public Map<String, Object> history() {
        return Map.of("runs", get("workflows/" + WORKFLOW + "/runs?per_page=30").getOrDefault("workflow_runs", List.of()));
    }
    public Map<String, Object> evidence(long runId) {
        if (runId < 1) throw new IllegalArgumentException("无效演练编号");
        Map<String, Object> run = get("runs/" + runId);
        if (!String.valueOf(run.get("path")).equals(".github/workflows/" + WORKFLOW))
            throw new IllegalArgumentException("不是恢复工作流");
        return Map.of("run", run, "jobs", get("runs/" + runId + "/jobs?per_page=100").getOrDefault("jobs", List.of()),
            "artifacts", get("runs/" + runId + "/artifacts?per_page=100").getOrDefault("artifacts", List.of()));
    }
    public Map<String, Object> dispatch(Long userId, String confirmation) {
        if (!"ISOLATED DRILL".equals(confirmation)) throw new IllegalArgumentException("必须确认隔离恢复演练");
        http.exchange(url("workflows/" + WORKFLOW + "/dispatches"), HttpMethod.POST,
            new HttpEntity<>(Map.of("ref", "main"), headers()), Void.class);
        operations.record(operations.newOperationId(), userId, "recovery_drill", "main", "dispatch", "accepted", Map.of(), null);
        return Map.of("status", "accepted");
    }
}

package com.mneme.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import java.util.Map;

/** The privileged executor runs on the operator's host, outside the service being restored. */
@Service
public class SiteRecoveryService {
    private final RestTemplate http;
    private final String url;
    private final String token;
    private final OperationLogService operations;
    public SiteRecoveryService(@Qualifier("recoveryHttp") RestTemplate http, OperationLogService operations,
        @Value("${mneme.recovery-worker-url:}") String url,
        @Value("${mneme.recovery-worker-token:}") String token) {
        this.http = http; this.operations = operations; this.url = url; this.token = token;
    }
    @SuppressWarnings("unchecked")
    private Map<String,Object> call(String path, HttpMethod method, Map<String,String> body) {
        if (url.isBlank() || token.length() < 32) throw new IllegalArgumentException("整站恢复执行器未配置。请在 Docker 宿主机启动 scripts/recovery_worker.py 并设置恢复服务地址与凭证。");
        HttpHeaders headers = new HttpHeaders(); headers.setBearerAuth(token); headers.setContentType(MediaType.APPLICATION_JSON);
        try {
            Map<String,Object> result = http.exchange(url.replaceAll("/+$", "") + "/site" + path, method, new HttpEntity<>(body, headers), Map.class).getBody();
            return result == null ? Map.of() : result;
        } catch (org.springframework.web.client.HttpClientErrorException error) {
            throw new IllegalArgumentException("整站恢复请求被拒绝，请检查归档、确认语句与摘要，或等待现有任务完成。");
        } catch (org.springframework.web.client.RestClientException error) {
            throw new IllegalArgumentException("宿主机恢复执行器不可用或校验超时，请检查服务后刷新任务历史，避免重复提交。");
        }
    }
    public Map<String,Object> history() { return call("", HttpMethod.GET, null); }
    public Map<String,Object> preview(String archive) {
        return call("/preview", HttpMethod.POST, Map.of("archive", archive));
    }
    public Map<String,Object> submit(Long user, Map<String,String> body) {
        String action = body.getOrDefault("action", "");
        if (!java.util.List.of("backup", "restore").contains(action)) throw new IllegalArgumentException("无效整站操作");
        String expected = action.equals("restore") ? "RESTORE SITE" : "BACKUP SITE";
        if (!expected.equals(body.get("confirmation"))) throw new IllegalArgumentException("请确认整站操作范围");
        Map<String,Object> result = call("/jobs", HttpMethod.POST, Map.of(
            "action", action, "confirmation", expected,
            "archive", body.getOrDefault("archive", ""), "sha256", body.getOrDefault("sha256", "")));
        operations.record(operations.newOperationId(), user, "site_" + action, String.valueOf(result.get("id")), "dispatch", "accepted", Map.of(), null);
        return result;
    }
}

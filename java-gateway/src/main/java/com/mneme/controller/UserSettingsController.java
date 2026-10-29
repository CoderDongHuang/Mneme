package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.service.UserSettingsService;
import com.mneme.service.InternalServiceTokenProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.Base64;
import com.fasterxml.jackson.databind.ObjectMapper;

@RestController
@RequestMapping("/api/v1/settings")
public class UserSettingsController {
    private final UserSettingsService settings;
    private final InternalServiceTokenProvider tokens;
    private final ObjectMapper mapper;
    private final String pythonUrl;
    public UserSettingsController(UserSettingsService settings, InternalServiceTokenProvider tokens, ObjectMapper mapper,
        @Value("${mneme.python-agent-url}") String pythonUrl) {
        this.settings = settings; this.tokens = tokens; this.mapper = mapper; this.pythonUrl = pythonUrl;
    }
    @GetMapping("/preferences") public Result<?> preferences(@RequestAttribute("userId") Long userId) { return Result.success(settings.preferences(userId)); }
    @PutMapping("/preferences") public Result<?> preferences(@RequestAttribute("userId") Long userId, @RequestBody Map<String,Object> body) { return Result.success(settings.savePreferences(userId, body)); }
    @GetMapping("/models") public Result<?> models(@RequestAttribute("userId") Long userId) { return Result.success(settings.models(userId)); }
    @PutMapping("/models") public Result<?> models(@RequestAttribute("userId") Long userId, @RequestBody Map<String,Object> body) { return Result.success(settings.saveModels(userId, body)); }
    @PostMapping("/models/test") public Result<?> test(@RequestAttribute("userId") Long userId, @RequestBody Map<String,Object> body) throws Exception {
        var config = settings.validated(userId, body);
        if (String.valueOf(config.get("apiKey")).isBlank()) throw new IllegalArgumentException("请填写待测试密钥");
        var request = HttpRequest.newBuilder(URI.create(pythonUrl + "/api/v1/models/test"))
            .timeout(Duration.ofSeconds(45)).header("X-Internal-Service-Token", tokens.current())
            .header("X-Mneme-Model", Base64.getEncoder().encodeToString(mapper.writeValueAsBytes(config)))
            .POST(HttpRequest.BodyPublishers.noBody()).build();
        var response = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build().send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) throw new IllegalArgumentException("模型测试失败，请检查服务、模型名称与密钥");
        return Result.success(mapper.readValue(response.body(), Map.class));
    }
}

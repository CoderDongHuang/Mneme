package com.mneme.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.ZoneId;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class UserSettingsService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final SecretKeySpec key;
    private static final Map<String, String> PROVIDERS = Map.of(
        "deepseek", "https://api.deepseek.com/v1",
        "dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "openai", "https://api.openai.com/v1"
    );

    public UserSettingsService(JdbcTemplate jdbc, ObjectMapper mapper,
        @Value("${mneme.model-config-encryption-key:}") String encryptionKey,
        @Value("${mneme.jwt-secret}") String jwtSecret) {
        this.jdbc = jdbc; this.mapper = mapper;
        String effectiveKey = encryptionKey.isBlank() ? jwtSecret : encryptionKey;
        if (effectiveKey.length() < 32) throw new IllegalArgumentException("配置加密密钥至少需要 32 个字符");
        try {
            key = new SecretKeySpec(MessageDigest.getInstance("SHA-256").digest(
                ("mneme:user-model:v1:" + effectiveKey).getBytes(StandardCharsets.UTF_8)), "AES");
        } catch (Exception error) { throw new IllegalStateException("无法初始化配置加密", error); }
    }

    public Map<String, Object> preferences(Long userId) {
        var rows = jdbc.queryForList("SELECT language,timezone,notifications,theme FROM user_preference WHERE user_id=?", userId);
        return rows.isEmpty() ? Map.of("language", "zh-CN", "timezone", "Asia/Shanghai", "notifications", true, "theme", "system") : rows.get(0);
    }

    public Map<String, Object> savePreferences(Long userId, Map<String, Object> body) {
        String language = String.valueOf(body.getOrDefault("language", "zh-CN"));
        String timezone = String.valueOf(body.getOrDefault("timezone", "Asia/Shanghai"));
        String theme = String.valueOf(body.getOrDefault("theme", "system"));
        if (!List.of("zh-CN", "en").contains(language) || !List.of("system", "light", "dark").contains(theme)) {
            throw new IllegalArgumentException("语言或主题无效");
        }
        try { ZoneId.of(timezone); } catch (Exception error) { throw new IllegalArgumentException("时区无效"); }
        if (!(body.getOrDefault("notifications", true) instanceof Boolean)) throw new IllegalArgumentException("通知偏好无效");
        jdbc.update("""
            INSERT INTO user_preference(user_id,language,timezone,notifications,theme) VALUES(?,?,?,?,?)
            ON DUPLICATE KEY UPDATE language=VALUES(language),timezone=VALUES(timezone),notifications=VALUES(notifications),theme=VALUES(theme)
            """, userId, language, timezone, body.getOrDefault("notifications", true), theme);
        return preferences(userId);
    }

    public Map<String, Object> models(Long userId) {
        Map<String, Object> result = new LinkedHashMap<>(decrypted(userId));
        String apiKey = String.valueOf(result.remove("apiKey"));
        result.put("hasKey", !apiKey.isBlank() && !"null".equals(apiKey));
        result.put("keyMask", Boolean.TRUE.equals(result.get("hasKey")) ? "••••" + apiKey.substring(Math.max(0, apiKey.length() - 4)) : "");
        return result;
    }

    public Map<String, Object> validated(Long userId, Map<String, Object> body) {
        for (String field : List.of("provider", "model", "apiKey")) {
            if (body.containsKey(field) && !(body.get(field) instanceof String))
                throw new IllegalArgumentException("模型配置字段必须为文本");
        }
        for (String field : List.of("enabled", "clearKey")) {
            if (body.containsKey(field) && !(body.get(field) instanceof Boolean))
                throw new IllegalArgumentException("模型开关必须为布尔值");
        }
        String provider = String.valueOf(body.getOrDefault("provider", "deepseek"));
        String model = String.valueOf(body.getOrDefault("model", "deepseek-chat")).trim();
        String apiKey = String.valueOf(body.getOrDefault("apiKey", "")).trim();
        boolean enabled = Boolean.TRUE.equals(body.get("enabled"));
        if (Boolean.TRUE.equals(body.get("clearKey"))) apiKey = "";
        if (apiKey.isEmpty() && !Boolean.TRUE.equals(body.get("clearKey"))) {
            var previous = decrypted(userId);
            if (provider.equals(previous.get("provider"))) apiKey = String.valueOf(previous.getOrDefault("apiKey", ""));
        }
        if (!PROVIDERS.containsKey(provider)) throw new IllegalArgumentException("不支持的模型服务");
        if (!model.matches("[A-Za-z0-9._:/-]{1,120}")) throw new IllegalArgumentException("模型名称无效");
        if (apiKey.length() > 512 || apiKey.chars().anyMatch(character -> character < 32 || character == 127)) throw new IllegalArgumentException("密钥格式无效");
        if (enabled && apiKey.isBlank()) throw new IllegalArgumentException("启用个人模型前请填写密钥");
        return Map.of("provider", provider, "model", model, "apiKey", apiKey, "enabled", enabled, "baseUrl", PROVIDERS.get(provider));
    }

    public Map<String, Object> saveModels(Long userId, Map<String, Object> body) {
        var config = validated(userId, body);
        try {
            byte[] nonce = new byte[12]; new SecureRandom().nextBytes(nonce);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(128, nonce));
            cipher.updateAAD(userId.toString().getBytes(StandardCharsets.UTF_8));
            byte[] encrypted = cipher.doFinal(mapper.writeValueAsBytes(config));
            String payload = Base64.getEncoder().encodeToString(nonce) + "." + Base64.getEncoder().encodeToString(encrypted);
            jdbc.update("INSERT INTO user_model_config(user_id,config_encrypted) VALUES(?,?) ON DUPLICATE KEY UPDATE config_encrypted=VALUES(config_encrypted)", userId, payload);
            return models(userId);
        } catch (Exception error) { throw new IllegalStateException("模型配置保存失败"); }
    }

    public Map<String, Object> decrypted(Long userId) {
        var rows = jdbc.queryForList("SELECT config_encrypted FROM user_model_config WHERE user_id=?", userId);
        if (rows.isEmpty()) return Map.of("provider", "deepseek", "model", "deepseek-chat", "enabled", false, "apiKey", "", "baseUrl", PROVIDERS.get("deepseek"));
        try {
            String[] parts = String.valueOf(rows.get(0).get("config_encrypted")).split("\\.");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, Base64.getDecoder().decode(parts[0])));
            cipher.updateAAD(userId.toString().getBytes(StandardCharsets.UTF_8));
            return mapper.readValue(cipher.doFinal(Base64.getDecoder().decode(parts[1])), new TypeReference<>() {});
        } catch (Exception error) { throw new IllegalStateException("模型配置无法解密，请重新保存配置"); }
    }

    public String modelHeader(Long userId) {
        var config = decrypted(userId);
        if (!Boolean.TRUE.equals(config.get("enabled"))) return "";
        try { return Base64.getEncoder().encodeToString(mapper.writeValueAsBytes(config)); }
        catch (Exception error) { throw new IllegalStateException("无法读取模型配置"); }
    }
}

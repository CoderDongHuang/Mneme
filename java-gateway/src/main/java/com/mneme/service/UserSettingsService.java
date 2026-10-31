package com.mneme.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import org.springframework.transaction.annotation.Transactional;
import java.time.ZoneId;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class UserSettingsService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final ModelConfigKeys keys;
    private static final Map<String, String> PROVIDERS = Map.of(
        "deepseek", "https://api.deepseek.com/v1",
        "dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "openai", "https://api.openai.com/v1"
    );

    public UserSettingsService(JdbcTemplate jdbc, ObjectMapper mapper, ModelConfigKeys keys) {
        this.jdbc = jdbc; this.mapper = mapper; this.keys = keys;
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

    @Transactional
    public Map<String, Object> saveModels(Long userId, Map<String, Object> body) {
        // Serialize updates with rotation before reading a preserved API key.
        jdbc.queryForList("SELECT user_id FROM user_model_config WHERE user_id=? FOR UPDATE", userId);
        // Never overwrite an unreadable existing row, including explicit clearKey.
        decrypted(userId);
        var config = validated(userId, body);
        try {
            String payload = keys.encrypt(userId, mapper.writeValueAsBytes(config));
            jdbc.update("INSERT INTO user_model_config(user_id,config_encrypted,key_version) VALUES(?,?,?) ON DUPLICATE KEY UPDATE config_encrypted=VALUES(config_encrypted),key_version=VALUES(key_version)", userId, payload, keys.activeVersion());
            return models(userId);
        } catch (Exception error) { throw new IllegalStateException("模型配置保存失败"); }
    }

    public Map<String, Object> decrypted(Long userId) {
        var rows = jdbc.queryForList("SELECT config_encrypted,key_version FROM user_model_config WHERE user_id=?", userId);
        if (rows.isEmpty()) return Map.of("provider", "deepseek", "model", "deepseek-chat", "enabled", false, "apiKey", "", "baseUrl", PROVIDERS.get("deepseek"));
        try {
            return mapper.readValue(keys.decrypt(userId, String.valueOf(rows.get(0).get("key_version")),
                String.valueOf(rows.get(0).get("config_encrypted"))), new TypeReference<>() {});
        } catch (Exception error) { throw new IllegalStateException("模型配置无法解密：密钥或版本不匹配，请管理员恢复对应密钥；原配置未更改"); }
    }

    public Map<String, Object> keyStatus() {
        var counts = jdbc.queryForList("SELECT key_version,COUNT(*) AS total FROM user_model_config GROUP BY key_version");
        boolean missing = counts.stream().anyMatch(row -> !keys.availableVersions().contains(String.valueOf(row.get("key_version"))));
        boolean old = counts.stream().anyMatch(row -> !keys.activeVersion().equals(row.get("key_version")));
        return Map.of("active_version", keys.activeVersion(), "stored_versions", counts,
            "rotation_status", missing ? "missing_keys" : old ? "required" : "current",
            "development_jwt_fallback", keys.developmentFallback());
    }

    /** All-or-nothing transaction. Row locks also fence concurrent user saves/rotations. */
    @Transactional
    public Map<String, Object> rotateModelKeys(String expectedVersion) {
        if (!keys.activeVersion().equals(expectedVersion)) throw new IllegalArgumentException("当前密钥版本已改变，请重新确认");
        var rows = jdbc.queryForList("SELECT user_id,config_encrypted,key_version FROM user_model_config ORDER BY user_id FOR UPDATE");
        int changed = 0;
        for (var row : rows) {
            Long user = ((Number) row.get("user_id")).longValue();
            String version = String.valueOf(row.get("key_version"));
            String previous = String.valueOf(row.get("config_encrypted"));
            byte[] plain = keys.decrypt(user, version, previous);
            if (version.equals(keys.activeVersion())) continue;
            String encrypted = keys.encrypt(user, plain);
            if (!java.security.MessageDigest.isEqual(plain, keys.decrypt(user, keys.activeVersion(), encrypted)))
                throw new IllegalStateException("模型配置轮换校验失败");
            int count = jdbc.update("UPDATE user_model_config SET config_encrypted=?,key_version=? WHERE user_id=? AND key_version=? AND config_encrypted=?",
                encrypted, keys.activeVersion(), user, version, previous);
            if (count != 1) throw new IllegalStateException("模型配置已并发改变，轮换已回滚");
            changed++;
        }
        return Map.of("active_version", keys.activeVersion(), "rotated", changed, "verified", rows.size());
    }

    public String modelHeader(Long userId) {
        var config = decrypted(userId);
        if (!Boolean.TRUE.equals(config.get("enabled"))) return "";
        try { return Base64.getEncoder().encodeToString(mapper.writeValueAsBytes(config)); }
        catch (Exception error) { throw new IllegalStateException("无法读取模型配置"); }
    }
}

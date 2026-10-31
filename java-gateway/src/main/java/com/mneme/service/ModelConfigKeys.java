package com.mneme.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;

/** Versioned keyring. Secrets never leave this component or enter diagnostics. */
@Component
public class ModelConfigKeys {
    public static final String LEGACY = "legacy-v1";
    private final Map<String, SecretKeySpec> keys = new HashMap<>();
    private final String activeVersion;
    private final boolean developmentFallback;

    public ModelConfigKeys(ObjectMapper mapper,
        @Value("${mneme.model-config-encryption-key:}") String secret,
        @Value("${mneme.jwt-secret}") String jwt,
        @Value("${mneme.model-config-key-version:v2}") String version,
        @Value("${mneme.model-config-previous-keys:{}}") String previous,
        @Value("${mneme.production:false}") boolean production) {
        if (production && (secret.isBlank() || secret.equals(jwt)))
            throw new IllegalArgumentException("生产环境必须配置独立的 MODEL_CONFIG_ENCRYPTION_KEY");
        if (!validVersion(version) || LEGACY.equals(version))
            throw new IllegalArgumentException("模型配置当前密钥版本无效");
        activeVersion = version;
        developmentFallback = secret.isBlank();
        String effective = developmentFallback ? jwt : secret;
        try {
            Map<String, String> old = mapper.readerFor(new TypeReference<Map<String, String>>() {})
                .with(com.fasterxml.jackson.core.JsonParser.Feature.STRICT_DUPLICATE_DETECTION).readValue(previous);
            for (var entry : old.entrySet()) add(entry.getKey(), entry.getValue());
            if (old.containsKey(version)) throw new IllegalArgumentException();
            // Existing local installations used the same unversioned derivation.
            // Production requires an explicit legacy entry; JWT is never tried there.
            if (!production && !keys.containsKey(LEGACY)) add(LEGACY, effective);
            add(version, effective);
        } catch (Exception error) {
            throw new IllegalArgumentException("模型配置密钥环无效：版本须唯一且密钥至少 32 字符");
        }
    }

    private static boolean validVersion(String value) { return value != null && value.matches("[A-Za-z0-9_-]{1,48}"); }
    private void add(String version, String secret) throws Exception {
        if (!validVersion(version) || secret == null || secret.length() < 32) throw new IllegalArgumentException();
        keys.put(version, new SecretKeySpec(MessageDigest.getInstance("SHA-256").digest(
            ("mneme:user-model:v1:" + secret).getBytes(StandardCharsets.UTF_8)), "AES"));
    }
    public String activeVersion() { return activeVersion; }
    public Set<String> availableVersions() { return Set.copyOf(keys.keySet()); }
    public boolean developmentFallback() { return developmentFallback; }

    private byte[] aad(Long user, String version) {
        return (LEGACY.equals(version) ? user.toString() : "mneme:user-model:v2:" + version + ":" + user).getBytes(StandardCharsets.UTF_8);
    }
    public String encrypt(Long user, byte[] plaintext) {
        try {
            byte[] nonce = new byte[12]; new SecureRandom().nextBytes(nonce);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, keys.get(activeVersion), new GCMParameterSpec(128, nonce));
            cipher.updateAAD(aad(user, activeVersion));
            return activeVersion + "." + Base64.getEncoder().encodeToString(nonce) + "." + Base64.getEncoder().encodeToString(cipher.doFinal(plaintext));
        } catch (Exception error) { throw new IllegalStateException("模型配置加密失败"); }
    }
    public byte[] decrypt(Long user, String version, String payload) {
        try {
            if (!keys.containsKey(version)) throw new IllegalArgumentException();
            String[] parts = payload.split("\\.", -1);
            int offset = LEGACY.equals(version) ? 0 : 1;
            if (parts.length != offset + 2 || (offset == 1 && !parts[0].equals(version))) throw new IllegalArgumentException();
            byte[] nonce = Base64.getDecoder().decode(parts[offset]);
            if (nonce.length != 12) throw new IllegalArgumentException();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, keys.get(version), new GCMParameterSpec(128, nonce));
            cipher.updateAAD(aad(user, version));
            return cipher.doFinal(Base64.getDecoder().decode(parts[offset + 1]));
        } catch (Exception error) {
            throw new IllegalStateException("模型配置无法解密：密钥或版本不匹配，请管理员恢复对应密钥；原配置未更改");
        }
    }
}

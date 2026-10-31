package com.mneme.migration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.service.ModelConfigKeys;
import com.mneme.service.UserSettingsService;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;

@Testcontainers(disabledWithoutDocker = true)
class ModelConfigRotationTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("mneme-test-password");
    private static final String OLD = "original-legacy-jwt-secret-at-least-32";
    private static final String NEW = "independent-new-model-key-at-least-32";

    private UserSettingsService service(DriverManagerDataSource source, String key, String version, String previous) {
        var mapper = new ObjectMapper();
        var target = new UserSettingsService(new JdbcTemplate(source), mapper,
            new ModelConfigKeys(mapper, key, "unrelated-rotated-jwt", version, previous, true));
        var factory = new org.springframework.aop.framework.ProxyFactory(target);
        factory.addAdvice(new org.springframework.transaction.interceptor.TransactionInterceptor(
            new DataSourceTransactionManager(source), new org.springframework.transaction.annotation.AnnotationTransactionAttributeSource()));
        return (UserSettingsService) factory.getProxy();
    }
    @Test void migratesLegacyCiphertextAndRollsBackWholeRotationOnAnyBadRow() throws Exception {
        Flyway.configure().dataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword())
            .locations("classpath:db/migration").target("24").load().migrate();
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        var jdbc = new JdbcTemplate(source);
        jdbc.update("INSERT INTO user(username,password_hash) VALUES('legacy-a','hash'),('legacy-b','hash')");
        Long a = jdbc.queryForObject("SELECT id FROM user WHERE username='legacy-a'", Long.class);
        Long b = jdbc.queryForObject("SELECT id FROM user WHERE username='legacy-b'", Long.class);
        String oldA = legacy(a, "private-a"), oldB = legacy(b, "private-b");
        jdbc.update("INSERT INTO user_model_config(user_id,config_encrypted) VALUES(?,?),(?,?)", a, oldA, b, oldB);
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
        assertThat(jdbc.queryForObject("SELECT key_version FROM user_model_config WHERE user_id=?", String.class, a)).isEqualTo("legacy-v1");
        var service = service(source, NEW, "v2", new ObjectMapper().writeValueAsString(Map.of("legacy-v1", OLD)));
        assertThat(service.keyStatus()).containsEntry("rotation_status", "required");
        assertThat(service.decrypted(a)).containsEntry("apiKey", "private-a");
        assertThatThrownBy(() -> service(source, NEW, "v2", "{}").decrypted(a)).isInstanceOf(IllegalStateException.class);
        assertThat(service(source, NEW, "v2", "{}").keyStatus()).containsEntry("rotation_status", "missing_keys");
        assertThatThrownBy(() -> service.rotateModelKeys("stale-version")).isInstanceOf(IllegalArgumentException.class);
        jdbc.update("UPDATE user_model_config SET config_encrypted='corrupt' WHERE user_id=?", b);
        assertThatThrownBy(() -> service.rotateModelKeys("v2")).isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject("SELECT config_encrypted FROM user_model_config WHERE user_id=?", String.class, a)).isEqualTo(oldA);
        assertThatThrownBy(() -> service.saveModels(b, Map.of("clearKey", true))).isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject("SELECT config_encrypted FROM user_model_config WHERE user_id=?", String.class, b)).isEqualTo("corrupt");
        jdbc.update("UPDATE user_model_config SET config_encrypted=? WHERE user_id=?", oldB, b);
        assertThat(service.rotateModelKeys("v2")).containsEntry("rotated", 2).containsEntry("verified", 2);
        assertThat(service.keyStatus()).containsEntry("rotation_status", "current");
        assertThat(service.rotateModelKeys("v2")).containsEntry("rotated", 0);
        var withoutOld = service(source, NEW, "v2", "{}");
        assertThat(withoutOld.decrypted(a)).containsEntry("apiKey", "private-a");
        assertThat(withoutOld.decrypted(b)).containsEntry("apiKey", "private-b");
        var third = service(source, NEW + "-third", "v3", new ObjectMapper().writeValueAsString(Map.of("v2", NEW)));
        assertThat(third.rotateModelKeys("v3")).containsEntry("rotated", 2);
        assertThat(third.decrypted(b)).containsEntry("apiKey", "private-b");
        assertThatThrownBy(() -> withoutOld.decrypted(a)).isInstanceOf(IllegalStateException.class);
    }
    private String legacy(Long user, String apiKey) throws Exception {
        var cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding");
        byte[] nonce = new byte[12]; new java.security.SecureRandom().nextBytes(nonce);
        var key = new javax.crypto.spec.SecretKeySpec(java.security.MessageDigest.getInstance("SHA-256")
            .digest(("mneme:user-model:v1:" + OLD).getBytes(java.nio.charset.StandardCharsets.UTF_8)), "AES");
        cipher.init(javax.crypto.Cipher.ENCRYPT_MODE, key, new javax.crypto.spec.GCMParameterSpec(128, nonce));
        cipher.updateAAD(user.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        byte[] plain = new ObjectMapper().writeValueAsBytes(Map.of("apiKey", apiKey, "enabled", true));
        return java.util.Base64.getEncoder().encodeToString(nonce) + "." + java.util.Base64.getEncoder().encodeToString(cipher.doFinal(plain));
    }
}

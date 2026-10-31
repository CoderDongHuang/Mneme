package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class UserSettingsServiceTest {
    @Test
    void encryptsAtRestMasksReadsAndKeepsBlankKeyWithinOneUserAndProvider() {
        var jdbc = mock(JdbcTemplate.class);
        var rows = new HashMap<Long,String>();
        when(jdbc.queryForList(anyString(), anyLong())).thenAnswer(call -> {
            String value = rows.get(call.getArgument(1, Long.class));
            return value == null ? List.of() : List.of(Map.of("config_encrypted", value, "key_version", "v2"));
        });
        when(jdbc.update(anyString(), anyLong(), anyString(), anyString())).thenAnswer(call -> {
            rows.put(call.getArgument(1), call.getArgument(2)); return 1;
        });
        var service = service(jdbc, "persistent-test-key-at-least-32-characters", "original-jwt");
        var body = Map.<String,Object>of("provider", "openai", "model", "gpt-4.1-mini", "apiKey", "private-user-a", "enabled", true);
        var publicConfig = service.saveModels(1L, body);
        assertThat(publicConfig).doesNotContainKey("apiKey").containsEntry("hasKey", true);
        assertThat(rows.get(1L)).doesNotContain("private-user-a").doesNotContain("openai");
        assertThat(service.decrypted(1L)).containsEntry("apiKey", "private-user-a");
        assertThat(service(jdbc, "persistent-test-key-at-least-32-characters", "rotated-jwt")
            .decrypted(1L)).containsEntry("apiKey", "private-user-a");
        assertThatThrownBy(() -> service(jdbc, "short-key", "long-jwt-key-at-least-32-characters"))
            .isInstanceOf(IllegalArgumentException.class);
        assertThat(service.models(2L)).containsEntry("hasKey", false);
        assertThat(service.validated(1L, Map.of("provider", "openai", "model", "gpt-4.1-mini", "apiKey", "", "enabled", true)))
            .containsEntry("apiKey", "private-user-a");
        assertThatThrownBy(() -> service.validated(1L, Map.of("provider", "deepseek", "enabled", true)))
            .isInstanceOf(IllegalArgumentException.class);
        String ciphertext = rows.get(1L);
        service.saveModels(1L, body);
        assertThat(rows.get(1L)).isNotEqualTo(ciphertext);
        rows.put(2L, rows.get(1L));
        assertThatThrownBy(() -> service.decrypted(2L)).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void rejectsInvalidPreferencesBeforeWriting() {
        var jdbc = mock(JdbcTemplate.class);
        var service = service(jdbc, "test-key-at-least-32-characters-long", "unused");
        assertThatThrownBy(() -> service.savePreferences(1L, Map.of("language", "xx"))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.savePreferences(1L, Map.of("timezone", "invented/timezone"))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.savePreferences(1L, Map.of("notifications", "true"))).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(jdbc);
    }

    private UserSettingsService service(JdbcTemplate jdbc, String key, String jwt) {
        var mapper = new ObjectMapper();
        return new UserSettingsService(jdbc, mapper, new ModelConfigKeys(mapper, key, jwt, "v2", "{}", false));
    }
}

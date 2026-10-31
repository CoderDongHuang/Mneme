package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class ModelConfigKeysTest {
    private static final String SECRET = "independent-test-model-secret-at-least-32";
    private ModelConfigKeys keys(String secret, String jwt, String version, String previous, boolean production) {
        return new ModelConfigKeys(new ObjectMapper(), secret, jwt, version, previous, production);
    }
    @Test void productionRequiresIndependentSecretAndValidVersionedKeyring() {
        assertThatThrownBy(() -> keys("", SECRET, "v2", "{}", true)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> keys(SECRET, SECRET, "v2", "{}", true)).isInstanceOf(IllegalArgumentException.class);
        for (String version : new String[]{"legacy-v1", "bad.version", ""})
            assertThatThrownBy(() -> keys(SECRET, "jwt", version, "{}", true)).isInstanceOf(IllegalArgumentException.class);
        for (String old : new String[]{"not-json", "null", "{\"v2\":\"" + SECRET + "\"}", "{\"v1\":\"short\"}", "{\"v1\":\"" + SECRET + "\",\"v1\":\"" + SECRET + "\"}"})
            assertThatThrownBy(() -> keys(SECRET, "jwt", "v2", old, true)).isInstanceOf(IllegalArgumentException.class);
        assertThat(keys(SECRET, "jwt", "v2", "{}", true).availableVersions()).containsExactly("v2");
        assertThat(keys("", SECRET, "v2", "{}", false).developmentFallback()).isTrue();
    }
    @Test void jwtRotationDoesNotAffectIndependentKeyAndPayloadAuthenticatesOwnerAndVersion() {
        byte[] plain = "secret-user-key".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        var original = keys(SECRET, "jwt-original", "v2", "{}", true);
        String encrypted = original.encrypt(1L, plain);
        assertThat(encrypted).startsWith("v2.").doesNotContain("secret-user-key");
        assertThat(keys(SECRET, "jwt-new", "v2", "{}", true).decrypt(1L, "v2", encrypted)).isEqualTo(plain);
        assertThat(original.encrypt(1L, plain)).isNotEqualTo(encrypted);
        assertThatThrownBy(() -> original.decrypt(2L, "v2", encrypted)).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> original.decrypt(1L, "v3", encrypted)).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> keys(SECRET + "wrong", "jwt", "v2", "{}", true).decrypt(1L, "v2", encrypted))
            .isInstanceOf(IllegalStateException.class).hasMessageContaining("原配置未更改");
        var anotherVersion = keys(SECRET, "jwt", "v3", "{}", true);
        assertThatThrownBy(() -> anotherVersion.decrypt(1L, "v3", encrypted.replaceFirst("v2", "v3")))
            .isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> original.decrypt(1L, "v2", "v2.invalid.invalid")).isInstanceOf(IllegalStateException.class);
    }
    @Test void rotationEndpointChecksAdminBeforeTouchingSettings() {
        var admin = org.mockito.Mockito.mock(AdminAuthorizationService.class);
        var settings = org.mockito.Mockito.mock(UserSettingsService.class);
        org.mockito.Mockito.doThrow(new SecurityException("denied")).when(admin).requireAdmin(2L, "wrong");
        var controller = new com.mneme.controller.ModelKeyRotationController(admin, settings);
        assertThatThrownBy(() -> controller.rotate(2L, "wrong", java.util.Map.of("expected_version", "v2")))
            .isInstanceOf(SecurityException.class);
        org.mockito.Mockito.verifyNoInteractions(settings);
    }
}

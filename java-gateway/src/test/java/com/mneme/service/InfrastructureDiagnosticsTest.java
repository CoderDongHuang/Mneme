package com.mneme.service;

import com.mneme.controller.InfrastructureDiagnosticsController;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.web.client.RestTemplate;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.http.MediaType;
import java.util.Map;
import java.util.List;
import java.time.Duration;
import static org.mockito.Mockito.*;
import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class InfrastructureDiagnosticsTest {
    final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    final PasswordResetDelivery mail = mock(PasswordResetDelivery.class);
    final RestTemplate http = new RestTemplate();
    InfrastructureDiagnosticsService service() {
        return new InfrastructureDiagnosticsService(jdbc, redis, mock(ObjectStorageService.class), mail, http,
            "http://agent", "http://worker", "x".repeat(32));
    }
    @Test void malformedRemoteAndSecretFieldsNeverEscape() {
        assertThat(DiagnosticResult.remote(Map.of())).containsEntry("code", "INVALID_DIAGNOSTIC_RESPONSE");
        assertThat(DiagnosticResult.remote(Map.of("configuration", "present"))).containsEntry("code", "INVALID_DIAGNOSTIC_RESPONSE");
        var value = Map.of("configuration", "present", "connection", "passed", "operation", "passed", "cleanup", "passed", "code", "OK", "private", "secret-key");
        assertThat(DiagnosticResult.remote(value)).doesNotContainKey("private");
        var server = MockRestServiceServer.bindTo(http).build();
        server.expect(request -> assertThat(request.getURI().getPath()).isEqualTo("/health/storage/check"))
            .andRespond(withSuccess("{\"configuration\":\"present\",\"private\":\"secret-key\"}", MediaType.APPLICATION_JSON));
        assertThat(service().check("qdrant", 1L)).containsEntry("code", "INVALID_DIAGNOSTIC_RESPONSE");
        server.verify();
    }
    @Test void adminGuardRunsBeforeAnyDiagnosticAndTargetsAreAllowlisted() {
        var admins = mock(AdminAuthorizationService.class);
        var diagnostics = mock(InfrastructureDiagnosticsService.class);
        doThrow(new SecurityException("denied")).when(admins).requireAdmin(2L, "wrong");
        var controller = new InfrastructureDiagnosticsController(admins, diagnostics);
        assertThatThrownBy(() -> controller.check(2L, "wrong", "smtp")).isInstanceOf(SecurityException.class);
        verifyNoInteractions(diagnostics);
        assertThatThrownBy(() -> service().check("http://evil", 1L)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void failedSqlConnectionNeverClaimsBusinessSuccessOrExposesException() {
        when(jdbc.queryForObject("SELECT 1", Integer.class)).thenThrow(new IllegalStateException("mysql://private-password"));
        assertThat(service().check("mysql", 1L)).containsEntry("connection", "failed").containsEntry("operation", "not_run")
            .containsEntry("code", "CONNECTION_FAILED").doesNotContainValue("mysql://private-password");
    }
    @SuppressWarnings("unchecked")
    @Test void smtpIsOptInVerifiedSelfOnlyThrottledAndAcceptanceIsDistinct() {
        when(mail.configured()).thenReturn(true);
        when(jdbc.queryForList(anyString(), eq(7L))).thenReturn(List.of(Map.of("email", "verified@local.test")));
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.setIfAbsent("mneme:diagnostics:smtp:7", "reserved", Duration.ofSeconds(60))).thenReturn(true, false);
        assertThat(service().check("smtp", 7L)).containsEntry("code", "SMTP_ACCEPTED").containsEntry("operation", "passed");
        verify(mail).checkConnection(); verify(mail).sendDiagnostic("verified@local.test");
        assertThat(service().check("smtp", 7L)).containsEntry("code", "RATE_LIMITED");
        verify(mail, times(1)).sendDiagnostic(anyString());
    }
    @Test void smtpMissingConfigOrUnverifiedAccountCannotSend() {
        assertThat(service().check("smtp", 7L)).containsEntry("configuration", "missing");
        when(mail.configured()).thenReturn(true);
        when(jdbc.queryForList(anyString(), eq(7L))).thenReturn(List.of());
        assertThat(service().check("smtp", 7L)).containsEntry("code", "VERIFIED_EMAIL_REQUIRED");
        verify(mail, never()).sendDiagnostic(anyString()); verifyNoInteractions(redis);
    }
    @Test void backupKeyProxyUsesOnlyServerCredentialAndFixedPath() {
        var server = MockRestServiceServer.bindTo(http).build();
        server.expect(request -> {
            assertThat(request.getURI().toString()).isEqualTo("http://worker/site/keys/check");
            assertThat(request.getHeaders().getFirst("Authorization")).isEqualTo("Bearer " + "x".repeat(32));
        }).andRespond(withSuccess("{\"configuration\":\"present\",\"connection\":\"not_applicable\",\"operation\":\"passed\",\"cleanup\":\"not_required\",\"code\":\"OK\"}", MediaType.APPLICATION_JSON));
        assertThat(service().check("backup_keys", 7L)).containsEntry("operation", "passed");
        server.verify();
    }
}

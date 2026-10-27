package com.mneme.controller;

import com.mneme.service.AdminAuthorizationService;
import com.mneme.service.StorageDiagnosticsService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class HealthControllerTest {
    @Test void providerCheckUsesFixedInternalEndpointAndDoesNotReturnCredentials() {
        var http = mock(RestTemplate.class);
        var controller = new HealthController(mock(JdbcTemplate.class), http,
            mock(StorageDiagnosticsService.class), mock(AdminAuthorizationService.class));
        ReflectionTestUtils.setField(controller, "pythonAgentUrl", "http://agent:8001");
        var synthetic = Map.of("results", Map.of("chat", Map.of("state", "ok", "latency_ms", 1)));
        when(http.postForObject("http://agent:8001/health/providers/check", null, Map.class)).thenReturn(synthetic);
        assertEquals(synthetic, controller.checkProviders(7L));
        verify(http).postForObject("http://agent:8001/health/providers/check", null, Map.class);
        verifyNoMoreInteractions(http);
    }
}

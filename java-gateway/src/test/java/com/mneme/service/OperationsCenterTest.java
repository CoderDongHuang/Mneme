package com.mneme.service;
import com.mneme.controller.OperationsCenterController;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.client.RestTemplate;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.http.MediaType;
import java.util.Map;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
class OperationsCenterTest {
    private OperationsCenterService service(RestTemplate metrics, String url) {
        return new OperationsCenterService(mock(JdbcTemplate.class), mock(StringRedisTemplate.class),
            mock(RestTemplate.class), metrics, mock(StorageDiagnosticsService.class), "http://agent", url, ".");
    }
    @Test void unavailableMetricsAreNotFabricated() {
        assertEquals("not_configured", service(new RestTemplate(), "").monitoring().get("status"));
        assertEquals("unavailable", service(new RestTemplate(), "file:///secret").monitoring().get("status"));
    }
    @Test void emptyMetricsStayNullAndAlertsAreFetched() {
        var client = new RestTemplate();
        var server = MockRestServiceServer.bindTo(client).build();
        for (int i = 0; i < 4; i++) server.expect(request -> assertTrue(request.getURI().getPath().endsWith("/query")))
            .andRespond(withSuccess("{\"status\":\"success\",\"data\":{\"result\":[]}}", MediaType.APPLICATION_JSON));
        server.expect(request -> assertTrue(request.getURI().getPath().endsWith("/alerts")))
            .andRespond(withSuccess("{\"status\":\"success\",\"data\":{\"alerts\":[]}}", MediaType.APPLICATION_JSON));
        var result = service(client, "http://prometheus").monitoring();
        assertEquals("available", result.get("status"));
        assertNull(result.get("mneme:gateway_availability:rate5m"));
        server.verify();
    }
    @Test void deniedAdminCannotQueryOperations() {
        var admins = mock(AdminAuthorizationService.class);
        var operations = mock(OperationsCenterService.class);
        doThrow(new SecurityException("denied")).when(admins).requireAdmin(2L, "wrong");
        var controller = new OperationsCenterController(admins, operations);
        assertThrows(SecurityException.class, () -> controller.snapshot(2L, "wrong"));
        verifyNoInteractions(operations);
    }
}

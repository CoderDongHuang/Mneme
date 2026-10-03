package com.mneme.controller;
import com.mneme.service.OperationLogService;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestTemplate;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class PrivacyControllerTest {
    @Test void usesAuthenticatedOwnerAndRequiresConfirmation() {
        RestTemplate client = mock(RestTemplate.class);
        PrivacyController controller = new PrivacyController(client, mock(OperationLogService.class), "http://agent");
        controller.get(42L);
        verify(client).getForObject("http://agent/api/v1/agent/privacy/42", Object.class);
        assertThrows(IllegalArgumentException.class, () -> controller.delete(42L, "yes"));
        verifyNoMoreInteractions(client);
    }
}

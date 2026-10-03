package com.mneme.service;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestTemplate;
import static org.mockito.Mockito.*;
import static org.assertj.core.api.Assertions.*;
class RecoveryManagementTest {
    @Test void refusesUnconfiguredRepositoryAndUnconfirmedDrill() {
        RestTemplate http = mock(RestTemplate.class);
        RecoveryManagementService service = new RecoveryManagementService(http, mock(OperationLogService.class), "", "");
        assertThatThrownBy(service::history).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.dispatch(1L, "yes")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.evidence(-1)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(http);
    }
}

package com.mneme.controller;
import com.mneme.service.AdminAuthorizationService;
import com.mneme.service.RecoveryManagementService;
import org.junit.jupiter.api.Test;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
class RecoveryAuthorizationTest {
    @Test void deniedAdminCannotReadOrDispatch() {
        var admins = mock(AdminAuthorizationService.class);
        var recovery = mock(RecoveryManagementService.class);
        doThrow(new IllegalArgumentException("denied")).when(admins).requireAdmin(7L, "invalid");
        var controller = new RecoveryManagementController(admins, recovery);
        assertThrows(IllegalArgumentException.class, () -> controller.history(7L, "invalid"));
        assertThrows(IllegalArgumentException.class, () -> controller.evidence(7L, "invalid", 1));
        assertThrows(IllegalArgumentException.class, () -> controller.dispatch(7L, "invalid", Map.of("confirmation", "ISOLATED DRILL")));
        verifyNoInteractions(recovery);
    }
}

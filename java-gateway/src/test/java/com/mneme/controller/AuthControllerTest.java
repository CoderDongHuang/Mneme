package com.mneme.controller;

import com.mneme.dto.AuthRequest;
import com.mneme.dto.AuthResponse;
import com.mneme.service.AuthService;
import com.mneme.service.PasswordResetDelivery;
import com.mneme.service.ProfileService;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

class AuthControllerTest {
    @Test
    void rememberCookieUsesTokenLifetime() {
        AuthService auth = mock(AuthService.class);
        when(auth.login("alice", "password", true))
            .thenReturn(new AuthResponse("jwt", 7L, "alice", 2_592_000L));
        AuthController controller = controller(auth);
        AuthRequest request = new AuthRequest();
        request.setUsername("alice"); request.setPassword("password"); request.setRemember(true);

        String cookie = controller.login(request).getHeaders().getFirst(HttpHeaders.SET_COOKIE);

        assertThat(cookie).contains("mneme_session=jwt", "Max-Age=2592000", "HttpOnly", "SameSite=Strict");
    }

    @Test
    void logoutRevokesCookieTokenAndClearsCookie() {
        AuthService auth = mock(AuthService.class);
        AuthController controller = controller(auth);
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getCookies()).thenReturn(new Cookie[] { new Cookie("mneme_session", "jwt") });

        String cookie = controller.logout(request).getHeaders().getFirst(HttpHeaders.SET_COOKIE);

        verify(auth).revokeToken("jwt");
        assertThat(cookie).contains("mneme_session=", "Max-Age=0");
    }

    private AuthController controller(AuthService auth) {
        return new AuthController(auth, mock(ProfileService.class), mock(PasswordResetDelivery.class));
    }
}

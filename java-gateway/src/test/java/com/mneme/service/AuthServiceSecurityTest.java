package com.mneme.service;

import com.mneme.entity.PasswordResetToken;
import com.mneme.entity.User;
import com.mneme.mapper.PasswordResetTokenMapper;
import com.mneme.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;
import java.time.LocalDateTime;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class AuthServiceSecurityTest {
    @Test void resetTokenIsStoredHashedAndExpires() {
        UserMapper users = mock(UserMapper.class); PasswordResetTokenMapper tokens = mock(PasswordResetTokenMapper.class);
        AuthSessionService sessions = mock(AuthSessionService.class);
        User user = new User(); user.setId(7L); user.setEmail("a@example.com"); user.setUsername("alice");
        when(users.selectOne(any())).thenReturn(user);
        AuthService service = new AuthService(users, tokens, sessions);
        String raw = service.issuePasswordResetToken("alice", "a@example.com");
        ArgumentCaptor<PasswordResetToken> saved = ArgumentCaptor.forClass(PasswordResetToken.class);
        verify(tokens).insert(saved.capture());
        assertThat(raw).hasSize(64); assertThat(saved.getValue().getTokenHash()).hasSize(64).isNotEqualTo(raw);
        assertThat(saved.getValue().getExpiresAt()).isAfter(LocalDateTime.now().plusMinutes(14));
    }

    @Test void expiredResetTokenCannotChangePassword() {
        UserMapper users = mock(UserMapper.class); PasswordResetTokenMapper tokens = mock(PasswordResetTokenMapper.class);
        PasswordResetToken expired = new PasswordResetToken(); expired.setExpiresAt(LocalDateTime.now().minusSeconds(1));
        when(tokens.selectOne(any())).thenReturn(expired);
        AuthService service = new AuthService(users, tokens, mock(AuthSessionService.class));
        assertThatThrownBy(() -> service.confirmPasswordReset("expired", "new-password"))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("过期");
        verify(users, never()).updateById(any());
    }

    @Test void resetTokenMustBeClaimedBeforePasswordChanges() {
        UserMapper users = mock(UserMapper.class);
        PasswordResetTokenMapper tokens = mock(PasswordResetTokenMapper.class);
        AuthSessionService sessions = mock(AuthSessionService.class);
        PasswordResetToken token = validToken();
        when(tokens.selectOne(any())).thenReturn(token);
        when(tokens.update(isNull(), any())).thenReturn(0);

        AuthService service = new AuthService(users, tokens, sessions);
        assertThatThrownBy(() -> service.confirmPasswordReset("contended", "new-password"))
            .isInstanceOf(IllegalArgumentException.class);

        verify(users, never()).updateById(any());
        verify(sessions, never()).revokeAll(any());
    }

    @Test void successfulResetRevokesEveryExistingSession() {
        UserMapper users = mock(UserMapper.class);
        PasswordResetTokenMapper tokens = mock(PasswordResetTokenMapper.class);
        AuthSessionService sessions = mock(AuthSessionService.class);
        PasswordResetToken token = validToken();
        User user = new User(); user.setId(7L); user.setStatus("active");
        when(tokens.selectOne(any())).thenReturn(token);
        when(tokens.update(isNull(), any())).thenReturn(1);
        when(users.selectById(7L)).thenReturn(user);

        new AuthService(users, tokens, sessions).confirmPasswordReset("valid", "new-password");

        verify(users).updateById(user);
        verify(sessions).revokeAll(7L);
        assertThat(user.getPasswordHash()).startsWith("$2");
    }

    @Test void rememberLoginUsesConfiguredLongerLifetime() {
        UserMapper users = mock(UserMapper.class);
        PasswordResetTokenMapper tokens = mock(PasswordResetTokenMapper.class);
        AuthSessionService sessions = mock(AuthSessionService.class);
        User user = new User();
        user.setId(7L); user.setUsername("alice"); user.setStatus("active");
        user.setPasswordHash(new org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder().encode("password"));
        when(users.selectOne(any())).thenReturn(user);
        when(sessions.create(eq(7L), any(), eq(true))).thenReturn("session-7");
        AuthService service = new AuthService(users, tokens, sessions);
        ReflectionTestUtils.setField(service, "jwtSecret", "01234567890123456789012345678901");
        ReflectionTestUtils.setField(service, "jwtExpiration", 86_400_000L);
        ReflectionTestUtils.setField(service, "jwtRememberExpiration", 2_592_000_000L);
        service.validateSecrets();

        var response = service.login("alice", "password", true);

        assertThat(response.maxAgeSeconds()).isEqualTo(2_592_000L);
        assertThat(response.token()).isNotBlank();
        verify(sessions).create(eq(7L), any(LocalDateTime.class), eq(true));
    }

    private PasswordResetToken validToken() {
        PasswordResetToken token = new PasswordResetToken();
        token.setId(3L);
        token.setUserId(7L);
        token.setExpiresAt(LocalDateTime.now().plusMinutes(10));
        return token;
    }
}

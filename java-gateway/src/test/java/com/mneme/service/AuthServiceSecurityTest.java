package com.mneme.service;

import com.mneme.entity.PasswordResetToken;
import com.mneme.entity.User;
import com.mneme.mapper.PasswordResetTokenMapper;
import com.mneme.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import java.time.LocalDateTime;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class AuthServiceSecurityTest {
    @Test void resetTokenIsStoredHashedAndExpires() {
        UserMapper users = mock(UserMapper.class); PasswordResetTokenMapper tokens = mock(PasswordResetTokenMapper.class);
        User user = new User(); user.setId(7L); user.setEmail("a@example.com"); user.setUsername("alice");
        when(users.selectOne(any())).thenReturn(user);
        AuthService service = new AuthService(users, tokens);
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
        AuthService service = new AuthService(users, tokens);
        assertThatThrownBy(() -> service.confirmPasswordReset("expired", "new-password"))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("过期");
        verify(users, never()).updateById(any());
    }
}

package com.mneme.service;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AuthSessionServiceTest {
    @Test
    void createsAndValidatesSession() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(contains("FROM auth_session"), eq(Long.class), anyString(), eq(7L)))
            .thenReturn(1L);
        AuthSessionService service = new AuthSessionService(jdbc);

        String sessionId = service.create(7L, LocalDateTime.now().plusHours(1), true);

        assertThat(sessionId).isNotBlank();
        assertThat(service.isActive(sessionId, 7L)).isTrue();
        verify(jdbc).update(contains("INSERT INTO auth_session"), eq(sessionId), eq(7L), eq(true), any());
        verify(jdbc).update(contains("last_seen_at"), eq(sessionId));
    }

    @Test
    void revokesOneOrAllSessions() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        AuthSessionService service = new AuthSessionService(jdbc);

        service.revoke("session-7");
        service.revokeAll(7L);

        verify(jdbc).update(contains("session_id=?"), eq("session-7"));
        verify(jdbc).update(contains("user_id=?"), eq(7L));
    }
}

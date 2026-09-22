package com.mneme.service;

import com.mneme.entity.ChatMessage;
import com.mneme.entity.ChatSession;
import com.mneme.exception.RequestInProgressException;
import com.mneme.mapper.ChatMessageMapper;
import com.mneme.mapper.ChatSessionMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ChatSessionServiceTest {
    @Test
    void completedRequestIsReplayedWithoutCreatingMessages() {
        Fixture fixture = fixture();
        ChatMessage user = message(1L, "user", "question", "completed");
        ChatMessage assistant = message(2L, "assistant", "answer", "completed");
        when(fixture.messages.selectOne(any())).thenReturn(user, assistant);

        ChatSessionService.Exchange exchange = fixture.service.prepareExchange(7L, 9L, "request-1", "question");

        assertThat(exchange.completed()).isTrue();
        assertThat(exchange.assistantMessage().getContent()).isEqualTo("answer");
        verify(fixture.messages, never()).insert(any());
    }

    @Test
    void processingRequestReturnsConflict() {
        Fixture fixture = fixture();
        when(fixture.messages.selectOne(any())).thenReturn(
            message(1L, "user", "question", "completed"),
            message(2L, "assistant", "", "processing")
        );

        assertThatThrownBy(() -> fixture.service.prepareExchange(7L, 9L, "request-1", "question"))
            .isInstanceOf(RequestInProgressException.class);
    }

    @Test
    void failedRequestCanRetryWithSamePlaceholder() {
        Fixture fixture = fixture();
        ChatMessage assistant = message(2L, "assistant", "partial", "failed");
        assistant.setErrorCode("TIMEOUT");
        when(fixture.messages.selectOne(any())).thenReturn(
            message(1L, "user", "question", "completed"), assistant);

        ChatSessionService.Exchange exchange = fixture.service.prepareExchange(7L, 9L, "request-1", "question");

        assertThat(exchange.completed()).isFalse();
        assertThat(assistant.getStatus()).isEqualTo("processing");
        assertThat(assistant.getContent()).isEmpty();
        assertThat(assistant.getErrorCode()).isNull();
        verify(fixture.messages).updateById(assistant);
    }

    @Test
    void requestIdCannotBeReusedForDifferentContent() {
        Fixture fixture = fixture();
        when(fixture.messages.selectOne(any())).thenReturn(
            message(1L, "user", "first question", "completed"), (ChatMessage) null);

        assertThatThrownBy(() -> fixture.service.prepareExchange(7L, 9L, "request-1", "second question"))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("request_id");
    }

    @Test
    void newRequestCreatesUserAndAssistantAtomically() {
        Fixture fixture = fixture();
        ChatSession session = new ChatSession();
        session.setId(9L); session.setUserId(7L); session.setTitle("新对话");
        when(fixture.sessions.selectById(9L)).thenReturn(session);

        ChatSessionService.Exchange exchange = fixture.service.prepareExchange(7L, 9L, "request-1", "question");

        assertThat(exchange.userMessage().getSessionId()).isEqualTo(9L);
        assertThat(exchange.assistantMessage().getStatus()).isEqualTo("processing");
        assertThat(session.getTitle()).isEqualTo("question");
        verify(fixture.messages, times(2)).insert(any());
        verify(fixture.sessions).updateById(session);
    }

    private Fixture fixture() {
        ChatSessionMapper sessions = mock(ChatSessionMapper.class);
        ChatMessageMapper messages = mock(ChatMessageMapper.class);
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(contains("FOR UPDATE"), eq(Long.class), eq(9L), eq(7L)))
            .thenReturn(List.of(9L));
        return new Fixture(new ChatSessionService(sessions, messages, jdbc), sessions, messages);
    }

    private ChatMessage message(Long id, String role, String content, String status) {
        ChatMessage message = new ChatMessage();
        message.setId(id);
        message.setSessionId(9L);
        message.setRequestId("request-1");
        message.setRole(role);
        message.setContent(content);
        message.setStatus(status);
        return message;
    }

    private record Fixture(
        ChatSessionService service,
        ChatSessionMapper sessions,
        ChatMessageMapper messages
    ) { }
}

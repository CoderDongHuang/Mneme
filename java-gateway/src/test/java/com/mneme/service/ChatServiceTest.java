package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.ChatRequest;
import com.mneme.entity.ChatMessage;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.web.client.RestTemplate;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ChatServiceTest {
    @Test void synchronousAnswerReturnsQueuedOnlyAfterDurableHandoff() {
        var rest = mock(RestTemplate.class); var sessions = mock(ChatSessionService.class);
        var assistant = assistant(""); assistant.setAnswerGeneration(1L);
        when(sessions.prepareExchange(7L, 9L, "request-1", "question"))
            .thenReturn(new ChatSessionService.Exchange(null, assistant, false));
        var response = new com.mneme.dto.ChatResponse(); response.setAnswer("verified answer");
        var candidate = new com.mneme.dto.ChatResponse.PendingMemory(); candidate.setTempId("m1");
        response.setPendingMemories(java.util.List.of(candidate));
        when(rest.postForObject(anyString(), any(), eq(com.mneme.dto.ChatResponse.class))).thenReturn(response);
        var result = service(rest, sessions).chat(7L, request());
        verify(sessions).finishAnswer(2L, 1L, "verified answer", "[]", java.util.List.of(candidate));
        assertThat(result.getMemoryStatus()).isEqualTo("queued");
        assertThat(result.getPendingMemories()).isEmpty();
        verify(sessions, never()).failMessage(anyLong(), anyLong(), anyString(), anyString());
    }

    @Test
    void completedRequestDoesNotCallPythonAgain() {
        RestTemplate rest = mock(RestTemplate.class);
        ChatSessionService sessions = mock(ChatSessionService.class);
        ChatMessage assistant = assistant("saved answer");
        when(sessions.prepareExchange(7L, 9L, "request-1", "question"))
            .thenReturn(new ChatSessionService.Exchange(null, assistant, true));
        ChatService service = service(rest, sessions);

        var response = service.chat(7L, request());

        assertThat(response.getAnswer()).isEqualTo("saved answer");
        verify(rest, never()).postForObject(anyString(), any(), any());
    }

    @Test
    void completedStreamReplaysTokenAndDoneEvents() throws Exception {
        RestTemplate rest = mock(RestTemplate.class);
        ChatSessionService sessions = mock(ChatSessionService.class);
        when(sessions.prepareExchange(7L, 9L, "request-1", "question"))
            .thenReturn(new ChatSessionService.Exchange(null, assistant("saved answer"), true));
        ByteArrayOutputStream output = new ByteArrayOutputStream();

        service(rest, sessions).stream(7L, request()).writeTo(output);

        String events = output.toString(StandardCharsets.UTF_8);
        assertThat(events).contains("event: token", "saved answer", "event: done", "\"replayed\":true");
        verify(rest, never()).postForObject(anyString(), any(), any());
    }

    @SuppressWarnings("unchecked")
    private ChatService service(RestTemplate rest, ChatSessionService sessions) {
        return new ChatService(
            rest,
            (RedisTemplate<String, Object>) mock(RedisTemplate.class),
            new ObjectMapper(),
            sessions,
            mock(ChatStreamMonitor.class)
        );
    }

    private ChatRequest request() {
        ChatRequest request = new ChatRequest();
        request.setSessionId("9");
        request.setRequestId("request-1");
        request.setMessage("question");
        return request;
    }

    private ChatMessage assistant(String content) {
        ChatMessage message = new ChatMessage();
        message.setId(2L);
        message.setContent(content);
        message.setStatus("completed");
        return message;
    }
}

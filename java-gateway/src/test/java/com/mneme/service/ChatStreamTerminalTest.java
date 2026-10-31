package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.ChatRequest;
import com.mneme.entity.ChatMessage;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ChatStreamTerminalTest {
    @Test void persistsBeforeDoneWithoutWaitingForProviderEof() throws Exception {
        try (var fixture = new Fixture("event:meta\ndata:{\"sources\":[]}\n\nevent:token\ndata:{\n"
            + "data: \"content\":\"verified answer\"}\n\nevent:done\ndata:{\"ok\":true}\n\n", true)) {
            var committed = new AtomicBoolean();
            doAnswer(call -> { committed.set(true); return null; }).when(fixture.sessions)
                .finishAnswer(2L, 3L, "verified answer", "[]");
            var output = new ByteArrayOutputStream() {
                @Override public synchronized void write(byte[] data, int offset, int length) {
                    String frame = new String(data, offset, length, StandardCharsets.UTF_8);
                    if (frame.contains("event: done")) assertThat(committed).isTrue();
                    super.write(data, offset, length);
                }
            };
            var pool = Executors.newSingleThreadExecutor();
            try { pool.submit(() -> { fixture.run(output); return true; }).get(5, TimeUnit.SECONDS); }
            finally { pool.shutdownNow(); }
            assertThat(output.toString(StandardCharsets.UTF_8)).contains("data: {\"content\":\"verified answer\"}\n\n", "event: done");
            verify(fixture.sessions, never()).failMessage(anyLong(), anyLong(), anyString(), anyString());
        }
    }

    @Test void persistenceFailureNeverPublishesDone() throws Exception {
        try (var fixture = new Fixture(success(), false)) {
            doThrow(new IllegalStateException("database unavailable")).when(fixture.sessions)
                .finishAnswer(anyLong(), anyLong(), anyString(), anyString());
            var output = new ByteArrayOutputStream(); fixture.run(output);
            assertThat(output.toString(StandardCharsets.UTF_8)).contains("event: error").doesNotContain("event: done", "database unavailable");
            verify(fixture.sessions).failMessage(2L, 3L, "answer", "IllegalStateException");
        }
    }

    @Test void disconnectDeliveringDoneCannotUndoCommittedAnswer() throws Exception {
        try (var fixture = new Fixture(success(), false)) {
            fixture.run(new ByteArrayOutputStream() {
                @Override public synchronized void write(byte[] data, int offset, int length) {
                    if (new String(data, offset, length, StandardCharsets.UTF_8).contains("event: done"))
                        throw new java.io.UncheckedIOException(new IOException("client closed"));
                    super.write(data, offset, length);
                }
            });
            verify(fixture.sessions).finishAnswer(2L, 3L, "answer", "[]");
            verify(fixture.sessions, never()).failMessage(anyLong(), anyLong(), anyString(), anyString());
        }
    }

    @Test void prematureEofAndTruncatedOrMalformedFramesCannotComplete() throws Exception {
        for (String body : new String[]{"event: token\ndata: {\"content\":\"partial\"}\n\n",
            "event: token\ndata: {\"content\":\"partial\"}\n\nevent: done\ndata: {}\n",
            "event: token\ndata: invalid-json\n\n", "event: done\ndata: {}\n\n"}) {
            try (var fixture = new Fixture(body, false)) {
                if (body.startsWith("event: done")) doThrow(new IllegalArgumentException("empty answer"))
                    .when(fixture.sessions).finishAnswer(2L, 3L, "", "[]");
                var output = new ByteArrayOutputStream(); fixture.run(output);
                assertThat(output.toString(StandardCharsets.UTF_8)).contains("event: error").doesNotContain("event: done");
                verify(fixture.sessions).failMessage(eq(2L), eq(3L), anyString(), anyString());
            }
        }
    }

    private static String success() {
        return "event: token\ndata: {\"content\":\"answer\"}\n\nevent: done\ndata: {\"ok\":true}\n\n";
    }

    private static class Fixture implements AutoCloseable {
        final ChatSessionService sessions = mock(ChatSessionService.class);
        final HttpServer server;
        final CountDownLatch release = new CountDownLatch(1);
        final ExecutorService executor = Executors.newCachedThreadPool();
        final ChatService service;
        final ChatStreamMonitor monitor;
        @SuppressWarnings("unchecked") Fixture(String response, boolean holdOpen) throws Exception {
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.setExecutor(executor);
            server.createContext("/api/v1/chat/stream", exchange -> {
                exchange.getRequestBody().readAllBytes();
                exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
                exchange.sendResponseHeaders(200, 0);
                try (var out = exchange.getResponseBody()) {
                    out.write(response.getBytes(StandardCharsets.UTF_8)); out.flush();
                    if (holdOpen) try { release.await(10, TimeUnit.SECONDS); }
                    catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
                }
            });
            server.start();
            var assistant = new ChatMessage(); assistant.setId(2L); assistant.setAnswerGeneration(3L);
            when(sessions.prepareExchange(7L, 9L, "request", "question"))
                .thenReturn(new ChatSessionService.Exchange(null, assistant, false));
            when(sessions.answerState(2L)).thenReturn(new ChatSessionService.AnswerState(3L, "processing"));
            monitor = new ChatStreamMonitor(sessions);
            service = new ChatService(mock(RestTemplate.class), (RedisTemplate<String,Object>) mock(RedisTemplate.class),
                new ObjectMapper(), sessions, mock(PendingMemoryService.class), monitor);
            ReflectionTestUtils.setField(service, "pythonAgentUrl", "http://127.0.0.1:" + server.getAddress().getPort());
            ReflectionTestUtils.setField(service, "internalServiceToken", "test-only");
        }
        void run(java.io.OutputStream out) throws IOException {
            var request = new ChatRequest(); request.setSessionId("9"); request.setRequestId("request"); request.setMessage("question");
            service.stream(7L, request).writeTo(out);
        }
        public void close() { monitor.close(); release.countDown(); server.stop(0); executor.shutdownNow(); }
    }
}

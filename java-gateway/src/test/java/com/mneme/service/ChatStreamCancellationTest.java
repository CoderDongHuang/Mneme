package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.ChatRequest;
import com.mneme.entity.ChatMessage;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ChatStreamCancellationTest {
    @Test void blockedHeartbeatDoesNotPreventStopOrMonitorShutdown() throws Exception {
        try (var fixture = new Fixture(false)) {
            var writing = new CountDownLatch(1);
            var release = new CountDownLatch(1);
            var pending = new CompletableFuture<Void>();
            var output = new OutputStream() {
                @Override public void write(int value) { }
                @Override public void write(byte[] bytes, int offset, int size) throws IOException {
                    writing.countDown();
                    try { release.await(6, TimeUnit.SECONDS); }
                    catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IOException(error); }
                }
            };
            var control = fixture.monitor.watch(2L, 3L, output);
            control.response(pending);
            try {
                assertThat(writing.await(3, TimeUnit.SECONDS)).isTrue();
                fixture.state.set(new ChatSessionService.AnswerState(3, "stopped"));
                assertThatThrownBy(() -> pending.get(3, TimeUnit.SECONDS)).isInstanceOf(CancellationException.class);
                assertThat(control.reason()).isEqualTo("USER_STOPPED");
                assertThatCode(fixture.monitor::close).doesNotThrowAnyException();
            } finally { release.countDown(); control.close(); }
        }
    }

    @Test void stopCancelsEvenBeforeProviderHeaders() throws Exception {
        try (var fixture = new Fixture(false)) {
            var output = new ByteArrayOutputStream(); var result = fixture.run(output);
            assertThat(fixture.entered.await(3, TimeUnit.SECONDS)).isTrue();
            fixture.state.set(new ChatSessionService.AnswerState(3, "stopped"));
            result.get(3, TimeUnit.SECONDS);
            assertThat(output.toString(StandardCharsets.UTF_8)).contains("event: start", "event: stopped", "USER_STOPPED").doesNotContain("event: done");
            verify(fixture.sessions).saveStoppedPartial(2L, 3L, "", "[]");
            verify(fixture.sessions, never()).failMessage(anyLong(), anyLong(), anyString(), anyString());
        }
    }

    @Test void stopClosesSilentBodyAndPersistsPartialWithoutWaitingForAnotherToken() throws Exception {
        try (var fixture = new Fixture(true)) {
            var consumed = new CountDownLatch(1);
            var output = new ByteArrayOutputStream() {
                @Override public synchronized void write(byte[] bytes, int offset, int size) {
                    super.write(bytes, offset, size);
                    if (new String(bytes, offset, size, StandardCharsets.UTF_8).contains("event: token")) consumed.countDown();
                }
            };
            var result = fixture.run(output);
            assertThat(consumed.await(3, TimeUnit.SECONDS)).isTrue();
            fixture.state.set(new ChatSessionService.AnswerState(3, "stopped"));
            result.get(3, TimeUnit.SECONDS);
            assertThat(output.toString(StandardCharsets.UTF_8)).contains("event: stopped");
            verify(fixture.sessions).saveStoppedPartial(2L, 3L, "partial", "[]");
            fixture.probe.countDown();
            assertThat(fixture.disconnected.await(3, TimeUnit.SECONDS)).isTrue();
        }
    }

    @Test void silentProviderTimesOutWithADistinctCode() throws Exception {
        try (var fixture = new Fixture(false)) {
            ReflectionTestUtils.setField(fixture.monitor, "timeoutMillis", 600L);
            var output = new ByteArrayOutputStream(); fixture.run(output).get(3, TimeUnit.SECONDS);
            verify(fixture.sessions).failMessage(2L, 3L, "", "MODEL_TIMEOUT");
            assertThat(output.toString(StandardCharsets.UTF_8)).contains("MODEL_TIMEOUT").doesNotContain("event: stopped");
        }
    }

    @Test void heartbeatDetectsClientDisconnectWithoutAnyProviderOutput() throws Exception {
        try (var fixture = new Fixture(false)) {
            var output = new OutputStream() {
                @Override public void write(int value) { }
                @Override public synchronized void write(byte[] bytes, int offset, int size) throws IOException {
                    if (new String(bytes, offset, size, StandardCharsets.UTF_8).contains(": heartbeat"))
                        throw new IOException("closed");
                }
            };
            fixture.run(output).get(3, TimeUnit.SECONDS);
            verify(fixture.sessions).failMessage(2L, 3L, "", "CLIENT_DISCONNECTED");
        }
    }

    @Test void staleStreamLosesOwnershipAcrossGatewayInstances() throws Exception {
        try (var fixture = new Fixture(false)) {
            var output = new ByteArrayOutputStream(); var result = fixture.run(output);
            assertThat(fixture.entered.await(3, TimeUnit.SECONDS)).isTrue();
            fixture.state.set(new ChatSessionService.AnswerState(4, "processing"));
            result.get(3, TimeUnit.SECONDS);
            verify(fixture.sessions).failMessage(2L, 3L, "", "ANSWER_SUPERSEDED");
            assertThat(output.toString(StandardCharsets.UTF_8)).doesNotContain("event: done", "event: stopped");
        }
    }

    private static class Fixture implements AutoCloseable {
        final ChatSessionService sessions = mock(ChatSessionService.class);
        final AtomicReference<ChatSessionService.AnswerState> state = new AtomicReference<>(new ChatSessionService.AnswerState(3, "processing"));
        final ChatStreamMonitor monitor = new ChatStreamMonitor(sessions);
        final HttpServer server;
        final ExecutorService pool = Executors.newCachedThreadPool();
        final CountDownLatch entered = new CountDownLatch(1), tokenSent = new CountDownLatch(1), probe = new CountDownLatch(1), disconnected = new CountDownLatch(1);
        final ChatService service;

        @SuppressWarnings("unchecked") Fixture(boolean headers) throws Exception {
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0); server.setExecutor(pool);
            server.createContext("/api/v1/chat/stream", exchange -> {
                exchange.getRequestBody().readAllBytes(); entered.countDown();
                try {
                    if (!headers) { probe.await(10, TimeUnit.SECONDS); return; }
                    exchange.sendResponseHeaders(200, 0);
                    try (var out = exchange.getResponseBody()) {
                        out.write("event: token\ndata: {\"content\":\"partial\"}\n\n".getBytes(StandardCharsets.UTF_8)); out.flush(); tokenSent.countDown();
                        probe.await(10, TimeUnit.SECONDS);
                        for (int i = 0; i < 200; i++) { out.write(new byte[8192]); out.flush(); }
                    }
                } catch (IOException closed) { disconnected.countDown(); }
                catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
                finally { exchange.close(); }
            }); server.start();
            var assistant = new ChatMessage(); assistant.setId(2L); assistant.setAnswerGeneration(3L);
            when(sessions.prepareExchange(7L, 9L, "request", "question")).thenReturn(new ChatSessionService.Exchange(null, assistant, false));
            when(sessions.answerState(2L)).thenAnswer(call -> state.get());
            service = new ChatService(mock(RestTemplate.class), (RedisTemplate<String,Object>) mock(RedisTemplate.class), new ObjectMapper(), sessions, monitor);
            ReflectionTestUtils.setField(service, "pythonAgentUrl", "http://127.0.0.1:" + server.getAddress().getPort());
            ReflectionTestUtils.setField(service, "internalServiceToken", "test-only");
        }
        Future<?> run(OutputStream output) {
            var request = new ChatRequest(); request.setSessionId("9"); request.setRequestId("request"); request.setMessage("question");
            return pool.submit(() -> { service.stream(7L, request).writeTo(output); return true; });
        }
        public void close() { monitor.close(); probe.countDown(); server.stop(0); pool.shutdownNow(); }
    }
}

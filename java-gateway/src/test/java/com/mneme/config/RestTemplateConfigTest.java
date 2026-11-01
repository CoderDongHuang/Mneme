package com.mneme.config;

import com.mneme.service.InternalServiceTokenProvider;
import io.micrometer.tracing.Span;
import io.micrometer.tracing.TraceContext;
import io.micrometer.tracing.Tracer;
import org.junit.jupiter.api.Test;
import org.springframework.boot.restclient.RestTemplateBuilder;
import org.springframework.http.client.InterceptingClientHttpRequestFactory;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.http.HttpMethod;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class RestTemplateConfigTest {

    @Test
    void externalClientDoesNotCarryInternalCredentials() {
        RestTemplate template = new RestTemplateConfig().recoveryHttp();
        MockRestServiceServer server = MockRestServiceServer.bindTo(template).build();
        server.expect(requestTo("https://api.github.com/repos/test/repo/actions/runs"))
            .andExpect(request -> assertThat(request.getHeaders().getFirst("X-Internal-Service-Token")).isNull())
            .andRespond(withSuccess());
        template.getForObject("https://api.github.com/repos/test/repo/actions/runs", String.class);
        server.verify();
    }

    @Test
    void recoveryRequestsUseBoundedContentLength() throws Exception {
        var server = com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1", 0), 0);
        var length = new java.util.concurrent.atomic.AtomicReference<String>();
        var transfer = new java.util.concurrent.atomic.AtomicReference<String>();
        var received = new java.util.concurrent.atomic.AtomicReference<byte[]>();
        server.createContext("/site/jobs", exchange -> {
            length.set(exchange.getRequestHeaders().getFirst("Content-Length"));
            transfer.set(exchange.getRequestHeaders().getFirst("Transfer-Encoding"));
            received.set(exchange.getRequestBody().readAllBytes());
            exchange.sendResponseHeaders(200, -1);
            exchange.close();
        });
        server.start();
        try {
            new RestTemplateConfig().recoveryHttp().postForObject(
                "http://127.0.0.1:" + server.getAddress().getPort() + "/site/jobs",
                java.util.Map.of("action", "backup", "confirmation", "BACKUP SITE"), String.class);
            assertThat(length.get()).isEqualTo(String.valueOf(received.get().length));
            assertThat(transfer.get()).isNull();
            assertThat(new String(received.get(), java.nio.charset.StandardCharsets.UTF_8)).contains("BACKUP SITE");
        } finally { server.stop(0); }
    }

    @Test
    void usesHttp11CompatibleRequestFactoryForPythonAgent() {
        Tracer tracer = mock(Tracer.class);
        var template = new RestTemplateConfig().restTemplate(
            new RestTemplateBuilder(), mock(InternalServiceTokenProvider.class), tracer
        );

        assertThat(template.getRequestFactory())
            .isInstanceOf(InterceptingClientHttpRequestFactory.class);
        assertThat(ReflectionTestUtils.getField(template.getRequestFactory(), "requestFactory"))
            .isInstanceOf(JdkClientHttpRequestFactory.class);
    }

    @Test
    void memoryPatchUsesRealHttp11TransportAndPreservesJsonAndInternalAuthentication() throws Exception {
        var server = com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1", 0), 0);
        var received = new java.util.concurrent.atomic.AtomicReference<String>();
        var method = new java.util.concurrent.atomic.AtomicReference<String>();
        var protocol = new java.util.concurrent.atomic.AtomicReference<String>();
        var upgrade = new java.util.concurrent.atomic.AtomicReference<String>();
        var token = new java.util.concurrent.atomic.AtomicReference<String>();
        server.createContext("/api/v1/memory/admin/test", exchange -> {
            method.set(exchange.getRequestMethod());
            protocol.set(exchange.getProtocol());
            upgrade.set(exchange.getRequestHeaders().getFirst("Upgrade"));
            token.set(exchange.getRequestHeaders().getFirst("X-Internal-Service-Token"));
            received.set(new String(exchange.getRequestBody().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8));
            byte[] response = "{\"status\":\"updated\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            var config = new RestTemplateConfig();
            String origin = "http://127.0.0.1:" + server.getAddress().getPort();
            ReflectionTestUtils.setField(config, "pythonAgentUrl", origin);
            var tokens = mock(InternalServiceTokenProvider.class);
            when(tokens.current()).thenReturn("patch-test-token");
            var template = config.restTemplate(new RestTemplateBuilder(), tokens, mock(Tracer.class));
            var result = template.exchange(origin + "/api/v1/memory/admin/test", HttpMethod.PATCH,
                new org.springframework.http.HttpEntity<>(java.util.Map.of("content", "修改后的记忆", "tags", java.util.List.of("复习"))),
                java.util.Map.class);
            assertThat(result.getBody()).containsEntry("status", "updated");
            assertThat(method.get()).isEqualTo("PATCH");
            assertThat(protocol.get()).isEqualTo("HTTP/1.1");
            assertThat(upgrade.get()).isNull();
            assertThat(token.get()).isEqualTo("patch-test-token");
            var body = new com.fasterxml.jackson.databind.ObjectMapper().readTree(received.get());
            assertThat(body.path("content").asText()).isEqualTo("修改后的记忆");
            assertThat(body.path("tags").get(0).asText()).isEqualTo("复习");
            // An unrelated origin must not receive the service credential.
            ReflectionTestUtils.setField(config, "pythonAgentUrl", "http://unrelated.invalid:8001");
            template.exchange(origin + "/api/v1/memory/admin/test", HttpMethod.POST,
                new org.springframework.http.HttpEntity<>(java.util.Map.of("content", "普通请求")), java.util.Map.class);
            assertThat(method.get()).isEqualTo("POST");
            assertThat(token.get()).isNull();
        } finally { server.stop(0); }
    }

    @Test
    void propagatesCurrentTraceToPythonAgent() {
        InternalServiceTokenProvider tokens = mock(InternalServiceTokenProvider.class);
        Tracer tracer = mock(Tracer.class);
        Span span = mock(Span.class);
        TraceContext context = mock(TraceContext.class);
        when(tokens.current()).thenReturn("test-token");
        when(tracer.currentSpan()).thenReturn(span);
        when(span.context()).thenReturn(context);
        when(context.traceId()).thenReturn("0123456789abcdef0123456789abcdef");
        when(context.spanId()).thenReturn("0123456789abcdef");
        when(context.sampled()).thenReturn(true);
        var config = new RestTemplateConfig();
        ReflectionTestUtils.setField(config, "pythonAgentUrl", "http://python-agent");
        RestTemplate template = config.restTemplate(
            new RestTemplateBuilder(), tokens, tracer
        );
        MockRestServiceServer server = MockRestServiceServer.bindTo(template).build();
        server.expect(requestTo("http://python-agent/api/v1/chat"))
            .andExpect(header("X-Internal-Service-Token", "test-token"))
            .andExpect(header(
                "traceparent", "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
            ))
            .andRespond(withSuccess());

        template.exchange("http://python-agent/api/v1/chat", HttpMethod.POST, null, Void.class);

        server.verify();
    }
}

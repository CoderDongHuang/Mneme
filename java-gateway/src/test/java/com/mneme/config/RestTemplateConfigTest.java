package com.mneme.config;

import com.mneme.service.InternalServiceTokenProvider;
import io.micrometer.tracing.Span;
import io.micrometer.tracing.TraceContext;
import io.micrometer.tracing.Tracer;
import org.junit.jupiter.api.Test;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.client.InterceptingClientHttpRequestFactory;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
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
    void usesHttp11CompatibleRequestFactoryForPythonAgent() {
        Tracer tracer = mock(Tracer.class);
        var template = new RestTemplateConfig().restTemplate(
            new RestTemplateBuilder(), mock(InternalServiceTokenProvider.class), tracer
        );

        assertThat(template.getRequestFactory())
            .isInstanceOf(InterceptingClientHttpRequestFactory.class);
        assertThat(ReflectionTestUtils.getField(template.getRequestFactory(), "requestFactory"))
            .isInstanceOf(SimpleClientHttpRequestFactory.class);
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
        RestTemplate template = new RestTemplateConfig().restTemplate(
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

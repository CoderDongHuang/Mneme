package com.mneme.config;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import com.mneme.service.InternalServiceTokenProvider;
import io.micrometer.tracing.Tracer;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

@Configuration
public class RestTemplateConfig {

    @Bean
    public RestTemplate restTemplate(
        RestTemplateBuilder builder,
        InternalServiceTokenProvider tokens,
        Tracer tracer
    ) {
        return builder
            .requestFactory(SimpleClientHttpRequestFactory::new)
            .additionalInterceptors((request, body, execution) -> {
                request.getHeaders().set("X-Internal-Service-Token", tokens.current());
                var span = tracer.currentSpan();
                if (span != null && !request.getHeaders().containsKey("traceparent")) {
                    var context = span.context();
                    var flags = Boolean.TRUE.equals(context.sampled()) ? "01" : "00";
                    request.getHeaders().set(
                        "traceparent",
                        "00-" + context.traceId() + "-" + context.spanId() + "-" + flags
                    );
                }
                return execution.execute(request, body);
            })
            .setConnectTimeout(Duration.ofSeconds(30))
            .setReadTimeout(Duration.ofSeconds(120))
            .build();
    }
}

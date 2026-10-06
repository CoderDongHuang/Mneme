package com.mneme.config;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import com.mneme.service.InternalServiceTokenProvider;
import io.micrometer.tracing.Tracer;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

@Configuration
public class RestTemplateConfig {

    @Bean
    @Primary
    public RestTemplate restTemplate(
        RestTemplateBuilder builder,
        InternalServiceTokenProvider tokens,
        Tracer tracer
    ) {
        var requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(30));
        requestFactory.setReadTimeout(Duration.ofSeconds(120));
        return builder
            .requestFactory(() -> requestFactory)
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
            .build();
    }

    @Bean("healthHttp")
    public RestTemplate healthHttp(InternalServiceTokenProvider tokens) {
        var client = monitoringHttp();
        client.getInterceptors().add((request, body, execution) -> {
            request.getHeaders().set("X-Internal-Service-Token", tokens.current());
            return execution.execute(request, body);
        });
        return client;
    }

    @Bean("monitoringHttp")
    public RestTemplate monitoringHttp() {
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(2));
        factory.setReadTimeout(Duration.ofSeconds(3));
        return new RestTemplate(factory);
    }

    @Bean("recoveryHttp")
    public RestTemplate recoveryHttp() {
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(15));
        factory.setReadTimeout(Duration.ofSeconds(30));
        return new RestTemplate(factory);
    }
}

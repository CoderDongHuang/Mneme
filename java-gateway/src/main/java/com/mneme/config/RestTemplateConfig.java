package com.mneme.config;

import org.springframework.boot.restclient.RestTemplateBuilder;
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
    @org.springframework.beans.factory.annotation.Autowired
    private com.mneme.service.UserSettingsService userSettings;
    @org.springframework.beans.factory.annotation.Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

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
                if (userSettings != null && sameOrigin(request.getURI(), java.net.URI.create(pythonAgentUrl))
                    && org.springframework.web.context.request.RequestContextHolder.getRequestAttributes()
                       instanceof org.springframework.web.context.request.ServletRequestAttributes attributes
                    && attributes.getRequest().getAttribute("userId") instanceof Long userId) {
                    String model = userSettings.modelHeader(userId);
                    if (!model.isEmpty()) request.getHeaders().set("X-Mneme-Model", model);
                }
                if (pythonAgentUrl != null && sameOrigin(request.getURI(), java.net.URI.create(pythonAgentUrl)))
                    request.getHeaders().set("X-Internal-Service-Token", tokens.current());
                var span = tracer.currentSpan();
                if (span != null && !request.getHeaders().containsHeader("traceparent")) {
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

    private static boolean sameOrigin(java.net.URI target, java.net.URI configured) {
        return java.util.Objects.equals(target.getScheme(), configured.getScheme())
            && java.util.Objects.equals(target.getHost(), configured.getHost())
            && target.getPort() == configured.getPort();
    }

    @Bean("healthHttp")
    public RestTemplate healthHttp(InternalServiceTokenProvider tokens) {
        var client = monitoringHttp();
        client.getInterceptors().add((request, body, execution) -> {
            if (pythonAgentUrl != null && sameOrigin(request.getURI(), java.net.URI.create(pythonAgentUrl)))
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
        var client = new RestTemplate(factory);
        // The small host HTTP executor accepts bounded, fixed-length JSON requests.
        // Spring's streaming request factory otherwise uses chunked encoding.
        client.getInterceptors().add((request, body, execution) -> {
            request.getHeaders().setContentLength(body.length);
            return execution.execute(request, body);
        });
        return client;
    }
}

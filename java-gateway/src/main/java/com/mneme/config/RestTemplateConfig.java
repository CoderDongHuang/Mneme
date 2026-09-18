package com.mneme.config;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import com.mneme.service.InternalServiceTokenProvider;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

@Configuration
public class RestTemplateConfig {

    @Bean
    public RestTemplate restTemplate(
        RestTemplateBuilder builder,
        InternalServiceTokenProvider tokens
    ) {
        return builder
            .requestFactory(SimpleClientHttpRequestFactory::new)
            .additionalInterceptors((request, body, execution) -> {
                request.getHeaders().set("X-Internal-Service-Token", tokens.current());
                return execution.execute(request, body);
            })
            .setConnectTimeout(Duration.ofSeconds(30))
            .setReadTimeout(Duration.ofSeconds(120))
            .build();
    }
}

package com.mneme.config;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

@Configuration
public class RestTemplateConfig {

    @Bean
    public RestTemplate restTemplate(
        RestTemplateBuilder builder,
        @Value("${mneme.internal-service-token}") String internalServiceToken
    ) {
        return builder
            .additionalInterceptors((request, body, execution) -> {
                request.getHeaders().set("X-Internal-Service-Token", internalServiceToken);
                return execution.execute(request, body);
            })
            .setConnectTimeout(Duration.ofSeconds(30))
            .setReadTimeout(Duration.ofSeconds(120))
            .build();
    }
}

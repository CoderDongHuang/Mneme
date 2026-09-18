package com.mneme.config;

import com.mneme.service.InternalServiceTokenProvider;
import org.junit.jupiter.api.Test;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.client.InterceptingClientHttpRequestFactory;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class RestTemplateConfigTest {

    @Test
    void usesHttp11CompatibleRequestFactoryForPythonAgent() {
        var template = new RestTemplateConfig().restTemplate(
            new RestTemplateBuilder(), mock(InternalServiceTokenProvider.class)
        );

        assertThat(template.getRequestFactory())
            .isInstanceOf(InterceptingClientHttpRequestFactory.class);
        assertThat(ReflectionTestUtils.getField(template.getRequestFactory(), "requestFactory"))
            .isInstanceOf(SimpleClientHttpRequestFactory.class);
    }
}

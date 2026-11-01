package com.mneme.controller;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.HttpClientErrorException;
import java.nio.charset.StandardCharsets;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class UpstreamRateLimitTest {
    @RestController
    static class LimitedController {
        @GetMapping("/limited") Object limited() {
            var headers = new HttpHeaders();
            headers.add("Retry-After", "7");
            headers.add("X-Private", "private-upstream-value");
            throw HttpClientErrorException.create(HttpStatus.TOO_MANY_REQUESTS, "limited", headers,
                "private-upstream-body".getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8);
        }
        @GetMapping("/invalid-retry") Object invalidRetry() {
            var headers = new HttpHeaders();
            headers.add("Retry-After", "invalid-private-value");
            throw HttpClientErrorException.create(HttpStatus.TOO_MANY_REQUESTS, "limited", headers,
                new byte[0], StandardCharsets.UTF_8);
        }
    }

    @Test void preservesRateLimitAndRetryWithoutLeakingUpstreamDetails() throws Exception {
        var mvc = MockMvcBuilders.standaloneSetup(new LimitedController())
            .setControllerAdvice(new GlobalExceptionHandler()).build();
        mvc.perform(get("/limited")).andExpect(status().isTooManyRequests())
            .andExpect(header().string("Retry-After", "7"))
            .andExpect(header().doesNotExist("X-Private"))
            .andExpect(jsonPath("$.code").value(429))
            .andExpect(jsonPath("$.message").value("请求过于频繁，请稍后再试"));
        mvc.perform(get("/invalid-retry")).andExpect(status().isTooManyRequests())
            .andExpect(header().string("Retry-After", "1"));
    }
}

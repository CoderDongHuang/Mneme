package com.mneme.config;

import jakarta.servlet.http.HttpServletRequest;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.*;

class RateLimitInterceptorTest {
    @Test
    void ignoresForwardedHeaderFromUntrustedPeer() {
        RateLimitInterceptor interceptor = new RateLimitInterceptor(mock(StringRedisTemplate.class), "", new ObjectMapper());
        HttpServletRequest request = request("203.0.113.9", "198.51.100.4");

        assertThat(interceptor.clientIp(request)).isEqualTo("203.0.113.9");
    }

    @Test
    void stripsTrustedProxyChainFromRight() {
        RateLimitInterceptor interceptor = new RateLimitInterceptor(
            mock(StringRedisTemplate.class), "10.0.0.0/8,2001:db8:1::/48", new ObjectMapper());
        HttpServletRequest request = request(
            "10.0.0.8", "198.51.100.7, 2001:db8:1::4, 10.1.2.3");

        assertThat(interceptor.clientIp(request)).isEqualTo("198.51.100.7");
    }

    @Test
    void malformedForwardedChainFallsBackToPeer() {
        RateLimitInterceptor interceptor = new RateLimitInterceptor(
            mock(StringRedisTemplate.class), "10.0.0.0/8", new ObjectMapper());

        assertThat(interceptor.clientIp(request("10.0.0.8", "198.51.100.7, attacker.example")))
            .isEqualTo("10.0.0.8");
    }

    @Test
    void rejectsInvalidTrustedProxyConfiguration() {
        assertThatThrownBy(() -> new RateLimitInterceptor(mock(StringRedisTemplate.class), "10.0.0.0/99", new ObjectMapper()))
            .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void authLimitReturnsReadableJsonAndRetryTime() throws Exception {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.increment(anyString())).thenReturn(12L, 13L);
        ObjectMapper mapper = new ObjectMapper();
        RateLimitInterceptor interceptor = new RateLimitInterceptor(redis, "", mapper);
        HttpServletRequest request = request("203.0.113.9", null);
        when(request.getRequestURI()).thenReturn("/api/v1/auth/login");
        when(request.getMethod()).thenReturn("POST");

        assertThat(interceptor.preHandle(request, new MockHttpServletResponse(), new Object())).isTrue();
        MockHttpServletResponse response = new MockHttpServletResponse();
        assertThat(interceptor.preHandle(request, response, new Object())).isFalse();
        assertThat(response.getStatus()).isEqualTo(429);
        assertThat(response.getContentType()).startsWith("application/json");
        int retryAfter = Integer.parseInt(response.getHeader("Retry-After"));
        assertThat(retryAfter).isBetween(1, 60);
        var payload = mapper.readTree(response.getContentAsString());
        assertThat(payload.path("code").asInt()).isEqualTo(429);
        assertThat(payload.path("message").asText()).isEqualTo("请求过于频繁，请在 " + retryAfter + " 秒后重试");
    }

    private HttpServletRequest request(String remoteAddress, String forwarded) {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getRemoteAddr()).thenReturn(remoteAddress);
        when(request.getHeader("X-Forwarded-For")).thenReturn(forwarded);
        return request;
    }
}

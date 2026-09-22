package com.mneme.config;

import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.*;

class RateLimitInterceptorTest {
    @Test
    void ignoresForwardedHeaderFromUntrustedPeer() {
        RateLimitInterceptor interceptor = new RateLimitInterceptor(mock(StringRedisTemplate.class), "");
        HttpServletRequest request = request("203.0.113.9", "198.51.100.4");

        assertThat(interceptor.clientIp(request)).isEqualTo("203.0.113.9");
    }

    @Test
    void stripsTrustedProxyChainFromRight() {
        RateLimitInterceptor interceptor = new RateLimitInterceptor(
            mock(StringRedisTemplate.class), "10.0.0.0/8,2001:db8:1::/48");
        HttpServletRequest request = request(
            "10.0.0.8", "198.51.100.7, 2001:db8:1::4, 10.1.2.3");

        assertThat(interceptor.clientIp(request)).isEqualTo("198.51.100.7");
    }

    @Test
    void malformedForwardedChainFallsBackToPeer() {
        RateLimitInterceptor interceptor = new RateLimitInterceptor(
            mock(StringRedisTemplate.class), "10.0.0.0/8");

        assertThat(interceptor.clientIp(request("10.0.0.8", "198.51.100.7, attacker.example")))
            .isEqualTo("10.0.0.8");
    }

    @Test
    void rejectsInvalidTrustedProxyConfiguration() {
        assertThatThrownBy(() -> new RateLimitInterceptor(mock(StringRedisTemplate.class), "10.0.0.0/99"))
            .isInstanceOf(IllegalArgumentException.class);
    }

    private HttpServletRequest request(String remoteAddress, String forwarded) {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getRemoteAddr()).thenReturn(remoteAddress);
        when(request.getHeader("X-Forwarded-For")).thenReturn(forwarded);
        return request;
    }
}

package com.mneme.service;

import com.mneme.controller.ChatController;
import com.mneme.dto.ChatRequest;
import org.eclipse.jetty.ee11.servlet.ServletContextHandler;
import org.eclipse.jetty.ee11.servlet.ServletHolder;
import org.eclipse.jetty.server.Server;
import org.eclipse.jetty.server.ServerConnector;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.context.support.AnnotationConfigWebApplicationContext;
import org.springframework.web.servlet.DispatcherServlet;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Real Spring MVC / Jetty socket; a byte-array service test cannot detect buffering. */
class ChatServletStreamingTest {
    @Configuration @EnableWebMvc
    static class Config implements WebMvcConfigurer {
        @Bean ChatService service() { return mock(ChatService.class); }
        @Bean UserSettingsService settings() { return mock(UserSettingsService.class); }
        @Bean ChatController controller(ChatService service) { return new ChatController(service); }
        @Override public void addInterceptors(InterceptorRegistry registry) {
            registry.addInterceptor(new HandlerInterceptor() {
                @Override public boolean preHandle(jakarta.servlet.http.HttpServletRequest request,
                    jakarta.servlet.http.HttpServletResponse response, Object handler) {
                    request.setAttribute("userId", 1L); return true;
                }
            });
        }
        @Override public void configureMessageConverters(java.util.List<org.springframework.http.converter.HttpMessageConverter<?>> converters) {
            converters.add(new org.springframework.http.converter.json.MappingJackson2HttpMessageConverter(
                new com.fasterxml.jackson.databind.ObjectMapper()));
        }
    }

    @Test void handshakeAndHeartbeatArriveBeforeProviderFinishes() throws Exception {
        var context = new AnnotationConfigWebApplicationContext();
        context.register(Config.class);
        var server = new Server();
        var connector = new ServerConnector(server); connector.setHost("127.0.0.1"); connector.setPort(0);
        server.addConnector(connector);
        var handler = new ServletContextHandler(); handler.setContextPath("/");
        handler.addServlet(new ServletHolder(new DispatcherServlet(context)), "/*");
        server.setHandler(handler);
        var finish = new CountDownLatch(1);
        try {
            server.start();
            when(context.getBean(ChatService.class).stream(eq(1L), any(ChatRequest.class))).thenReturn(output -> {
                output.write("event: start\ndata: {}\n\n".getBytes(StandardCharsets.UTF_8)); output.flush();
                output.write(": heartbeat\n\n".getBytes(StandardCharsets.UTF_8)); output.flush();
                try { finish.await(8, TimeUnit.SECONDS); }
                catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            });
            var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + connector.getLocalPort() + "/api/v1/chat/stream"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString("{\"session_id\":\"1\",\"message\":\"hello\"}")).build();
            var client = HttpClient.newHttpClient();
            var executor = java.util.concurrent.Executors.newSingleThreadExecutor();
            try {
                var response = client.sendAsync(request, HttpResponse.BodyHandlers.ofInputStream()).get(3, TimeUnit.SECONDS);
                assertThat(response.statusCode()).isEqualTo(200);
                try (var body = response.body()) {
                    var received = executor.submit(() -> new String(body.readNBytes(36), StandardCharsets.UTF_8)).get(3, TimeUnit.SECONDS);
                    assertThat(received).isEqualTo("event: start\ndata: {}\n\n: heartbeat\n\n");
                    assertThat(finish.getCount()).isEqualTo(1);
                }
            } finally { executor.shutdownNow(); }
        } finally { finish.countDown(); server.stop(); context.close(); }
    }
}

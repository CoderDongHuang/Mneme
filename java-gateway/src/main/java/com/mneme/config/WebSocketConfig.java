package com.mneme.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;
import com.mneme.websocket.ChatWebSocketHandler;
import com.mneme.service.AuthService;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final ChatWebSocketHandler chatWebSocketHandler;
    private final AuthService authService;

    public WebSocketConfig(ChatWebSocketHandler chatWebSocketHandler, AuthService authService) {
        this.chatWebSocketHandler = chatWebSocketHandler;
        this.authService = authService;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(chatWebSocketHandler, "/ws/chat")
                .addInterceptors(new WebSocketHandshakeInterceptor(authService))
                .setAllowedOrigins("http://localhost:5173", "http://localhost:3000");
    }
}

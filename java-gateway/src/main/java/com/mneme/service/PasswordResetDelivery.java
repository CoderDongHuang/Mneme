package com.mneme.service;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;
import com.mneme.exception.MailDeliveryException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.mail.MailException;
import java.time.Instant;
import java.util.Map;

@Service
public class PasswordResetDelivery {
    private static final Logger log = LoggerFactory.getLogger(PasswordResetDelivery.class);
    private final ObjectProvider<JavaMailSender> sender;
    @Value("${mneme.password-reset-from:}") private String from;
    @Value("${spring.mail.host:}") private String host;
    @Value("${spring.mail.properties.mail.smtp.auth:true}") private boolean authentication;
    @Value("${spring.mail.username:}") private String username;
    @Value("${spring.mail.password:}") private String password;
    private volatile Map<String, String> lastDelivery = Map.of("status", "not_attempted");
    public PasswordResetDelivery(ObjectProvider<JavaMailSender> sender) { this.sender = sender; }
    public boolean configured() {
        return !host.isBlank() && !from.isBlank() && sender.getIfAvailable() != null
            && (!authentication || (!username.isBlank() && !password.isBlank()));
    }
    public void requireConfigured() {
        if (!configured()) throw new MailDeliveryException("邮件服务未配置");
    }
    public Map<String, Object> status() {
        // Configuration is not a connectivity probe or proof of mailbox delivery.
        return Map.of("status", configured() ? "configured" : "not_configured",
            "last_delivery", lastDelivery, "scope", "current_gateway_instance");
    }
    public void send(String email, String token) {
        deliver(email, "Mneme 密码重置", "你的密码重置验证码为：" + token + "。验证码 15 分钟内有效，若非本人操作请忽略。");
    }
    public void sendVerification(String email, String token) {
        deliver(email, "Mneme 邮箱验证", "你的邮箱验证验证码为：" + token + "。验证码 15 分钟内有效，请登录 Mneme 在个人资料中验证。若非本人操作请忽略。");
    }
    private void deliver(String email, String subject, String body) {
        requireConfigured();
        JavaMailSender mailer = sender.getIfAvailable();
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(from); message.setTo(email); message.setSubject(subject);
        message.setText(body);
        try {
            mailer.send(message);
            lastDelivery = Map.of("status", "smtp_accepted", "checked_at", Instant.now().toString());
        } catch (MailException exception) {
            lastDelivery = Map.of("status", "failed", "checked_at", Instant.now().toString());
            log.warn("password_reset_delivery_failed code=SMTP_DELIVERY_FAILED");
            throw new MailDeliveryException("邮件发送失败，请稍后重试或联系管理员");
        }
    }
}

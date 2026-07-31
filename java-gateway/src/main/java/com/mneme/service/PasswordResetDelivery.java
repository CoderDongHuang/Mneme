package com.mneme.service;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;

@Service
public class PasswordResetDelivery {
    private final ObjectProvider<JavaMailSender> sender;
    @Value("${mneme.password-reset-from:}") private String from;
    public PasswordResetDelivery(ObjectProvider<JavaMailSender> sender) { this.sender = sender; }
    public void send(String email, String token) {
        JavaMailSender mailer = sender.getIfAvailable();
        if (mailer == null || from.isBlank()) throw new IllegalStateException("密码重置邮件服务未配置");
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(from); message.setTo(email); message.setSubject("忆知密码重置");
        message.setText("你的密码重置验证码为：" + token + "。验证码 15 分钟内有效，若非本人操作请忽略。");
        mailer.send(message);
    }
}

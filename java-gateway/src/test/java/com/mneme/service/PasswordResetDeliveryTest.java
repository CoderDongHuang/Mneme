package com.mneme.service;

import com.mneme.exception.MailDeliveryException;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.mail.MailAuthenticationException;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.test.util.ReflectionTestUtils;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class PasswordResetDeliveryTest {
    private PasswordResetDelivery service(JavaMailSender sender) {
        var beans = new DefaultListableBeanFactory();
        beans.registerSingleton("mailSender", sender);
        var delivery = new PasswordResetDelivery(beans.getBeanProvider(JavaMailSender.class));
        ReflectionTestUtils.setField(delivery, "host", "localhost");
        ReflectionTestUtils.setField(delivery, "from", "mneme@local.test");
        ReflectionTestUtils.setField(delivery, "username", "");
        ReflectionTestUtils.setField(delivery, "password", "");
        return delivery;
    }
    @Test void missingOrIncompleteConfigurationNeverClaimsSuccess() {
        var sender = mock(JavaMailSender.class);
        var delivery = service(sender);
        ReflectionTestUtils.setField(delivery, "host", "");
        assertThat(delivery.status().get("status")).isEqualTo("not_configured");
        assertThatThrownBy(() -> delivery.send("person@example.com", "private-code"))
            .isInstanceOf(MailDeliveryException.class).hasMessage("邮件服务未配置");
        ReflectionTestUtils.setField(delivery, "host", "smtp.example.com");
        ReflectionTestUtils.setField(delivery, "authentication", true);
        assertThat(delivery.configured()).isFalse();
        verifyNoInteractions(sender);
    }
    @Test void authenticationAndTimeoutExceptionsDropPrivateCause() {
        var logger = (ch.qos.logback.classic.Logger) org.slf4j.LoggerFactory.getLogger(PasswordResetDelivery.class);
        var logs = new ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent>();
        logs.start(); logger.addAppender(logs);
        try {
        for (var failure : new org.springframework.mail.MailException[] {
            new MailAuthenticationException("person@example.com private-code"),
            new MailSendException("person@example.com private-code", new SocketTimeoutException("private-code")) }) {
            var sender = mock(JavaMailSender.class);
            doThrow(failure).when(sender).send(any(SimpleMailMessage.class));
            var delivery = service(sender);
            assertThatThrownBy(() -> delivery.send("person@example.com", "private-code"))
                .isInstanceOf(MailDeliveryException.class).hasNoCause()
                .hasMessageNotContaining("person@example.com").hasMessageNotContaining("private-code");
            assertThat(((Map<?, ?>) delivery.status().get("last_delivery")).get("status")).isEqualTo("failed");
        }
        assertThat(logs.list).allSatisfy(event -> {
            assertThat(event.getFormattedMessage()).doesNotContain("person@example.com", "private-code");
            assertThat(event.getThrowableProxy()).isNull();
        });
        } finally { logger.detachAppender(logs); logs.stop(); }
    }
    @Test void realSmtpTransportReceivesResetMessage() throws Exception {
        try (var server = new ServerSocket(0, 1, InetAddress.getLoopbackAddress())) {
            server.setSoTimeout(5000);
            var received = CompletableFuture.supplyAsync(() -> {
                try (var socket = server.accept()) {
                    socket.setSoTimeout(5000);
                    var reader = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
                    var writer = new PrintWriter(new OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8), true);
                    writer.print("220 test SMTP\r\n"); writer.flush();
                    var message = new StringBuilder(); boolean data = false;
                    for (String line; (line = reader.readLine()) != null;) {
                        if (data && !line.equals(".")) { message.append(line).append('\n'); continue; }
                        if (line.equals(".")) { data = false; writer.print("250 queued\r\n"); }
                        else if (line.equals("DATA")) { data = true; writer.print("354 message\r\n"); }
                        else if (line.equals("QUIT")) { writer.print("221 bye\r\n"); writer.flush(); break; }
                        else writer.print("250 OK\r\n");
                        writer.flush();
                    }
                    return message.toString();
                } catch (IOException e) { throw new UncheckedIOException(e); }
            });
            var sender = new JavaMailSenderImpl();
            sender.setHost("localhost"); sender.setPort(server.getLocalPort());
            sender.getJavaMailProperties().put("mail.smtp.timeout", "5000");
            var delivery = service(sender);
            delivery.send("qa@example.test", "qa-reset-code");
            assertThat(received.get(10, TimeUnit.SECONDS)).contains("To: qa@example.test", "Subject:");
            assertThat(((Map<?, ?>) delivery.status().get("last_delivery")).get("status")).isEqualTo("smtp_accepted");
        }
    }
}

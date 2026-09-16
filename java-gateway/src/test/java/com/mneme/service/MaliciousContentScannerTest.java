package com.mneme.service;

import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.net.ServerSocket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;

class MaliciousContentScannerTest {
    @Test
    void disabledScannerDoesNotRequireClamAv() {
        MaliciousContentScanner scanner = new MaliciousContentScanner(false, true, "127.0.0.1", 1, 500);
        assertDoesNotThrow(() -> scanner.scan(new ByteArrayInputStream("file".getBytes(StandardCharsets.UTF_8))));
    }

    @Test
    void rejectsAClamAvFoundResponse() throws Exception {
        var executor = Executors.newSingleThreadExecutor();
        try (ServerSocket server = new ServerSocket(0)) {
            executor.submit(() -> {
                try (var socket = server.accept()) {
                    DataInputStream input = new DataInputStream(socket.getInputStream());
                    input.readNBytes(10);
                    for (int size = input.readInt(); size > 0; size = input.readInt()) {
                        input.readNBytes(size);
                    }
                    socket.getOutputStream().write("stream: Test-Signature FOUND\0".getBytes(StandardCharsets.UTF_8));
                }
                return null;
            });
            MaliciousContentScanner scanner = new MaliciousContentScanner(
                true, true, "127.0.0.1", server.getLocalPort(), 2000);
            assertThatThrownBy(() -> scanner.scan(new ByteArrayInputStream("infected".getBytes(StandardCharsets.UTF_8))))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("恶意内容扫描");
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void failOpenAllowsUnavailableScannerOnlyWhenConfigured() {
        MaliciousContentScanner scanner = new MaliciousContentScanner(true, false, "127.0.0.1", 1, 500);
        assertDoesNotThrow(() -> scanner.scan(new ByteArrayInputStream("file".getBytes(StandardCharsets.UTF_8))));
    }
}

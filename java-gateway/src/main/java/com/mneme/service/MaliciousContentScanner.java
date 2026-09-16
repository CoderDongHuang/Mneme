package com.mneme.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.DataOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

@Service
public class MaliciousContentScanner {
    private final boolean enabled;
    private final boolean failClosed;
    private final String host;
    private final int port;
    private final int timeoutMs;

    public MaliciousContentScanner(
        @Value("${mneme.malware-scan-enabled:false}") boolean enabled,
        @Value("${mneme.malware-scan-fail-closed:true}") boolean failClosed,
        @Value("${mneme.clamav-host:localhost}") String host,
        @Value("${mneme.clamav-port:3310}") int port,
        @Value("${mneme.clamav-timeout-ms:5000}") int timeoutMs
    ) {
        this.enabled = enabled;
        this.failClosed = failClosed;
        this.host = host;
        this.port = port;
        this.timeoutMs = Math.max(500, timeoutMs);
    }

    public void scan(InputStream input) {
        if (!enabled) return;
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(host, port), timeoutMs);
            socket.setSoTimeout(timeoutMs);
            DataOutputStream output = new DataOutputStream(socket.getOutputStream());
            output.write("zINSTREAM\0".getBytes(StandardCharsets.US_ASCII));
            byte[] buffer = new byte[8192];
            for (int read = input.read(buffer); read >= 0; read = input.read(buffer)) {
                if (read == 0) continue;
                output.writeInt(read);
                output.write(buffer, 0, read);
            }
            output.writeInt(0);
            output.flush();
            ByteArrayOutputStream responseBytes = new ByteArrayOutputStream();
            for (int value = socket.getInputStream().read(); value >= 0 && value != 0; value = socket.getInputStream().read()) {
                if (responseBytes.size() >= 4096) throw new IllegalStateException("ClamAV 返回结果过长");
                responseBytes.write(value);
            }
            String response = responseBytes.toString(StandardCharsets.UTF_8).trim();
            if (response.endsWith("FOUND")) {
                throw new IllegalArgumentException("文件未通过恶意内容扫描");
            }
            if (!response.endsWith("OK")) {
                throw new IllegalStateException("ClamAV 返回未知结果: " + response);
            }
        } catch (IllegalArgumentException error) {
            throw error;
        } catch (Exception error) {
            if (failClosed) throw new IllegalStateException("恶意内容扫描服务不可用", error);
        }
    }
}

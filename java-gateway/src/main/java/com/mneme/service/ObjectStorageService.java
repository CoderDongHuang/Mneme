package com.mneme.service;

import io.minio.BucketExistsArgs;
import io.minio.GetObjectArgs;
import io.minio.ListObjectsArgs;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import io.minio.StatObjectArgs;
import io.minio.errors.ErrorResponseException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.util.HexFormat;

@Service
public class ObjectStorageService {
    private final String backend;
    private final Path root;
    private final Path cacheRoot;
    private final String bucket;
    private final MinioClient minio;
    private final MinioClient diagnosticMinio;

    public ObjectStorageService(
        @Value("${mneme.storage-backend:local}") String backend,
        @Value("${mneme.file-storage-path:../data/files}") String fileStoragePath,
        @Value("${mneme.object-storage-endpoint:}") String endpoint,
        @Value("${mneme.object-storage-access-key:}") String accessKey,
        @Value("${mneme.object-storage-secret-key:}") String secretKey,
        @Value("${mneme.object-storage-bucket:mneme}") String bucket
    ) {
        this.backend = backend.toLowerCase();
        this.root = Path.of(fileStoragePath).toAbsolutePath().normalize();
        this.cacheRoot = root.resolve(".object-cache").normalize();
        this.bucket = bucket;
        if ("s3".equals(this.backend)) {
            if (endpoint.isBlank() || accessKey.isBlank() || secretKey.isBlank()) {
                throw new IllegalStateException("S3 对象存储需要 endpoint、access key 和 secret key");
            }
            this.minio = MinioClient.builder().endpoint(endpoint).credentials(accessKey, secretKey).build();
            this.diagnosticMinio = MinioClient.builder().endpoint(endpoint).credentials(accessKey, secretKey)
                .httpClient(new okhttp3.OkHttpClient.Builder().connectTimeout(java.time.Duration.ofSeconds(3))
                    .readTimeout(java.time.Duration.ofSeconds(5)).writeTimeout(java.time.Duration.ofSeconds(5))
                    .callTimeout(java.time.Duration.ofSeconds(8)).build()).build();
            ensureBucket();
        } else if ("local".equals(this.backend)) {
            this.minio = null;
            this.diagnosticMinio = null;
        } else {
            throw new IllegalStateException("不支持的存储后端: " + backend);
        }
    }

    public String persist(Path localPath, Long userId, Long kbId, String fileName) {
        if (minio == null) return localPath.toAbsolutePath().normalize().toString();
        String key = "users/" + userId + "/knowledge/" + kbId + "/" + localPath.getFileName();
        try (InputStream input = Files.newInputStream(localPath)) {
            minio.putObject(PutObjectArgs.builder().bucket(bucket).object(key)
                .stream(input, Files.size(localPath), -1).contentType("application/octet-stream").build());
            return "s3://" + bucket + "/" + key;
        } catch (Exception error) {
            throw new IllegalStateException("对象存储写入失败", error);
        }
    }

    public Path materialize(String location) {
        if (!location.startsWith("s3://")) return checkedLocal(location, true);
        String key = objectKey(location);
        try {
            Files.createDirectories(cacheRoot);
            Path target = cachedPath(location);
            if (!Files.isRegularFile(target)) {
                try (InputStream input = minio.getObject(
                    GetObjectArgs.builder().bucket(bucket).object(key).build())) {
                    Files.copy(input, target, StandardCopyOption.REPLACE_EXISTING);
                }
            }
            return target;
        } catch (Exception error) {
            throw new IllegalStateException("对象存储读取失败", error);
        }
    }

    public void delete(String location) {
        try {
            if (!location.startsWith("s3://")) {
                Files.deleteIfExists(checkedLocal(location, false));
                return;
            }
            minio.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(objectKey(location)).build());
            Files.deleteIfExists(cachedPath(location));
        } catch (Exception error) {
            throw new IllegalStateException("对象删除失败", error);
        }
    }

    public void deleteUserPrefix(Long userId) {
        if (minio == null) return;
        deletePrefix("users/" + userId + "/");
    }

    public void deleteKnowledgeBasePrefix(Long userId, Long kbId) {
        if (minio == null) return;
        deletePrefix("users/" + userId + "/knowledge/" + kbId + "/");
    }

    public boolean ready() {
        if (minio == null) return true;
        try { return minio.bucketExists(BucketExistsArgs.builder().bucket(bucket).build()); }
        catch (Exception error) { return false; }
    }

    public String backend() { return backend; }

    public java.util.Map<String, Object> diagnose() {
        var result = new DiagnosticResult(true);
        byte[] payload = "Mneme synthetic storage diagnostic".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        String key = ".mneme-diagnostics/" + java.util.UUID.randomUUID();
        Path temporary = null;
        boolean attempted = false, connected = false;
        try {
            if (diagnosticMinio == null) {
                result.stage("connection", "not_applicable");
                // Uses the configured file volume, not the host's unrelated temp directory.
                checkedLocal(root.toString(), false);
                Files.createDirectories(root);
                temporary = Files.createTempFile(checkedLocal(root.toString(), false), ".mneme-diagnostic-", ".tmp");
                attempted = true;
                Files.write(temporary, payload);
                if (!java.util.Arrays.equals(payload, Files.readAllBytes(temporary))) throw new IllegalStateException();
            } else {
                if (!diagnosticMinio.bucketExists(BucketExistsArgs.builder().bucket(bucket).build())) throw new IllegalStateException();
                connected = true;
                result.stage("connection", "passed");
                attempted = true;
                diagnosticMinio.putObject(PutObjectArgs.builder().bucket(bucket).object(key)
                    .stream(new java.io.ByteArrayInputStream(payload), payload.length, -1).build());
                try (var input = diagnosticMinio.getObject(GetObjectArgs.builder().bucket(bucket).object(key).build())) {
                    if (!java.util.Arrays.equals(payload, input.readNBytes(payload.length + 1))) throw new IllegalStateException();
                }
            }
            result.stage("operation", "passed").code("OK");
        } catch (Exception ignored) {
            boolean connectionFailure = diagnosticMinio != null && !connected;
            result.stage(connectionFailure ? "connection" : "operation", "failed")
                .code(connectionFailure ? "CONNECTION_FAILED" : "OPERATION_FAILED");
        } finally {
            if (attempted) {
                try {
                    if (diagnosticMinio == null) {
                        Files.deleteIfExists(temporary);
                        if (Files.exists(temporary, LinkOption.NOFOLLOW_LINKS)) throw new IllegalStateException();
                    } else {
                        diagnosticMinio.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(key).build());
                        try {
                            diagnosticMinio.statObject(StatObjectArgs.builder().bucket(bucket).object(key).build());
                            throw new IllegalStateException();
                        } catch (ErrorResponseException missing) {
                            if (!"NoSuchKey".equals(missing.errorResponse().code())) throw missing;
                        }
                    }
                    result.stage("cleanup", "passed");
                } catch (Exception ignored) { result.stage("cleanup", "failed").code("CLEANUP_FAILED"); }
            }
        }
        return result.finish();
    }

    public long countLocation(String location) throws Exception {
        if (!location.startsWith("s3://")) return countPath(checkedLocal(location, false));
        long remote = 1;
        try { minio.statObject(StatObjectArgs.builder().bucket(bucket).object(objectKey(location)).build()); }
        catch (ErrorResponseException error) {
            if (!"NoSuchKey".equals(error.errorResponse().code())) throw error;
            remote = 0;
        }
        return remote + countPath(cachedPath(location));
    }

    public long countKnowledgeBasePrefix(Long userId, Long kbId) throws Exception {
        return countPrefix("users/" + userId + "/knowledge/" + kbId + "/");
    }

    public long countUserPrefix(Long userId) throws Exception {
        return countPrefix("users/" + userId + "/");
    }

    private long countPrefix(String prefix) throws Exception {
        if (minio == null) return 0;
        long count = 0;
        for (var result : minio.listObjects(ListObjectsArgs.builder().bucket(bucket).prefix(prefix).recursive(true).build())) {
            result.get(); // Includes network/list errors; an unavailable listing is never empty.
            count++;
        }
        return count;
    }

    static long countPath(Path path) throws Exception {
        try { Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS); }
        catch (NoSuchFileException missing) { return 0; }
        // Count the directory itself as a resource too; do not follow symlinks.
        try (var paths = Files.walk(path)) { return paths.count(); }
    }

    private void deletePrefix(String prefix) {
        try {
            var results = minio.listObjects(ListObjectsArgs.builder().bucket(bucket).prefix(prefix).recursive(true).build());
            for (var result : results) {
                String key = result.get().objectName();
                String location = "s3://" + bucket + "/" + key;
                minio.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(key).build());
                Files.deleteIfExists(cachedPath(location));
            }
        } catch (Exception error) {
            throw new IllegalStateException("对象前缀删除失败", error);
        }
    }

    private void ensureBucket() {
        try {
            if (!minio.bucketExists(BucketExistsArgs.builder().bucket(bucket).build())) {
                minio.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
            }
        } catch (Exception error) {
            throw new IllegalStateException("对象存储初始化失败", error);
        }
    }

    private String objectKey(String location) {
        String prefix = "s3://" + bucket + "/";
        if (!location.startsWith(prefix)) throw new IllegalArgumentException("对象 URI 不属于当前 bucket");
        String key = location.substring(prefix.length());
        if (key.isBlank() || key.contains("../")) throw new IllegalArgumentException("对象 URI 无效");
        return key;
    }

    private Path checkedLocal(String rawPath, boolean requireFile) {
        Path path = Path.of(rawPath).toAbsolutePath().normalize();
        if (!path.startsWith(root) || (requireFile && !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS))) {
            throw new IllegalArgumentException("文件路径无效");
        }
        Path current = root;
        if (Files.isSymbolicLink(current)) throw new IllegalArgumentException("文件路径无效");
        for (Path part : root.relativize(path)) {
            current = current.resolve(part);
            if (Files.isSymbolicLink(current)) throw new IllegalArgumentException("文件路径无效");
        }
        return path;
    }

    Path cachedPath(String location) throws Exception {
        String suffix = Path.of(objectKey(location)).getFileName().toString();
        Path target = cacheRoot.resolve(hash(location) + "-" + suffix).normalize();
        if (!target.startsWith(cacheRoot)) throw new IllegalArgumentException("对象缓存路径无效");
        return checkedLocal(target.toString(), false);
    }

    private String hash(String value) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes())).substring(0, 24);
    }
}

package com.mneme.service;

import io.minio.MinioClient;
import io.minio.BucketExistsArgs;
import io.minio.RemoveObjectArgs;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.test.util.ReflectionTestUtils;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.*;

@Testcontainers(disabledWithoutDocker = true)
class ObjectStorageReadbackTest {
    static final String ACCESS = "mneme-readback";
    static final String SECRET = "mneme-readback-test-secret";
    // Match the maintained S3 service used by full-stack CI; MinIO's old Hub image is unavailable.
    @Container static final GenericContainer<?> S3 = new GenericContainer<>("ghcr.io/rustfs/rustfs:1.0.0")
        .withEnv("RUSTFS_ACCESS_KEY", ACCESS).withEnv("RUSTFS_SECRET_KEY", SECRET)
        .withEnv("RUSTFS_VOLUMES", "/data").withEnv("RUSTFS_ADDRESS", "0.0.0.0:9000")
        .withEnv("RUSTFS_UNSAFE_BYPASS_DISK_CHECK", "true")
        .withExposedPorts(9000)
        .waitingFor(Wait.forHttp("/health").forPort(9000));
    @BeforeAll static void waitForStorageQuorum() throws Exception {
        // HTTP health can precede both IAM initialization and the S3 quorum.
        var client = MinioClient.builder().endpoint("http://" + S3.getHost() + ":" + S3.getMappedPort(9000))
            .credentials(ACCESS, SECRET).build();
        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(60);
        while (true) {
            try { client.bucketExists(BucketExistsArgs.builder().bucket("mneme-readiness-probe").build()); return; }
            catch (io.minio.errors.InvalidResponseException starting) {
                String message = starting.getMessage();
                boolean initializing = message.contains("Response code: 503")
                    && (message.contains("storage_quorum") || message.contains("Service not ready: waiting for iam"));
                if (!initializing || System.nanoTime() >= deadline) throw starting;
                Thread.sleep(200);
            }
        }
    }
    @TempDir Path root;
    String endpoint() { return "http://" + S3.getHost() + ":" + S3.getMappedPort(9000); }
    ObjectStorageService storage() { return new ObjectStorageService("s3", root.toString(), endpoint(), ACCESS, SECRET, "mneme"); }
    String put(ObjectStorageService storage, long user, long kb, String name) throws Exception {
        var path = root.resolve(name); Files.writeString(path, "isolated QA object");
        return storage.persist(path, user, kb, name);
    }

    @Test void absentObjectStillCountsCacheAndRetryDeletesItAndKeepsOtherTenant() throws Exception {
        var storage = storage();
        String location = put(storage, 7, 3, "history.txt");
        String other = put(storage, 8, 3, "other.txt");
        storage.materialize(location);
        assertThat(storage.countLocation(location)).isEqualTo(2);
        var client = MinioClient.builder().endpoint(endpoint()).credentials(ACCESS, SECRET).build();
        client.removeObject(RemoveObjectArgs.builder().bucket("mneme").object("users/7/knowledge/3/history.txt").build());
        assertThat(storage.countLocation(location)).isEqualTo(1);
        storage.delete(location);
        assertThat(storage.countLocation(location)).isZero();
        assertThat(storage.countKnowledgeBasePrefix(7L, 3L)).isZero();
        assertThat(storage.countLocation(other)).isEqualTo(1);
        storage.delete(other);
    }

    @Test void prefixDeletionIncludesAllVersionsAndOnlyRequestedTenant() throws Exception {
        var storage = storage();
        String first = put(storage, 17, 3, "v1.txt"), second = put(storage, 17, 3, "v2.txt");
        String keep = put(storage, 18, 3, "keep.txt");
        storage.materialize(first); storage.materialize(second);
        assertThat(storage.countKnowledgeBasePrefix(17L, 3L)).isEqualTo(2);
        storage.deleteKnowledgeBasePrefix(17L, 3L);
        assertThat(storage.countLocation(first)).isZero(); assertThat(storage.countLocation(second)).isZero();
        assertThat(storage.countUserPrefix(17L)).isZero();
        assertThat(storage.countLocation(keep)).isEqualTo(1);
        storage.delete(keep);
    }

    @Test void forbiddenAndUnavailableReadsAreNeverReportedAsAbsent() throws Exception {
        var storage = storage();
        var forbidden = MinioClient.builder().endpoint(endpoint()).credentials(ACCESS, "wrong-test-secret").build();
        ReflectionTestUtils.setField(storage, "minio", forbidden);
        assertThatThrownBy(() -> storage.countLocation("s3://mneme/users/99/knowledge/3/missing.txt")).isInstanceOf(Exception.class);
        assertThatThrownBy(() -> storage.countUserPrefix(99L)).isInstanceOf(Exception.class);
        var offline = MinioClient.builder().endpoint("http://127.0.0.1:1").credentials(ACCESS, SECRET).build();
        ReflectionTestUtils.setField(storage, "minio", offline);
        assertThatThrownBy(() -> storage.countLocation("s3://mneme/users/99/knowledge/3/missing.txt")).isInstanceOf(Exception.class);
        assertThatThrownBy(() -> storage.countUserPrefix(99L)).isInstanceOf(Exception.class);
    }

    @Test void localReadbackCountsDirectoriesAndRejectsOutsidePaths() throws Exception {
        var storage = new ObjectStorageService("local", root.toString(), "", "", "", "mneme");
        var nested = root.resolve("7/3"); Files.createDirectories(nested);
        Files.writeString(nested.resolve("file.txt"), "QA");
        assertThat(storage.countLocation(nested.toString())).isEqualTo(2);
        assertThat(storage.countLocation(nested.resolve("absent.txt").toString())).isZero();
        assertThatThrownBy(() -> storage.countLocation(root.resolve("../outside.txt").toString())).isInstanceOf(IllegalArgumentException.class);
    }
}

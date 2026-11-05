package com.mneme.service;

import io.minio.GetObjectArgs;
import io.minio.GetObjectResponse;
import io.minio.MinioClient;
import okhttp3.Headers;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class ObjectCachePublicationTest {
    @TempDir Path root;
    static final String LOCATION = "s3://mneme/users/7/knowledge/3/history.txt";

    ObjectStorageService storage(MinioClient client) {
        var storage = new ObjectStorageService("local", root.toString(), "", "", "", "mneme");
        ReflectionTestUtils.setField(storage, "minio", client);
        return storage;
    }

    GetObjectResponse response(InputStream input) {
        return new GetObjectResponse(new Headers.Builder().build(), "", "mneme", "", input);
    }

    @Test void failedDownloadLeavesNoCacheAndRetryReadsWholeObject() throws Exception {
        var client = mock(MinioClient.class);
        var broken = spy(new InputStream() {
            int count;
            @Override public int read() throws IOException {
                if (count++ > 1) throw new IOException("interrupted");
                return 'x';
            }
        });
        when(client.getObject(any(GetObjectArgs.class))).thenReturn(response(broken),
            response(new ByteArrayInputStream("complete object".getBytes())));
        var storage = storage(client);
        assertThatThrownBy(() -> storage.materialize(LOCATION)).hasMessage("对象存储读取失败");
        verify(broken).close();
        try (var files = Files.list(root.resolve(".object-cache"))) { assertThat(files.count()).isZero(); }
        var path = storage.materialize(LOCATION);
        assertThat(Files.readString(path)).isEqualTo("complete object");
        assertThat(storage.materialize(LOCATION)).isEqualTo(path);
        verify(client, times(2)).getObject(any(GetObjectArgs.class));
    }

    @Test void anotherInstanceCannotObservePartialFileAndFailedWriterCannotDeletePublishedCache() throws Exception {
        var started = new CountDownLatch(1);
        var finish = new CountDownLatch(1);
        var firstClient = mock(MinioClient.class);
        var blocked = new InputStream() {
            int count;
            @Override public int read() throws IOException {
                if (count++ < 2) return 'x';
                started.countDown();
                try {
                    if (!finish.await(10, TimeUnit.SECONDS)) throw new IOException("timeout");
                } catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IOException(error); }
                throw new IOException("interrupted");
            }
        };
        when(firstClient.getObject(any(GetObjectArgs.class))).thenReturn(response(blocked));
        var secondClient = mock(MinioClient.class);
        when(secondClient.getObject(any(GetObjectArgs.class))).thenReturn(response(new ByteArrayInputStream("complete object".getBytes())));
        var first = storage(firstClient);
        var second = storage(secondClient);
        var pool = Executors.newSingleThreadExecutor();
        try {
            var download = pool.submit(() -> first.materialize(LOCATION));
            assertThat(started.await(10, TimeUnit.SECONDS)).isTrue();
            assertThat(Files.exists(first.cachedPath(LOCATION))).isFalse();
            var published = second.materialize(LOCATION);
            assertThat(Files.readString(published)).isEqualTo("complete object");
            finish.countDown();
            assertThatThrownBy(() -> download.get(10, TimeUnit.SECONDS)).hasCauseInstanceOf(IllegalStateException.class);
            assertThat(Files.readString(published)).isEqualTo("complete object");
            try (var files = Files.list(published.getParent())) {
                assertThat(files.map(Path::getFileName).toList()).containsExactly(published.getFileName());
            }
        } finally { finish.countDown(); pool.shutdownNow(); }
    }
}

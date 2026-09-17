package com.mneme.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

class ObjectStorageServiceTest {
    @TempDir Path root;

    @Test
    void localBackendPersistsMaterializesAndDeletesWithinTenantRoot() throws Exception {
        ObjectStorageService storage = new ObjectStorageService(
            "local", root.toString(), "", "", "", "mneme");
        Path file = root.resolve("7/3/note.txt");
        Files.createDirectories(file.getParent());
        Files.writeString(file, "content");

        String location = storage.persist(file, 7L, 3L, "note.txt");

        assertEquals(file.toAbsolutePath().normalize(), storage.materialize(location));
        storage.delete(location);
        assertFalse(Files.exists(file));
    }

    @Test
    void localBackendRejectsPathsOutsideRoot() throws Exception {
        ObjectStorageService storage = new ObjectStorageService(
            "local", root.toString(), "", "", "", "mneme");
        Path outside = Files.createTempFile("mneme-outside", ".txt");
        try {
            assertThrows(IllegalArgumentException.class, () -> storage.materialize(outside.toString()));
        } finally {
            Files.deleteIfExists(outside);
        }
    }

    @Test
    void cachePathIsStableAndScopedToCacheRoot() throws Exception {
        ObjectStorageService storage = new ObjectStorageService(
            "local", root.toString(), "", "", "", "mneme");

        Path first = storage.cachedPath("s3://mneme/users/7/knowledge/3/note.txt");
        Path second = storage.cachedPath("s3://mneme/users/7/knowledge/3/note.txt");

        assertEquals(first, second);
        assertTrue(first.startsWith(root.resolve(".object-cache")));
        assertTrue(first.getFileName().toString().endsWith("-note.txt"));
        assertThrows(IllegalArgumentException.class,
            () -> storage.cachedPath("s3://other/users/7/note.txt"));
    }
}

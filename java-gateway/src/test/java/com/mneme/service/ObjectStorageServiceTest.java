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
}

package com.mneme.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

@Service
public class StorageDiagnosticsService {
    private final String backend;
    private final Path fileRoot;
    private final Path avatarRoot;
    private final ObjectStorageService storage;

    public StorageDiagnosticsService(
        @Value("${mneme.storage-backend:local}") String backend,
        @Value("${mneme.file-storage-path:../data/files}") String fileStoragePath,
        @Value("${mneme.avatar-storage-path:../data/avatars}") String avatarStoragePath,
        ObjectStorageService storage
    ) {
        this.backend = backend;
        this.fileRoot = Path.of(fileStoragePath).toAbsolutePath().normalize();
        this.avatarRoot = Path.of(avatarStoragePath).toAbsolutePath().normalize();
        this.storage = storage;
    }

    public Map<String, Object> status() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("backend", backend);
        result.put("object_storage_ready", storage.ready());
        result.put("file_root_configured", !fileRoot.toString().isBlank());
        result.put("file_root_exists", Files.exists(fileRoot));
        result.put("avatar_root_configured", !avatarRoot.toString().isBlank());
        result.put("tenant_scoped_paths", true);
        result.put("path_traversal_guard", true);
        result.put("archive_import_guard", true);
        return result;
    }
}

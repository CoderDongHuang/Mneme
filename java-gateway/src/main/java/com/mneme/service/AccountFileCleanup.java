package com.mneme.service;

import org.springframework.jdbc.core.JdbcTemplate;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.FileVisitResult;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.function.Consumer;

/** The SQL manifest must survive until both objects and local copies are verified absent. */
final class AccountFileCleanup {
    private final JdbcTemplate jdbc;
    private final ObjectStorageService storage;
    private final Path root;

    AccountFileCleanup(JdbcTemplate jdbc, ObjectStorageService storage, Path root) {
        this.jdbc = jdbc;
        this.storage = storage;
        this.root = root;
    }

    void cleanAndVerify(long userId) throws Exception {
        Path directory = root.resolve(Long.toString(userId));
        // Listing S3 alone cannot discover cached objects already missing remotely.
        locations(userId, storage::delete);
        storage.deleteUserPrefix(userId);
        // Validates the configured root and symlink ancestors, and propagates unreadable paths.
        if (storage.countLocation(directory.toString()) != 0) {
            Files.walkFileTree(directory, new SimpleFileVisitor<>() {
                @Override public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) throws IOException {
                    Files.delete(file);
                    return FileVisitResult.CONTINUE;
                }
                @Override public FileVisitResult postVisitDirectory(Path dir, IOException error) throws IOException {
                    if (error != null) throw error;
                    Files.delete(dir);
                    return FileVisitResult.CONTINUE;
                }
            });
        }
        locations(userId, location -> {
            try { requireZero(storage.countLocation(location)); }
            catch (Exception error) { throw new IllegalStateException("账号版本文件未通过读回核验", error); }
        });
        requireZero(storage.countUserPrefix(userId));
        requireZero(storage.countLocation(directory.toString()));
    }

    void readReport(long userId, CleanupReport report) {
        report.read("files", () -> {
            long[] count = {0};
            locations(userId, location -> {
                try { count[0] = Math.addExact(count[0], storage.countLocation(location)); }
                catch (Exception error) { throw new IllegalStateException("版本文件无法读取", error); }
            });
            return count[0];
        });
        report.read("object_prefix", () -> storage.countUserPrefix(userId));
        report.read("local_directory", () -> storage.countLocation(root.resolve(Long.toString(userId)).toString()));
    }

    private static void requireZero(long count) {
        if (count != 0) throw new IllegalStateException("账号文件清理未通过读回核验");
    }

    private void locations(long userId, Consumer<String> action) {
        // Separate keyset cursors keep both manifests bounded, including all historical versions.
        for (boolean versions : new boolean[] {false, true}) {
            long after = 0;
            String sql = versions ? """
                SELECT v.id,v.file_path FROM knowledge_document_version v
                JOIN knowledge_document d ON d.id=v.document_id JOIN knowledge_base k ON k.id=d.kb_id
                WHERE k.user_id=? AND v.id>? ORDER BY v.id LIMIT 256
                """ : """
                SELECT d.id,d.file_path FROM knowledge_document d JOIN knowledge_base k ON k.id=d.kb_id
                WHERE k.user_id=? AND d.id>? ORDER BY d.id LIMIT 256
                """;
            while (true) {
                var batch = jdbc.queryForList(sql, userId, after);
                if (batch.isEmpty()) break;
                for (var row : batch) {
                    Object location = row.get("file_path");
                    if (!(location instanceof String path) || path.isBlank()) {
                        throw new IllegalStateException("账号版本清理清单无效");
                    }
                    action.accept(path);
                }
                after = ((Number) batch.get(batch.size() - 1).get("id")).longValue();
            }
        }
    }
}

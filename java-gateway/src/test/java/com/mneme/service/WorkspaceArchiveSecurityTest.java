package com.mneme.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestTemplate;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class WorkspaceArchiveSecurityTest {
    private final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();

    @TempDir
    Path tempDir;

    @Test
    void exportsAUsableArchiveWithoutLeakingStoragePaths() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        Path stored = Files.writeString(tempDir.resolve("resume.pdf"), "%PDF-1.7 test");
        Map<String, Object> document = new LinkedHashMap<>();
        document.put("id", 9L);
        document.put("kb_id", 4L);
        document.put("file_name", "resume.pdf");
        document.put("file_path", stored.toString());
        document.put("status", "ready");
        document.put("chunk_count", 3);
        document.put("created_at", "2026-09-14T10:00:00");
        document.put("updated_at", "2026-09-14T10:01:00");
        when(jdbc.queryForList(anyString(), any(Object[].class))).thenAnswer(invocation ->
            invocation.<String>getArgument(0).contains("knowledge_document")
                ? List.of(document) : List.of()
        );

        WorkspaceService service = service(jdbc, tempDir);
        byte[] archive = service.exportArchive(1L);
        JsonNode manifest = readEntry(archive, "workspace.json");

        assertThat(manifest.path("documents")).hasSize(1);
        assertThat(manifest.path("documents").get(0).has("file_path")).isFalse();
        assertThat(readEntryBytes(archive, "files/9/resume.pdf"))
            .isEqualTo("%PDF-1.7 test".getBytes(StandardCharsets.UTF_8));
    }

    @Test
    void rejectsOversizedFilesDuringExport() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        Path stored = tempDir.resolve("large.pdf");
        try (var output = Files.newOutputStream(stored)) {
            output.write(new byte[20 * 1024 * 1024 + 1]);
        }
        Map<String, Object> document = new LinkedHashMap<>();
        document.put("id", 9L);
        document.put("kb_id", 4L);
        document.put("file_name", "large.pdf");
        document.put("file_path", stored.toString());
        when(jdbc.queryForList(anyString(), any(Object[].class))).thenAnswer(invocation ->
            invocation.<String>getArgument(0).contains("knowledge_document")
                ? List.of(document) : List.of()
        );

        assertThatThrownBy(() -> service(jdbc, tempDir).exportArchive(1L))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("单文件大小限制");
    }

    @Test
    void previewDoesNotLeakServerPathAndRejectsFilesOutsideStorage() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        Path stored = Files.writeString(tempDir.resolve("notes.txt"), "citation text");
        Map<String, Object> document = new LinkedHashMap<>();
        document.put("id", 9L);
        document.put("kb_id", 4L);
        document.put("file_name", "notes.txt");
        document.put("file_path", stored.toString());
        document.put("status", "ready");
        document.put("chunk_count", 1);
        when(jdbc.queryForList(anyString(), any(Object[].class))).thenReturn(List.of(document));

        WorkspaceService service = service(jdbc, tempDir);
        Map<String, Object> preview = service.preview(1L, 9L);
        @SuppressWarnings("unchecked") Map<String, Object> publicDocument = (Map<String, Object>) preview.get("document");
        assertThat(publicDocument).doesNotContainKey("file_path");
        assertThat(preview.get("content")).isEqualTo("citation text");
        assertThat(service.documentPath(1L, 9L)).isEqualTo(stored.toAbsolutePath().normalize());

        document.put("file_path", tempDir.getParent().resolve("outside.txt").toString());
        assertThatThrownBy(() -> service.documentPath(1L, 9L))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("路径无效");
    }

    @Test
    void importsAValidArchiveAndRestoresOnlyRelationalData() throws Exception {
        WorkspaceService service = service(mock(JdbcTemplate.class), tempDir);
        Map<String, Object> result = service.importArchive(1L, zip(
            Map.of("workspace.json", "{\"schema\":\"mneme.workspace\",\"version\":2,\"knowledge_bases\":[]}")
        ));

        assertThat(result).containsEntry("status", "imported")
            .containsEntry("original_files", "not_restored");
        assertThat(result.get("message").toString()).contains("重新上传");
    }

    @Test
    void rejectsMalformedAndIncompleteArchives() throws Exception {
        WorkspaceService service = service(mock(JdbcTemplate.class), tempDir);

        assertThatThrownBy(() -> service.importArchive(1L, "not-a-zip".getBytes(StandardCharsets.UTF_8)))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("有效的 ZIP");
        assertThatThrownBy(() -> service.importArchive(1L, zip(Map.of("files/readme.txt", "x"))))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("workspace.json");
    }

    @Test
    void rejectsUnsafeArchiveEntryNames() throws Exception {
        WorkspaceService service = service(mock(JdbcTemplate.class), tempDir);

        for (String name : List.of("../../outside.txt", "/outside.txt", "C:/outside.txt", "notes.txt")) {
            assertThatThrownBy(() -> service.importArchive(1L, zip(Map.of(name, "x"))))
                .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test
    void rejectsArchivesWithTooManyEntries() throws Exception {
        Map<String, String> entries = new LinkedHashMap<>();
        for (int index = 0; index < 501; index++) entries.put("files/" + index + ".txt", "x");

        assertThatThrownBy(() -> service(mock(JdbcTemplate.class), tempDir).importArchive(1L, zip(entries)))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("文件数量超限");
    }

    @Test
    void rejectsEntryAndTotalUncompressedSizeLimits() throws Exception {
        byte[] oversizedEntry = new byte[20 * 1024 * 1024 + 1];
        assertThatThrownBy(() -> service(mock(JdbcTemplate.class), tempDir).importArchive(
            1L, zipBytes(Map.of("files/large.bin", oversizedEntry))))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("解压大小超限");

        Map<String, byte[]> entries = new LinkedHashMap<>();
        byte[] block = new byte[1024 * 1024];
        for (int index = 0; index < 11; index++) {
            ByteArrayOutputStream content = new ByteArrayOutputStream();
            for (int blockIndex = 0; blockIndex < 19; blockIndex++) content.write(block);
            entries.put("files/total-" + index + ".bin", content.toByteArray());
        }
        assertThatThrownBy(() -> service(mock(JdbcTemplate.class), tempDir).importArchive(1L, zipBytes(entries)))
            .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("解压大小超限");
    }

    private WorkspaceService service(JdbcTemplate jdbc, Path storage) throws Exception {
        WorkspaceService service = new WorkspaceService(jdbc, mapper, new RestTemplate());
        Field field = WorkspaceService.class.getDeclaredField("fileStoragePath");
        field.setAccessible(true);
        field.set(service, storage.toString());
        return service;
    }

    private byte[] zip(Map<String, String> entries) throws Exception {
        Map<String, byte[]> bytes = new LinkedHashMap<>();
        entries.forEach((name, value) -> bytes.put(name, value.getBytes(StandardCharsets.UTF_8)));
        return zipBytes(bytes);
    }

    private byte[] zipBytes(Map<String, byte[]> entries) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            for (Map.Entry<String, byte[]> entry : entries.entrySet()) {
                zip.putNextEntry(new ZipEntry(entry.getKey()));
                zip.write(entry.getValue());
                zip.closeEntry();
            }
        }
        return output.toByteArray();
    }

    private JsonNode readEntry(byte[] archive, String name) throws Exception {
        return mapper.readTree(readEntryBytes(archive, name));
    }

    private byte[] readEntryBytes(byte[] archive, String name) throws Exception {
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(archive))) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                if (entry.getName().equals(name)) return zip.readAllBytes();
            }
        }
        throw new IllegalArgumentException("missing test entry: " + name);
    }
}

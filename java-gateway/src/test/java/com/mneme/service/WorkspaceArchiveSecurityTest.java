package com.mneme.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.KnowledgeDocument;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestTemplate;
import org.springframework.test.util.ReflectionTestUtils;

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
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.doThrow;

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
        assertThat(manifest.path("documents").get(0).path("sha256").asText()).hasSize(64);
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
    void importsAValidArchiveWithoutDocuments() throws Exception {
        WorkspaceService service = service(mock(JdbcTemplate.class), tempDir);
        Map<String, Object> result = service.importArchive(1L, zip(
            Map.of("workspace.json", "{\"schema\":\"mneme.workspace\",\"version\":2,\"knowledge_bases\":[]}")
        ));

        assertThat(result).containsEntry("status", "imported")
            .containsEntry("original_files", "restored");
        assertThat(result.get("message").toString()).contains("索引重建队列");
    }

    @Test
    void restoresVerifiedOriginalFilesAndQueuesIngestion() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class)).thenReturn(31L);
        WorkspaceService service = service(jdbc, tempDir);
        KnowledgeService knowledge = mock(KnowledgeService.class);
        ReflectionTestUtils.setField(service, "knowledgeService", knowledge);
        byte[] content = "archived notes".getBytes(StandardCharsets.UTF_8);
        String hash = java.util.HexFormat.of().formatHex(
            java.security.MessageDigest.getInstance("SHA-256").digest(content));
        String workspace = mapper.writeValueAsString(Map.of(
            "schema", "mneme.workspace",
            "version", 2,
            "knowledge_bases", List.of(Map.of("id", 4, "name", "Imported")),
            "documents", List.of(Map.of(
                "id", 9, "kb_id", 4, "file_name", "notes.txt", "sha256", hash))
        ));

        Map<String, Object> result = service.importArchive(7L, zipBytes(Map.of(
            "workspace.json", workspace.getBytes(StandardCharsets.UTF_8),
            "files/9/notes.txt", content
        )));

        @SuppressWarnings("unchecked") Map<String, Integer> documents =
            (Map<String, Integer>) result.get("documents");
        assertThat(documents).containsEntry("restored", 1).containsEntry("skipped", 0);
        verify(knowledge).importArchivedDocument(7L, 31L, "notes.txt", content);
    }

    @Test
    void rejectsArchiveFileWhoseDigestDoesNotMatchManifest() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class)).thenReturn(31L);
        String workspace = mapper.writeValueAsString(Map.of(
            "schema", "mneme.workspace", "version", 2,
            "knowledge_bases", List.of(Map.of("id", 4, "name", "Imported")),
            "documents", List.of(Map.of(
                "id", 9, "kb_id", 4, "file_name", "notes.txt", "sha256", "0".repeat(64)))
        ));

        assertThatThrownBy(() -> service(jdbc, tempDir).importArchive(7L, zipBytes(Map.of(
            "workspace.json", workspace.getBytes(StandardCharsets.UTF_8),
            "files/9/notes.txt", "tampered".getBytes(StandardCharsets.UTF_8)
        )))).isInstanceOf(IllegalArgumentException.class).hasMessageContaining("完整性校验失败");
    }

    @Test
    void removesAlreadyRestoredFilesWhenALaterImportFails() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class)).thenReturn(31L);
        WorkspaceService service = service(jdbc, tempDir);
        KnowledgeService knowledge = mock(KnowledgeService.class);
        ReflectionTestUtils.setField(service, "knowledgeService", knowledge);
        byte[] first = "first".getBytes(StandardCharsets.UTF_8);
        byte[] second = "second".getBytes(StandardCharsets.UTF_8);
        KnowledgeDocument restored = new KnowledgeDocument();
        restored.setId(101L);
        when(knowledge.importArchivedDocument(7L, 31L, "first.txt", first)).thenReturn(restored);
        doThrow(new IllegalStateException("storage unavailable")).when(knowledge)
            .importArchivedDocument(7L, 31L, "second.txt", second);
        String firstHash = java.util.HexFormat.of().formatHex(
            java.security.MessageDigest.getInstance("SHA-256").digest(first));
        String secondHash = java.util.HexFormat.of().formatHex(
            java.security.MessageDigest.getInstance("SHA-256").digest(second));
        String workspace = mapper.writeValueAsString(Map.of(
            "schema", "mneme.workspace", "version", 2,
            "knowledge_bases", List.of(Map.of("id", 4, "name", "Imported")),
            "documents", List.of(
                Map.of("id", 9, "kb_id", 4, "file_name", "first.txt", "sha256", firstHash),
                Map.of("id", 10, "kb_id", 4, "file_name", "second.txt", "sha256", secondHash))
        ));

        assertThatThrownBy(() -> service.importArchive(7L, zipBytes(Map.of(
            "workspace.json", workspace.getBytes(StandardCharsets.UTF_8),
            "files/9/first.txt", first,
            "files/10/second.txt", second
        )))).isInstanceOf(IllegalStateException.class).hasMessageContaining("storage unavailable");
        verify(knowledge).discardImportedDocument(restored);
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

package com.mneme.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Duration;
import java.time.Instant;
import java.util.*;

/** Operator-only mark/sweep. The host launcher enforces stopped Gateway/Agent writers. */
public final class StorageRetention {
    public record Policy(int versions, int versionDays, int taskDays, int orphanHours,
                         int cacheHours, long cacheBytes, Set<String> pinnedLocations) {
        public Policy {
            if (versions < 1 || versionDays < 1 || taskDays < 1 || orphanHours < 1
                    || cacheHours < 1 || cacheBytes < 0 || pinnedLocations == null) {
                throw new IllegalArgumentException("invalid_retention_policy");
            }
            pinnedLocations = Set.copyOf(pinnedLocations);
        }
    }

    private record Version(long id, long document, int number, String location, Instant created) {}
    private record Task(long id, String taskId, String status, String payload, Instant updated) {}
    public record Receipt(String status, int versions, int tasks, int objects, int caches, long bytes) {}
    private final JdbcTemplate jdbc;
    private final ObjectStorageService storage;
    private final ObjectMapper json = new ObjectMapper();

    public StorageRetention(JdbcTemplate jdbc, ObjectStorageService storage) {
        this.jdbc = jdbc;
        this.storage = storage;
    }

    public Receipt run(Policy policy, boolean apply, Instant now) throws Exception {
        // Materialize the *entire* listing and validate all payloads before mutation.
        var inventory = storage.retentionInventory();
        var versions = jdbc.query("SELECT id,document_id,version_number,file_path,created_at FROM knowledge_document_version ORDER BY document_id,version_number DESC",
            (row, n) -> new Version(row.getLong(1), row.getLong(2), row.getInt(3),
                normalized(row.getString(4)), row.getTimestamp(5).toInstant()));
        var tasks = jdbc.query("SELECT id,task_id,status,payload,updated_at FROM processing_task",
            (row, n) -> new Task(row.getLong(1), row.getString(2), row.getString(3),
                row.getString(4), row.getTimestamp(5).toInstant()));
        var active = new HashSet<String>();
        for (String location : jdbc.queryForList("SELECT file_path FROM knowledge_document", String.class)) {
            active.add(normalized(location));
        }
        policy.pinnedLocations().forEach(location -> active.add(normalized(location)));
        var currentTasks = new HashSet<>(jdbc.queryForList(
            "SELECT parse_task_id FROM knowledge_document WHERE parse_task_id IS NOT NULL", String.class));
        var removableTasks = new ArrayList<Task>();
        var taskReferences = new HashSet<String>();
        Instant taskCutoff = now.minus(Duration.ofDays(policy.taskDays()));
        for (Task task : tasks) {
            var payload = json.readTree(task.payload()); // Malformed JSON fails closed.
            boolean terminal = Set.of("completed", "cancelled").contains(task.status());
            if (terminal && task.updated().isBefore(taskCutoff) && !currentTasks.contains(task.taskId())) {
                removableTasks.add(task);
            } else {
                collectLocations(payload, taskReferences);
            }
        }
        active.addAll(taskReferences);
        var removableVersions = new ArrayList<Version>();
        var ranks = new HashMap<Long, Integer>();
        Instant versionCutoff = now.minus(Duration.ofDays(policy.versionDays()));
        for (Version version : versions) {
            int rank = ranks.merge(version.document(), 1, Integer::sum);
            // Preserve the largest version number even when the restored active version is old.
            if (rank > policy.versions() && version.created().isBefore(versionCutoff)
                    && !active.contains(version.location())) removableVersions.add(version);
        }
        var removedIds = new HashSet<Long>();
        removableVersions.forEach(version -> removedIds.add(version.id()));
        var retained = new HashSet<>(active);
        versions.stream().filter(version -> !removedIds.contains(version.id()))
            .forEach(version -> retained.add(version.location()));
        var objects = new ArrayList<ObjectStorageService.RetentionObject>();
        var caches = new ArrayList<ObjectStorageService.RetentionObject>();
        long totalCache = inventory.stream().filter(ObjectStorageService.RetentionObject::cache)
            .mapToLong(ObjectStorageService.RetentionObject::bytes).sum();
        long orphanCutoff = now.minus(Duration.ofHours(policy.orphanHours())).toEpochMilli();
        long cacheCutoff = now.minus(Duration.ofHours(policy.cacheHours())).toEpochMilli();
        var sorted = inventory.stream().sorted(Comparator.comparingLong(ObjectStorageService.RetentionObject::modifiedMillis)).toList();
        for (var item : sorted) {
            String location = normalized(item.location());
            if (item.cache()) {
                // Cache has no authoritative data. Offline readers can safely fetch it again.
                if (!retained.contains(location) && (item.modifiedMillis() < cacheCutoff || totalCache > policy.cacheBytes())) {
                    caches.add(item);
                    totalCache -= item.bytes();
                }
            } else if (!retained.contains(location) && item.modifiedMillis() < orphanCutoff) {
                objects.add(item);
            }
        }
        if (apply) {
            new TransactionTemplate(new DataSourceTransactionManager(Objects.requireNonNull(jdbc.getDataSource())))
                .executeWithoutResult(status -> {
                    for (Task task : removableTasks) {
                        int changed = jdbc.update("DELETE FROM processing_task WHERE id=? AND status IN ('completed','cancelled') AND updated_at<?",
                            task.id(), java.sql.Timestamp.from(taskCutoff));
                        if (changed != 1) throw new IllegalStateException("task_changed_stop_writers");
                    }
                    for (Version version : removableVersions) {
                        int changed = jdbc.update("DELETE FROM knowledge_document_version WHERE id=? AND document_id=? AND version_number=?",
                            version.id(), version.document(), version.number());
                        if (changed != 1) throw new IllegalStateException("version_changed_stop_writers");
                    }
                });
            // Commit metadata first: a failed object deletion remains an observable orphan.
            for (var item : objects) storage.delete(item.location());
            for (var item : caches) storage.delete(item.location());
        }
        long bytes = java.util.stream.Stream.concat(objects.stream(), caches.stream())
            .mapToLong(ObjectStorageService.RetentionObject::bytes).sum();
        return new Receipt(apply ? "completed" : "planned", removableVersions.size(), removableTasks.size(),
            objects.size(), caches.size(), bytes);
    }

    private String normalized(String location) {
        if (location == null || location.isBlank()) throw new IllegalStateException("invalid_storage_reference");
        return storage.normalizedLocation(location);
    }

    private void collectLocations(JsonNode node, Set<String> references) {
        if (node == null) throw new IllegalStateException("invalid_task_payload");
        if (node.isObject()) {
            node.fields().forEachRemaining(entry -> {
                if (Set.of("file_path", "file_paths").contains(entry.getKey())) {
                    collectPathValues(entry.getValue(), references);
                } else if (entry.getValue().isContainerNode()) collectLocations(entry.getValue(), references);
            });
        } else if (node.isArray()) node.forEach(child -> collectLocations(child, references));
    }

    private void collectPathValues(JsonNode node, Set<String> references) {
        if (node.isTextual()) references.add(normalized(node.textValue()));
        else if (node.isArray()) node.forEach(child -> collectPathValues(child, references));
        else if (!node.isNull()) throw new IllegalStateException("invalid_task_file_reference");
    }
}

package com.mneme.service;

import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import io.minio.MinioClient;
import io.minio.BucketExistsArgs;
import io.minio.RemoveObjectArgs;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.springframework.web.client.RestTemplate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Real MySQL/Flyway, object server, and filesystem; failures must preserve the SQL retry manifest. */
@Testcontainers(disabledWithoutDocker = true)
class AccountFileCleanupTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("mneme-test-password");
    static final String ACCESS = "mneme-account-qa", SECRET = "mneme-account-qa-secret";
    @Container static final GenericContainer<?> S3 = new GenericContainer<>("ghcr.io/rustfs/rustfs:1.0.0")
        .withEnv("RUSTFS_ACCESS_KEY", ACCESS).withEnv("RUSTFS_SECRET_KEY", SECRET)
        .withEnv("RUSTFS_VOLUMES", "/data").withEnv("RUSTFS_ADDRESS", "0.0.0.0:9000")
        .withEnv("RUSTFS_UNSAFE_BYPASS_DISK_CHECK", "true").withExposedPorts(9000)
        .waitingFor(Wait.forHttp("/health").forPort(9000));
    static JdbcTemplate jdbc;
    static DataSourceTransactionManager manager;
    @TempDir Path root;

    static String endpoint() { return "http://" + S3.getHost() + ":" + S3.getMappedPort(9000); }
    static MinioClient client() { return MinioClient.builder().endpoint(endpoint()).credentials(ACCESS, SECRET).build(); }
    @BeforeAll static void databaseAndStorage() throws Exception {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        jdbc = new JdbcTemplate(source); manager = new DataSourceTransactionManager(source);
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(60);
        while (true) {
            try { client().bucketExists(BucketExistsArgs.builder().bucket("mneme-readiness-probe").build()); break; }
            catch (io.minio.errors.InvalidResponseException starting) {
                String message = starting.getMessage();
                if (!message.contains("Response code: 503") || System.nanoTime() >= deadline) throw starting;
                Thread.sleep(200);
            }
        }
    }

    long insert(String sql, Object... args) {
        var keys = new org.springframework.jdbc.support.GeneratedKeyHolder();
        jdbc.update(connection -> {
            var statement = connection.prepareStatement(sql, java.sql.Statement.RETURN_GENERATED_KEYS);
            for (int i = 0; i < args.length; i++) statement.setObject(i + 1, args[i]);
            return statement;
        }, keys);
        return keys.getKey().longValue();
    }

    final class Fixture implements AutoCloseable {
        final long user = user(), keep = user();
        final long kb = kb(user), keepKb = kb(keep);
        final ObjectStorageService storage;
        final String current, history, retained;
        final long document, task;
        final Path avatar;
        final UserMapper users = mock(UserMapper.class);
        final TaskLeaseService leases = new TaskLeaseService(jdbc, manager, 30);
        final AccountDeletionService service;
        Fixture(boolean objects, String checkpoint) throws Exception {
            storage = spy(new ObjectStorageService(objects ? "s3" : "local", root.toString(),
                objects ? endpoint() : "", ACCESS, SECRET, "mneme"));
            current = file(user, kb, "current.txt"); history = file(user, kb, "history.txt");
            retained = file(keep, keepKb, "keep.txt");
            document = doc(kb, current); doc(keepKb, retained);
            jdbc.update("INSERT INTO knowledge_document_version(document_id,version_number,file_name,file_path,sha256,size_bytes) VALUES(?,1,'history',?,?,2)", document, history, "a".repeat(64));
            avatar = root.resolve("avatars/" + user + ".png");
            Files.createDirectories(avatar.getParent()); Files.writeString(avatar, "QA avatar");
            var snapshot = new User(); snapshot.setId(user); snapshot.setAvatarPath(avatar.toString());
            when(users.selectById(user)).thenReturn(snapshot);
            realDelete();
            task = insert("INSERT INTO account_deletion_task(operation_id,user_id,status,current_step,next_attempt_at) VALUES(?,?,'pending',?,UTC_TIMESTAMP())",
                UUID.randomUUID().toString(), user, checkpoint);
            service = new AccountDeletionService(users, jdbc, mock(RestTemplate.class), mock(OperationLogService.class),
                "http://agent", root.toString(), 8, storage, leases);
        }
        long user() { return insert("INSERT INTO user(username,password_hash,status) VALUES(?,'QA','deleting')", UUID.randomUUID().toString()); }
        long kb(long owner) { return insert("INSERT INTO knowledge_base(user_id,name) VALUES(?,'QA')", owner); }
        long doc(long base, String location) { return insert("INSERT INTO knowledge_document(kb_id,file_name,file_path) VALUES(?,'QA',?)", base, location); }
        String file(long owner, long base, String name) throws Exception {
            Path path = root.resolve(owner + "/" + base + "/" + name);
            Files.createDirectories(path.getParent()); Files.writeString(path, "QA object");
            String location = storage.persist(path, owner, base, name);
            storage.materialize(location);
            return location;
        }
        void realDelete() { doAnswer(call -> jdbc.update("DELETE FROM user WHERE id=?", user)).when(users).deleteById(user); }
        void run() {
            try (var lease = leases.claim(TaskLeaseService.Queue.ACCOUNT_DELETION, task, false)) {
                assertThat(lease).isNotNull(); service.execute(lease);
            }
        }
        void retry() {
            jdbc.update("UPDATE account_deletion_task SET next_attempt_at=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP()) WHERE id=?", task); run();
        }
        void retained() {
            assertThat(jdbc.queryForObject("SELECT status FROM account_deletion_task WHERE id=?", String.class, task)).isEqualTo("retry");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM user WHERE id=?", Integer.class, user)).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document WHERE id=?", Integer.class, document)).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document_version WHERE document_id=?", Integer.class, document)).isEqualTo(1);
        }
        void completed() throws Exception {
            assertThat(jdbc.queryForObject("SELECT status FROM account_deletion_task WHERE id=?", String.class, task)).isEqualTo("completed");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM user WHERE id=?", Integer.class, user)).isZero();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document WHERE id=?", Integer.class, document)).isZero();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM knowledge_document_version WHERE document_id=?", Integer.class, document)).isZero();
            assertThat(storage.countLocation(current)).isZero(); assertThat(storage.countLocation(history)).isZero();
            assertThat(storage.countUserPrefix(user)).isZero();
            assertThat(Files.exists(root.resolve(Long.toString(user)))).isFalse();
            assertThat(Files.exists(avatar)).isFalse();
            assertThat(storage.countLocation(retained)).isPositive();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM user WHERE id=?", Integer.class, keep)).isEqualTo(1);
        }
        public void close() { leases.close(); }
    }

    @Test void remoteMissingCurrentAndHistoricalCachesAreDeletedAndOtherTenantSurvives() throws Exception {
        try (var f = new Fixture(true, "session_cleanup")) {
            for (String location : new String[] {f.current, f.history}) {
                client().removeObject(RemoveObjectArgs.builder().bucket("mneme").object(location.substring("s3://mneme/".length())).build());
                assertThat(f.storage.countLocation(location)).isEqualTo(1);
            }
            f.run(); f.completed();
        }
    }

    @Test void residualVersionReadbackKeepsManifestUntilRetry() throws Exception {
        try (var f = new Fixture(false, "session_cleanup")) {
            doReturn(1L).when(f.storage).countLocation(f.history);
            f.run(); f.retained(); verify(f.users, never()).deleteById(f.user);
            doCallRealMethod().when(f.storage).countLocation(f.history);
            f.retry(); f.completed();
        }
    }

    @Test void prefixResidualAndUnavailableReadCannotBecomeSuccessfulDeletion() throws Exception {
        try (var f = new Fixture(true, "session_cleanup")) {
            doReturn(1L).when(f.storage).countUserPrefix(f.user);
            f.run(); f.retained();
            doThrow(new java.io.IOException("storage unavailable")).when(f.storage).countUserPrefix(f.user);
            f.retry(); f.retained(); verify(f.users, never()).deleteById(f.user);
            doCallRealMethod().when(f.storage).countUserPrefix(f.user);
            f.retry(); f.completed();
        }
    }

    @Test void oldAvatarCheckpointStillReplaysAndVerifiesFiles() throws Exception {
        try (var f = new Fixture(true, "avatar_cleanup")) {
            f.run(); f.completed();
        }
    }

    @Test void silentSqlDeleteDoesNotCompleteAndRetryManifestIsRetained() throws Exception {
        try (var f = new Fixture(false, "session_cleanup")) {
            doReturn(0).when(f.users).deleteById(f.user);
            f.run(); f.retained();
            f.realDelete(); f.retry(); f.completed();
        }
    }

    @Test void bothCurrentAndHistoryManifestsArePaginatedBeyondOneBatch() throws Exception {
        try (var f = new Fixture(false, "session_cleanup")) {
            for (int i = 0; i < 260; i++) {
                String current = f.file(f.user, f.kb, "page-current-" + i);
                String history = f.file(f.user, f.kb, "page-history-" + i);
                f.doc(f.kb, current);
                jdbc.update("INSERT INTO knowledge_document_version(document_id,version_number,file_name,file_path,sha256,size_bytes) VALUES(?,?,'QA',?,?,2)", f.document, i + 2, history, "b".repeat(64));
            }
            f.run(); f.completed();
            verify(f.storage, atLeastOnce()).delete(root.resolve(f.user + "/" + f.kb + "/page-current-259").toString());
            verify(f.storage, atLeastOnce()).delete(root.resolve(f.user + "/" + f.kb + "/page-history-259").toString());
        }
    }
}

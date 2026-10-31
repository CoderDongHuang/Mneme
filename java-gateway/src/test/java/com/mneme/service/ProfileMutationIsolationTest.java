package com.mneme.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.PasswordChangeRequest;
import com.mneme.mapper.UserMapper;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.RestTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.io.*;
import java.nio.file.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@Testcontainers(disabledWithoutDocker = true)
class ProfileMutationIsolationTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("profile-isolation-test")
        // Fault-injection triggers belong only to this disposable test database.
        .withCommand("--log-bin-trust-function-creators=1");
    static JdbcTemplate jdbc;
    static UserMapper users;
    static DataSourceTransactionManager manager;
    static final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
    static final String OLD = "Initial!123", NEXT = "Changed!123";
    @TempDir Path root;
    ProfileService service;
    AccountDeletionService deletions;
    ExecutorService pool;
    TaskLeaseService leases;
    Path oldAvatar;

    @BeforeAll static void database() throws Exception {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(source);
        manager = new DataSourceTransactionManager(source);
        var config = new MybatisConfiguration(); config.setMapUnderscoreToCamelCase(true); config.addMapper(UserMapper.class);
        var factory = new MybatisSqlSessionFactoryBean(); factory.setDataSource(source); factory.setConfiguration(config);
        users = new SqlSessionTemplate(factory.getObject()).getMapper(UserMapper.class);
    }

    @SuppressWarnings("unchecked")
    static <T> T transactional(T target) {
        var proxy = new ProxyFactory(target); proxy.setProxyTargetClass(true);
        proxy.addAdvice(new TransactionInterceptor(manager, new AnnotationTransactionAttributeSource()));
        return (T) proxy.getProxy();
    }

    @BeforeEach void setup() throws Exception {
        jdbc.execute("DROP TRIGGER IF EXISTS reject_avatar");
        jdbc.execute("DROP TRIGGER IF EXISTS reject_revocation");
        jdbc.update("DELETE FROM user"); jdbc.update("DELETE FROM account_deletion_task");
        jdbc.update("INSERT INTO user(id,username,password_hash,email,email_verified_at) VALUES(1,'profile',?,'initial@example.test',UTC_TIMESTAMP())", encoder.encode(OLD));
        jdbc.update("INSERT INTO user(id,username,password_hash) VALUES(2,'other',?)", encoder.encode(OLD));
        oldAvatar = root.resolve("1-old.png"); Files.writeString(oldAvatar, "previous");
        jdbc.update("UPDATE user SET avatar_path=? WHERE id=1", oldAvatar.toString());
        var sessions = new AuthSessionService(jdbc);
        sessions.create(1L, java.time.LocalDateTime.now().plusDays(1), false);
        sessions.create(2L, java.time.LocalDateTime.now().plusDays(1), false);
        leases = new TaskLeaseService(jdbc, manager, 10);
        deletions = transactional(new AccountDeletionService(users, jdbc, new RestTemplate(),
            new OperationLogService(jdbc, new ObjectMapper()), "http://unused", root.toString(), 3,
            mock(ObjectStorageService.class), leases));
        service = transactional(new ProfileService(users, jdbc, deletions, sessions,
            new EmailVerificationService(jdbc, mock(PasswordResetDelivery.class)), root.toString(), "http://unused", root.toString()));
        pool = Executors.newFixedThreadPool(3);
    }

    @AfterEach void cleanup() {
        pool.shutdownNow(); leases.close();
        jdbc.execute("DROP TRIGGER IF EXISTS reject_avatar");
        jdbc.execute("DROP TRIGGER IF EXISTS reject_revocation");
    }

    static class Upload extends MockMultipartFile {
        final AtomicBoolean closed = new AtomicBoolean();
        final CountDownLatch copying = new CountDownLatch(1), release = new CountDownLatch(1);
        final boolean block, fail;
        Upload(boolean block, boolean fail) { super("file", "avatar.png", "image/png", new byte[]{1, 2, 3}); this.block = block; this.fail = fail; }
        @Override public InputStream getInputStream() throws IOException {
            return new ByteArrayInputStream(getBytes()) {
                @Override public synchronized int read(byte[] bytes, int offset, int length) {
                    copying.countDown();
                    if (block) try { if (!release.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("test upload deadline"); }
                    catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IllegalStateException(error); }
                    return super.read(bytes, offset, length);
                }
                @Override public void close() throws IOException { closed.set(true); super.close(); }
                @Override public long transferTo(OutputStream output) throws IOException {
                    if (fail) { copying.countDown(); output.write(1); throw new IOException("injected partial copy"); }
                    byte[] bytes = new byte[1024]; long size = 0; int count;
                    while ((count = read(bytes, 0, bytes.length)) != -1) { output.write(bytes, 0, count); size += count; }
                    return size;
                }
            };
        }
    }

    @Test void slowUploadCannotUndoPasswordEmailRoleOrSessionRevocation() throws Exception {
        var file = new Upload(true, false);
        var upload = pool.submit(() -> service.uploadAvatar(1L, file));
        assertThat(file.copying.await(5, TimeUnit.SECONDS)).isTrue();
        try {
            service.changePassword(1L, new PasswordChangeRequest(OLD, NEXT));
            new TransactionTemplate(manager).execute(status -> {
                jdbc.queryForObject("SELECT id FROM user WHERE id=1 FOR UPDATE", Long.class);
                jdbc.update("UPDATE user SET role='admin',nickname='latest',email='latest@example.test',email_verified_at=NULL WHERE id=1");
                return null;
            });
        } finally { file.release.countDown(); }
        assertThat(upload.get(10, TimeUnit.SECONDS)).containsEntry("nickname", "latest").containsEntry("email", "latest@example.test").containsEntry("role", "admin").containsEntry("emailVerified", false);
        assertThat(encoder.matches(NEXT, users.selectById(1L).getPasswordHash())).isTrue();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM auth_session WHERE user_id=1 AND revoked_at IS NULL", Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM auth_session WHERE user_id=2 AND revoked_at IS NULL", Long.class)).isEqualTo(1L);
        assertThat(file.closed).isTrue(); assertThat(oldAvatar).doesNotExist();
        assertThat(Path.of(users.selectById(1L).getAvatarPath())).exists();
    }

    @Test void deletionDuringCopyWinsAndRollbackRemovesOnlyNewAvatar() throws Exception {
        var file = new Upload(true, false);
        var upload = pool.submit(() -> service.uploadAvatar(1L, file));
        assertThat(file.copying.await(5, TimeUnit.SECONDS)).isTrue();
        try { assertThat(deletions.enqueue(1L)).isNotBlank(); }
        finally { file.release.countDown(); }
        assertThatThrownBy(() -> upload.get(10, TimeUnit.SECONDS)).hasCauseInstanceOf(IllegalArgumentException.class);
        assertThat(users.selectById(1L).getStatus()).isEqualTo("deleting");
        assertThat(users.selectById(1L).getAvatarPath()).isEqualTo(oldAvatar.toString());
        assertThat(file.closed).isTrue(); assertOnlyOldAvatar();
    }

    @Test void concurrentUploadsKeepExactlyTheCommittedCurrentFile() throws Exception {
        var first = new Upload(true, false); var second = new Upload(false, false);
        var waiting = pool.submit(() -> service.uploadAvatar(1L, first));
        assertThat(first.copying.await(5, TimeUnit.SECONDS)).isTrue();
        try { service.uploadAvatar(1L, second); }
        finally { first.release.countDown(); }
        waiting.get(10, TimeUnit.SECONDS);
        try (var paths = Files.list(root)) { assertThat(paths.toList()).containsExactly(Path.of(users.selectById(1L).getAvatarPath())); }
        assertThat(first.closed).isTrue(); assertThat(second.closed).isTrue();
        assertThat(users.selectById(2L).getAvatarPath()).isNull();
    }

    @Test void passwordChecksLatestHashAfterWaitingForTheUserLock() throws Exception {
        var locked = new CountDownLatch(1); var release = new CountDownLatch(1);
        var reset = pool.submit(() -> new TransactionTemplate(manager).execute(status -> {
            jdbc.queryForObject("SELECT id FROM user WHERE id=1 FOR UPDATE", Long.class);
            jdbc.update("UPDATE user SET password_hash=? WHERE id=1", encoder.encode(NEXT));
            locked.countDown();
            try { assertThat(release.await(10, TimeUnit.SECONDS)).isTrue(); }
            catch (InterruptedException error) { throw new IllegalStateException(error); }
            return null;
        }));
        assertThat(locked.await(5, TimeUnit.SECONDS)).isTrue();
        var change = pool.submit(() -> service.changePassword(1L, new PasswordChangeRequest(OLD, "Stale!123")));
        try { assertThatThrownBy(() -> change.get(250, TimeUnit.MILLISECONDS)).isInstanceOf(TimeoutException.class); }
        finally { release.countDown(); }
        reset.get(10, TimeUnit.SECONDS);
        assertThatThrownBy(() -> change.get(10, TimeUnit.SECONDS)).hasCauseInstanceOf(IllegalArgumentException.class);
        assertThat(encoder.matches(NEXT, users.selectById(1L).getPasswordHash())).isTrue();
    }

    @Test void sessionRevocationFailureRollsBackPassword() {
        jdbc.execute("CREATE TRIGGER reject_revocation BEFORE UPDATE ON auth_session FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='injected revocation failure'");
        assertThatThrownBy(() -> service.changePassword(1L, new PasswordChangeRequest(OLD, NEXT))).isInstanceOf(RuntimeException.class);
        assertThat(encoder.matches(OLD, users.selectById(1L).getPasswordHash())).isTrue();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM auth_session WHERE user_id=1 AND revoked_at IS NULL", Long.class)).isEqualTo(1L);
    }

    @Test void avatarDatabaseFailureClosesInputAndRemovesUncommittedFile() {
        jdbc.execute("CREATE TRIGGER reject_avatar BEFORE UPDATE ON user FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='injected avatar failure'");
        var file = new Upload(false, false);
        assertThatThrownBy(() -> service.uploadAvatar(1L, file)).isInstanceOf(RuntimeException.class);
        assertThat(file.closed).isTrue(); assertOnlyOldAvatar();
        assertThat(users.selectById(1L).getAvatarPath()).isEqualTo(oldAvatar.toString());
    }

    @Test void partialCopyFailureClosesInputAndRemovesPartialFile() {
        var file = new Upload(false, true);
        assertThatThrownBy(() -> service.uploadAvatar(1L, file)).isInstanceOf(IOException.class);
        assertThat(file.closed).isTrue(); assertOnlyOldAvatar();
    }

    @Test void inactiveAccountCannotReadProfileUploadOrChangePassword() {
        jdbc.update("UPDATE user SET status='deletion_failed' WHERE id=1");
        var file = new Upload(false, false);
        assertThatThrownBy(() -> service.profile(1L)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.uploadAvatar(1L, file)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.changePassword(1L, new PasswordChangeRequest(OLD, NEXT))).isInstanceOf(IllegalArgumentException.class);
        assertThat(file.copying.getCount()).isEqualTo(1); assertOnlyOldAvatar();
    }

    @Test void concurrentPasswordChangesUsingSameOldPasswordHaveOneWinner() throws Exception {
        var start = new CountDownLatch(1);
        var first = pool.submit(() -> change(start, NEXT));
        var second = pool.submit(() -> change(start, "Alternative!123"));
        start.countDown();
        assertThat(first.get(10, TimeUnit.SECONDS) ^ second.get(10, TimeUnit.SECONDS)).isTrue();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM auth_session WHERE user_id=1 AND revoked_at IS NULL", Long.class)).isZero();
    }

    boolean change(CountDownLatch start, String password) throws InterruptedException {
        start.await();
        try { service.changePassword(1L, new PasswordChangeRequest(OLD, password)); return true; }
        catch (IllegalArgumentException lost) { return false; }
    }
    void assertOnlyOldAvatar() {
        try (var paths = Files.list(root)) { assertThat(paths.toList()).containsExactly(oldAvatar); }
        catch (IOException error) { throw new UncheckedIOException(error); }
    }
}

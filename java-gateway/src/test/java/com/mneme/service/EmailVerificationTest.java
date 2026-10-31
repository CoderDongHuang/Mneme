package com.mneme.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.spring.MybatisSqlSessionFactoryBean;
import com.mneme.entity.User;
import com.mneme.mapper.PasswordResetTokenMapper;
import com.mneme.mapper.UserMapper;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.mockito.AdditionalAnswers.delegatesTo;

/** Real MySQL, Flyway, MyBatis field policies, transactions and two independent service instances. */
@Testcontainers(disabledWithoutDocker = true)
class EmailVerificationTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("email-test-password");
    static JdbcTemplate jdbc;
    static DataSourceTransactionManager manager;
    static UserMapper users;
    static PasswordResetTokenMapper resets;

    @BeforeAll static void database() throws Exception {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        jdbc = new JdbcTemplate(source); manager = new DataSourceTransactionManager(source);
        Flyway.configure().dataSource(source).locations("classpath:db/migration").target("28").load().migrate();
        jdbc.update("INSERT INTO user(username,password_hash,email) VALUES('legacy-email','hash','legacy@example.test')");
        long legacy = jdbc.queryForObject("SELECT id FROM user WHERE username='legacy-email'", Long.class);
        jdbc.update("INSERT INTO password_reset_token(user_id,token_hash,expires_at) VALUES(?,?,TIMESTAMPADD(MINUTE,15,UTC_TIMESTAMP()))", legacy, "0".repeat(64));
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM password_reset_token", Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT email_verified_at FROM user WHERE id=?", Object.class, legacy)).isNull();
        var config = new MybatisConfiguration(); config.setMapUnderscoreToCamelCase(true);
        config.addMapper(UserMapper.class); config.addMapper(PasswordResetTokenMapper.class);
        var factory = new MybatisSqlSessionFactoryBean(); factory.setDataSource(source); factory.setConfiguration(config);
        var session = new SqlSessionTemplate(factory.getObject());
        users = session.getMapper(UserMapper.class); resets = session.getMapper(PasswordResetTokenMapper.class);
    }

    @SuppressWarnings("unchecked") static <T> T transactional(T target) {
        var proxy = new ProxyFactory(target);
        proxy.addAdvice(new TransactionInterceptor(manager, new AnnotationTransactionAttributeSource()));
        return (T) proxy.getProxy();
    }

    final class Fixture implements AutoCloseable {
        final String name = "verify_" + UUID.randomUUID().toString().replace("-", "");
        final String email = name + "@example.test";
        final long id;
        final PasswordResetDelivery mail = mock(PasswordResetDelivery.class);
        final AtomicReference<String> delivered = new AtomicReference<>();
        final AuthSessionService sessions = mock(AuthSessionService.class);
        final EmailVerificationService verify = transactional(new EmailVerificationService(jdbc, mail));
        final AuthService auth = transactional(new AuthService(users, resets, sessions));
        Fixture() {
            jdbc.update("INSERT INTO user(username,password_hash,email) VALUES(?,'old-hash',?)", name, email);
            id = jdbc.queryForObject("SELECT id FROM user WHERE username=?", Long.class, name);
            doAnswer(call -> { delivered.set(call.getArgument(1)); return null; }).when(mail).sendVerification(eq(email), anyString());
        }
        String request() { verify.request(id, email); return delivered.get(); }
        void verified() { verify.confirm(id, request()); }
        long count(String table) { return jdbc.queryForObject("SELECT COUNT(*) FROM " + table + " WHERE user_id=?", Long.class, id); }
        void age() { jdbc.update("UPDATE email_verification_token SET created_at=TIMESTAMPADD(SECOND,-61,UTC_TIMESTAMP(6)) WHERE user_id=?", id); }
        public void close() { jdbc.update("DELETE FROM user WHERE id=?", id); }
    }

    @Test void ownershipIsRequiredForBothIssuingAndConsumingResetTokens() {
        try (var f = new Fixture()) {
            assertThatThrownBy(() -> f.auth.issuePasswordResetToken(f.name, f.email)).isInstanceOf(IllegalArgumentException.class);
            assertThat(f.count("password_reset_token")).isZero();
            // Even an old or manually retained reset token cannot bypass ownership checks.
            jdbc.update("INSERT INTO password_reset_token(user_id,token_hash,expires_at) VALUES(?,?,TIMESTAMPADD(MINUTE,15,UTC_TIMESTAMP()))",
                f.id, EmailVerificationService.hash("legacy-unverified-reset"));
            assertThatThrownBy(() -> f.auth.confirmPasswordReset("legacy-unverified-reset", "must-not-change"))
                .isInstanceOf(IllegalArgumentException.class);
            assertThat(users.selectById(f.id).getPasswordHash()).isEqualTo("old-hash");
            String token = f.request();
            assertThat(token).hasSize(64);
            assertThat(jdbc.queryForObject("SELECT token_hash FROM email_verification_token WHERE user_id=?", String.class, f.id))
                .isEqualTo(EmailVerificationService.hash(token)).isNotEqualTo(token);
            assertThatThrownBy(() -> f.verify.confirm(f.id, "0".repeat(64))).isInstanceOf(IllegalArgumentException.class);
            f.verify.confirm(f.id, token);
            assertThat(f.count("email_verification_token")).isZero();
            assertThatThrownBy(() -> f.verify.confirm(f.id, token)).isInstanceOf(IllegalArgumentException.class);
            String reset = f.auth.issuePasswordResetToken(f.name, f.email);
            f.auth.confirmPasswordReset(reset, "NewPassword!123");
            assertThat(new org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder().matches("NewPassword!123", users.selectById(f.id).getPasswordHash())).isTrue();
            verify(f.sessions).revokeAll(f.id);
            assertThatThrownBy(() -> f.auth.confirmPasswordReset(reset, "OtherPassword!123")).isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test void expiryResendCooldownAndDeliveryFailureNeverVerifyOrExposeRawToken() {
        try (var f = new Fixture()) {
            String first = f.request();
            assertThatThrownBy(f::request).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
            verify(f.mail, times(1)).sendVerification(eq(f.email), anyString());
            f.age();
            doThrow(new com.mneme.exception.MailDeliveryException("mail unavailable")).when(f.mail).sendVerification(eq(f.email), anyString());
            assertThatThrownBy(f::request).isInstanceOf(com.mneme.exception.MailDeliveryException.class);
            assertThat(jdbc.queryForObject("SELECT token_hash FROM email_verification_token WHERE user_id=?", String.class, f.id))
                .isEqualTo(EmailVerificationService.hash(first));
            doAnswer(call -> { f.delivered.set(call.getArgument(1)); return null; }).when(f.mail).sendVerification(eq(f.email), anyString());
            String second = f.request();
            assertThatThrownBy(() -> f.verify.confirm(f.id, first)).isInstanceOf(IllegalArgumentException.class);
            jdbc.update("UPDATE email_verification_token SET expires_at=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE user_id=?", f.id);
            assertThatThrownBy(() -> f.verify.confirm(f.id, second)).isInstanceOf(IllegalArgumentException.class);
            assertThat(users.selectById(f.id).getEmailVerifiedAt()).isNull();
        }
    }

    @Test void emailChangeAndRemovalInvalidateBothTokenTypesAndPreventAwayBackReplay() {
        try (var f = new Fixture()) {
            String verification = f.request(); f.verify.confirm(f.id, verification);
            String reset = f.auth.issuePasswordResetToken(f.name, f.email);
            f.verify.updateProfile(f.id, "nickname", "  " + f.email.toUpperCase(java.util.Locale.ROOT) + "  ");
            assertThat(users.selectById(f.id).getEmailVerifiedAt()).isNotNull();
            assertThat(f.count("password_reset_token")).isOne();
            f.verify.updateProfile(f.id, "changed", "new-" + f.email);
            assertThat(users.selectById(f.id).getEmailVerifiedAt()).isNull();
            assertThat(f.count("password_reset_token")).isZero();
            f.verify.updateProfile(f.id, "back", f.email);
            assertThatThrownBy(() -> f.verify.confirm(f.id, verification)).isInstanceOf(IllegalArgumentException.class);
            assertThatThrownBy(() -> f.auth.confirmPasswordReset(reset, "NewPassword!123")).isInstanceOf(IllegalArgumentException.class);
            f.request();
            f.verify.updateProfile(f.id, "removed", "");
            assertThat(users.selectById(f.id).getEmail()).isNull();
            assertThat(f.count("email_verification_token")).isZero();
        }
    }

    @Test void aTokenCannotVerifyAnotherTenantOrUnsavedEmailAndDuplicateEmailRollsBack() {
        try (var f = new Fixture(); var other = new Fixture()) {
            String token = f.request();
            assertThatThrownBy(() -> other.verify.confirm(other.id, token)).isInstanceOf(IllegalArgumentException.class);
            assertThatThrownBy(() -> f.verify.request(f.id, other.email)).isInstanceOf(IllegalArgumentException.class);
            other.verified();
            assertThatThrownBy(() -> other.verify.updateProfile(other.id, "must rollback", f.email))
                .isInstanceOf(IllegalArgumentException.class).hasMessage("该邮箱已被绑定");
            assertThat(users.selectById(other.id).getEmail()).isEqualTo(other.email);
            assertThat(users.selectById(other.id).getEmailVerifiedAt()).isNotNull();
            assertThat(f.count("email_verification_token")).isOne();
        }
    }

    @Test void twoWorkersConsumeVerificationOnlyOnce() throws Exception {
        try (var f = new Fixture()) {
            String token = f.request();
            var second = transactional(new EmailVerificationService(jdbc, f.mail));
            var pool = Executors.newFixedThreadPool(2); var start = new CountDownLatch(1);
            try {
                var jobs = java.util.List.of(f.verify, second).stream().map(service -> pool.submit(() -> {
                    start.await();
                    try { service.confirm(f.id, token); return true; } catch (IllegalArgumentException invalid) { return false; }
                })).toList();
                start.countDown();
                int successes = 0;
                for (var job : jobs) if (job.get(10, TimeUnit.SECONDS)) successes++;
                assertThat(successes).isOne();
            } finally { pool.shutdownNow(); }
        }
    }

    @Test void anEmailChangeWinsAgainstAlreadyReadResetTokenAndStaleEntityCannotRestoreIt() throws Exception {
        try (var f = new Fixture()) {
            f.verified(); String reset = f.auth.issuePasswordResetToken(f.name, f.email);
            User stale = users.selectById(f.id);
            var pool = Executors.newSingleThreadExecutor(); var readToken = new CountDownLatch(1);
            var observedResets = mock(PasswordResetTokenMapper.class, delegatesTo(resets));
            doAnswer(call -> {
                var record = resets.selectOne(call.getArgument(0));
                assertThat(record).isNotNull();
                readToken.countDown();
                return record;
            }).when(observedResets).selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class));
            var resetWorker = transactional(new AuthService(users, observedResets, f.sessions));
            final AtomicReference<Future<Boolean>> job = new AtomicReference<>();
            try {
                new TransactionTemplate(manager).execute(status -> {
                    f.verify.updateProfile(f.id, "changed", "new-" + f.email);
                    job.set(pool.submit(() -> {
                        try { resetWorker.confirmPasswordReset(reset, "must-not-change"); return true; }
                        catch (IllegalArgumentException invalid) { return false; }
                    }));
                    try { assertThat(readToken.await(5, TimeUnit.SECONDS)).isTrue(); }
                    catch (InterruptedException e) { throw new IllegalStateException(e); }
                    return null;
                });
                assertThat(job.get().get(10, TimeUnit.SECONDS)).isFalse();
                stale.setAvatarPath("new-avatar"); users.updateById(stale);
                assertThat(users.selectById(f.id).getEmail()).isEqualTo("new-" + f.email);
                assertThat(users.selectById(f.id).getEmailVerifiedAt()).isNull();
                assertThat(users.selectById(f.id).getPasswordHash()).isEqualTo("old-hash");
                verifyNoInteractions(f.sessions);
            } finally { pool.shutdownNow(); }
        }
    }

    @Test void deletingUserCannotRequestOrConfirmAndCascadesVerificationManifest() {
        try (var f = new Fixture()) {
            String token = f.request();
            jdbc.update("UPDATE user SET status='deleting' WHERE id=?", f.id);
            assertThatThrownBy(() -> f.verify.confirm(f.id, token)).isInstanceOf(IllegalArgumentException.class);
            assertThatThrownBy(f::request).isInstanceOf(IllegalArgumentException.class);
            jdbc.update("DELETE FROM user WHERE id=?", f.id);
            assertThat(f.count("email_verification_token")).isZero();
        }
    }
}

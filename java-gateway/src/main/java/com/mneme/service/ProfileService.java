package com.mneme.service;

import com.mneme.dto.PasswordChangeRequest;
import com.mneme.dto.ProfileUpdateRequest;
import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

@Service
public class ProfileService {
    private static final Logger log = LoggerFactory.getLogger(ProfileService.class);
    private static final Set<String> IMAGE_TYPES = Set.of("image/jpeg", "image/png", "image/webp");
    private final UserMapper users;
    private final JdbcTemplate jdbc;
    private final AccountDeletionService accountDeletions;
    private final AuthSessionService sessions;
    private final EmailVerificationService emailVerification;
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
    private final Path avatarRoot;

    public ProfileService(
        UserMapper users,
        JdbcTemplate jdbc,
        AccountDeletionService accountDeletions,
        AuthSessionService sessions,
        EmailVerificationService emailVerification,
        @Value("${mneme.avatar-storage-path:${mneme.file-storage-path:../data/files}/avatars}") String avatarStoragePath,
        @Value("${mneme.python-agent-url}") String ignoredPythonAgentUrl,
        @Value("${mneme.file-storage-path:../data/files}") String ignoredFileStoragePath
    ) {
        this.users = users;
        this.jdbc = jdbc;
        this.accountDeletions = accountDeletions;
        this.sessions = sessions;
        this.emailVerification = emailVerification;
        this.avatarRoot = Path.of(avatarStoragePath).toAbsolutePath().normalize();
    }

    public Map<String, Object> profile(Long userId) {
        return profile(requireUser(userId));
    }

    private Map<String, Object> profile(User user) {
        return Map.of(
            "userId", user.getId(), "username", user.getUsername(),
            "nickname", value(user.getNickname()), "email", value(user.getEmail()), "role", user.getRole(),
            "emailVerified", user.getEmail() != null && user.getEmailVerifiedAt() != null,
            "hasAvatar", user.getAvatarPath() != null && Files.isRegularFile(Path.of(user.getAvatarPath()))
        );
    }

    public java.util.List<Map<String,Object>> sessions(Long userId) { return sessions.list(userId); }
    public void revokeSession(Long userId, String sessionId) { sessions.revokeOwned(userId, sessionId); }

    public Map<String, Object> update(Long userId, ProfileUpdateRequest request) {
        emailVerification.updateProfile(userId, normalize(request.nickname()), request.email());
        return profile(userId);
    }

    @Transactional(rollbackFor = IOException.class)
    public Map<String, Object> uploadAvatar(Long userId, MultipartFile file) throws IOException {
        if (file.isEmpty() || file.getSize() > 5 * 1024 * 1024) throw new IllegalArgumentException("头像大小必须在 5MB 以内");
        if (!IMAGE_TYPES.contains(file.getContentType())) throw new IllegalArgumentException("头像仅支持 JPG、PNG 或 WebP");
        Files.createDirectories(avatarRoot);
        String extension = switch (file.getContentType()) { case "image/png" -> ".png"; case "image/webp" -> ".webp"; default -> ".jpg"; };
        Path target = avatarRoot.resolve(userId + "-" + UUID.randomUUID() + extension).normalize();
        if (!target.startsWith(avatarRoot)) throw new IllegalArgumentException("头像路径无效");
        requireUser(userId);
        // Rollback includes failed copies and an account deleted during upload.
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCompletion(int status) {
                if (status != STATUS_COMMITTED) deleteAvatarFile(target);
            }
        });
        try (var input = file.getInputStream()) {
            Files.copy(input, target, StandardCopyOption.REPLACE_EXISTING);
        }
        // Serialize with deletion, reset and other uploads, reading the latest row.
        // No user row lock is held while receiving/copying the upload.
        User user = lockUser(userId);
        String previous = user.getAvatarPath();
        jdbc.update("UPDATE user SET avatar_path=? WHERE id=?", target.toString(), userId);
        user.setAvatarPath(target.toString());
        if (previous != null) TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() { deleteAvatarFile(Path.of(previous)); }
        });
        return profile(user);
    }

    public byte[] avatar(Long userId) throws IOException {
        User user = requireUser(userId);
        if (user.getAvatarPath() == null) throw new IllegalArgumentException("尚未设置头像");
        return Files.readAllBytes(Path.of(user.getAvatarPath()));
    }

    public String avatarType(Long userId) throws IOException {
        User user = requireUser(userId);
        if (user.getAvatarPath() == null) return "image/jpeg";
        String type = Files.probeContentType(Path.of(user.getAvatarPath()));
        return type == null ? "image/jpeg" : type;
    }

    @Transactional
    public void changePassword(Long userId, PasswordChangeRequest request) {
        User user = lockUser(userId);
        if (!encoder.matches(request.currentPassword(), user.getPasswordHash())) throw new IllegalArgumentException("当前密码不正确");
        jdbc.update("UPDATE user SET password_hash=? WHERE id=?", encoder.encode(request.newPassword()), userId);
        sessions.revokeAll(userId);
    }

    public String deleteAccount(Long userId) {
        return accountDeletions.enqueue(userId);
    }

    private User requireUser(Long id) {
        User user = users.selectById(id);
        requireActive(user);
        return user;
    }
    private User lockUser(Long id) {
        User user = users.selectOne(new LambdaQueryWrapper<User>().eq(User::getId, id).last("FOR UPDATE"));
        requireActive(user);
        return user;
    }
    private void requireActive(User user) {
        if (user == null || !"active".equals(user.getStatus())) throw new IllegalArgumentException("账号当前不可用");
    }
    private void deleteAvatarFile(Path path) {
        Path normalized = path.toAbsolutePath().normalize();
        if (!normalized.startsWith(avatarRoot) || normalized.equals(avatarRoot)) return;
        try { Files.deleteIfExists(normalized); }
        catch (IOException error) { log.warn("头像文件清理失败: errorType={}", error.getClass().getSimpleName()); }
    }
    private String normalize(String value) { return value == null ? "" : value.trim(); }
    private String value(String value) { return value == null ? "" : value; }
}

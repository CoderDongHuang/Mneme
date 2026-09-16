package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.mneme.dto.PasswordChangeRequest;
import com.mneme.dto.ProfileUpdateRequest;
import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.client.RestTemplate;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

@Service
public class ProfileService {
    private static final Set<String> IMAGE_TYPES = Set.of("image/jpeg", "image/png", "image/webp");
    private final UserMapper users;
    private final RestTemplate restTemplate;
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
    private final Path avatarRoot;
    private final String pythonAgentUrl;
    private final Path fileRoot;

    @Autowired(required = false)
    private OperationLogService operationLog;

    public ProfileService(
        UserMapper users,
        RestTemplate restTemplate,
        @Value("${mneme.avatar-storage-path:${mneme.file-storage-path:../data/files}/avatars}") String avatarStoragePath,
        @Value("${mneme.python-agent-url}") String pythonAgentUrl,
        @Value("${mneme.file-storage-path:../data/files}") String fileStoragePath
    ) {
        this.users = users;
        this.restTemplate = restTemplate;
        this.avatarRoot = Path.of(avatarStoragePath).toAbsolutePath().normalize();
        this.pythonAgentUrl = pythonAgentUrl;
        this.fileRoot = Path.of(fileStoragePath).toAbsolutePath().normalize();
    }

    public Map<String, Object> profile(Long userId) {
        User user = requireUser(userId);
        return Map.of(
            "userId", user.getId(), "username", user.getUsername(),
            "nickname", value(user.getNickname()), "email", value(user.getEmail()),
            "hasAvatar", user.getAvatarPath() != null && Files.isRegularFile(Path.of(user.getAvatarPath()))
        );
    }

    public Map<String, Object> update(Long userId, ProfileUpdateRequest request) {
        User user = requireUser(userId);
        String email = normalize(request.email());
        if (!email.isBlank()) {
            User owner = users.selectOne(new LambdaQueryWrapper<User>().eq(User::getEmail, email));
            if (owner != null && !owner.getId().equals(userId)) throw new IllegalArgumentException("该邮箱已被绑定");
        }
        user.setNickname(normalize(request.nickname()));
        user.setEmail(email.isBlank() ? null : email);
        users.updateById(user);
        return profile(userId);
    }

    public Map<String, Object> uploadAvatar(Long userId, MultipartFile file) throws IOException {
        if (file.isEmpty() || file.getSize() > 5 * 1024 * 1024) throw new IllegalArgumentException("头像大小必须在 5MB 以内");
        if (!IMAGE_TYPES.contains(file.getContentType())) throw new IllegalArgumentException("头像仅支持 JPG、PNG 或 WebP");
        Files.createDirectories(avatarRoot);
        String extension = switch (file.getContentType()) { case "image/png" -> ".png"; case "image/webp" -> ".webp"; default -> ".jpg"; };
        Path target = avatarRoot.resolve(userId + "-" + UUID.randomUUID() + extension).normalize();
        if (!target.startsWith(avatarRoot)) throw new IllegalArgumentException("头像路径无效");
        User user = requireUser(userId);
        String previous = user.getAvatarPath();
        Files.copy(file.getInputStream(), target, StandardCopyOption.REPLACE_EXISTING);
        user.setAvatarPath(target.toString());
        users.updateById(user);
        if (previous != null) Files.deleteIfExists(Path.of(previous));
        return profile(userId);
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

    public void changePassword(Long userId, PasswordChangeRequest request) {
        User user = requireUser(userId);
        if (!encoder.matches(request.currentPassword(), user.getPasswordHash())) throw new IllegalArgumentException("当前密码不正确");
        user.setPasswordHash(encoder.encode(request.newPassword()));
        users.updateById(user);
    }

    public void resetPassword(String username, String email, String password) {
        User user = users.selectOne(new LambdaQueryWrapper<User>()
            .eq(User::getUsername, username.trim()).eq(User::getEmail, email.trim().toLowerCase()));
        if (user == null) throw new IllegalArgumentException("用户名与绑定邮箱不匹配");
        user.setPasswordHash(encoder.encode(password));
        users.updateById(user);
    }

    public void deleteAccount(Long userId) throws IOException {
        User user = users.selectById(userId);
        if (user == null) return;
        String operationId = operationLog == null ? UUID.randomUUID().toString() : operationLog.newOperationId();
        String id = userId.toString();
        record(operationId, userId, "account_delete", id, "start", "started", Map.of("username", user.getUsername()), null);
        try {
            restTemplate.delete(pythonAgentUrl + "/api/v1/knowledge/admin/user/" + id);
            record(operationId, userId, "account_delete", id, "knowledge_cleanup", "completed", Map.of(), null);
            restTemplate.delete(pythonAgentUrl + "/api/v1/memory/admin/user/" + id);
            record(operationId, userId, "account_delete", id, "memory_cleanup", "completed", Map.of(), null);
            restTemplate.delete(pythonAgentUrl + "/api/v1/admin/user/" + id);
            record(operationId, userId, "account_delete", id, "session_cleanup", "completed", Map.of(), null);
            deleteDirectory(fileRoot.resolve(id).normalize(), fileRoot);
            record(operationId, userId, "account_delete", id, "file_cleanup", "completed", Map.of(), null);
            if (user.getAvatarPath() != null) Files.deleteIfExists(Path.of(user.getAvatarPath()));
            users.deleteById(user.getId());
            record(operationId, userId, "account_delete", id, "user_delete", "completed", Map.of(), null);
        } catch (IOException | RuntimeException error) {
            record(operationId, userId, "account_delete", id, "failed", "failed", Map.of(), error);
            throw error;
        }
    }

    private void record(
        String operationId,
        Long userId,
        String type,
        String aggregateId,
        String step,
        String status,
        Map<String, ?> payload,
        Exception error
    ) {
        if (operationLog != null) {
            operationLog.record(operationId, userId, type, aggregateId, step, status, payload, error);
        }
    }

    private void deleteDirectory(Path directory, Path root) throws IOException {
        if (!directory.startsWith(root) || !Files.exists(directory)) return;
        try (var paths = Files.walk(directory)) {
            paths.sorted(java.util.Comparator.reverseOrder()).forEach(path -> {
                try { Files.deleteIfExists(path); }
                catch (IOException error) { throw new IllegalStateException(error); }
            });
        }
    }

    private User requireUser(Long id) {
        User user = users.selectById(id);
        if (user == null) throw new IllegalArgumentException("用户不存在");
        return user;
    }
    private String normalize(String value) { return value == null ? "" : value.trim(); }
    private String value(String value) { return value == null ? "" : value; }
}

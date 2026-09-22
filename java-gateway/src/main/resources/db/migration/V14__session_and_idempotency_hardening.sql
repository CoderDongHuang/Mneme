ALTER TABLE `chat_message`
    DROP INDEX `uk_chat_message_request_role`,
    ADD UNIQUE INDEX `uk_chat_message_session_request_role` (`session_id`, `request_id`, `role`);

DELETE duplicate_task FROM `account_deletion_task` duplicate_task
INNER JOIN `account_deletion_task` first_task
    ON duplicate_task.`user_id` = first_task.`user_id`
    AND duplicate_task.`id` > first_task.`id`;

ALTER TABLE `account_deletion_task`
    ADD UNIQUE INDEX `uk_account_deletion_user` (`user_id`);

CREATE TABLE IF NOT EXISTS `auth_session` (
    `session_id` CHAR(36) PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `remembered` BOOLEAN NOT NULL DEFAULT FALSE,
    `expires_at` DATETIME NOT NULL,
    `revoked_at` DATETIME NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `last_seen_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_auth_session_user_active` (`user_id`, `revoked_at`, `expires_at`),
    INDEX `idx_auth_session_expiry` (`expires_at`),
    CONSTRAINT `fk_auth_session_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
);

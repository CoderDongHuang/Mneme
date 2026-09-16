ALTER TABLE `user`
    ADD COLUMN `role` VARCHAR(32) NOT NULL DEFAULT 'user' AFTER `avatar_path`,
    ADD COLUMN `status` VARCHAR(32) NOT NULL DEFAULT 'active' AFTER `role`,
    ADD INDEX `idx_user_role_status` (`role`, `status`);

CREATE TABLE IF NOT EXISTS `notification_event` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `event_type` VARCHAR(64) NOT NULL,
    `aggregate_id` VARCHAR(128),
    `severity` VARCHAR(24) NOT NULL DEFAULT 'info',
    `payload_json` JSON NOT NULL,
    `read_at` DATETIME NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_notification_user_created` (`user_id`, `created_at`),
    INDEX `idx_notification_user_read` (`user_id`, `read_at`, `created_at`),
    CONSTRAINT `fk_notification_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS `account_deletion_task` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `operation_id` VARCHAR(64) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `current_step` VARCHAR(128),
    `attempt_count` INT NOT NULL DEFAULT 0,
    `error_message` TEXT,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX `uk_account_deletion_operation` (`operation_id`),
    INDEX `idx_account_deletion_user` (`user_id`, `created_at`),
    INDEX `idx_account_deletion_status` (`status`, `updated_at`)
);

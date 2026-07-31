CREATE TABLE `audit_log` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NULL,
    `action` VARCHAR(32) NOT NULL,
    `resource` VARCHAR(255) NOT NULL,
    `status_code` INT NOT NULL,
    `client_ip` VARCHAR(64) NULL,
    `trace_id` VARCHAR(64) NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_audit_user_created` (`user_id`, `created_at`),
    INDEX `idx_audit_created` (`created_at`)
);

CREATE TABLE IF NOT EXISTS `operation_log` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `operation_id` VARCHAR(64) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `operation_type` VARCHAR(64) NOT NULL,
    `aggregate_id` VARCHAR(128),
    `step` VARCHAR(128) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `payload_json` JSON,
    `error_message` TEXT,
    `attempts` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_operation_log_operation` (`operation_id`, `id`),
    INDEX `idx_operation_log_user_type` (`user_id`, `operation_type`, `created_at`),
    INDEX `idx_operation_log_status` (`status`, `updated_at`)
);

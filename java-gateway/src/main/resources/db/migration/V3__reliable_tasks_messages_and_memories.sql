ALTER TABLE `chat_message`
    ADD COLUMN `request_id` VARCHAR(64) NULL AFTER `session_id`,
    ADD COLUMN `status` VARCHAR(20) NOT NULL DEFAULT 'completed' AFTER `content`,
    ADD COLUMN `error_code` VARCHAR(64) NULL AFTER `status`,
    ADD UNIQUE INDEX `uk_chat_message_request_role` (`request_id`, `role`);

ALTER TABLE `knowledge_base`
    ADD COLUMN `status` VARCHAR(20) NOT NULL DEFAULT 'active' AFTER `chroma_collection_id`;

CREATE TABLE `processing_task` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `task_id` VARCHAR(64) NOT NULL,
    `task_type` VARCHAR(32) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `aggregate_id` BIGINT NULL,
    `idempotency_key` VARCHAR(128) NOT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
    `payload` JSON NOT NULL,
    `attempt_count` INT NOT NULL DEFAULT 0,
    `max_attempts` INT NOT NULL DEFAULT 3,
    `next_attempt_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `locked_at` DATETIME NULL,
    `locked_by` VARCHAR(100) NULL,
    `error_code` VARCHAR(64) NULL,
    `error_message` TEXT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX `uk_processing_task_id` (`task_id`),
    UNIQUE INDEX `uk_processing_task_idempotency` (`task_type`, `idempotency_key`),
    INDEX `idx_processing_task_poll` (`status`, `next_attempt_at`),
    CONSTRAINT `fk_processing_task_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
);

CREATE TABLE `pending_memory` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `memory_id` VARCHAR(64) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `session_id` BIGINT NULL,
    `source_message_id` BIGINT NULL,
    `category` VARCHAR(32) NOT NULL,
    `content` TEXT NOT NULL,
    `topic` VARCHAR(255) NOT NULL DEFAULT '',
    `confidence` DECIMAL(5,4) NOT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
    `resolved_at` DATETIME NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX `uk_pending_memory_id` (`memory_id`),
    INDEX `idx_pending_memory_user_status` (`user_id`, `status`, `created_at`),
    CONSTRAINT `fk_pending_memory_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_pending_memory_session` FOREIGN KEY (`session_id`) REFERENCES `chat_session` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_pending_memory_message` FOREIGN KEY (`source_message_id`) REFERENCES `chat_message` (`id`) ON DELETE SET NULL
);

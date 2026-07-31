ALTER TABLE `knowledge_document`
    ADD COLUMN `parse_task_id` VARCHAR(64) NULL AFTER `status`,
    ADD COLUMN `chunk_count` INT NOT NULL DEFAULT 0 AFTER `parse_task_id`,
    ADD COLUMN `error_message` TEXT NULL AFTER `chunk_count`;

CREATE TABLE IF NOT EXISTS `chat_message` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `session_id` BIGINT NOT NULL,
    `role` VARCHAR(20) NOT NULL,
    `content` LONGTEXT NOT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`session_id`) REFERENCES `chat_session`(`id`) ON DELETE CASCADE,
    INDEX `idx_session_created` (`session_id`, `created_at`)
);

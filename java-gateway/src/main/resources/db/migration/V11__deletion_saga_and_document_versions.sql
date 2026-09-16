ALTER TABLE `account_deletion_task`
    ADD COLUMN `next_attempt_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER `attempt_count`,
    ADD COLUMN `locked_at` DATETIME NULL AFTER `next_attempt_at`,
    ADD COLUMN `locked_by` VARCHAR(128) NULL AFTER `locked_at`,
    ADD COLUMN `completed_at` DATETIME NULL AFTER `error_message`,
    ADD INDEX `idx_account_deletion_claim` (`status`, `next_attempt_at`, `locked_at`);

CREATE TABLE IF NOT EXISTS `knowledge_document_version` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `document_id` BIGINT NOT NULL,
    `version_number` INT NOT NULL,
    `file_name` VARCHAR(255) NOT NULL,
    `file_path` VARCHAR(1024) NOT NULL,
    `sha256` CHAR(64) NOT NULL,
    `size_bytes` BIGINT NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE INDEX `uk_document_version` (`document_id`, `version_number`),
    INDEX `idx_document_version_created` (`document_id`, `created_at`),
    CONSTRAINT `fk_document_version_document` FOREIGN KEY (`document_id`)
        REFERENCES `knowledge_document` (`id`) ON DELETE CASCADE
);

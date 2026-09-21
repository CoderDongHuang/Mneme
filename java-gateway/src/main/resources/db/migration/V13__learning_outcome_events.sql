ALTER TABLE `review_card`
    ADD COLUMN `topic` VARCHAR(200) NOT NULL DEFAULT '' AFTER `origin`,
    ADD INDEX `idx_review_card_user_topic` (`user_id`, `topic`);

CREATE TABLE IF NOT EXISTS `learning_outcome_event` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `event_type` VARCHAR(32) NOT NULL,
    `topic` VARCHAR(200) NOT NULL DEFAULT '',
    `score` DECIMAL(8,2) NOT NULL,
    `success` BOOLEAN NOT NULL DEFAULT FALSE,
    `source_id` BIGINT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_learning_outcome_user_time` (`user_id`, `created_at`),
    INDEX `idx_learning_outcome_user_topic` (`user_id`, `topic`, `created_at`),
    CONSTRAINT `fk_learning_outcome_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS `agent_trace` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` VARCHAR(128) NOT NULL,
    `session_id` VARCHAR(128) NOT NULL,
    `node` VARCHAR(255) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `duration_ms` DOUBLE NOT NULL DEFAULT 0,
    `payload_json` JSON NOT NULL,
    `error` VARCHAR(1000) NOT NULL DEFAULT '',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_agent_trace_session` (`user_id`, `session_id`, `id`)
);

CREATE TABLE IF NOT EXISTS `memory_version` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `memory_id` VARCHAR(128) NOT NULL,
    `user_id` VARCHAR(128) NOT NULL,
    `version` INT NOT NULL,
    `action` VARCHAR(64) NOT NULL,
    `content` LONGTEXT NOT NULL,
    `metadata_json` JSON NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_memory_version` (`memory_id`, `version`),
    INDEX `idx_memory_version_owner` (`user_id`, `memory_id`, `version`)
);

CREATE TABLE IF NOT EXISTS `agent_tool_usage` (
    `user_id` VARCHAR(128) NOT NULL,
    `usage_date` DATE NOT NULL,
    `used_units` INT NOT NULL DEFAULT 0,
    PRIMARY KEY (`user_id`, `usage_date`)
);

CREATE TABLE IF NOT EXISTS `agent_tool_approval` (
    `token_hash` CHAR(64) PRIMARY KEY,
    `tool_name` VARCHAR(255) NOT NULL,
    `user_id` VARCHAR(128) NOT NULL,
    `approved_by` VARCHAR(128) NOT NULL,
    `expires_at` TIMESTAMP NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_tool_approval_lookup` (`tool_name`, `user_id`, `expires_at`)
);

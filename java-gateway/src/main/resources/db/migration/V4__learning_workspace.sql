CREATE TABLE `learning_plan` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `title` VARCHAR(200) NOT NULL,
    `goal` TEXT NOT NULL,
    `target_date` DATE NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'active',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_learning_plan_user_status` (`user_id`, `status`),
    CONSTRAINT `fk_learning_plan_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
);

CREATE TABLE `review_card` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `plan_id` BIGINT NULL,
    `prompt` TEXT NOT NULL,
    `answer` TEXT NOT NULL,
    `interval_days` INT NOT NULL DEFAULT 1,
    `ease_factor` DECIMAL(4,2) NOT NULL DEFAULT 2.50,
    `due_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `last_rating` INT NULL,
    `review_count` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_review_card_user_due` (`user_id`, `due_at`),
    CONSTRAINT `fk_review_card_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_review_card_plan` FOREIGN KEY (`plan_id`) REFERENCES `learning_plan` (`id`) ON DELETE SET NULL
);

CREATE TABLE `knowledge_quiz` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `kb_id` BIGINT NULL,
    `title` VARCHAR(200) NOT NULL,
    `topic` VARCHAR(200) NOT NULL,
    `questions_json` JSON NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_quiz_user_created` (`user_id`, `created_at`),
    CONSTRAINT `fk_quiz_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_quiz_kb` FOREIGN KEY (`kb_id`) REFERENCES `knowledge_base` (`id`) ON DELETE SET NULL
);

CREATE TABLE `quiz_attempt` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `quiz_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `answers_json` JSON NOT NULL,
    `score` INT NOT NULL,
    `feedback_json` JSON NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_attempt_user_created` (`user_id`, `created_at`),
    CONSTRAINT `fk_attempt_quiz` FOREIGN KEY (`quiz_id`) REFERENCES `knowledge_quiz` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_attempt_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
);

CREATE TABLE `chat_branch` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `source_session_id` BIGINT NOT NULL,
    `source_message_id` BIGINT NULL,
    `branch_session_id` BIGINT NOT NULL,
    `label` VARCHAR(120) NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_chat_branch_user` (`user_id`, `created_at`),
    CONSTRAINT `fk_branch_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_branch_source_session` FOREIGN KEY (`source_session_id`) REFERENCES `chat_session` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_branch_source_message` FOREIGN KEY (`source_message_id`) REFERENCES `chat_message` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_branch_session` FOREIGN KEY (`branch_session_id`) REFERENCES `chat_session` (`id`) ON DELETE CASCADE
);

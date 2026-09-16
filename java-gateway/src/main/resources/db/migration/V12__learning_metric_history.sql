CREATE TABLE IF NOT EXISTS `learning_metric_snapshot` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `snapshot_date` DATE NOT NULL,
    `plan_completion_rate` DECIMAL(8,4) NOT NULL DEFAULT 0,
    `review_due` INT NOT NULL DEFAULT 0,
    `reviewed_total` INT NOT NULL DEFAULT 0,
    `average_interval_days` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `quiz_average_score` DECIMAL(8,2) NOT NULL DEFAULT 0,
    `quiz_attempts` INT NOT NULL DEFAULT 0,
    `mistake_cards` INT NOT NULL DEFAULT 0,
    `pending_weak_points` INT NOT NULL DEFAULT 0,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX `uk_metric_snapshot_user_date` (`user_id`, `snapshot_date`),
    INDEX `idx_metric_snapshot_user_date` (`user_id`, `snapshot_date`),
    CONSTRAINT `fk_metric_snapshot_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
);

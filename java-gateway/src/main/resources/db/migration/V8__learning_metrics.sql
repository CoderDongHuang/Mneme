ALTER TABLE `review_card`
    ADD COLUMN `origin` VARCHAR(32) NOT NULL DEFAULT 'manual' AFTER `review_count`,
    ADD INDEX `idx_review_card_user_origin` (`user_id`, `origin`);

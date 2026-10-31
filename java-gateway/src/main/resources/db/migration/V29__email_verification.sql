-- Existing email addresses have no ownership evidence; do not grandfather them.
ALTER TABLE `user` ADD COLUMN `email_verified_at` DATETIME(6) NULL;

CREATE TABLE `email_verification_token` (
    `user_id` BIGINT PRIMARY KEY,
    `email` VARCHAR(120) NOT NULL,
    `token_hash` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `expires_at` DATETIME(6) NOT NULL,
    CONSTRAINT `fk_email_verification_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
);

-- Tokens issued before ownership verification was enforced must not bypass it.
DELETE FROM `password_reset_token`;

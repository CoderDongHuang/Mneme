ALTER TABLE `user`
    ADD COLUMN `nickname` VARCHAR(50) NULL AFTER `username`,
    ADD COLUMN `email` VARCHAR(120) NULL AFTER `nickname`,
    ADD COLUMN `avatar_path` VARCHAR(500) NULL AFTER `email`;

CREATE UNIQUE INDEX `uk_user_email` ON `user` (`email`);

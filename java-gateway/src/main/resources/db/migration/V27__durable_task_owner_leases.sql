ALTER TABLE processing_task
    ADD COLUMN owner_token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    ADD COLUMN lease_fence BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN lease_until DATETIME(6) NULL,
    ADD INDEX idx_processing_lease (status, lease_until);

ALTER TABLE account_deletion_task
    ADD COLUMN owner_token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    ADD COLUMN lease_fence BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN lease_until DATETIME(6) NULL,
    ADD INDEX idx_account_deletion_lease (status, lease_until);

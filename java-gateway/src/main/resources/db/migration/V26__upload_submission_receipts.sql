CREATE TABLE upload_submission (
    user_id BIGINT NOT NULL,
    request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    kb_id BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL,
    document_id BIGINT NULL,
    task_id VARCHAR(64) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (user_id, request_id),
    CONSTRAINT fk_upload_submission_user FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
    INDEX idx_upload_submission_created (created_at)
);

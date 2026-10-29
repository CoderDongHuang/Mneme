ALTER TABLE quiz_attempt ADD COLUMN request_id VARCHAR(64) NULL,
    ADD COLUMN raw_score INT NULL,
    ADD UNIQUE KEY uk_quiz_attempt_request (user_id, quiz_id, request_id);

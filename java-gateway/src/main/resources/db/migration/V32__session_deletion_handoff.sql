ALTER TABLE chat_session
    ADD COLUMN deletion_status VARCHAR(20) NOT NULL DEFAULT 'active';

CREATE TABLE rag_quality_feedback (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    outcome VARCHAR(32) NOT NULL,
    citation_rating VARCHAR(32) NOT NULL,
    reason VARCHAR(32) NOT NULL,
    note VARCHAR(1000) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_feedback_user_message (user_id, message_id),
    INDEX idx_feedback_user_time (user_id, updated_at),
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES chat_message(id) ON DELETE CASCADE
);

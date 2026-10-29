CREATE TABLE quiz_draft (
    user_id BIGINT NOT NULL,
    quiz_id BIGINT NOT NULL,
    answers_json JSON NOT NULL,
    current_question INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id,quiz_id),
    FOREIGN KEY(user_id) REFERENCES `user`(id) ON DELETE CASCADE,
    FOREIGN KEY(quiz_id) REFERENCES knowledge_quiz(id) ON DELETE CASCADE
);
CREATE TABLE quiz_question_report (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    quiz_id BIGINT NOT NULL,
    question_number INT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES `user`(id) ON DELETE CASCADE,
    FOREIGN KEY(quiz_id) REFERENCES knowledge_quiz(id) ON DELETE CASCADE
);

-- Fence terminal callbacks from earlier attempts of the same request_id.
ALTER TABLE chat_message ADD COLUMN answer_generation BIGINT NOT NULL DEFAULT 0;

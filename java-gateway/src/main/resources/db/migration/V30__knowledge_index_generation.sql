ALTER TABLE knowledge_document ADD COLUMN index_generation BIGINT NOT NULL DEFAULT 0;

-- No FK/cascade: tombstones must survive document/KB/account removal so an
-- in-flight worker cannot recreate data. Contains IDs/counters only, no content.
CREATE TABLE knowledge_index_state (
    user_id VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin PRIMARY KEY,
    state_json JSON NOT NULL
);

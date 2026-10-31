ALTER TABLE user_model_config
    ADD COLUMN key_version VARCHAR(48) NOT NULL DEFAULT 'legacy-v1';

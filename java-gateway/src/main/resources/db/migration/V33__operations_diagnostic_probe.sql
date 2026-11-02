-- Isolated CRUD probe; diagnostics never write to user or document records.
CREATE TABLE operations_diagnostic_probe (
    probe_id VARCHAR(64) PRIMARY KEY,
    probe_value VARCHAR(64) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6))
);

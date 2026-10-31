-- Deletion readback receipts contain counts only, never document text or credentials.
ALTER TABLE processing_task ADD COLUMN cleanup_report JSON NULL;

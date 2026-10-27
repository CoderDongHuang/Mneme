CREATE TABLE knowledge_document_tag (
    document_id BIGINT NOT NULL,
    tag VARCHAR(80) NOT NULL,
    PRIMARY KEY(document_id, tag),
    CONSTRAINT fk_document_tag FOREIGN KEY(document_id) REFERENCES knowledge_document(id) ON DELETE CASCADE
);
ALTER TABLE knowledge_document_version ADD COLUMN parse_report LONGTEXT NULL;
UPDATE knowledge_document_version v JOIN knowledge_document d
  ON v.document_id=d.id AND v.file_path=d.file_path
  SET v.parse_report=d.parse_report;

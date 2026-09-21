-- This file intentionally rebuilds only the dedicated checkpoint schema.
-- scripts/import_c1.py requires an explicit --rebuild flag before executing it.
DROP SCHEMA IF EXISTS c1_checkpoint CASCADE;
CREATE SCHEMA c1_checkpoint;

CREATE TABLE c1_checkpoint.documents (
    source_id BIGINT PRIMARY KEY,
    file_key TEXT NOT NULL,
    dataset TEXT NOT NULL,
    document_type TEXT,
    CONSTRAINT documents_file_key_uk UNIQUE (file_key)
);

CREATE TABLE c1_checkpoint.chunks (
    source_id BIGINT PRIMARY KEY,
    document_source_id BIGINT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT,
    CONSTRAINT chunks_document_position_uk
        UNIQUE (document_source_id, chunk_index),
    CONSTRAINT chunks_document_fk
        FOREIGN KEY (document_source_id)
        REFERENCES c1_checkpoint.documents (source_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT
);

COMMENT ON COLUMN c1_checkpoint.documents.source_id IS
    'Original documents.id from the pinned Hugging Face revision';
COMMENT ON COLUMN c1_checkpoint.chunks.source_id IS
    'Original chunks.id from the pinned Hugging Face revision';
COMMENT ON COLUMN c1_checkpoint.chunks.document_source_id IS
    'Original chunks.document_id; validated FK to documents.source_id';


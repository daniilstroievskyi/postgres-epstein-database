-- Integrity checks for checkpoint C1. Only identifiers and aggregates are
-- selected. scripts/import_c1.py and scripts/verify_c1.py run the same checks
-- and record the results in C1/evidence/verification.txt.

-- 1. Counts and source ID range. Expected: 1000, 1, 1000, 160, 157.
SELECT
    (SELECT count(*) FROM c1_checkpoint.documents) AS document_count,
    (SELECT min(source_id) FROM c1_checkpoint.documents) AS min_document_id,
    (SELECT max(source_id) FROM c1_checkpoint.documents) AS max_document_id,
    (SELECT count(*) FROM c1_checkpoint.chunks) AS chunk_count,
    (SELECT count(DISTINCT document_source_id)
     FROM c1_checkpoint.chunks) AS referenced_document_count;

-- 2. Duplicate source IDs. Expected: no rows (the primary keys forbid them).
SELECT source_id, count(*)
FROM c1_checkpoint.documents
GROUP BY source_id HAVING count(*) > 1;

SELECT source_id, count(*)
FROM c1_checkpoint.chunks
GROUP BY source_id HAVING count(*) > 1;

-- 3. Duplicate chunk positions. Expected: no rows (UNIQUE constraint).
SELECT document_source_id, chunk_index, count(*)
FROM c1_checkpoint.chunks
GROUP BY document_source_id, chunk_index HAVING count(*) > 1;

-- 4. Orphan chunks. Expected: 0 (the validated FK forbids them).
SELECT count(*) AS orphan_chunk_count
FROM c1_checkpoint.chunks AS c
LEFT JOIN c1_checkpoint.documents AS d ON d.source_id = c.document_source_id
WHERE d.source_id IS NULL;

-- 5. Constraints with validation status. chunks_document_fk must show
--    convalidated = true.
SELECT conrelid::regclass AS table_name,
       conname,
       contype,
       convalidated,
       pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE connamespace = 'c1_checkpoint'::regnamespace
ORDER BY 1, 2;

-- 6. Informational: sample documents without a chunk in this shard.
--    Expected 843. This is not "documents without text"; their chunks live in
--    other chunk shards (see C1/run.md).
SELECT count(*) AS documents_without_chunk_in_sample
FROM c1_checkpoint.documents AS d
WHERE NOT EXISTS (
    SELECT 1 FROM c1_checkpoint.chunks AS c
    WHERE c.document_source_id = d.source_id
);

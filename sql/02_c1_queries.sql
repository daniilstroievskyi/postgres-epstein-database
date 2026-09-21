-- Establish the required "before" state.
DROP INDEX IF EXISTS c1_checkpoint.chunks_content_fts_gin;

-- Required C1 query. Run before and after creating the GIN index.
SELECT source_id AS chunk_id, document_source_id AS document_id
FROM c1_checkpoint.chunks
WHERE to_tsvector('english', coalesce(content, ''))
      @@ plainto_tsquery('english', 'flight')
ORDER BY source_id;

EXPLAIN
SELECT source_id AS chunk_id, document_source_id AS document_id
FROM c1_checkpoint.chunks
WHERE to_tsvector('english', coalesce(content, ''))
      @@ plainto_tsquery('english', 'flight')
ORDER BY source_id;

CREATE INDEX chunks_content_fts_gin
ON c1_checkpoint.chunks
USING GIN (to_tsvector('english', coalesce(content, '')));

-- Semantic comparison: stemming differs from substring matching.
WITH examples(value) AS (
    VALUES ('flight'), ('flights'), ('preflight')
)
SELECT
    value,
    to_tsvector('english', value)::text AS normalized_fts,
    to_tsvector('english', value) @@ plainto_tsquery('english', 'flight')
        AS fts_matches_flight,
    value ILIKE '%flight%' AS ilike_contains_flight
FROM examples
ORDER BY value;

-- AI-claim check (C1/run.md): the empty FTS result is genuine. ILIKE is the widest
-- possible match; 'floor' is a positive control. Expected: 160, 0, 11.
SELECT
    count(*) AS chunks_total,
    count(*) FILTER (WHERE content ILIKE '%flight%') AS chunks_with_flight,
    count(*) FILTER (WHERE content ILIKE '%floor%') AS chunks_with_floor
FROM c1_checkpoint.chunks;

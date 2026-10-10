-- Section 7: execute after setup_z1_queries.py (pg_trgm must be installed).
-- All statements return their complete result; there is no hidden LIMIT.
-- Optional session settings are documented in docs/queries-and-indexes.md.

-- name: Q1
-- English lexemes, not substrings; source chunk ID and document ID are retained.
WITH parameters AS (
    SELECT websearch_to_tsquery('english'::regconfig,
        COALESCE(current_setting('z1.fts_input', true), 'aircraft')) AS query
)
SELECT c.source_id AS chunk_source_id, c.document_id AS document_source_id,
       c.chunk_index,
       ts_rank_cd(to_tsvector('english'::regconfig, COALESCE(c.content, '')), p.query) AS relevance
FROM "z1".chunks c CROSS JOIN parameters p
WHERE to_tsvector('english'::regconfig, COALESCE(c.content, '')) @@ p.query
ORDER BY relevance DESC, c.source_id;

-- name: Q2
-- The CLI normalizes input with nfkc-casefold-space-v1, the stored-value rule.
-- '%' uses the explicitly configured pg_trgm.similarity_threshold (default 0.3).
-- This searches canonical person names, not aliases; a score is not identity confidence.
WITH parameters AS (
    SELECT COALESCE(NULLIF(current_setting('z1.fuzzy_raw_input', true), ''), 'Jeffrey Epstien') AS raw_input,
           COALESCE(NULLIF(current_setting('z1.fuzzy_input', true), ''), 'jeffrey epstien') AS normalized_input,
           COALESCE(current_setting('pg_trgm.similarity_threshold', true), '0.3')::real AS threshold
)
SELECT p.source_id AS person_source_id, p.canonical_name, p.search_value,
       q.raw_input, q.normalized_input, q.threshold,
       'pg_trgm.similarity'::text AS method, p.normalization_version,
       public.similarity(p.search_value, q.normalized_input) AS similarity_score
FROM "z1".persons p CROSS JOIN parameters q
WHERE p.search_value OPERATOR(public.%) q.normalized_input
ORDER BY similarity_score DESC, p.source_id;

-- name: Q3
-- Exactly two directed edges. All three nodes and both edges must be distinct.
-- Preserve parallel-edge paths as distinct results; do not DISTINCT endpoints.
WITH parameters AS (
    SELECT COALESCE(NULLIF(current_setting('z1.kg_start', true), ''), '1')::bigint AS start_id
)
SELECT e1.from_node_id AS start_node_source_id,
       e1.to_node_id AS middle_node_source_id,
       e2.to_node_id AS end_node_source_id,
       e1.source_id AS first_edge_source_id, e2.source_id AS second_edge_source_id
FROM "z1".kg_edges e1
JOIN "z1".kg_edges e2 ON e2.from_node_id = e1.to_node_id
CROSS JOIN parameters p
WHERE e1.from_node_id = p.start_id
  AND e1.source_id <> e2.source_id
  AND e1.from_node_id <> e1.to_node_id
  AND e2.to_node_id NOT IN (e1.from_node_id, e1.to_node_id)
ORDER BY e1.source_id, e2.source_id;

-- name: Q4
-- Group by currency AND normalized merchant label, not verified merchant identity.
-- Unset filters include all rows, including unknown currency/merchant buckets.
-- SUM returns NULL if no valid amount/known currency exists; unknown amounts never become zero.
WITH parameters AS (
    SELECT NULLIF(current_setting('z1.currency', true), '') AS currency,
           NULLIF(current_setting('z1.merchant', true), '') AS merchant
)
SELECT t.currency, t.search_value AS merchant_search_value,
       count(*) AS transaction_records,
       count(*) FILTER (WHERE t.amount_state = 'valid') AS valid_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'missing') AS missing_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'invalid') AS invalid_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'valid' AND t.amount < 0) AS negative_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'valid' AND t.amount = 0) AS zero_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'valid' AND t.amount > 0) AS positive_amount_records,
       sum(t.amount) FILTER (WHERE t.amount_state = 'valid' AND t.currency IS NOT NULL) AS amount_sum
FROM "z1".financial_transactions t CROSS JOIN parameters p
WHERE (p.currency IS NULL OR t.currency = p.currency)
  AND (p.merchant IS NULL OR t.search_value = p.merchant)
GROUP BY t.currency, t.search_value
ORDER BY t.currency NULLS FIRST, t.search_value NULLS FIRST;

-- name: Q4_FILTER
-- Focused variant of Q4 demonstrating the composite B-tree equality predicates.
-- Defaults: USD / fedex. Unlike the optional-filter form, both predicates are mandatory.
WITH parameters AS (
    SELECT COALESCE(NULLIF(current_setting('z1.currency', true), ''), 'USD') AS currency,
           COALESCE(NULLIF(current_setting('z1.merchant', true), ''), 'fedex') AS merchant
)
SELECT t.currency, t.search_value AS merchant_search_value,
       count(*) AS transaction_records,
       count(*) FILTER (WHERE t.amount_state = 'valid') AS valid_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'missing') AS missing_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'invalid') AS invalid_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'valid' AND t.amount < 0) AS negative_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'valid' AND t.amount = 0) AS zero_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'valid' AND t.amount > 0) AS positive_amount_records,
       sum(t.amount) FILTER (WHERE t.amount_state = 'valid' AND t.currency IS NOT NULL) AS amount_sum
FROM "z1".financial_transactions t CROSS JOIN parameters p
WHERE t.currency = p.currency AND t.search_value = p.merchant
GROUP BY t.currency, t.search_value
ORDER BY t.currency NULLS FIRST, t.search_value NULLS FIRST;

-- name: Q5
-- Unit: upstream file-output records, whose PK is (output_name,file_key).
-- Multiple outputs for one file are not proof of distinct chronological attempts.
-- Upstream run IDs describe the source producer's runs, not our ETL attempts.
SELECT f.file_key, count(*) AS file_output_records,
       count(DISTINCT f.output_name) AS distinct_outputs,
       count(DISTINCT f.run_id) AS distinct_referenced_upstream_runs,
       count(*) FILTER (WHERE f.run_id IS NULL) AS records_without_upstream_run
FROM "z1".upstream_files f
GROUP BY f.file_key
HAVING count(*) > 1
ORDER BY f.file_key;

-- name: Q6
-- Own question: how complete is email metadata in each dataset?
-- First seven categories are disjoint; subject categories subdivide valid objects.
SELECT d.dataset, count(*) AS document_records,
       count(*) FILTER (WHERE d.email_fields_state = 'missing') AS missing_sql_null,
       count(*) FILTER (WHERE d.email_fields_state = 'empty') AS empty_raw,
       count(*) FILTER (WHERE d.email_fields_state = 'invalid') AS invalid_raw,
       count(*) FILTER (WHERE d.email_fields_state = 'json_null') AS whole_json_null,
       count(*) FILTER (WHERE d.email_fields_state = 'valid' AND jsonb_typeof(d.email_fields) = 'object') AS valid_objects,
       count(*) FILTER (WHERE d.email_fields_state = 'valid' AND jsonb_typeof(d.email_fields) = 'array') AS valid_arrays,
       count(*) FILTER (WHERE d.email_fields_state = 'valid' AND jsonb_typeof(d.email_fields) NOT IN ('object','array')) AS valid_other_scalars,
       count(*) FILTER (WHERE d.email_fields_state = 'valid' AND jsonb_typeof(d.email_fields) = 'object'
                         AND NOT (d.email_fields ? 'subject')) AS object_subject_absent,
       count(*) FILTER (WHERE d.email_fields_state = 'valid' AND jsonb_typeof(d.email_fields) = 'object'
                         AND d.email_fields @> '{"subject":null}'::jsonb) AS object_subject_json_null,
       count(*) FILTER (WHERE d.email_fields_state = 'valid' AND jsonb_typeof(d.email_fields) = 'object'
                         AND d.email_fields ? 'subject' AND d.email_fields -> 'subject' <> 'null'::jsonb) AS object_subject_nonnull
FROM "z1".documents d
GROUP BY d.dataset
ORDER BY d.dataset NULLS FIRST;

-- name: Q6_JSON
-- Drill-down of Q6, not a seventh independent analytical question.
-- An explicit JSON null subject is different from SQL NULL or an absent key.
SELECT d.source_id AS document_source_id, d.dataset, d.file_key,
       d.email_fields_raw IS NOT NULL AS original_json_retained,
       d.email_fields IS NULL AS parsed_is_sql_null,
       d.email_fields ? 'subject' AS subject_key_present,
       jsonb_typeof(d.email_fields -> 'subject') AS subject_value_type
FROM "z1".documents d
WHERE d.email_fields_state = 'valid'
  AND jsonb_typeof(d.email_fields) = 'object'
  AND d.email_fields @> '{"subject":null}'::jsonb
ORDER BY d.source_id;

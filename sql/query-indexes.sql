-- Section 7 auxiliary indexes; PK/UNIQUE indexes remain in schema.sql.
-- pg_trgm is a trusted PostgreSQL extension installed by the database owner.
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

-- name: chunks_fts_gin
-- Q1 @@; explicit English configuration matches the query expression exactly.
CREATE INDEX IF NOT EXISTS chunks_fts_gin ON "z1".chunks
USING gin (to_tsvector('english'::regconfig, COALESCE(content, '')));

-- name: persons_name_trgm_gin
-- Q2 '%' trigram similarity; scores still need calculation and sorting.
CREATE INDEX IF NOT EXISTS persons_name_trgm_gin ON "z1".persons
USING gin (search_value public.gin_trgm_ops);

-- name: financial_currency_merchant_btree
-- Q4 optional equality filters: currency first, merchant within that currency.
-- This one index satisfies both B-tree and composite-index requirements.
CREATE INDEX IF NOT EXISTS financial_currency_merchant_btree
ON "z1".financial_transactions USING btree (currency, search_value);

-- name: documents_email_object_gin
-- Own choice: partial JSONB GIN. Q6_JSON '@>' uses jsonb_path_ops.
-- Restrict entries to valid objects; missing values and arrays stay in Q6 totals.
CREATE INDEX IF NOT EXISTS documents_email_object_gin ON "z1".documents
USING gin (email_fields jsonb_path_ops)
WHERE email_fields_state = 'valid' AND jsonb_typeof(email_fields) = 'object';

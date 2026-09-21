# C1 run notes

Checkpoint C1, sample `c1-sample-v1`. Evidence in `C1/evidence/`, manifest in `C1/manifest.tsv`.
Environment: PostgreSQL 18.3 (local, database `dbs2`, port 5432), Python 3.13.7,
`huggingface_hub` 1.31.0, `duckdb` 1.5.5, `psycopg` 3.3.6.

## Procedure

1. `scripts/data_download.py` — `hf_hub_download` of the two shards from
   `kabasshouse/epstein-data`, revision `133ef9f0a539fafc270cde8fa8638dc38d89968d`.
   Files go to `data/data/…` (git-ignored, never modified); everything after this runs offline.
2. `scripts/manifest_c1.py` — SHA-256 of both files → `C1/manifest.tsv`, checked against
   the hash Hugging Face recorded for the revision (both match).
3. `python -m unittest discover -s tests` — tests of the sample selection.
4. `scripts/import_c1.py --rebuild` — DuckDB selects the 1 000 documents with the lowest
   `id` (`ORDER BY id LIMIT 1000`) and all chunks of the shard whose `document_id` is among
   them; `sql/01_c1_schema.sql` drops and recreates only schema `c1_checkpoint`; `COPY`;
   `ANALYZE`; asserts counts and the validated FK. One transaction, so a re-run cannot
   duplicate rows.
5. `scripts/verify_c1.py` — integrity checks (same as `sql/03_c1_checks.sql`), FTS query
   without index → GIN → query again, comparison, plans, index size, literal test,
   AI-claim check → `C1/evidence/`.

Password only via `$env:PGPASSWORD` for the current shell; commands in `README.md`.

## Field mapping

| Source column           | Column                      | Type    | Constraint                                          |
| ----------------------- | --------------------------- | ------- | --------------------------------------------------- |
| documents.id            | documents.source_id         | BIGINT  | PRIMARY KEY                                         |
| documents.file_key      | documents.file_key          | TEXT    | NOT NULL, UNIQUE                                    |
| documents.dataset       | documents.dataset           | TEXT    | NOT NULL                                            |
| documents.document_type | documents.document_type     | TEXT    | nullable (137 of 1 000 NULL)                        |
| chunks.id               | chunks.source_id            | BIGINT  | PRIMARY KEY                                         |
| chunks.document_id      | chunks.document_source_id   | BIGINT  | NOT NULL, FK → documents.source_id, validated, RESTRICT |
| chunks.chunk_index      | chunks.chunk_index          | INTEGER | NOT NULL, CHECK ≥ 0, UNIQUE (document_source_id, chunk_index) |
| chunks.content          | chunks.content              | TEXT    | nullable; FTS uses `coalesce(content, '')`          |

Source IDs are the primary keys (one pinned revision, no surrogate keys). The remaining
source columns are left for Z1.

## Results

- Integrity: 1 000 documents (IDs 1–1 000), 160 chunks → 157 documents, 0 duplicates,
  0 orphans, FK `convalidated = true`. 843 documents have no chunk in this shard although
  all have `full_text`: chunk shards are not aligned with document shards.
- FTS `to_tsvector('english', coalesce(content,'')) @@ plainto_tsquery('english','flight')`:
  0 rows before and after the GIN, rows and order identical. The zero is correct: no
  sample chunk contains the substring `flight` (the shard has 1 024 such chunks, none for
  documents 1–1 000).
- Plans: before **Seq Scan** (Filter) → **Sort** on `source_id`; after **Bitmap Index Scan**
  on `chunks_content_fts_gin` → **Bitmap Heap Scan** (Recheck) → **Sort**. Nothing forced;
  the Sort stays because GIN returns matches unordered.
- Index: `gin (to_tsvector('english'::regconfig, COALESCE(content, ''::text)))`, 120 kB.
  Usable because the expression is identical to the query's, including `'english'`.
- Literals: `flight` true/true, `flights` true/true (stemmed to `flight`), `preflight`
  **false**/true (FTS / `ILIKE '%flight%'`). FTS compares stemmed lexemes, `ILIKE`
  compares character substrings.

## Design lines 

| Query                        | Operator                | Index                                                            | Risk                                                                                                    |
| ---------------------------- | ----------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| exact `file_key`             | `=`                     | B-tree | may not stay unique across all shards/datasets in Z1 → `(dataset, file_key)`; `=` is case-sensitive    |
| substring                    | `LIKE '%…%'` / `ILIKE`  | GIN | large and slow to update; patterns under 3 chars unusable; false candidates rechecked on the heap       |
| JSONB containment            | `@>`                    | GIN | no range comparisons inside the JSON; `jsonb_path_ops` lacks key existence; write amplification         |
| time range, append-only log  | `BETWEEN` / `>= AND <`  | BRIN | BRIN needs insert order ≈ time — out-of-order rows, updates or deletes degrade it toward a seq scan     |

## AI claim verified

Claim (Claude, used for review and this write-up): no imported sample chunk contains the
substring `flight` in any form, so the empty FTS result is correct data, not an indexing
error.
Test (`verify_c1.py`, also in `sql/02_c1_queries.sql`): `count(*) FILTER (WHERE content
ILIKE '%flight%')` on `c1_checkpoint.chunks` — the widest possible match — with
`ILIKE '%floor%'` as a positive control that the same test does find rows.
Result (`evidence/ai_claim_check.txt`): 160 chunks, 0 with `flight`, 11 with `floor`.
Confirmed.

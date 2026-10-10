# Section 8: one full-input index comparison

Recorded at 2026-10-10T20:16:11.794857+00:00. Query **Q6_JSON**, the explicit-JSON-null drill-down of Q6.
This is one benchmark of the existing own question, using the full documents layer.

## Reproduce

Run after the complete import, validation and section-7 setup:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_z1.py
```

The command verifies all frozen files offline and requires a completed full import. It obtains
the importer advisory lock, changes only `z1.documents_email_object_gin`, and leaves it active
when finished. DROP, CREATE and both variants run in one transaction: failure rolls back the
index changes. Use an idle database; the index DDL locks the documents table during the run.
Repeat the command to regenerate the evidence and this report; timings may change.

## Expectation and fixed workload

The JSONB @> containment query should benefit from the partial jsonb_path_ops GIN index: it can locate subject JSON null within the sparse valid-object subset instead of scanning the full documents table. This is a hypothesis, not a forced plan.

Frozen repository: `kabasshouse/epstein-data`, revision `133ef9f0a539fafc270cde8fa8638dc38d89968d`.
Source documents: **1,424,673**; accepted target documents: **1,424,662**; quarantined: **11**.
The index covers **631** valid objects. No corpus subset or copy is created.

Fixed parameters: valid JSON objects containing `{"subject":null}`. No session inputs,
LIMIT, ranking or parameters change between variants. SQL NULL and absent subject keys do
not meet this containment condition. The output includes original document IDs and orders by
the unique `source_id`, so ordering has no unresolved ties.

Exact SQL, unchanged from `sql/queries.sql`:

```sql
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
```

Exact index DDL captured from PostgreSQL and used for rebuilding:

```sql
CREATE INDEX documents_email_object_gin ON z1.documents USING gin (email_fields jsonb_path_ops) WHERE ((email_fields_state = 'valid'::text) AND (jsonb_typeof(email_fields) = 'object'::text));
```

## Environment and controls

- PostgreSQL: `PostgreSQL 18.3 (Debian 18.3-1.pgdg12+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit`.
- Extensions: `pg_trgm 1.6`, `plpgsql 1.0`.
- Client: Python 3.13.7, psycopg 3.3.6; Windows-11-10.0.26200-SP0; 24 client logical CPUs.
- Docker configuration: `postgres:18.3-bookworm`, local TCP connection.
- Database locale: en_US.utf8, en_US.utf8.
- `maintenance_work_mem`: 65536 kB.
- `max_parallel_workers_per_gather`: 2.
- `shared_buffers`: 16384 8kB.
- `work_mem`: 4096 kB.
- Resource note (recorded by the operator): Intel Core i7-14650HX; host 24 logical CPUs and 16944848896 bytes RAM; Docker Linux backend 24 logical CPUs and 8204201984 bytes RAM; container has no additional CPU or RAM limit.

Both variants use the same REPEATABLE READ snapshot and client; the script performs no
data writes. All **50 foreign keys** and all PK/UNIQUE/CHECK constraints stay active
and validated. Catalog comparison verifies unchanged constraint definitions/enforcement,
FK trigger states, and every other index definition, identity, readiness and size.
No concurrent project import, planner forcing, ANALYZE, cache flush or restart occurs.
Client auto-preparation is disabled in both variants to keep the execution protocol fixed.
The target index is absent in the baseline and recreated with its exact original DDL.

## Complete-result equivalence

All eight executions (two warm-ups and six measured runs) returned **20 rows**
and the same complete-result SHA-256:

```text
77e9a07077e6b3b00a385903e9b44ae41fcaf95236a1b16133a282e6a3166f3b
```

SHA256: columns as compact UTF-8 JSON, then every ordered row as compact UTF-8 JSON of typed values; each JSON block is prefixed by its 8-byte big-endian byte length. Types: null, bool, int (decimal string), text, float64 (IEEE hex), decimal (text). No deduplication or LIMIT; ORDER BY document source_id.

Column names and every output value are included, including document IDs and repeated rows.
The hash is computed after each timer stops. It is not a count-only or preview comparison.
All returned document IDs are also saved in the JSON evidence.

## Warm measurements

perf_counter immediately before cursor.execute(SQL) through cursor.fetchall(); same unnamed psycopg cursor type with prepare=False for both variants; hashing, plans, index DDL, transaction setup/commit, rendering and file writes are outside query timing.

One warm-up followed by three measured runs per variant, in the order before then after.

| Variant | Warm-up (s, excluded) | Run 1 (s) | Run 2 (s) | Run 3 (s) | Median (s) |
|---|---:|---:|---:|---:|---:|
| Before: index absent | 0.170073 | 0.144770 | 0.166454 | 0.153763 | 0.153763 |
| After: index present | 0.000565 | 0.000505 | 0.000406 | 0.000346 | 0.000406 |

## Basic plans

Before:

```text
Sort  (cost=189387.30..189387.31 rows=1 width=65)
  Sort Key: source_id
  ->  Gather  (cost=1000.00..189387.29 rows=1 width=65)
        Workers Planned: 2
        ->  Parallel Seq Scan on documents d  (cost=0.00..188387.19 rows=1 width=65)
              Filter: ((email_fields @> '{"subject": null}'::jsonb) AND (email_fields_state = 'valid'::text) AND (jsonb_typeof(email_fields) = 'object'::text))
JIT:
  Functions: 4
  Options: Inlining false, Optimization false, Expressions true, Deforming true
```

After:

```text
Sort  (cost=12.60..12.60 rows=1 width=65)
  Sort Key: source_id
  ->  Bitmap Heap Scan on documents d  (cost=8.56..12.59 rows=1 width=65)
        Recheck Cond: ((email_fields @> '{"subject": null}'::jsonb) AND (email_fields_state = 'valid'::text) AND (jsonb_typeof(email_fields) = 'object'::text))
        ->  Bitmap Index Scan on documents_email_object_gin  (cost=0.00..8.56 rows=1 width=0)
              Index Cond: (email_fields @> '{"subject": null}'::jsonb)
```

These are basic EXPLAIN plans, not EXPLAIN ANALYZE. The chosen access and any sorting are
shown above; no planner method was disabled to make the index appear.

## Interpretation and costs

The observed median changed from **0.153763 s** to **0.000406 s** (before/after ratio **378.35**).
The baseline reads the documents relation to evaluate the predicate. With the index, the
planner can use a bitmap index lookup for `@>`, followed by heap checks and source-ID sorting.
The partial predicate excludes missing values and non-object JSON from the index while the
query still runs against the complete table. `jsonb_path_ops` supports this containment
operator; it does not provide the `?` key-existence lookup used elsewhere in Q6.

The rebuilt index occupies **81,920 bytes** (80 KiB). Its separate build took **0.227700 s**; this is excluded from query timings.
Initial creation scans the table and evaluates the predicate even though few rows qualify.
Later writes evaluate the partial predicate; qualifying inserts/updates maintain GIN
entries, and deletes/changed entries require later index cleanup. These write costs are
explained, not measured as another performance experiment.

The three warm repetitions describe this local corpus, query and environment. Building
the index may also warm caches; this prescribed warm comparison does not isolate all cache
effects or establish general production performance.

Primary references: [JSONB operators and index classes](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING),
[CREATE INDEX and locking](https://www.postgresql.org/docs/18/sql-createindex.html),
[REPEATABLE READ](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-REPEATABLE-READ).

## Synthetic safety checks

The isolated tests in `tests/test_z1_queries_db.py` verify complete before/after equality,
identity/multiplicity-sensitive hashes, unchanged other indexes/constraints, and rollback
that restores the original index after a synthetic interruption. They use separate test
schemas and never change the corpus. Run the whole suite with:

```powershell
$env:Z1_DB_TESTS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:Z1_DB_TESTS
```

Actual complete-suite results: [benchmark-tests.json](../evidence/benchmark-tests.json).

Evidence: [benchmark.json](../evidence/benchmark.json), which contains the
before/after plans and timing results.

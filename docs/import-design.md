# Full Z1 importer

Status: implemented. Actual full-load results are in import-report.md; repeat and
synthetic recovery evidence are in evidence/. This
document explains how to implement the [schema proposal](schema-proposal.md)
and satisfy PDF sections 5-6. The checkpoints in archive/C1 are independent.

## Components and responsibilities

Implemented components:

| Component | Responsibility |
|---|---|
| `sql/schema.sql` | Domain tables, audit tables, keys, foreign keys and state CHECK constraints |
| `scripts/z1_transform.py` | Pure, versioned date/JSON/amount/name transformations and issue classification |
| `scripts/import_z1.py` | Verified source iteration, batches, COPY staging, relational resolution, commits and recovery |
| `scripts/validate_z1.py` | Automated source-to-target and database integrity validation, accounting and reports |
| Synthetic transformation and database tests | Required edge cases in separate test data/schema; never appended to the frozen corpus |

Continue using Python, DuckDB, psycopg and PostgreSQL. DuckDB reads verified
Parquet. Python implements our transformations and orchestrates loading.
PostgreSQL stores the final model and enforces integrity. A direct unhandled
Parquet-to-table cast would not satisfy the transformation/error requirements.

## Audit tables

| `z1_audit` table | Important contents and purpose |
|---|---|
| `load_state` | Single current snapshot content fingerprint, schema/transform versions and loading/validating/complete/failed state |
| `source_files` | Original layer/path, repository, revision, size, SHA-256 and source row count; generated file ID is catalog identity only |
| `import_runs` | Our attempt UUID, start/end, command/options, software versions, manifest hash, status and failure stage |
| `import_batches` | File ID, source-row range, counts read/accepted/quarantined/duplicate, attempt FK and committed outcome |
| `import_issues` | Source locator, field/code/severity, safe explanation and target locator; multiple issues may describe one accepted row |
| `quarantined_rows` | One source locator and failure classification per rejected source record; the immutable source is the complete recoverable raw record |
| `duplicate_rows` | Source locator, existing target/source locator, equal-record fingerprint and explicit duplicate reason |

Domain rows reference the catalog file and the run that first loaded them. Audit
records keep source layer + pinned file + original ID/physical row location.
Do not put full document text, personal names, or credentials in exported logs.
Quarantine pointers are sufficient to retrieve the immutable original; a local
database error payload may include limited problematic raw values when necessary,
but public reports contain IDs/positions, reason codes and aggregate counts.

## Processing order and memory

1. Verify all manifest files/hashes/sizes/rows using `load_manifest(verify=True)`.
2. Verify actual PostgreSQL connection identity/version and acquire a session
   advisory lock so two imports cannot process the same schema simultaneously.
3. Check load identity/schema versions; initialize an empty working schema and
   audit catalog if absent. Never reset existing tables automatically.
4. Load parents: documents, persons, KG nodes, events, upstream runs.
5. Load dependent layers: chunks, mentions, KG edges, event participants, event
   sources, financial transactions, curated annotations, upstream files. Emit
   person aliases and curated alternate links with their respective parent batch.
6. Validate the entire load before marking it complete, then build justified
   query indexes and run ANALYZE. A chosen benchmark index is managed separately.

Read one exact manifest-listed file at a time. Use DuckDB
`read_parquet(path, file_row_number=true)` and physical row number + 1 for
traceability, not a counter dependent on unspecified query output order.
Use single-file Parquet SELECT/WHERE with threads=1 and preserve_insertion_order=true;
no full-shard ORDER BY is needed. Resume after the last committed physical
range and verify every physical row number for continuity before committing. The installed
DuckDB returns physical row numbers 0..1613 for the 1,614-row persons shard;
other files must be checked too. [DuckDB Parquet options](https://duckdb.org/docs/current/data/parquet/overview.html).

Fetch small chunks with `fetchmany`, never `fetchall` for the full corpus. Start
with a configurable ceiling of 2,000 rows and approximately 16 MiB of serialized
payload per write batch. Text-heavy layers need a byte ceiling as well as row
count. One exceptionally large row may exceed that byte target and must be
handled separately with a recorded size; this is not an absolute process-memory
guarantee. DuckDB also has a memory limit and an on-disk spill directory.

Do not load all document IDs or 10.6 million mentions into Python dictionaries.
A temporary indexed document-length cache computes each parent length once for
chunk offset diagnostics. It avoids repeatedly decompressing the same large text.
COPY each bounded batch to a temporary staging table, then resolve references
through SQL joins against indexed parent keys. Use explicit column lists,
parameterized values and psycopg.sql identifiers; do not construct SQL from
source values. [psycopg COPY documentation](https://www.psycopg.org/psycopg3/docs/basic/copy.html).

## One batch transaction

```text
begin transaction
    COPY transformed rows into temporary staging
    resolve required and optional parent references using SQL joins
    classify every source row exactly once
    insert accepted source rows and their derived rows
    insert issues, quarantine and duplicate evidence
    record batch counts and committed source-row range
commit transaction
```

The audit checkpoint and domain rows must commit together. A progress message
printed to the console is not a checkpoint. If a batch fails, roll it back
entirely, so no record can be committed without corresponding accounting.

Classify expected data problems before COPY to typed targets. Required-key or
required-parent failure quarantines the whole source row. Optional metadata
errors keep a row accepted, with raw value, NULL parsed value, error state and
issue. For example, an invalid email JSON value does not erase a valid document.
Valid but uncertain dates and unresolved optional references are also accepted
with explicit states and issues. Source upstream failures remain source status
values, not automatically errors in our importer.

COPY staging is a transport optimization, not a substitute for validation. If
an unexpected database constraint violation occurs, roll back and stop with an
actionable error. Do not broadly catch exceptions and quietly count a programming
bug as a rejected source record. The implementation must handle PostgreSQL text
limitations (for example NUL) explicitly and preserve a source pointer if a whole
row cannot be represented. [PostgreSQL constraints](https://www.postgresql.org/docs/18/ddl-constraints.html).

## Accounting and duplicate policy

For a complete source snapshot and each individual layer:

```text
N_read = N_accepted + N_quarantined + N_duplicate
```

These are disjoint source-row dispositions. Ten issues on one accepted document
still count as one accepted source row. A parent row that emits five aliases
counts once as accepted; five derived target rows are reported separately.

Duplicate means the same layer identity with the same canonical raw source
payload already exists. An identical repeated source record is counted as
duplicate with a pointer to the existing target. Same identity with different
payload is an identity conflict and is quarantined, not overwritten. Fingerprints
use a documented canonical serialization including field names/types, SQL NULL,
original strings and float bits; source row position is not part of payload
equality. SHA-256 collisions are not treated as proof if an actual key conflict
requires a full value comparison.

Repeated names, repeated transaction document keys, repeated curated file keys,
and repeated provenance file keys with different output names are legitimate
records. They must not be deduplicated by those non-unique fields.

Report cumulative unique source coverage and per-attempt committed activity separately.
Attempt counters come from committed batches; work rolled back after interruption is
replayed and does not count as another committed source disposition.
A resumed or repeated invocation skips committed ranges; skipped rows are not
newly read rows or newly discovered source duplicates. For a completed no-op
attempt, newly read/accepted/quarantined/duplicate counts can all be zero, with
15,725,373 source rows reported as previously processed. The cumulative load
still reconciles every prescribed row against the manifest.

## Idempotency and interrupted work

Idempotency means repeating the same import does not change domain records or
create more aliases, links, issues or source dispositions. A new audit attempt
is allowed; timestamps and attempt logs are not domain data. Run scripts/prove_z1_repeat.py
for the full-table hash comparison; it holds the import lock for the entire proof.

Load identity is a canonical hash of repository, revision and sorted shard
paths/content hashes/row counts plus schema and transformation versions.
Acquisition timestamps are excluded: rerunning download can change manifest
metadata while leaving source contents identical. Record the actual manifest
hash in each run as evidence without using it alone as domain identity.

Enforce source primary/unique keys, derived array-position keys and audit
source-location keys in PostgreSQL. The single-import lock, committed batch
ledger and active constraints work together; `ON CONFLICT DO NOTHING` alone is
insufficient because it can hide conflicting data.

| Interruption or repeat | Required behavior |
|---|---|
| Process dies before batch commit | PostgreSQL rolls back the batch; replay the whole uncommitted range |
| Process dies after commit but before console progress | Ledger shows completion; skip it on resume |
| Process dies during final validation | Committed data remains in loading/validating state; rerun validation before complete |
| Same input and code versions run again | Verify source; skip committed work; rerun final checks; domain counts/hashes unchanged |
| Different source or schema/transform version | Refuse to mix versions; require a separately documented, explicit rebuild of the named working schema |

A held session advisory lock is released when the connection ends. A prior run
can remain marked running after a crash; after acquiring the lock, the next
attempt marks that prior attempt interrupted and uses only committed ledger
entries for recovery. Connection/server failures must not leave a false complete
status. No Docker volume reset or C1 database manipulation is part of this design.

## Validation and proof required before claiming completion

1. Source coverage: every file covers physical rows 1..manifest row_count exactly
   once across non-overlapping committed ranges; no omissions or extra rows.
2. Accounting: each layer equation balances and N_read equals its prescribed
   complete-source count in cumulative load evidence.
3. Target counts: accepted source rows agree with corresponding source-row target
   tables; derived alias/link counts are reconciled separately to valid arrays.
4. Keys and references: PK/UNIQUE/CHECK/FK constraints exist; pg_constraint shows
   active, validated constraints, with no disabled enforcement triggers. Explicit
   anti-joins find zero invalid nonnull references.
5. Transformations: raw values/states remain traceable, money sign and NULL are
   preserved, JSON null differs from SQL NULL, and precision/timezone rules hold.
6. Repeat proof: compare domain counts and deterministic ordered content hashes
   before/after a second invocation, excluding run metadata. Confirm no extra
   derived rows or issue records. Re-run full validation even on a skipped load.
7. Recovery proof: inject a controlled failure before commit and after commit in
   an isolated synthetic fixture; resume and compare to uninterrupted output.
8. Required synthetic cases: invalid calendar date, invalid JSON versus SQL NULL,
   JSON null/key absence, nonexistent document reference, identical repeated row,
   conflicting repeated identity and direct DB rejection of a bad nonnull FK.
   Keep test rows separate from the frozen source and final domain schema.

Success produces `docs/import-report.md` and small JSON evidence with actual
counts, issues and constraint checks. Version/options metadata are in z1_audit.import_runs.
The separate repeat script produces evidence/import-repeat.json, and isolated integration
tests cover before/after commit recovery, identical repeats, conflicts and DB FK rejection.
The importer also recovered from a real DuckDB memory-limit failure after committed document
shards; the whole-shard sort was removed and committed shards were skipped on resume.

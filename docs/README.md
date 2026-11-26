# Z1 documentation

The root [README](../README.md) contains environment setup and execution commands.
Project reports live in this directory. Run their commands from the project root.
Keep the original downloaded documentation in `data/` unchanged.

## Current reports

| Report | Purpose |
|---|---|
| [requirements-checklist.md](requirements-checklist.md) | Audit of completed, partial and outstanding PDF requirements |
| [data-profile.md](data-profile.md) | Measured source schemas, counts, missing values, candidate keys, duplicates and reference candidates |
| [source-review.md](source-review.md) | Important findings and proposed decisions for the full relational model |
| [schema-proposal.md](schema-proposal.md) | Implemented tables, keys, relationships, types and measured reasons; includes an ER diagram |
| [data-mapping.md](data-mapping.md) | Implemented field-by-field mapping for all 147 source fields across 13 layers |
| [import-design.md](import-design.md) | Batch importer, error accounting, idempotency, recovery and validation |
| [import-report.md](import-report.md) | Actual full-load row accounting, derived counts, FK checks and issue aggregates |
| [queries-and-indexes.md](queries-and-indexes.md) | Q1-Q6 semantics, reproducible commands, four justified indexes, costs and full-corpus query evidence |
| [benchmark.md](benchmark.md) | Section 8: full documents-layer Q6 JSON comparison, complete-result equivalence, warm-up/three timings, medians, plans and index costs |
| [extension.md](extension.md) | Section 9 R2: materialized financial report, full Q4 comparison, refresh/staleness/repeat/rollback demonstration and costs |
| [ai-report.md](ai-report.md) | Concise section 10: tool/model/date/purpose, prompts, one verified materialized-view claim and its refinement, adopted parts and decisions |

## Current scripts and tests

| File | Purpose |
|---|---|
| [download_z1.py](../scripts/download_z1.py) | Selects the prescribed inventory at the fixed revision, downloads all inputs and builds the manifest; `--verify-only` checks them offline |
| [z1_source.py](../scripts/z1_source.py) | Independent source contract: repository, full revision, expected shards and rows, allowed paths, manifest and hash validation |
| [profile_z1.py](../scripts/profile_z1.py) | Reads every prescribed shard through DuckDB, computes metadata/aggregate diagnostics and writes the profile and evidence |
| [analyze_z1.py](../scripts/analyze_z1.py) | Additional offline schema-design checks for keys, offsets, JSON shapes, dates/time zones, currencies and document metadata disagreements |
| [z1_model.py](../scripts/z1_model.py) | Explicit model for all source fields; emits DDL and independent SQL source-fingerprint expressions |
| [schema.sql](../sql/schema.sql) | Reviewable full relational DDL generated from the model |
| [z1_transform.py](../scripts/z1_transform.py) | Versioned date/JSON/money/name rules and source fingerprints |
| [z1_db.py](../scripts/z1_db.py) | Reads local database settings without logging credentials |
| [import_z1.py](../scripts/import_z1.py) | Bounded COPY staging, reference resolution, errors, ledger and atomic commits/resume |
| [validate_z1.py](../scripts/validate_z1.py) | Full accounting/coverage, original-field fingerprints, amount precision and actual constraint checks |
| [prove_z1_repeat.py](../scripts/prove_z1_repeat.py) | Full-content before/after repeat proof, excluding audit attempt metadata |
| [trace_z1.py](../scripts/trace_z1.py) | Demonstrates exact original-field trace from a source ID to target, with no source text output |
| [queries.sql](../sql/queries.sql) | Complete Q1-Q6 plus financial/JSON drill-down variants; source IDs and deterministic ordering |
| [query-indexes.sql](../sql/query-indexes.sql) | pg_trgm and four auxiliary indexes covering B-tree, composite, FTS/trigram GIN and a custom partial JSONB index |
| [z1_workload.py](../scripts/z1_workload.py) | Shared SQL/parameters, live index checks, bounded complete-result hashing and basic plan capture |
| [setup_z1_queries.py](../scripts/setup_z1_queries.py) | Installs/verifies the extension and indexes; records actual sizes and build costs |
| [run_z1_queries.py](../scripts/run_z1_queries.py) | Executes the full workload or a parameterized demonstration; saves default full-result evidence |
| [benchmark_z1.py](../scripts/benchmark_z1.py) | Temporarily removes/rebuilds one auxiliary index, measures the fixed Q6 JSON query, verifies complete results and generates benchmark evidence/report |
| [extension.sql](../sql/extension.sql) | Financial materialized-view definition, refresh command and sorted read |
| [extend_z1.py](../scripts/extend_z1.py) | Creates/reuses, refreshes and verifies the full financial report; check-only and separate synthetic staleness demo modes |
| [check_z1_ai_claim.py](../scripts/check_z1_ai_claim.py) | Optional additional check of stale-report behavior on separate synthetic data; saves whole-result evidence |
| [test_z1_transform.py](../tests/test_z1_transform.py) | Synthetic missing/invalid JSON, dates, money, normalization and content-identity tests |
| [test_z1_import_db.py](../tests/test_z1_import_db.py) | Isolated database integrity, duplicate/conflict accounting and before/after commit recovery tests |
| [test_z1_source.py](../tests/test_z1_source.py) | Rejects missing shards, duplicate inventory entries and unwanted parallel exports |
| [test_z1_profile.py](../tests/test_z1_profile.py) | Checks missing/unmatched/ambiguous reference accounting and preservation of repeated processing occurrences |
| [test_z1_queries_db.py](../tests/test_z1_queries_db.py) | Separate synthetic query semantics, index equivalence/repeated creation, benchmark result checks and index rollback after failure |
| [test_z1_extension_db.py](../tests/test_z1_extension_db.py) | Synthetic R2 stale/refresh/repeat/rollback, amount/currency semantics, fixed scope and conflicting-object/definition rejection |
| [00_docker_existing_volume.sql](../sql/00_docker_existing_volume.sql) | One-time repair for the earlier Docker initialization: creates a normal login and database while preserving existing data; not the final schema/importer |

## Configuration and evidence

| File | Purpose |
|---|---|
| [compose.yaml](../compose.yaml) | PostgreSQL version, environment, port, persistent volume and health check |
| [.env.example](../.env.example) | Configuration template; the real `.env` is private and ignored |
| [requirements.txt](../requirements.txt) | Pinned Python dependencies |
| [.gitignore](../.gitignore) | Excludes data, credentials, environments and caches; allows the full manifest and aggregate evidence |
| [source-manifest.json](../source-manifest.json) | Repository, revision, acquisition metadata, tool version, 56 shard paths/hashes/sizes/counts and source-documentation hashes |
| [source-validation.json](../evidence/source-validation.json) | Result of the last successful offline input validation |
| [source-profile.json](../evidence/source-profile.json) | Structured measured statistics underlying the Markdown profile |
| [schema-analysis.json](../evidence/schema-analysis.json) | Additional measured aggregates behind the schema proposal |
| [import-tests.json](../evidence/import-tests.json) | Actual synthetic transformation, integrity and fresh-connection recovery test results |
| [import-trace.json](../evidence/import-trace.json) | Exact original-field traces for document and chunk ID 1 |
| [import-validation.json](../evidence/import-validation.json) | Actual cumulative source accounting, target counts, original-field and constraint checks |
| [import-repeat.json](../evidence/import-repeat.json) | Identical full contents before/after repeat, with zero newly read source rows |
| [import-recovery.json](../evidence/import-recovery.json) | Real interruption/resume history and runtime versions |
| [query-indexes.json](../evidence/query-indexes.json) | Actual full-table index definitions, sizes and measured build durations |
| [query-results.json](../evidence/query-results.json) | Complete default result hashes, financial/JSON accounting and basic EXPLAIN plans |
| [query-tests.json](../evidence/query-tests.json) | Actual complete-suite results including seven synthetic section 7 query tests |
| [query-tests.txt](../evidence/query-tests.txt) | Readable complete-suite execution log |
| [query-index-repeat.json](../evidence/query-index-repeat.json) | Repeated setup preserved index identities, definitions and sizes |
| [benchmark.json](../evidence/benchmark.json) | Full-input section-8 comparison: all timings/hashes, source counts, environment, exact SQL/DDL, plans and unchanged catalog controls |
| [benchmark-before-plan.txt](../evidence/benchmark-before-plan.txt) | Basic EXPLAIN without the selected auxiliary index |
| [benchmark-after-plan.txt](../evidence/benchmark-after-plan.txt) | Basic EXPLAIN with the selected auxiliary index |
| [benchmark-tests.json](../evidence/benchmark-tests.json) | Actual 25-test complete-suite result, including benchmark safety/equivalence tests |
| [benchmark-tests.txt](../evidence/benchmark-tests.txt) | Readable complete-suite execution log |
| [extension.json](../evidence/extension.json) | Actual full financial materialization and complete Q4 equality, source counts, SQL/environment, refresh cost and storage |
| [extension-input-before.json](../evidence/extension-input-before.json) | Pre-extension constraint/index catalog and complete financial source fingerprint snapshot |
| [extension-repeat.json](../evidence/extension-repeat.json) | Actual repeated full refresh preserved the same report/result, financial source and original indexes/constraints |
| [extension-staleness.json](../evidence/extension-staleness.json) | Separate synthetic stale/refresh/repeat/rollback demonstration with all whole-result hashes |
| [extension-tests.json](../evidence/extension-tests.json) | Actual 28-test complete-suite results, including three R2 tests |
| [extension-tests.txt](../evidence/extension-tests.txt) | Readable complete-suite execution log |
| [ai-claim-check.json](../evidence/ai-claim-check.json) | Actual unused-field/offsetting-change counterexamples, changed-source observations and whole-result equality before/after refresh |

## Remaining work

DDL, the model/mapping, importer, validation, section 7 workload, section 8 benchmark
and section 9 R2 are implemented. `ai-report.md` is finalized with the recorded
review, available model/date metadata and an actual verified claim refinement.
Defense and final submission preparation remain.

The separate historical project in `archive/C1/` is excluded from final Z1 execution,
tests, and submission. No full-project script imports its code or reads its outputs.

# Z1: Parquet to PostgreSQL

**Author:** Stroievskyi Daniil.

This project is being developed for the full Z1 assignment from an empty PostgreSQL working
database, using the 56 prescribed shards across all 13 source layers. The source
revision is fixed to `133ef9f0a539fafc270cde8fa8638dc38d89968d` in
`kabasshouse/epstein-data`.

## Implementation status

Download, manifest validation, profiling, the relational model and the full ETL
are implemented. See [the model](docs/schema-proposal.md),
[field mapping](docs/data-mapping.md), [importer design](docs/import-design.md)
and [import report](docs/import-report.md) for decisions and measured validation.
Section 7 queries and auxiliary workload indexes are implemented; see
[queries and indexes](docs/queries-and-indexes.md) for semantics and actual evidence.
The section 8 full-input benchmark is implemented and measured; see
[benchmark](docs/benchmark.md). The section 9 R2 materialized financial report is
implemented and verified; see [extension](docs/extension.md).
The [AI report](docs/ai-report.md) is finalized with the available model/date
information, recorded student review and an actual verified/refined claim.
The final source commit, ZIP generation and individual defense remain.

## Project layout

- `scripts/`: independent full Z1 download, profiling, ETL, validation and repeat proof.
- `tests/`: source/profiling, transformation and isolated database integrity/recovery tests.
- `sql/`: full-project SQL and Docker setup utilities.
- `source-manifest.json`: complete pinned source inventory, hashes, sizes and counts.
- `docs/`: project reports, including the data profile, model mapping, import report,
  benchmark, extension and AI report.
- `evidence/`: metadata-only evidence from the full source.
- `data/`: ignored original source files and profiling scratch space.

The historical checkpoint is isolated in `archive/C1/`, with its own documentation,
scripts, SQL, tests, dependencies and local data. It is excluded from the final
project's execution and test commands. Final Z1 does not import its modules, use its
sample selection, or read its manifest, evidence or local data. Exclude `archive/`
from the final Z1 submission package.

## Environment

The current full-project environment uses:

- Docker image: `postgres:18.3-bookworm` (PostgreSQL 18.3 on Debian/Linux).
- Python: 3.13.7.
- DuckDB: 1.5.5.
- psycopg: 3.3.6.
- huggingface_hub: 1.31.0.

Install dependencies:

```powershell
# On a fresh checkout, create the virtual environment first:
if (-not (Test-Path -LiteralPath .venv)) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

## PostgreSQL with Docker

Requirements: Docker Desktop with Docker Compose. Create the configuration file if
it does not exist, set its password, validate the configuration and start PostgreSQL:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
# Edit .env and set POSTGRES_PASSWORD.
docker compose config --quiet
docker compose up -d
docker compose ps
```

The database is `dbs2`, user `postgres`, at `localhost:5432`. The `.env` file is
private and ignored by Git. Database and user settings initialize a new volume;
changing them does not rename an existing volume's users or databases. The provided
`sql/00_docker_existing_volume.sql` repairs the earlier Docker initialization without
deleting existing data; it is a Docker setup utility, not part of the data importer.

If the original Windows PostgreSQL service occupies port 5432, stop it from an
Administrator PowerShell before starting the Docker instance:

```powershell
Stop-Service -Name postgresql-x64-18 -ErrorAction Stop
```

Check server identity:

```powershell
docker compose exec postgres psql -U postgres -d dbs2 -c "SELECT current_database(), current_user, version();"
```

The Docker server version identifies Debian/Linux. Stop the container with
`docker compose stop`; restart with `docker compose up -d`. The named volume
preserves database contents. `docker compose down -v` deletes that storage.

## Full input and profiling

```powershell
.\.venv\Scripts\python.exe .\scripts\download_z1.py
.\.venv\Scripts\python.exe .\scripts\download_z1.py --verify-only
.\.venv\Scripts\python.exe .\scripts\profile_z1.py
.\.venv\Scripts\python.exe .\scripts\analyze_z1.py
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
```

Only the download command needs network access. The downloader uses its own explicit
56-shard inventory, excludes parallel exports, verifies content against the pinned
repository's recorded hashes, and preserves the three source documentation files.
The manifest is generated only after inventory, hashes, and row totals pass checks.
Interrupted downloads can be rerun against the same pinned revision; completed
immutable source files may be reused from the download library's local cache.

Verification and profiling work offline. Verification checks every file's inventory
membership, content SHA-256, byte size and row count against the full manifest and
writes `evidence/source-validation.json`.

The profile uses a 512 MB DuckDB memory limit with scratch space under `data/work/`.
It outputs schemas and aggregates without document text or person names. Equality
of source IDs alone does not prove a shared namespace or a correct identity link.
All final-project source selection is manifest-based rather than an unrestricted
`*.parquet` glob.

Keep project reports in `docs/` with the filenames required by the assignment.
The root README provides the entry point. The downloaded source `README.md` and
`PROVENANCE.md` stay unchanged under `data/` because their paths and content are
recorded in the manifest.

## Full ETL, validation and safe repetition

Run against the working database configured in `.env`:

```powershell
.\.venv\Scripts\python.exe scripts/import_z1.py
.\.venv\Scripts\python.exe scripts/validate_z1.py
.\.venv\Scripts\python.exe scripts/prove_z1_repeat.py
```

The importer creates `z1` and `z1_audit` on its first invocation. It verifies all
source files first, then streams bounded batches (default 2,000 rows / approximate
16 MiB payload), resolves references and commits data with its progress ledger.
Re-running the same command resumes committed work; completed loads skip all
source ranges and revalidate. Different source/schema/transformation versions are
refused. It never resets the database or Docker volume automatically.

The standalone `sql/schema.sql` is reviewable DDL generated from `scripts/z1_model.py`;
let the importer initialize its schema and catalog together instead of running the
DDL manually before the first import. Source acquisition timestamps are excluded
from load identity. The original source strings, IDs and IEEE floating values are
retained and compared through independently reconstructed fingerprints.

Database tests use random `z1_test_*` and `z1_query_test_*` schemas containing only synthetic records,
then remove those exact test schemas. They do not insert test rows into `z1`:

```powershell
$env:Z1_DB_TESTS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:Z1_DB_TESTS
```

To demonstrate one source-to-target trace without printing source text:

```powershell
.\.venv\Scripts\python.exe scripts/trace_z1.py --layer documents --id 1
```

Counts and issues are in `docs/import-report.md` and `evidence/import-validation.json`.
The repeat proof compares complete stored domain contents and source dispositions,
with evidence in `evidence/import-repeat.json`. Audit attempt timestamps are allowed
to change; domain records, aliases, links and issue records are not.

## Section 7 queries and indexes

After a complete import, install the query extension/indexes and run the workload:

```powershell
.\.venv\Scripts\python.exe scripts/setup_z1_queries.py
.\.venv\Scripts\python.exe scripts/run_z1_queries.py
```

The SQL is in `sql/queries.sql` and `sql/query-indexes.sql`. Setup safely reuses
existing matching indexes; it installs `pg_trgm`, then records sizes and build
durations in `evidence/query-indexes.json`. Complete query-result hashes, aggregate
checks and basic plans are in `evidence/query-results.json`. These are section 7
correctness checks, not the prescribed section 8 warm benchmark.

For a presentation, show a few rows while still checking the complete result:

```powershell
.\.venv\Scripts\python.exe scripts/run_z1_queries.py --query Q2 --name "Jeffrey Epstien" --threshold 0.3 --show-rows 5
.\.venv\Scripts\python.exe scripts/run_z1_queries.py --query Q4_FILTER --currency USD --merchant FedEx --show-rows 5
.\.venv\Scripts\python.exe scripts/run_z1_queries.py --query Q6_JSON --show-rows 5
```

The [workload report](docs/queries-and-indexes.md) explains all six questions, the
financial/JSON drill-down variants, normalization, path multiplicity, currency and
JSON semantics, index categories/opclasses and write costs. Synthetic query tests
run with the same `Z1_DB_TESTS=1` command above and need no source download.

## Section 8 full-input benchmark

After section-7 setup, run one prescribed warm comparison:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_z1.py
```

It benchmarks `Q6_JSON`, the Q6 drill-down for explicit JSON null subjects, against
all accepted documents. It removes only `documents_email_object_gin`, runs one
warm-up and three measured repetitions, recreates the same index, and repeats the
same protocol. It compares the complete ordered results, keeps all constraints and
other indexes active, and leaves the index present. A failed transaction restores
the original index. Run while the database is idle: the index DDL locks documents
during the comparison. No import runs concurrently.

Query timers stop after the last row is fetched; hashing, printing, file writes and
index building are excluded. All times, medians, full-result checks, basic plans,
index size, environment and interpretation are in [benchmark.md](docs/benchmark.md)
and `evidence/benchmark.json`. Repeat the command offline to regenerate them.
The section-8 complete test suite passed 25 tests, including isolated benchmark
equivalence and interruption/rollback tests; see `evidence/benchmark-tests.json`.

## Section 9 R2 materialized financial report

```powershell
# Create/reuse the report, refresh it, then verify every group against full Q4.
.\.venv\Scripts\python.exe scripts/extend_z1.py
# Verify without refreshing.
.\.venv\Scripts\python.exe scripts/extend_z1.py --check-only
# Demonstrate stale data and refresh on separate synthetic data; no download needed.
.\.venv\Scripts\python.exe scripts/extend_z1.py --demo
```

The stored `z1.financial_report` has one row per currency/normalized merchant
label, with amount-state/sign counts and the exact valid amount sum. It covers all
49,770 financial records and matches Q4's complete 18,392-group result. Changes
that alter the reported aggregates leave it stale until refresh. The demo proves this, as well as repeated
refresh and transaction rollback, in its own temporary schema.

SQL is in `sql/extension.sql`; decisions, measured evidence, update costs and
supervisor commands are in [extension.md](docs/extension.md). The latest complete
suite passed 28 tests; see `evidence/extension-tests.json`. Original corpus records,
constraints and section-7 indexes are preserved. Only R2 is implemented.

## Section 10 AI report and defense

The concise [ai-report.md](docs/ai-report.md) contains tool/model/date/purpose,
representative prompts, one claim in the required five-column table, adopted and
corrected parts, and recorded student decisions. The materialized-view claim is
refined using the saved synthetic evidence: some source edits preserve the report
result, while changes to the aggregate make it stale until refresh.

## Section 11 submission

Submit **one ZIP to the Z1 item in Teams**, named `Z1_Stroievskyi_Daniil.zip`.
It contains the root README, requirements, Docker configuration, `.env.example`,
`.gitignore`, source manifest, and the `scripts/`, `sql/`, `tests/`, `docs/` and
small `evidence/` files. Reports retain their required filenames under `docs/`.
The original dataset, database dump, real `.env`, virtual environment, caches,
Git history, assignment PDF and historical C1 archive are excluded.

Commit the full Z1 source, then create the archive for Teams using the committed
source files. Do not commit the archive itself:

```powershell
git add -A
git commit -m "Complete full Z1"
```

The ZIP must contain the root README, requirements, Docker configuration,
`.env.example`, `.gitignore`, source manifest, scripts, SQL, tests, reports and
small evidence files. Exclude the dataset, database dump, `.env`, virtual
environment, caches, Git history, PDF and C1 archive. Later source/report/evidence
changes require a new commit before creating a new submission ZIP.
C1 belongs in its separate Teams submission. The individual defense is separate
from uploading this source archive.

## Data safety

Do not commit source data, database dumps, credentials, virtual environments or caches.
The manifest and small aggregate evidence are included in the full project. Source
files remain unchanged; synthetic test records are separate from the source corpus.

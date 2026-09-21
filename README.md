# Z1 checkpoint C1: Parquet to PostgreSQL

## Original local setup notes

Method: local PostgreSQL installation.

- Server version: PostgreSQL 18.3 on x86_64-windows, compiled by
  msvc-19.44.35223, 64-bit.
- Working database: `dbs2`.
- Reproducibility: existing local PostgreSQL server, connected through pgAdmin 4
  on the default port 5432.
- Python environment: Python 3.13.7 with `huggingface_hub` 1.31.0.
- DuckDB version: 1.5.5.

Install the original requirements with:

```powershell
pip install -r .\requirements.txt
```

Explore the downloaded Parquet files with DuckDB:

```powershell
.\.venv\Scripts\python.exe .\scripts\explore_duckdb.py
```

The versioned download uses `hf_hub_download` with:

```python
from huggingface_hub import hf_hub_download

REPO_ID = "kabasshouse/epstein-data"
REVISION = "133ef9f0a539fafc270cde8fa8638dc38d89968d"

files = [
    "data/documents/documents-00000-of-00015.parquet",
    "data/chunks/chunks-00000-of-00011.parquet",
]

for filename in files:
    path = hf_hub_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        filename=filename,
        revision=REVISION,
        local_dir="./data",
    )
    print("Downloaded:", path)
```

Analyse the files with:

```powershell
py .\scripts\explore_duckdb.py
```

## C1 implementation

This repository implements the small C1 checkpoint from `assignment.md`. It does not
attempt the later, full 13-layer Z1 import. The checkpoint write-up is `C1/run.md`.

## What the checkpoint demonstrates

The pipeline downloads two immutable Parquet shards, selects `c1-sample-v1`
deterministically, imports it into a relational PostgreSQL model, verifies relational
integrity, and compares PostgreSQL full-text search before and after a compatible GIN
index is added.

Pinned source:

- dataset: `kabasshouse/epstein-data`
- revision: `133ef9f0a539fafc270cde8fa8638dc38d89968d`
- document shard: `data/documents/documents-00000-of-00015.parquet`
- chunk shard: `data/chunks/chunks-00000-of-00011.parquet`

The two currently downloaded files were inspected with DuckDB. They contain 100,000
documents and 200,000 chunks. The deterministic checkpoint selection has exactly 1,000
documents (source IDs 1 through 1,000) and 160 chunks referring to 157 documents.

## Relational model

`c1_checkpoint.documents` stores one source document per row. Its source `id` is kept as
the `BIGINT` primary key `source_id`; `file_key` is also unique. `dataset` and
`document_type` retain the required source metadata. `document_type` remains nullable
because it is missing in some source rows.

`c1_checkpoint.chunks` stores one source text chunk per row. Its source `id` is the
primary key. `document_source_id` is a real, validated foreign key to the document
table. `(document_source_id, chunk_index)` is unique, preserving the meaning of a
chunk's position within its document.

Using source IDs directly avoids an unnecessary surrogate-ID mapping for this fixed
revision. A larger multi-source design could add internal IDs while keeping these
source IDs under a source/revision-scoped unique constraint.

## Setup and execution

Prerequisites are Python 3.13 and a running PostgreSQL server. The defaults match the
local setup recorded for this repository: database `dbs2`, user `postgres`, host
`localhost`, port `5432`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe .\scripts\data_download.py
.\.venv\Scripts\python.exe .\scripts\manifest_c1.py
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
```

Give libpq the local password only for the current shell; never commit it:

```powershell
$env:PGPASSWORD = "your local PostgreSQL password"
.\.venv\Scripts\python.exe .\scripts\import_c1.py --rebuild
.\.venv\Scripts\python.exe .\scripts\verify_c1.py
Remove-Item Env:PGPASSWORD
```

If the connection differs, pass a DSN without putting a password in the repository:

```powershell
.\.venv\Scripts\python.exe .\scripts\import_c1.py --rebuild --dsn "host=localhost port=5432 dbname=dbs2 user=postgres"
.\.venv\Scripts\python.exe .\scripts\verify_c1.py --dsn "host=localhost port=5432 dbname=dbs2 user=postgres"
```

`--rebuild` is mandatory because the importer intentionally drops and recreates only
the dedicated `c1_checkpoint` schema. A second run therefore cannot silently duplicate
rows.

## Required FTS/GIN experiment

The experiment uses the required predicate:

```sql
to_tsvector('english', coalesce(content, ''))
@@ plainto_tsquery('english', 'flight')
```

It first removes the checkpoint's optional FTS index, saves the complete ordered
`(chunk_id, document_id)` result and basic `EXPLAIN`, creates the expression GIN index,
and repeats both. It fails if any result pair or its order changes. On the recorded run
the plan changed from Seq Scan + Sort to Bitmap Index Scan on the GIN + Bitmap Heap
Scan + Sort; the planner was not forced either way, and a sequential scan would also
have been acceptable on 160 rows. The script also verifies one AI-generated claim — that no
sample chunk contains the substring `flight`, so the empty result is genuine — with an
`ILIKE` count on the table (`C1/evidence/ai_claim_check.txt`).

The procedure, field mapping, named plans, design lines and the verified AI claim are
written up in `C1/run.md`; `C1/manifest.tsv` records repo, revision, paths and SHA-256
of the two source files. The human-readable SQL is in `sql/02_c1_queries.sql` (search)
and `sql/03_c1_checks.sql` (integrity checks).

For the literal comparison, FTS works with parsed and English-normalized lexemes, while
`ILIKE '%flight%'` searches a raw character substring. Consequently, `flight` and
`flights` match the same FTS lexeme, whereas `preflight` contains the substring but is
not the separate FTS lexeme `flight`.

## Data safety

The Parquet files, generated databases, dumps, credentials, and environment files are
ignored by Git. Evidence contains only source IDs, counts, query plans, and index
metadata—no document or chunk text.

# Section 7: queries and indexes

This workload is independent of C1 and uses the full imported Z1 corpus. The
source revision is `133ef9f0a539fafc270cde8fa8638dc38d89968d`. Rejected source
records remain accounted for in the import report; queries use accepted target
records. No subset database, text truncation, or invented corpus rows are used.

## Reproduce

After the complete ETL and validation, run from the project root:

```powershell
.\.venv\Scripts\python.exe scripts/setup_z1_queries.py
.\.venv\Scripts\python.exe scripts/run_z1_queries.py
```

Setup installs `pg_trgm` in `public`, builds four auxiliary indexes, records
actual sizes and client-observed build durations, and refreshes table statistics.
The configured database owner can install this trusted extension. Setup is
repeatable: it checks existing index definitions instead of blindly accepting a
name collision, and preserves previously measured build times for unchanged
indexes. It does not rebuild the input or reset any schema.
The actual repeated-setup proof is [query-index-repeat.json](../evidence/query-index-repeat.json):
all four index OIDs, definitions and sizes were unchanged.

Both commands verify the frozen input and require the full load to be complete.
They use the importer advisory lock to prevent overlap with import. The query
runner uses one read-only, repeatable-read transaction and bounded result fetches.
It hashes every returned row, not just a count or preview. Results and basic
EXPLAIN plans are in [query-results.json](../evidence/query-results.json).
There is no LIMIT in the SQL. `--show-rows` limits only console previews:

```powershell
.\.venv\Scripts\python.exe scripts/run_z1_queries.py --query Q1 --fts aircraft --show-rows 5
.\.venv\Scripts\python.exe scripts/run_z1_queries.py --query Q2 --name "Jeffrey Epstien" --threshold 0.3 --show-rows 5
.\.venv\Scripts\python.exe scripts/run_z1_queries.py --query Q3 --kg-start 1 --show-rows 5
.\.venv\Scripts\python.exe scripts/run_z1_queries.py --query Q4_FILTER --currency USD --merchant FedEx --show-rows 5
.\.venv\Scripts\python.exe scripts/run_z1_queries.py --query Q6_JSON --show-rows 5
```

Custom demonstrations do not overwrite the default complete-workload evidence.
`verification_seconds` includes client result hashing and is **not** the section-8
benchmark. The prescribed warm-up/three-run comparison is implemented separately
in [benchmark.md](benchmark.md), using Q6_JSON and its partial JSONB GIN index.

## Questions and meaning

The reviewable, independently executable SQL is [queries.sql](../sql/queries.sql).
With `pg_trgm` installed, it can also be executed directly in a SQL client.
Optional session settings use the `z1.*` namespace; the Python CLI sets them with
bound parameters. The raw SQL defaults work in a fresh connection.

| Query | Parameters and result | Interpretation and limits |
|---|---|---|
| Q1 | Default input `aircraft`; complete chunk source IDs, parent document IDs, chunk positions and rank | Fixed `english` configuration with `websearch_to_tsquery`; word lexemes/stemming, not a substring search. Rank DESC, source ID ASC breaks ties. Search is limited to each chunk, so a phrase crossing a chunk boundary is not searched as one phrase. |
| Q2 | Default deliberate misspelling `Jeffrey Epstien`; threshold 0.3; canonical person name, source ID, normalized input, method/version and similarity score | CLI applies `nfkc-casefold-space-v1`, matching stored search values. `%` uses the explicit pg_trgm threshold. Score DESC, source ID ASC. Canonical names only; aliases and mention resolution are outside this query. Similarity is not probability or verified identity. |
| Q3 | Start KG node ID 1; start/middle/end node source IDs and both edge source IDs | Exactly two directed edges; all three nodes and both edges distinct. Parallel-edge paths remain separate. Order by first and second edge ID. A path count is not a distinct-destination count. An absent start returns no paths. |
| Q4 | Complete aggregation by currency and normalized merchant label, optionally filtered by currency/merchant | Counts valid, missing and invalid amounts, negative/zero/positive amounts, and exact NUMERIC sum. Missing amounts do not become zero. An all-missing group has NULL sum. Unknown currencies retain record counts but their sum is NULL because their units cannot be assumed compatible; no grand total across currencies. Merchant normalization groups labels, not confirmed merchant identities. |
| Q4_FILTER | Same financial aggregate, focused defaults USD / fedex | Required equality predicates demonstrate the composite B-tree. This is a variant of Q4, not another independent analytical question. |
| Q5 | File keys present in multiple upstream output collections; file-output count, distinct outputs, referenced upstream runs and missing run references | Unit is `(output_name,file_key)`, not a document, ETL batch or historical attempt. Multiple output records cannot prove multiple chronological attempts. Upstream runs are distinct from our import runs. |
| Q6 | Email metadata completeness by dataset | Missing SQL NULL, empty raw text, invalid JSON, whole JSON null, objects, arrays and other scalars are disjoint categories. Object subject absence, JSON null and nonnull values are separate subdivisions. This answers whether source metadata supports later email analysis; a nonnull subject alone does not establish its quality. |
| Q6_JSON | Document IDs/file keys with explicit JSON null subject | Drill-down of Q6. Shows the raw representation exists, parsed JSONB is not SQL NULL, the subject key exists and its value type is `null`. An absent subject or missing email metadata does not match. |

For manual Q2 inputs, set `z1.fuzzy_input` to the value normalized with the
documented Python rule and `z1.fuzzy_raw_input` to the original text, and set
`pg_trgm.similarity_threshold`. SQL `lower()` alone is not equivalent to NFKC and
casefold. `z1.fts_input`, `z1.kg_start`, `z1.currency` and `z1.merchant` are the
other optional settings; the merchant setting is a normalized label. Unset
currency/merchant filters include every row in Q4. Q4_FILTER has documented
nonempty defaults. Empty full-text input produces no lexemes/results.

## Index decisions

The exact DDL is [query-indexes.sql](../sql/query-indexes.sql).
Actual definitions, sizes, full parent-table counts and build durations are in
[query-indexes.json](../evidence/query-indexes.json).

| Index | Query/operator and keys/opclass | Reason and write/import cost |
|---|---|---|
| `chunks_fts_gin` | Q1 `@@`; expression `to_tsvector('english'::regconfig, COALESCE(content,''))`, `tsvector_ops` | Inverted lexeme lookup over all accepted chunks. No separate stored vector or source-field change. Building scans/tokenizes all content; future content writes must tokenize and maintain GIN postings, including its default pending list. Rechecks/ranking still compute vectors. |
| `persons_name_trgm_gin` | Q2 `%`; `search_value public.gin_trgm_ops` | Supports threshold similarity predicates on canonical person names. It does not provide ranked order; scores and sorting remain. Each name update maintains multiple trigram entries. Only 1,614 persons exist, so a sequential scan can reasonably win; this is not a large-corpus performance claim. |
| `financial_currency_merchant_btree` | Q4_FILTER `=`; `(currency,search_value)`, `text_ops,text_ops` | Currency is the leading equality filter, merchant narrows within currency. This **one composite B-tree** satisfies two required categories. It also supports currency-only searches, but does not justify an unrestricted merchant-only lookup. Each transaction write adds one B-tree entry; updates to these keys maintain it. Complete Q4 aggregation may choose a sequential scan. |
| `documents_email_object_gin` | Q6_JSON `@>`; `email_fields jsonb_path_ops`; partial predicate: valid JSON objects | Own decision: index the sparse usable email objects instead of all documents or every JSON shape. `jsonb_path_ops` supports containment; it does not support the `?` key-existence operator used in the completeness aggregate. The query repeats the partial predicate. Every document write evaluates that predicate; only qualifying objects add GIN entries. |

Existing PK/UNIQUE B-trees remain active. There is no duplicated single-column
currency index. A foreign key does not itself create an index on its referencing
column; the existing chunk `(document_id,chunk_index)` unique index already
supports its document prefix. The graph has only 2,198 edges, so Q3 uses its
existing keys and normal planner decisions; an extra graph index is not required
to demonstrate correct two-hop semantics. No planner scan type is forced.

Build durations measure this machine's post-import CREATE INDEX cost, not an
experiment comparing complete ETL with and without indexes. The DDL is deliberately
applied after the initial import. Later inserted rows or rebuilt corpora would
incur index maintenance. GIN space and posting maintenance are the main FTS cost;
small name/JSON indexes still have predicate/evaluation costs.

Primary references: [PostgreSQL FTS expression indexes](https://www.postgresql.org/docs/18/textsearch-tables.html),
[pg_trgm operators/indexes](https://www.postgresql.org/docs/18/pgtrgm.html),
[multicolumn B-tree order](https://www.postgresql.org/docs/18/indexes-multicolumn.html),
and [JSONB indexing/operator classes](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING).

## Synthetic verification

Run the complete suite, including database tests, from the project root:

```powershell
$env:Z1_DB_TESTS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:Z1_DB_TESTS
```

[test_z1_queries_db.py](../tests/test_z1_queries_db.py) creates separate random
`z1_query_test_*` domain/audit schemas and removes them after each test. It verifies
FTS word boundaries/stemming and empty input, Unicode fuzzy normalization and
threshold/rank ties, parallel graph paths and repeated-node exclusion, exact money
with unknown/missing/invalid values and separate currencies, upstream count
granularity, JSON states and index-definition/repetition checks. Query results are
compared before/after the corresponding indexes on those fixtures. These checks
prove semantics; they do not replace the full-input section-8 benchmark.

## Measured full-corpus results

Recorded on 10 October 2026; PostgreSQL 18.3, pg_trgm 1.6. The complete default workload was executed and every returned row hashed.

| Query | Complete result rows | Unit |
|---|---:|---|
| Q1 | 29,166 | Matching chunks |
| Q2 | 8 | Canonical person-name search results |
| Q3 | 3,538 | Directed two-edge paths from KG node 1 |
| Q4 | 18,392 | Currency/merchant-label groups, covering all 49,770 transactions |
| Q4_FILTER | 1 | USD / fedex group, covering 6,520 transactions |
| Q5 | 8 | File keys with multiple upstream output records |
| Q6 | 52 | Dataset groups, covering all 1,424,662 accepted documents |
| Q6_JSON | 20 | Documents with explicit JSON null subject |

| Index | Actual bytes | Covered rows | Measured build seconds |
|---|---:|---:|---:|
| `chunks_fts_gin` | 1,287,847,936 | 2,193,027 | 290.921 |
| `persons_name_trgm_gin` | 278,528 | 1,614 | 0.027 |
| `financial_currency_merchant_btree` | 1,990,656 | 49,770 | 0.163 |
| `documents_email_object_gin` | 81,920 | 631 | 13.513 |

The FTS index occupies about 1.20 GiB; the other indexes occupy 272 KiB, 1.90 MiB and 80 KiB respectively. The partial email index covers 631 valid objects out of 1,424,662 accepted documents. These are actual build/space costs, not query speedup measurements.

Recorded plans use `chunks_fts_gin` for Q1, `financial_currency_merchant_btree` for Q4_FILTER and `documents_email_object_gin` for Q6_JSON. Q2 uses a sequential scan over the small person registry; Q3 uses a hash join over the small graph. Q4/Q6 full aggregates and Q5 use normal scan/aggregate plans. No planner method was forced.

Q4 accounted for 49,219 valid amounts, 551 missing and zero invalid; valid amounts include 18,237 negative, 532 zero and 30,450 positive records. Q6 accounted for 1,424,027 missing email values, 631 valid objects and four arrays; object subjects include 20 JSON null and 611 nonnull values. Synthetic fixtures additionally cover absent keys, invalid JSON, unknown currencies and values not present in this frozen source.

The section-7 suite passed **23 tests**, with zero failures, errors or skips. See [query-tests.json](../evidence/query-tests.json). The section-8 complete suite added two benchmark equality/rollback tests and passed **25 tests**; see [benchmark-tests.json](../evidence/benchmark-tests.json). The earlier import-only report remains a timestamped record of its 16-test run.

Section 9 now materializes the complete Q4 result in `z1.financial_report`; see
[extension.md](extension.md). Its full result matches the Q4 hash above. The current
complete suite adds three R2 tests and passed **28 tests**; see
[extension-tests.json](../evidence/extension-tests.json). The section-7/8 test evidence
remains a record of those earlier suites.

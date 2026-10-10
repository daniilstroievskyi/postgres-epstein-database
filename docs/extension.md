# Section 9: R2 materialized financial report

R2 is implemented as one materialized view, `z1.financial_report`, over the full
accepted `financial_transactions` layer. The analytical question is: **how many
transaction records and what net valid amount belong to each currency and
normalized merchant label, with missing/invalid amounts reported separately?**

This follows the existing Q4 question. The source remains the frozen revision
`133ef9f0a539fafc270cde8fa8638dc38d89968d` of `kabasshouse/epstein-data`.
The extension adds derived reporting data after the full ETL. It uses no checkpoint
code, sample records, or checkpoint outputs.

## Run and demonstrate

After the complete import and validation, run from the project root:

```powershell
# Create if absent, refresh, then compare the whole stored result with Q4.
.\.venv\Scripts\python.exe scripts/extend_z1.py

# Verify the existing report without refreshing it.
.\.venv\Scripts\python.exe scripts/extend_z1.py --check-only

# Demonstrate stale data, refresh, repetition and rollback on separate fake data.
# This demonstration needs PostgreSQL but no downloaded corpus.
.\.venv\Scripts\python.exe scripts/extend_z1.py --demo
```

The first two commands verify the full local manifest and require a completed
load. The script takes the importer advisory lock. It does not refresh while a
project import is running. Comparison and refresh use the same REPEATABLE READ
snapshot. The default command creates the view only if absent and verifies the
definition before reusing it. It refuses a conflicting table/view or a different
materialized definition rather than replacing it automatically.

`--check-only` raises an error if the report is absent, unpopulated or different
from current Q4. To refresh a valid existing definition, run the default command.
Its successful evidence is in [extension.json](../evidence/extension.json).
Check-only and synthetic demonstrations do not overwrite that full-input evidence.

## Model and choices

| Choice | Reason |
|---|---|
| One row per `(currency, merchant_search_value)` | Matches Q4's analytical grouping; preserves separate currencies and the NULL buckets |
| Materialized view | Persists the aggregate for later reads without recalculating every source transaction on each report read |
| Seven record-count columns | Retains amount-state and sign accounting: valid/missing/invalid, negative/zero/positive, and total records |
| Unconstrained NUMERIC sum of valid amounts only | Keeps the exact available imported precision and sign; no rounding or conversion to float |
| Unknown currency gives a NULL sum | Unknown currencies cannot be assumed compatible; their records remain counted |
| Missing-only group gives a NULL sum | An unknown amount is not zero; no `COALESCE(sum(...),0)` |
| Normalized merchant label, not merchant identity | Uses the existing `nfkc-casefold-space-v1` search value; matching labels do not verify a real-world entity |
| Full unfiltered definition | A connection's optional Q4 filters must not silently change which data are materialized |
| Explicit ordinary REFRESH | Sufficient for a frozen coursework corpus; no scheduler, incremental updates or refresh-specific index is needed |

The derived report adds no new entity IDs or foreign references. Its grouping keys
are values, not references to a merchant table. Original transaction IDs and source
lineage remain in `z1.financial_transactions`; all its original constraints stay
active. To trace a report group, filter that table by the two group values. Use
`IS NOT DISTINCT FROM` if the group contains NULL. An example for a known group:

```sql
SELECT source_id, input_file_id, source_row, amount_raw, amount, amount_state
FROM z1.financial_transactions
WHERE currency = 'USD' AND search_value = 'fedex'
ORDER BY source_id;
```

The materialized definition, refresh and sorted read are reviewable in
[sql/extension.sql](../sql/extension.sql). An example report read is:

```sql
SELECT currency, merchant_search_value, transaction_records,
       valid_amount_records, missing_amount_records, invalid_amount_records, amount_sum
FROM z1.financial_report
WHERE currency = 'USD' AND merchant_search_value = 'fedex';
```

## Ordinary VIEW versus materialized result

An ordinary VIEW stores a query definition. A read evaluates it against the source
visible to that statement. [PostgreSQL ordinary views](https://www.postgresql.org/docs/18/sql-createview.html)
A materialized view stores the definition **and its
calculated rows**; reads use those stored rows. Source INSERT/UPDATE/DELETE operations
do not automatically update them. `REFRESH MATERIALIZED VIEW` recalculates the stored
result. [PostgreSQL materialized views](https://www.postgresql.org/docs/18/rules-materializedviews.html)

The implementation uses `CREATE MATERIALIZED VIEW ... WITH NO DATA`, then refreshes
it. Creation, refresh and verification are one transaction, so an initial failure
does not leave a half-finished report. The initial unpopulated view is not readable.
On successful commit it is populated. Repeated commands refresh the same object.

For safe definition checking, the script briefly creates an ordinary temporary
view over the expected query, compares PostgreSQL's canonical definitions, and
removes that temporary view. It is a validation helper, not the reporting layer.

Report reads explicitly `ORDER BY currency NULLS FIRST, merchant_search_value NULLS
FIRST`. Materialized storage/refresh does not guarantee output order.
[REFRESH semantics](https://www.postgresql.org/docs/18/sql-refreshmaterializedview.html)

## Full-input verification

Measured on 10 October 2026 using PostgreSQL 18.3 and Python 3.13.7. The full source
financial layer contains **49,770 records**, all accepted, with no financial
quarantine or duplicate dispositions. Both direct Q4 and the materialized report
return **18,392 groups** covering those **49,770 records**.

| Accounting | Records |
|---|---:|
| Valid amount | 49,219 |
| Missing amount | 551 |
| Invalid amount | 0 |
| Negative valid amount | 18,237 |
| Zero valid amount | 532 |
| Positive valid amount | 30,450 |

Both full results have this SHA-256, also matching the original section-7 Q4 result:

```text
28d0a799618944e5d90c0eddb642878cb66af532ea881f0136af358370ffdf2c
```

The script fetches bounded batches of 2,000 groups and hashes every output column
and row in deterministic group order. The format is the section-7 length-prefixed
compact UTF-8 JSON encoding of column names and typed values: integers as decimal
strings, NUMERIC values as Decimal text, explicit NULL tags and unmodified text.
No LIMIT or deduplication is applied. This compares group keys, every count and
every sum, rather than only the number of groups.

Actual full repetition kept the materialized-view OID and complete results
unchanged. Existing constraints/indexes and all original financial source
fingerprints were preserved. All **50 FKs** and all **four workload indexes** stayed
active. See [extension-repeat.json](../evidence/extension-repeat.json) and the
[before snapshot](../evidence/extension-input-before.json).

## Staleness, refresh and rollback demonstration

`--demo` creates a random `z1_r2_demo_*` schema, with eight explicitly synthetic
transactions and the same materialized SQL. It removes that schema afterward.
Schema creation and removal are transactional, so a failed demo also leaves no
fixture schema. It never writes to the frozen corpus or production report.

| Step | Direct groups | Stored groups | Complete results equal? |
|---|---:|---:|---|
| Initial refresh | 4 | 4 | Yes |
| Change amount, insert a negative USD transaction, delete the EUR transaction | 3 | 4 | No: stored result is stale |
| Refresh | 3 | 3 | Yes |
| Repeat refresh | 3 | 3 | Yes, same full hash |
| Update and refresh inside a transaction that fails | 3 | 3 | Yes, prior source and report restored |

The source record count remains **eight before and after** the committed source
changes. Nevertheless, the USD demo-merchant sum changes from **10.00 to 13.00**,
and the EUR group disappears. This demonstrates why count-only comparison cannot
establish freshness. Unknown-currency and missing-only sums remain NULL. Separate
synthetic currencies are never combined. Actual results and all step hashes are in
[extension-staleness.json](../evidence/extension-staleness.json).

## Refresh cost, policy and limits

Run the default command after the full validated load or after intentionally
changing the reporting source. The report is correct as of its refresh snapshot;
a saved refresh/verification timestamp is not a guarantee of perpetual freshness.
Use `--check-only` to compare against the current source. For this frozen source,
later identical refreshes are expected to reproduce the same result.

Some source edits preserve the report result: unused-field changes and offsetting
amount edits can leave every aggregate unchanged. The stored rows are not
automatically recomputed, but can still equal the current calculation. This
refines the earlier broad AI statement that all source changes make the report
stale; optional additional evidence is in
[ai-claim-check.json](../evidence/ai-claim-check.json).

Refresh performs a full read and aggregation of all **49,770** financial records,
then replaces the materialized rows. The recorded repeat refresh took **0.097003
seconds**, excluding the subsequent result-hash verification. This is one observed
refresh cost, not a query-speed benchmark. The materialized relation's total
storage is **3,686,400 bytes**, about **3.52 MiB**, including PostgreSQL auxiliary
storage. Later runs can change the observed cost and physical size; see live
evidence for the latest measurement.

Ordinary refresh blocks other readers of the materialized report while it runs.
It also requires space to build replacement contents and incurs database writes.
That tradeoff is acceptable for this offline corpus and small report. Concurrent
refresh would require an appropriate UNIQUE index and an already populated view;
the current implementation uses the simpler ordinary refresh. It does not claim
incremental maintenance or measured production speedup.
[PostgreSQL refresh requirements](https://www.postgresql.org/docs/18/sql-refreshmaterializedview.html)

## Supervisor tests and file roles

```powershell
$env:Z1_DB_TESTS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:Z1_DB_TESTS
```

The complete suite passed **28 tests**, with zero failures, errors or skips.
The three new R2 tests check stale results despite unchanged total record counts,
refresh/repetition/rollback, NULL/currency/sign semantics, fixed unfiltered scope,
reuse of the same object and rejection of a conflicting object/definition. They
use separate synthetic schemas and require no corpus download. Evidence is in
[extension-tests.json](../evidence/extension-tests.json).

| File | Purpose |
|---|---|
| `sql/extension.sql` | Materialized-view definition, refresh command and deterministic report read |
| `scripts/extend_z1.py` | Full-input creation/refresh/verification, check-only mode and isolated stale-data demonstration |
| `tests/test_z1_extension_db.py` | Synthetic R2 correctness, repeat/rollback and safe object-reuse tests |
| `evidence/extension.json` | Actual full-source counts, whole-result comparison, SQL, versions, refresh cost and report storage |
| `evidence/extension-repeat.json` | Actual full repeated-refresh and source/catalog preservation checks |
| `evidence/extension-staleness.json` | Actual separate synthetic stale/refresh/repeat/rollback results |

This completes R2. The AI report is finalized; the defense and final submission
preparation remain.

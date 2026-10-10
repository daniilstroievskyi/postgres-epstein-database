# Full Z1 import report

Validated at 2026-10-10T19:11:29.951712+00:00.

Frozen revision: `133ef9f0a539fafc270cde8fa8638dc38d89968d`.

This report records actual database checks. Repeat/recovery evidence is recorded separately.

| Layer | Read | Accepted | Quarantined | Duplicate | Target rows |
|---|---:|---:|---:|---:|---:|
| chunks | 2,193,090 | 2,193,027 | 63 | 0 | 2,193,027 |
| curated_docs | 5,766 | 5,766 | 0 | 0 | 5,766 |
| derived_events | 3,038 | 3,038 | 0 | 0 | 3,038 |
| documents | 1,424,673 | 1,424,662 | 11 | 0 | 1,424,662 |
| entities | 10,629,198 | 10,629,198 | 0 | 0 | 10,629,198 |
| event_participants | 5,751 | 5,751 | 0 | 0 | 5,751 |
| event_sources | 21,910 | 21,910 | 0 | 0 | 21,910 |
| financial_transactions | 49,770 | 49,770 | 0 | 0 | 49,770 |
| kg_entities | 467 | 467 | 0 | 0 | 467 |
| kg_relationships | 2,198 | 2,198 | 0 | 0 | 2,198 |
| persons | 1,614 | 1,614 | 0 | 0 | 1,614 |
| provenance/files | 1,387,775 | 1,387,775 | 0 | 0 | 1,387,775 |
| provenance/runs | 123 | 123 | 0 | 0 | 123 |

Actual active, validated foreign keys: 50. Every nonnull FK passed an explicit anti-join check.

Every file's physical row coverage, disjoint dispositions and target counts reconcile with the manifest.

| Derived table | Expected string elements | Actual rows |
|---|---:|---:|
| person_aliases | 241 | 241 |
| curated_document_links | 1445 | 1445 |

| Layer | Field | Issue code | Source rows |
|---|---|---|---:|
| chunks | offsets | actual_length_exceeded | 81 |
| chunks | offsets | reported_length_disagreement | 14,832 |
| curated_docs | also_appears_as | alternate_document_unmatched | 99 |
| curated_docs | doc_date | date_invalid | 10 |
| curated_docs | doc_date | date_unparsed | 1,159 |
| documents | date | date_invalid | 2 |
| documents | date | date_unparsed | 766,231 |
| documents | email_fields | json_unexpected_shape | 4 |
| entities | document_reference | namespace_unverified | 10,628,725 |
| entities | document_reference | unmatched | 473 |
| event_sources | document_reference | unmatched | 16,651 |
| financial_transactions | dataset | document_dataset_disagreement | 482 |
| provenance/files | document_reference | unmatched | 16 |
| provenance/files | run_reference | missing | 63,676 |

Multiple issues can concern one accepted row. Namespace-unverified entity links remain candidates, not confirmed resolutions.

Commands from the project root:

```powershell
.\.venv\Scripts\python.exe scripts/import_z1.py
.\.venv\Scripts\python.exe scripts/validate_z1.py
```

## Completed ETL proof

All 15,725,373 prescribed source records were processed: 15,725,299 accepted,
74 quarantined and zero source duplicates. Derived rows are separate: 241 person
aliases and 1,445 alternate document links. All 50 actual FKs are active/validated;
nonnull FK anti-joins, original-field fingerprints and exact monetary conversion passed.

Quarantine: 11 documents with NUL text, 15 chunks with NUL text, and 48 chunks
whose required document was quarantined. Immutable source files and row locators
preserve every rejected record for investigation.

[Full repeat evidence](../evidence/import-repeat.json) proves identical full contents
for all 15 domain tables and source issue/quarantine/duplicate records, with zero
newly read source rows. This is a full comparison, not a count-only or sample check.

[16 passing tests](../evidence/import-tests.json)
include synthetic transformation edge cases, actual DB FK rejection, duplicate/conflict
accounting and fresh-connection before/after commit recovery. Test rows use separate
random schemas, removed after tests.

[Recovery/runtime evidence](../evidence/import-recovery.json) records actual resumed
attempts and versions. [Trace examples](../evidence/import-trace.json) demonstrate
exact original-field equality for document and chunk ID 1. The working database
used 11.34 GiB when measured; source data and Docker volume were preserved.

Reproduce full repeat proof:

```powershell
.\.venv\Scripts\python.exe scripts/prove_z1_repeat.py
```

Queries, workload indexes, benchmark and R2 are implemented as subsequent stages,
and the AI report is finalized. Defense and submission packaging remain.

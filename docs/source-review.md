# Source review before implementing the full model

This is the review document for the completed download and profiling stage,
not a claim that the final PostgreSQL import or the rest of Z1 is complete.
The full relational model and importer are now implemented. Current database
validation and repeat evidence are recorded in import-report.md and evidence/.

## Completed and measured

- Exactly 56 prescribed shards at revision `133ef9f0a539fafc270cde8fa8638dc38d89968d`.
- 1,453,369,989 compressed bytes and 15,725,373 source rows across all 13 layers.
- Content SHA-256 of every shard matches the pinned repository's recorded SHA-256.
- The three source documentation files are retained locally and included in the manifest.
- Offline verification checks the complete inventory, hashes, sizes, and row counts.
- Every source layer has consistent shard schemas and measured NULL/blank counts.

See [the manifest](../source-manifest.json), [the data profile](data-profile.md),
[source validation](../evidence/source-validation.json), and
[profile evidence](../evidence/source-profile.json). The source corpus remains
unchanged under `data/`. Commands and paths in these reports are relative to the
project root unless a Markdown link specifies otherwise.

## Findings that determine the next implementation

| Finding | Evidence | Proposed modeling decision |
|---|---|---|
| Document source IDs and file keys are unique in this frozen revision | 1,424,673 distinct, non-null values of each | Preserve source IDs; file_key can be a unique natural key for this revision |
| All chunks resolve to documents | 2,193,090 single equality candidates, zero missing/unmatched | Declare the required document FK, and separately check chunk positions |
| Entity document IDs require separate treatment | 78 numeric references have no document; equality for the remainder does not prove a common namespace | Preserve raw_document_id; do not silently turn all numeric equalities into confirmed document links |
| Event source file keys frequently do not resolve | 16,651 of 21,910 source records have no matching document file_key | Keep each event-source row; preserve the raw key and explicit unresolved state, with a nullable document FK |
| Participant and event-source event references resolve | Zero unmatched references | Declare real event FKs; participant names remain separate from person identities |
| Both KG edge endpoints resolve | All 2,198 source and target references match | Declare both mandatory KG-entity FKs; graph edges are not proof of real-world misconduct |
| Provenance file_key is not a unique record identity | 8 extra occurrences; (output_name,file_key) is unique in the frozen input | Preserve processing/output context; do not remove records solely because file_key repeats |
| Provenance file run IDs can be missing | 63,676 missing; zero unmatched non-null references | Preserve the raw value and use an optional FK to upstream runs |
| Financial amounts include negative and missing values | 18,237 negative, 532 zero, 551 NULL, zero nonfinite | Preserve sign and missingness; retain the source floating-point value and document any decimal conversion; aggregate separately by currency |
| Document dates are often free-form or imprecise | 787,599 nonblank; 752,558 are not directly timestamp-castable, including partial/free-form values | Preserve the original date string; classify precision and conversion separately without inventing a day or timezone |
| Email JSON exists only on a small subset | 635 valid non-null JSON values, 1,424,038 SQL NULL; no malformed JSON observed | Preserve raw text plus parsed JSONB and state; synthetic tests must still cover invalid JSON, JSON null, and missing keys |
| Curated records can share document file keys | 104 extra file_key occurrences; unique source IDs | Keep individual annotations by their source IDs rather than dropping repeated document references |

Date castability is diagnostic. It does not establish that every uncastable string
is an erroneous source record: some values have partial or uncertain precision.
Likewise, a successful FK proves target existence, not semantic identity correctness.

## What the author should review

1. Read the five required detailed profiles: documents, entities, event_sources,
   financial_transactions, and provenance/files.
2. Check the measured counts against the assignment and source documentation.
3. Understand why event-source links must be optional, why entity numeric equality
   is insufficient, and why repeated provenance file keys must be preserved.
4. Review the proposed financial and date handling before explaining it at defense.

The model, field-by-field mapping, transformations, integrity tests and importer
are implemented separately from C1. Queries, workload indexes, benchmark and R2
are implemented and verified; the AI report is finalized. Defense and the final
submission package remain outstanding.

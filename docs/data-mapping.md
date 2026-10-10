# Source-to-target mapping

Status: implemented mapping; full-load validation results are in import-report.md. Every source field
in the measured 13-layer schema is listed below. No source field is intentionally
discarded. See [schema-proposal.md](schema-proposal.md) for rationale and the ER
model, and [import-design.md](import-design.md) for row disposition and recovery.

Target tables have the `z1.` prefix. Date families below mean raw TEXT + state/
precision + year/month/day DATE or local TIMESTAMP/known TIMESTAMPTZ as applicable.
Timestamp families mean raw TEXT + state + local TIMESTAMP or known TIMESTAMPTZ.
JSON families mean raw TEXT + parsed JSONB + state; original formatting is retained.
All state columns have documented CHECK values; nullable typed results require
corresponding missing/error/uncertain state. Optional errors generate issues while
retaining the source row; structural/key/required-parent errors quarantine it.

## Common added columns

Each source-row table adds `input_file_id BIGINT` (FK audit source catalog),
`source_row BIGINT` (physical Parquet row number + 1), `loaded_by_run UUID` (FK our
import attempt), and `raw_record_hash BYTEA` (canonical source-payload fingerprint).
Generated catalog IDs and run UUIDs are bookkeeping, not substituted source IDs.
Derived tables trace through their source parent and array position. These are
implemented columns, declared in sql/schema.sql and scripts/z1_model.py.

## documents -> z1.documents

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| file_key VARCHAR | file_key TEXT | Keep exact identifier; missing/conflicting identity quarantines. | UNIQUE, NOT NULL | Measured unique document identifier in this frozen revision. |
| dataset VARCHAR | dataset TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| full_text VARCHAR | full_text TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| document_type VARCHAR | document_type TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| date VARCHAR | date_raw TEXT; date_state/precision TEXT; date_year/month SMALLINT; date_day DATE; date_local_timestamp TIMESTAMP; date_instant TIMESTAMPTZ | Strict documented formats; retain partial precision, missing, invalid and unparsed states; do not infer day or zone. | None | Historical dates can be partial/free-form; support safe date filters without invented values. |
| is_photo BOOLEAN | is_photo BOOLEAN | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain true/false/unknown distinctly. |
| has_handwriting BOOLEAN | has_handwriting BOOLEAN | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain true/false/unknown distinctly. |
| has_stamps BOOLEAN | has_stamps BOOLEAN | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain true/false/unknown distinctly. |
| ocr_source VARCHAR | ocr_source TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| additional_notes VARCHAR | additional_notes TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| page_number VARCHAR | page_number TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Identifiers/labels may contain formatting or leading zeros; preserve as TEXT. |
| document_number VARCHAR | document_number TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Identifiers/labels may contain formatting or leading zeros; preserve as TEXT. |
| char_count INTEGER | char_count INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |
| created_at VARCHAR | created_at_raw TEXT; created_at_state TEXT; created_at_local_timestamp TIMESTAMP; created_at_instant TIMESTAMPTZ | Parse explicit formats; explicit offset -> instant; no offset -> local timestamp; errors/missing retained. | None | Source mixes zoned and unzoned values; creation/processing time is not historical document date. |
| email_fields VARCHAR | email_fields_raw TEXT; email_fields JSONB; email_fields_state TEXT | Strict JSON parse; preserve SQL NULL, JSON null, invalid text and valid arrays/objects; record shape/representation errors. | None | Queryable structured metadata without losing original source representation. |

## chunks -> z1.chunks

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| document_id BIGINT | document_id BIGINT | Exact documented parent lookup; missing parent quarantines. | Required FK -> documents.source_id; composite UNIQUE with chunk_index | Each chunk belongs to one document; parent exists for every current source row. |
| chunk_index INTEGER | chunk_index INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | Part of UNIQUE(document_id,chunk_index); CHECK >= 0 | Stable within-document ordering; preserve source chunk ID separately. |
| content VARCHAR | content TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| token_count INTEGER | token_count INTEGER | Preserve integer; validate nonnegative count/start and end >= start; offset diagnostics create issues. | None | Retain source offsets; 81 ends exceed actual text length, pending offset-convention investigation. |
| char_start INTEGER | char_start INTEGER | Preserve integer; validate nonnegative count/start and end >= start; offset diagnostics create issues. | None | Retain source offsets; 81 ends exceed actual text length, pending offset-convention investigation. |
| char_end INTEGER | char_end INTEGER | Preserve integer; validate nonnegative count/start and end >= start; offset diagnostics create issues. | None | Retain source offsets; 81 ends exceed actual text length, pending offset-convention investigation. |

## entities -> z1.mentions

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| document_id BIGINT | raw_document_id BIGINT; candidate_document_id BIGINT; document_id BIGINT; document_match_status TEXT | Keep raw ID; equality candidate when present; resolved ID NULL until namespace evidence supports it; unmatched/unverified states explicit. | Optional candidate and resolved FKs -> documents.source_id | Numeric equality does not prove shared namespace; 78 source IDs have no candidate. |
| entity_type VARCHAR | entity_type TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| value VARCHAR | value_raw TEXT; search_value TEXT; normalization_version TEXT | Keep raw text; derive nfkc-casefold-space-v1 search value; missing remains missing; no identity inference. | None | Search normalization and fuzzy similarity are distinct from confirmed person identity. |
| normalized_value VARCHAR | normalized_value_raw TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Every upstream value is NULL; our derived search value must not be represented as upstream normalization. |

## persons -> z1.persons

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| canonical_name VARCHAR | canonical_name TEXT; search_value TEXT; normalization_version TEXT | Keep raw text; derive nfkc-casefold-space-v1 search value; missing remains missing; no identity inference. | None | Search normalization and fuzzy similarity are distinct from confirmed person identity. |
| slug VARCHAR | slug TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Only 1,608 distinct slugs across 1,614 rows; no UNIQUE constraint. |
| category VARCHAR | category TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| aliases VARCHAR | aliases_raw TEXT; aliases JSONB; aliases_state TEXT; person_aliases(person_id,alias_position,alias_raw,search_value,normalization_version) | Strict JSON parse; preserve SQL NULL, JSON null, invalid text and valid arrays/objects; record shape/representation errors. | Derived rows FK -> persons.source_id; PK person_id,alias_position | Expose each of 241 aliases for fuzzy search; keep duplicate elements by position. |
| search_terms VARCHAR | search_terms_raw TEXT; search_terms JSONB; search_terms_state TEXT | Strict JSON parse; preserve SQL NULL, JSON null, invalid text and valid arrays/objects; record shape/representation errors. | None | Queryable structured metadata without losing original source representation. |
| sources VARCHAR | sources_raw TEXT; sources JSONB; sources_state TEXT | Strict JSON parse; preserve SQL NULL, JSON null, invalid text and valid arrays/objects; record shape/representation errors. | None | Queryable structured metadata without losing original source representation. |
| notes VARCHAR | notes TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |

## kg_entities -> z1.kg_nodes

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| name VARCHAR | name TEXT; search_value TEXT; normalization_version TEXT | Keep raw text; derive nfkc-casefold-space-v1 search value; missing remains missing; no identity inference. | None | Search normalization and fuzzy similarity are distinct from confirmed person identity. |
| entity_type VARCHAR | entity_type TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| description VARCHAR | description TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| metadata VARCHAR | metadata_raw TEXT; metadata JSONB; metadata_state TEXT | Strict JSON parse; preserve SQL NULL, JSON null, invalid text and valid arrays/objects; record shape/representation errors. | None | Queryable structured metadata without losing original source representation. |

## kg_relationships -> z1.kg_edges

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| source_id BIGINT | from_node_id BIGINT | Preserve endpoint ID; missing parent quarantines. | Required FK -> kg_nodes.source_id | Explicit directed edges support exact two-edge paths. |
| target_id BIGINT | to_node_id BIGINT | Preserve endpoint ID; missing parent quarantines. | Required FK -> kg_nodes.source_id | Explicit directed edges support exact two-edge paths. |
| relationship_type VARCHAR | relationship_type TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| weight DOUBLE | weight DOUBLE PRECISION | Preserve value, SQL NULL and blanks; no inferred default. | None | Graph connection metric, not a monetary amount or a confirmed identity probability. |
| evidence VARCHAR | evidence TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| metadata VARCHAR | metadata_raw TEXT; metadata JSONB; metadata_state TEXT | Strict JSON parse; preserve SQL NULL, JSON null, invalid text and valid arrays/objects; record shape/representation errors. | None | Queryable structured metadata without losing original source representation. |

## derived_events -> z1.events

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| event_date VARCHAR | event_date_raw TEXT; event_date_state/precision TEXT; event_date_year/month SMALLINT; event_date_day DATE; event_date_local_timestamp TIMESTAMP; event_date_instant TIMESTAMPTZ | Strict documented formats; retain partial precision, missing, invalid and unparsed states; do not infer day or zone. | None | Historical dates can be partial/free-form; support safe date filters without invented values. |
| event_end_date VARCHAR | event_end_date_raw TEXT; event_end_date_state/precision TEXT; event_end_date_year/month SMALLINT; event_end_date_day DATE; event_end_date_local_timestamp TIMESTAMP; event_end_date_instant TIMESTAMPTZ | Strict documented formats; retain partial precision, missing, invalid and unparsed states; do not infer day or zone. | None | Historical dates can be partial/free-form; support safe date filters without invented values. |
| event_type VARCHAR | event_type TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| track VARCHAR | track TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| headline VARCHAR | headline TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| location VARCHAR | location TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| amount DOUBLE | amount_raw DOUBLE PRECISION; amount NUMERIC; amount_state TEXT | Finite float -> Decimal.from_float without forced scale; SQL NULL remains missing; nonfinite -> invalid parsed NULL and issue. | None | Preserve available binary source value and sign; exact decimal arithmetic does not recover original statement precision. |
| currency VARCHAR | currency_raw TEXT; currency TEXT; currency_state TEXT | Keep raw text; documented trim/uppercase grouping; unknown is explicit and never defaulted to USD. | None | Never aggregate different currencies without a stated conversion rule. |
| payer VARCHAR | payer TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| payee VARCHAR | payee TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| route_from VARCHAR | route_from TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| route_to VARCHAR | route_to TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| aircraft VARCHAR | aircraft TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| time_of_day VARCHAR | time_of_day TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| confidence VARCHAR | confidence TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Source is TEXT; do not fabricate a numeric probability. |
| narrative VARCHAR | narrative TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |

## event_participants -> z1.event_participants

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| event_id BIGINT | event_id BIGINT | Preserve event ID; missing parent quarantines. | Required FK -> events.source_id | Child entry belongs to an existing reconstructed event. |
| person_name VARCHAR | person_name TEXT; search_value TEXT; normalization_version TEXT | Keep raw text; derive nfkc-casefold-space-v1 search value; missing remains missing; no identity inference. | None | Search normalization and fuzzy similarity are distinct from confirmed person identity. |
| role VARCHAR | role TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |

## event_sources -> z1.event_sources

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| event_id BIGINT | event_id BIGINT | Preserve event ID; missing parent quarantines. | Required FK -> events.source_id | Child entry belongs to an existing reconstructed event. |
| file_key VARCHAR | file_key TEXT; document_id BIGINT; document_match_status TEXT | Keep exact raw key; unique equality lookup resolves document or preserves unresolved state; record dataset disagreement separately. | Optional FK document_id -> documents.source_id | Preserve evidence even when target document is absent; file_key alone is not this table identity. |

## financial_transactions -> z1.financial_transactions

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| file_key VARCHAR | file_key TEXT; document_id BIGINT; document_match_status TEXT | Keep exact raw key; unique equality lookup resolves document or preserves unresolved state; record dataset disagreement separately. | Optional FK document_id -> documents.source_id | Preserve evidence even when target document is absent; file_key alone is not this table identity. |
| dataset VARCHAR | dataset TEXT; dataset_match_status TEXT | Preserve transaction label; compare to linked document dataset; disagreement creates issue, no overwrite. | None | 482 source labels disagree with document labels; both observations must remain available. |
| transaction_date VARCHAR | transaction_date_raw TEXT; transaction_date_state/precision TEXT; transaction_date_year/month SMALLINT; transaction_date_day DATE; transaction_date_local_timestamp TIMESTAMP; transaction_date_instant TIMESTAMPTZ | Strict documented formats; retain partial precision, missing, invalid and unparsed states; do not infer day or zone. | None | Historical dates can be partial/free-form; support safe date filters without invented values. |
| amount DOUBLE | amount_raw DOUBLE PRECISION; amount NUMERIC; amount_state TEXT | Finite float -> Decimal.from_float without forced scale; SQL NULL remains missing; nonfinite -> invalid parsed NULL and issue. | None | Preserve available binary source value and sign; exact decimal arithmetic does not recover original statement precision. |
| currency VARCHAR | currency_raw TEXT; currency TEXT; currency_state TEXT | Keep raw text; documented trim/uppercase grouping; unknown is explicit and never defaulted to USD. | None | Never aggregate different currencies without a stated conversion rule. |
| merchant_name VARCHAR | merchant_name TEXT; search_value TEXT; normalization_version TEXT | Keep raw text; derive nfkc-casefold-space-v1 search value; missing remains missing; no identity inference. | None | Search normalization and fuzzy similarity are distinct from confirmed person identity. |
| merchant_raw VARCHAR | merchant_raw TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| merchant_category VARCHAR | merchant_category TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| location VARCHAR | location TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| cardholder VARCHAR | cardholder TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| description VARCHAR | description TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| card_type VARCHAR | card_type TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| account_digits VARCHAR | account_digits TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Identifiers/labels may contain formatting or leading zeros; preserve as TEXT. |
| statement_date VARCHAR | statement_date_raw TEXT; statement_date_state/precision TEXT; statement_date_year/month SMALLINT; statement_date_day DATE; statement_date_local_timestamp TIMESTAMP; statement_date_instant TIMESTAMPTZ | Strict documented formats; retain partial precision, missing, invalid and unparsed states; do not infer day or zone. | None | Historical dates can be partial/free-form; support safe date filters without invented values. |
| flight_from VARCHAR | flight_from TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| flight_to VARCHAR | flight_to TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| flight_carrier VARCHAR | flight_carrier TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| flight_departure VARCHAR | flight_departure TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| flight_ticket VARCHAR | flight_ticket TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| flight_passenger VARCHAR | flight_passenger TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| source_page INTEGER | source_page INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |
| extraction_model VARCHAR | extraction_model TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| extraction_confidence DOUBLE | extraction_confidence_raw DOUBLE PRECISION; extraction_confidence DOUBLE PRECISION; extraction_confidence_state TEXT | Preserve missing raw value; parsed finite 0..1 only if documented probability convention is established; otherwise retain unverified state. | None | Entirely NULL in this source; extraction confidence is not our match confidence. |

## curated_docs -> z1.curated_annotations

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| id BIGINT | source_id BIGINT | Preserve original numeric ID; missing or conflicting identity quarantines. | Primary key within this layer | Stable source identity; no insertion-order renumbering. |
| file_key VARCHAR | file_key TEXT; document_id BIGINT; document_match_status TEXT | Keep exact raw key; unique equality lookup resolves document or preserves unresolved state; record dataset disagreement separately. | Optional FK document_id -> documents.source_id | Preserve evidence even when target document is absent; file_key alone is not this table identity. |
| subject VARCHAR | subject TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| status VARCHAR | status TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| tier VARCHAR | tier TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| category VARCHAR | category TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| doc_date VARCHAR | doc_date_raw TEXT; doc_date_state/precision TEXT; doc_date_year/month SMALLINT; doc_date_day DATE; doc_date_local_timestamp TIMESTAMP; doc_date_instant TIMESTAMPTZ | Strict documented formats; retain partial precision, missing, invalid and unparsed states; do not infer day or zone. | None | Historical dates can be partial/free-form; support safe date filters without invented values. |
| doc_from VARCHAR | doc_from TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| doc_to VARCHAR | doc_to TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| headline VARCHAR | headline TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| key_quote VARCHAR | key_quote TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| detail VARCHAR | detail TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| thread_value VARCHAR | thread_value TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| also_appears_as VARCHAR | also_appears_as_raw TEXT; also_appears_as JSONB; also_appears_as_state TEXT; curated_document_links(annotation_id,link_position,file_key,document_id,document_match_status) | Strict JSON parse; preserve SQL NULL, JSON null, invalid text and valid arrays/objects; record shape/representation errors. | Parent annotation FK; optional document FK; PK annotation_id,link_position | 1,445 alternate key elements become traceable relational references. |

## provenance/runs -> z1.upstream_runs

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| run_id VARCHAR | run_id TEXT | Preserve original string ID; missing/conflicting identity quarantines. | Primary key | Upstream run identity, distinct from our UUID import attempts. |
| started_at VARCHAR | started_at_raw TEXT; started_at_state TEXT; started_at_local_timestamp TIMESTAMP; started_at_instant TIMESTAMPTZ | Parse explicit formats; explicit offset -> instant; no offset -> local timestamp; errors/missing retained. | None | Source mixes zoned and unzoned values; creation/processing time is not historical document date. |
| completed_at VARCHAR | completed_at_raw TEXT; completed_at_state TEXT; completed_at_local_timestamp TIMESTAMP; completed_at_instant TIMESTAMPTZ | Parse explicit formats; explicit offset -> instant; no offset -> local timestamp; errors/missing retained. | None | Source mixes zoned and unzoned values; creation/processing time is not historical document date. |
| status VARCHAR | status TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| input_dir VARCHAR | input_dir TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| output_name VARCHAR | output_name TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| model VARCHAR | model TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| dpi INTEGER | dpi INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |
| workers INTEGER | workers INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |
| rpm INTEGER | rpm INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |
| git_commit VARCHAR | git_commit TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| hostname VARCHAR | hostname TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| total_files INTEGER | total_files INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |
| success_count INTEGER | success_count INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |
| fail_count INTEGER | fail_count INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |
| input_tokens BIGINT | input_tokens BIGINT | Preserve value, SQL NULL and blanks; no inferred default. | None | Missing metrics remain unknown, not zero; upstream measurements stay separate from our importer. |
| output_tokens BIGINT | output_tokens BIGINT | Preserve value, SQL NULL and blanks; no inferred default. | None | Missing metrics remain unknown, not zero; upstream measurements stay separate from our importer. |
| cost_usd DOUBLE | cost_usd_raw DOUBLE PRECISION; cost_usd NUMERIC; cost_usd_state TEXT | Finite float -> Decimal.from_float without forced scale; SQL NULL remains missing; nonfinite -> invalid parsed NULL and issue. | None | Preserve available binary source value and sign; exact decimal arithmetic does not recover original statement precision. |
| last_heartbeat VARCHAR | last_heartbeat_raw TEXT; last_heartbeat_state TEXT; last_heartbeat_local_timestamp TIMESTAMP; last_heartbeat_instant TIMESTAMPTZ | Parse explicit formats; explicit offset -> instant; no offset -> local timestamp; errors/missing retained. | None | Source mixes zoned and unzoned values; creation/processing time is not historical document date. |

## provenance/files -> z1.upstream_files

| Source field/type | Target field/type | Conversion; NULL/error handling | Key or relationship | Reason |
|---|---|---|---|---|
| file_key VARCHAR | file_key TEXT; document_id BIGINT; document_match_status TEXT | Keep exact raw key; unique equality lookup resolves document or preserves unresolved state; record dataset disagreement separately. | Optional FK document_id -> documents.source_id; file_key part of PK (output_name,file_key) | Preserve evidence even when target document is absent; file_key alone is not this table identity. |
| output_name VARCHAR | output_name TEXT | Keep exact output context; conflicting composite identity quarantines. | Part of PK (output_name,file_key) | Same file key in different outputs represents separate processing records. |
| pdf_path VARCHAR | pdf_path TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| pdf_sha256 VARCHAR | pdf_sha256 TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| pdf_size_bytes BIGINT | pdf_size_bytes BIGINT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |
| status VARCHAR | status TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| output_path VARCHAR | output_path TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| output_sha256 VARCHAR | output_sha256 TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| first_seen_at VARCHAR | first_seen_at_raw TEXT; first_seen_at_state TEXT; first_seen_at_local_timestamp TIMESTAMP; first_seen_at_instant TIMESTAMPTZ | Parse explicit formats; explicit offset -> instant; no offset -> local timestamp; errors/missing retained. | None | Source mixes zoned and unzoned values; creation/processing time is not historical document date. |
| processed_at VARCHAR | processed_at_raw TEXT; processed_at_state TEXT; processed_at_local_timestamp TIMESTAMP; processed_at_instant TIMESTAMPTZ | Parse explicit formats; explicit offset -> instant; no offset -> local timestamp; errors/missing retained. | None | Source mixes zoned and unzoned values; creation/processing time is not historical document date. |
| run_id VARCHAR | raw_run_id TEXT; run_id TEXT; run_match_status TEXT | Keep raw value; resolve exact supplied run ID; missing/unmatched -> NULL FK and explicit state/issue. | Optional FK -> upstream_runs.run_id | 63,676 source rows have no run ID; retain their processing evidence. |
| input_tokens BIGINT | input_tokens BIGINT | Preserve value, SQL NULL and blanks; no inferred default. | None | Missing metrics remain unknown, not zero; upstream measurements stay separate from our importer. |
| output_tokens BIGINT | output_tokens BIGINT | Preserve value, SQL NULL and blanks; no inferred default. | None | Missing metrics remain unknown, not zero; upstream measurements stay separate from our importer. |
| api_latency_ms BIGINT | api_latency_ms BIGINT | Preserve value, SQL NULL and blanks; no inferred default. | None | Missing metrics remain unknown, not zero; upstream measurements stay separate from our importer. |
| attempts INTEGER | attempts INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Reported attempts count is metadata, not an individual attempt-history table. |
| error_message VARCHAR | error_message TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| model_used VARCHAR | model_used TEXT | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source metadata and traceability without inventing semantics. |
| validation_score INTEGER | validation_score INTEGER | Preserve value, SQL NULL and blanks; no inferred default. | None | Retain source integer width and avoid narrowing or rounding. |

## Additional derived fields

`chunks.offset_status` records diagnostics against reported/actual document lengths.
A chunk TSVECTOR and workload indexes will be implemented in the query stage; they
are not part of the current ETL schema.
Merchant/name search values are normalization outputs, not registry identities.
All optional-reference states are consistent with their nullable FK through CHECKs.
Domain/lineage FKs use ON UPDATE RESTRICT and ON DELETE RESTRICT; audit bookkeeping
FKs use default NO ACTION. Neither silently cascades deletion of source evidence.

## Verification

The source-to-target validation reconstructs fingerprints from all retained original
fields and compares them to source-generated fingerprints. Exact monetary conversion
is checked separately. Synthetic tests cover missing/invalid values, partial precision,
JSON states, repeats/conflicts, interrupted batches and actual DB FK rejection.
Update this mapping when subsequent query/index work adds derived fields.

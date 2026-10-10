# Z1 source data profile

Fixed revision: `133ef9f0a539fafc270cde8fa8638dc38d89968d`.

Generated from all 56 manifest-verified shards by `scripts/profile_z1.py`.
Outputs contain schemas and aggregates, not document text or names.

Equality candidate counts do not prove a shared ID namespace or identity.

Date castability is a diagnostic; partial precision requires separate import rules.

## documents

Rows: 1,424,673 (expected 1,424,673).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| file_key | VARCHAR | 0 | 0 |
| dataset | VARCHAR | 0 | 0 |
| full_text | VARCHAR | 0 | 511 |
| document_type | VARCHAR | 564974 | 0 |
| date | VARCHAR | 637074 | 0 |
| is_photo | BOOLEAN | 0 | 0 |
| has_handwriting | BOOLEAN | 56820 | 0 |
| has_stamps | BOOLEAN | 56820 | 0 |
| ocr_source | VARCHAR | 884769 | 0 |
| additional_notes | VARCHAR | 554401 | 1327 |
| page_number | VARCHAR | 1055932 | 0 |
| document_number | VARCHAR | 1352329 | 0 |
| char_count | INTEGER | 0 | 0 |
| created_at | VARCHAR | 0 | 0 |
| email_fields | VARCHAR | 1424038 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 1424673,
    "distinct": 1424673,
    "extra_occurrences": 0
  },
  "file_key": {
    "nonnull": 1424673,
    "distinct": 1424673,
    "extra_occurrences": 0
  },
  "dataset,file_key": {
    "groups": 1424673,
    "extra_occurrences": 0
  }
}
```

Value checks:

```json
{
  "date": {
    "nonblank": 787599,
    "year_only": 1209,
    "month_only": 10,
    "not_castable_as_timestamp": 752558
  },
  "created_at": {
    "nonblank": 1424673,
    "year_only": 0,
    "month_only": 0,
    "not_castable_as_timestamp": 0
  },
  "email_fields": {
    "sql_null": 1424038,
    "blank": 0,
    "invalid_json_nonblank": 0,
    "json_null": 0,
    "valid_nonnull_json": 635
  }
}
```

## chunks

Rows: 2,193,090 (expected 2,193,090).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| document_id | BIGINT | 0 | 0 |
| chunk_index | INTEGER | 0 | 0 |
| content | VARCHAR | 0 | 0 |
| token_count | INTEGER | 0 | 0 |
| char_start | INTEGER | 0 | 0 |
| char_end | INTEGER | 0 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 2193090,
    "distinct": 2193090,
    "extra_occurrences": 0
  }
}
```

## entities

Rows: 10,629,198 (expected 10,629,198).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| document_id | BIGINT | 0 | 0 |
| entity_type | VARCHAR | 0 | 0 |
| value | VARCHAR | 0 | 0 |
| normalized_value | VARCHAR | 10629198 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 10629198,
    "distinct": 10629198,
    "extra_occurrences": 0
  }
}
```

## persons

Rows: 1,614 (expected 1,614).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| canonical_name | VARCHAR | 0 | 0 |
| slug | VARCHAR | 0 | 0 |
| category | VARCHAR | 0 | 0 |
| aliases | VARCHAR | 0 | 0 |
| search_terms | VARCHAR | 0 | 0 |
| sources | VARCHAR | 0 | 0 |
| notes | VARCHAR | 1614 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 1614,
    "distinct": 1614,
    "extra_occurrences": 0
  }
}
```

## kg_entities

Rows: 467 (expected 467).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| name | VARCHAR | 0 | 0 |
| entity_type | VARCHAR | 0 | 0 |
| description | VARCHAR | 467 | 0 |
| metadata | VARCHAR | 0 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 467,
    "distinct": 467,
    "extra_occurrences": 0
  }
}
```

## kg_relationships

Rows: 2,198 (expected 2,198).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| source_id | BIGINT | 0 | 0 |
| target_id | BIGINT | 0 | 0 |
| relationship_type | VARCHAR | 0 | 0 |
| weight | DOUBLE | 0 | 0 |
| evidence | VARCHAR | 2198 | 0 |
| metadata | VARCHAR | 0 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 2198,
    "distinct": 2198,
    "extra_occurrences": 0
  }
}
```

## derived_events

Rows: 3,038 (expected 3,038).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| event_date | VARCHAR | 26 | 0 |
| event_end_date | VARCHAR | 2973 | 0 |
| event_type | VARCHAR | 0 | 0 |
| track | VARCHAR | 0 | 0 |
| headline | VARCHAR | 0 | 0 |
| location | VARCHAR | 1007 | 0 |
| amount | DOUBLE | 2700 | 0 |
| currency | VARCHAR | 0 | 0 |
| payer | VARCHAR | 3038 | 0 |
| payee | VARCHAR | 3036 | 0 |
| route_from | VARCHAR | 2766 | 0 |
| route_to | VARCHAR | 2766 | 0 |
| aircraft | VARCHAR | 3038 | 0 |
| time_of_day | VARCHAR | 1361 | 0 |
| confidence | VARCHAR | 0 | 0 |
| narrative | VARCHAR | 7 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 3038,
    "distinct": 3038,
    "extra_occurrences": 0
  }
}
```

Value checks:

```json
{
  "event_date": {
    "nonblank": 3012,
    "year_only": 0,
    "month_only": 0,
    "not_castable_as_timestamp": 0
  },
  "event_end_date": {
    "nonblank": 65,
    "year_only": 0,
    "month_only": 0,
    "not_castable_as_timestamp": 0
  },
  "amount": {
    "missing": 2700,
    "nonfinite": 0,
    "negative": 0,
    "zero": 0,
    "positive": 338
  }
}
```

## event_participants

Rows: 5,751 (expected 5,751).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| event_id | BIGINT | 0 | 0 |
| person_name | VARCHAR | 0 | 0 |
| role | VARCHAR | 0 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 5751,
    "distinct": 5751,
    "extra_occurrences": 0
  }
}
```

## event_sources

Rows: 21,910 (expected 21,910).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| event_id | BIGINT | 0 | 0 |
| file_key | VARCHAR | 0 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 21910,
    "distinct": 21910,
    "extra_occurrences": 0
  },
  "file_key": {
    "nonnull": 21910,
    "distinct": 720,
    "extra_occurrences": 21190
  }
}
```

## financial_transactions

Rows: 49,770 (expected 49,770).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| file_key | VARCHAR | 0 | 0 |
| dataset | VARCHAR | 0 | 0 |
| transaction_date | VARCHAR | 269 | 0 |
| amount | DOUBLE | 551 | 0 |
| currency | VARCHAR | 0 | 0 |
| merchant_name | VARCHAR | 295 | 0 |
| merchant_raw | VARCHAR | 23954 | 1 |
| merchant_category | VARCHAR | 61 | 0 |
| location | VARCHAR | 42979 | 0 |
| cardholder | VARCHAR | 7590 | 0 |
| description | VARCHAR | 25905 | 0 |
| card_type | VARCHAR | 48722 | 0 |
| account_digits | VARCHAR | 38994 | 0 |
| statement_date | VARCHAR | 6782 | 0 |
| flight_from | VARCHAR | 49702 | 0 |
| flight_to | VARCHAR | 49703 | 0 |
| flight_carrier | VARCHAR | 49695 | 0 |
| flight_departure | VARCHAR | 49702 | 0 |
| flight_ticket | VARCHAR | 49700 | 0 |
| flight_passenger | VARCHAR | 49753 | 0 |
| source_page | INTEGER | 49770 | 0 |
| extraction_model | VARCHAR | 0 | 0 |
| extraction_confidence | DOUBLE | 49770 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 49770,
    "distinct": 49770,
    "extra_occurrences": 0
  },
  "file_key": {
    "nonnull": 49770,
    "distinct": 4614,
    "extra_occurrences": 45156
  },
  "dataset,file_key": {
    "groups": 4614,
    "extra_occurrences": 45156
  }
}
```

Value checks:

```json
{
  "transaction_date": {
    "nonblank": 49501,
    "year_only": 0,
    "month_only": 0,
    "not_castable_as_timestamp": 0
  },
  "amount": {
    "missing": 551,
    "nonfinite": 0,
    "negative": 18237,
    "zero": 532,
    "positive": 30450
  },
  "statement_date": {
    "nonblank": 42988,
    "year_only": 0,
    "month_only": 0,
    "not_castable_as_timestamp": 0
  }
}
```

## curated_docs

Rows: 5,766 (expected 5,766).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| id | BIGINT | 0 | 0 |
| file_key | VARCHAR | 0 | 0 |
| subject | VARCHAR | 0 | 0 |
| status | VARCHAR | 0 | 0 |
| tier | VARCHAR | 0 | 0 |
| category | VARCHAR | 0 | 0 |
| doc_date | VARCHAR | 165 | 0 |
| doc_from | VARCHAR | 681 | 0 |
| doc_to | VARCHAR | 961 | 0 |
| headline | VARCHAR | 8 | 0 |
| key_quote | VARCHAR | 138 | 0 |
| detail | VARCHAR | 40 | 0 |
| thread_value | VARCHAR | 783 | 0 |
| also_appears_as | VARCHAR | 4928 | 0 |

Candidate keys:

```json
{
  "id": {
    "nonnull": 5766,
    "distinct": 5766,
    "extra_occurrences": 0
  },
  "file_key": {
    "nonnull": 5766,
    "distinct": 5662,
    "extra_occurrences": 104
  }
}
```

Value checks:

```json
{
  "doc_date": {
    "nonblank": 5601,
    "year_only": 60,
    "month_only": 39,
    "not_castable_as_timestamp": 1268
  }
}
```

## provenance/runs

Rows: 123 (expected 123).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| run_id | VARCHAR | 0 | 0 |
| started_at | VARCHAR | 0 | 0 |
| completed_at | VARCHAR | 0 | 0 |
| status | VARCHAR | 0 | 0 |
| input_dir | VARCHAR | 0 | 0 |
| output_name | VARCHAR | 0 | 0 |
| model | VARCHAR | 0 | 0 |
| dpi | INTEGER | 0 | 0 |
| workers | INTEGER | 0 | 0 |
| rpm | INTEGER | 0 | 0 |
| git_commit | VARCHAR | 11 | 0 |
| hostname | VARCHAR | 1 | 0 |
| total_files | INTEGER | 0 | 0 |
| success_count | INTEGER | 0 | 0 |
| fail_count | INTEGER | 0 | 0 |
| input_tokens | BIGINT | 0 | 0 |
| output_tokens | BIGINT | 0 | 0 |
| cost_usd | DOUBLE | 0 | 0 |
| last_heartbeat | VARCHAR | 100 | 0 |

Candidate keys:

```json
{
  "run_id": {
    "nonnull": 123,
    "distinct": 123,
    "extra_occurrences": 0
  }
}
```

Value checks:

```json
{
  "started_at": {
    "nonblank": 123,
    "year_only": 0,
    "month_only": 0,
    "not_castable_as_timestamp": 0
  },
  "completed_at": {
    "nonblank": 123,
    "year_only": 0,
    "month_only": 0,
    "not_castable_as_timestamp": 0
  }
}
```

## provenance/files

Rows: 1,387,775 (expected 1,387,775).

| Field | Source type | SQL NULL | Blank/whitespace |
|---|---|---:|---:|
| file_key | VARCHAR | 0 | 0 |
| output_name | VARCHAR | 0 | 0 |
| pdf_path | VARCHAR | 0 | 0 |
| pdf_sha256 | VARCHAR | 538933 | 0 |
| pdf_size_bytes | BIGINT | 538933 | 0 |
| status | VARCHAR | 0 | 0 |
| output_path | VARCHAR | 2 | 0 |
| output_sha256 | VARCHAR | 2 | 0 |
| first_seen_at | VARCHAR | 0 | 0 |
| processed_at | VARCHAR | 0 | 0 |
| run_id | VARCHAR | 63676 | 0 |
| input_tokens | BIGINT | 602786 | 0 |
| output_tokens | BIGINT | 602786 | 0 |
| api_latency_ms | BIGINT | 602786 | 0 |
| attempts | INTEGER | 0 | 0 |
| error_message | VARCHAR | 1383206 | 0 |
| model_used | VARCHAR | 0 | 0 |
| validation_score | INTEGER | 650620 | 0 |

Candidate keys:

```json
{
  "file_key": {
    "nonnull": 1387775,
    "distinct": 1387767,
    "extra_occurrences": 8
  },
  "run_id": {
    "nonnull": 1324099,
    "distinct": 83,
    "extra_occurrences": 1324016
  },
  "output_name,file_key": {
    "groups": 1387775,
    "extra_occurrences": 0
  }
}
```

Value checks:

```json
{
  "first_seen_at": {
    "nonblank": 1387775,
    "year_only": 0,
    "month_only": 0,
    "not_castable_as_timestamp": 0
  },
  "processed_at": {
    "nonblank": 1387775,
    "year_only": 0,
    "month_only": 0,
    "not_castable_as_timestamp": 0
  }
}
```

## Reference candidates

| Candidate relationship | Missing | Unmatched | Single equality candidate | Ambiguous |
|---|---:|---:|---:|---:|
| chunks.document_id -> documents.id | 0 | 0 | 2193090 | 0 |
| entities.document_id -> documents.id | 0 | 78 | 10629120 | 0 |
| event_participants.event_id -> derived_events.id | 0 | 0 | 5751 | 0 |
| event_sources.event_id -> derived_events.id | 0 | 0 | 21910 | 0 |
| event_sources.file_key -> documents.file_key | 0 | 16651 | 5259 | 0 |
| financial_transactions.file_key -> documents.file_key | 0 | 0 | 49770 | 0 |
| curated_docs.file_key -> documents.file_key | 0 | 0 | 5766 | 0 |
| provenance/files.run_id -> provenance/runs.run_id | 63676 | 0 | 1324099 | 0 |
| kg_relationships.source_id -> kg_entities.id | 0 | 0 | 2198 | 0 |
| kg_relationships.target_id -> kg_entities.id | 0 | 0 | 2198 | 0 |

## Reproduce offline

```powershell
.\.venv\Scripts\python.exe .\scripts\download_z1.py --verify-only
.\.venv\Scripts\python.exe .\scripts\profile_z1.py
```

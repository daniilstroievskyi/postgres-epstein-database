"""Measure additional schema-design facts without exporting source text or names."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb

from profile_z1 import create_source_views, identifier, literal
from z1_source import PROJECT_ROOT, REVISION, load_manifest, sha256_of, MANIFEST_PATH


def main() -> None:
    manifest = load_manifest(verify=True)
    report = {
        "revision": REVISION,
        "manifest_sha256": sha256_of(MANIFEST_PATH),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Aggregate diagnostics only; equality is not proof of identity.",
        "checks": {},
    }
    scratch = PROJECT_ROOT / "data" / "work" / "analysis"
    scratch.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute("SET memory_limit = '512MB'")
        connection.execute("SET threads = 2")
        connection.execute(f"SET temp_directory = {literal(str(scratch))}")
        create_source_views(connection, manifest)

        def measure(label: str, sql: str) -> None:
            result = connection.execute(sql)
            columns = [item[0] for item in result.description]
            report["checks"][label] = [dict(zip(columns, row)) for row in result.fetchall()]
            print(f"Measured: {label}", flush=True)

        measure("chunk_keys_and_offsets", """
            SELECT count(*) AS rows,
                   (SELECT count(*) FROM (SELECT document_id,chunk_index FROM chunks GROUP BY 1,2)) AS document_index_groups,
                   count(*) FILTER (WHERE chunk_index < 0 OR token_count < 0 OR char_start < 0 OR char_end < char_start) AS invalid_basic_bounds,
                   min(chunk_index) AS min_chunk_index, max(chunk_index) AS max_chunk_index
            FROM chunks
        """)
        measure("chunk_offsets_vs_document_char_count", """
            SELECT count(*) AS rows,
                   count(*) FILTER (WHERE c.char_end > d.char_count) AS end_exceeds_reported_document_length
            FROM chunks c JOIN documents d ON c.document_id = d.id
        """)
        measure("chunk_offsets_vs_actual_document_length", """
            SELECT count(*) AS chunk_rows,
                   count(*) FILTER (WHERE c.char_end > length(d.full_text)) AS end_exceeds_actual_document_length,
                   count(*) FILTER (WHERE d.char_count != length(d.full_text)) AS chunks_with_parent_reported_length_disagreement
            FROM chunks c JOIN documents d ON c.document_id = d.id
        """)
        measure("entity_id_ranges", """
            SELECT 'documents' AS layer, min(id) AS min_id,max(id) AS max_id FROM documents
            UNION ALL SELECT 'entities',min(id),max(id) FROM entities
            UNION ALL SELECT 'entities.document_id',min(document_id),max(document_id) FROM entities
        """)
        measure("finance_currencies", """
            SELECT currency, count(*) AS rows,
                   count(*) FILTER (WHERE amount IS NULL) AS missing_amount,
                   count(*) FILTER (WHERE amount < 0) AS negative_amount,
                   count(*) FILTER (WHERE amount IS NOT NULL AND isfinite(amount) AND amount != round(amount,2)) AS not_equal_to_two_decimal_rounding
            FROM financial_transactions GROUP BY currency ORDER BY currency NULLS FIRST
        """)
        measure("finance_document_dataset_consistency", """
            SELECT count(*) AS matched_rows,
                   count(*) FILTER (WHERE f.dataset IS DISTINCT FROM d.dataset) AS dataset_disagreements
            FROM financial_transactions f JOIN documents d ON f.file_key=d.file_key
        """)
        measure("provenance_document_candidates", """
            SELECT count(*) AS rows,
                   count(*) FILTER (WHERE d.id IS NULL) AS unmatched_file_keys,
                   count(*) FILTER (WHERE d.id IS NOT NULL) AS matched_file_keys
            FROM provenance_files f LEFT JOIN documents d ON f.file_key=d.file_key
        """)
        measure("person_slug_keys", """
            SELECT count(*) AS rows,count(DISTINCT slug) AS distinct_slugs FROM persons
        """)

        for table, field in [
            ("documents", "email_fields"), ("persons", "aliases"),
            ("persons", "search_terms"), ("persons", "sources"),
            ("kg_entities", "metadata"), ("kg_relationships", "metadata"),
            ("curated_docs", "also_appears_as"),
        ]:
            column = identifier(field)
            measure(f"json:{table}.{field}", f"""
                SELECT count(*) AS rows,
                    count(*) FILTER (WHERE {column} IS NULL) AS sql_null,
                    count(*) FILTER (WHERE trim({column}) = '') AS blank,
                    count(*) FILTER (WHERE trim({column}) <> '' AND NOT json_valid({column})) AS invalid_nonblank,
                    count(*) FILTER (WHERE json_type(try_cast({column} AS JSON)) = 'NULL') AS json_null,
                    count(*) FILTER (WHERE json_type(try_cast({column} AS JSON)) = 'ARRAY') AS arrays,
                    count(*) FILTER (WHERE json_type(try_cast({column} AS JSON)) = 'OBJECT') AS objects,
                    count(*) FILTER (WHERE json_valid({column}) AND json_type(try_cast({column} AS JSON)) NOT IN ('NULL','ARRAY','OBJECT')) AS other_valid
                FROM {identifier(table)}
            """)
        measure("person_alias_array_elements", """
            SELECT json_type(e.value) AS element_type, count(*) AS elements
            FROM persons p, json_each(try_cast(p.aliases AS JSON)) e
            GROUP BY 1 ORDER BY 1
        """)
        measure("curated_alternate_file_array_elements", """
            SELECT json_type(e.value) AS element_type, count(*) AS elements
            FROM curated_docs c, json_each(try_cast(c.also_appears_as AS JSON)) e
            GROUP BY 1 ORDER BY 1
        """)
        for table, field in [
            ("documents", "date"), ("documents", "created_at"),
            ("derived_events", "event_date"), ("derived_events", "event_end_date"),
            ("financial_transactions", "transaction_date"),
            ("financial_transactions", "statement_date"),
            ("curated_docs", "doc_date"),
            ("provenance_runs", "started_at"), ("provenance_runs", "completed_at"),
            ("provenance_runs", "last_heartbeat"),
            ("provenance_files", "first_seen_at"), ("provenance_files", "processed_at"),
        ]:
            column = identifier(field)
            measure(f"date_syntax:{table}.{field}", f"""
                SELECT category,count(*) AS rows FROM (
                    SELECT CASE
                        WHEN {column} IS NULL THEN 'sql_null'
                        WHEN trim({column}) = '' THEN 'blank'
                        WHEN regexp_full_match(trim({column}), '[0-9]{{4}}') THEN 'year_syntax'
                        WHEN regexp_full_match(trim({column}), '[0-9]{{4}}-[0-9]{{2}}') THEN 'month_syntax'
                        WHEN regexp_full_match(trim({column}), '[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}') THEN 'day_syntax'
                        WHEN regexp_full_match(trim({column}), '[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}[ T].*') THEN 'timestamp_syntax'
                        ELSE 'other_syntax'
                    END AS category FROM {identifier(table)}
                ) GROUP BY category ORDER BY category
            """)
        measure("email_object_key_presence", """
            SELECT count(*) AS valid_objects,
                   count(*) FILTER (WHERE json_exists(try_cast(email_fields AS JSON), '$.subject')) AS subject_key_present,
                   count(*) FILTER (WHERE NOT json_exists(try_cast(email_fields AS JSON), '$.subject')) AS subject_key_absent,
                   count(*) FILTER (WHERE json_type(try_cast(email_fields AS JSON), '$.subject')='NULL') AS subject_json_null
            FROM documents WHERE json_type(try_cast(email_fields AS JSON))='OBJECT'
        """)
        for table, fields in [
            ("documents", ["created_at"]),
            ("provenance_runs", ["started_at", "completed_at", "last_heartbeat"]),
            ("provenance_files", ["first_seen_at", "processed_at"]),
        ]:
            for field in fields:
                column = identifier(field)
                measure(f"timezone_syntax:{table}.{field}", f"""
                    SELECT count({column}) AS nonnull,
                           count(*) FILTER (WHERE regexp_matches(trim({column}), '(Z|[+-][0-9]{{2}}:[0-9]{{2}})$')) AS explicit_zone_suffix
                    FROM {identifier(table)}
                """)
    destination = PROJECT_ROOT / "evidence" / "schema-analysis.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Saved evidence/schema-analysis.json", flush=True)


if __name__ == "__main__":
    main()

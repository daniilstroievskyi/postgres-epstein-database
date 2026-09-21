"""Run the required C1 checks and save reproducible evidence."""

import argparse
import os
from pathlib import Path

import psycopg


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = PROJECT_ROOT / "C1" / "evidence"
DEFAULT_DSN = "host=localhost port=5432 dbname=dbs2 user=postgres"

FTS_QUERY = """
SELECT source_id AS chunk_id, document_source_id AS document_id
FROM c1_checkpoint.chunks
WHERE to_tsvector('english', coalesce(content, ''))
      @@ plainto_tsquery('english', 'flight')
ORDER BY source_id
"""

EXPLAIN_QUERY = "EXPLAIN (FORMAT TEXT) " + FTS_QUERY

LITERAL_QUERY = """
WITH examples(value) AS (
    VALUES ('flight'), ('flights'), ('preflight')
)
SELECT
    value,
    to_tsvector('english', value)::text AS normalized_fts,
    plainto_tsquery('english', 'flight')::text AS normalized_query,
    to_tsvector('english', value) @@ plainto_tsquery('english', 'flight')
        AS fts_matches_flight,
    value ILIKE '%flight%' AS ilike_contains_flight
FROM examples
ORDER BY value
"""

# One AI-generated claim, verified against the imported data (C1/run.md).
AI_CLAIM = (
    "No imported sample chunk contains the substring 'flight' in any form, "
    "so the empty FTS result is correct data, not an indexing error."
)

# ILIKE is the widest possible match; 'floor' is a positive control showing
# that the same test does find rows in this sample.
AI_CLAIM_QUERY = """
SELECT
    count(*) AS chunks_total,
    count(*) FILTER (WHERE content ILIKE '%flight%') AS chunks_with_flight,
    count(*) FILTER (WHERE content ILIKE '%floor%') AS chunks_with_floor
FROM c1_checkpoint.chunks
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL", DEFAULT_DSN),
        help=(
            "PostgreSQL connection string. Defaults to DATABASE_URL, then "
            f"{DEFAULT_DSN!r}. libpq PG* variables such as PGPASSWORD are honored."
        ),
    )
    return parser.parse_args()


def write_text(filename: str, content: str) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / filename).write_text(content.rstrip() + "\n", encoding="utf-8")


def write_pairs(filename: str, rows: list[tuple[int, int]]) -> None:
    lines = ["chunk_id\tdocument_id"]
    lines.extend(f"{chunk_id}\t{document_id}" for chunk_id, document_id in rows)
    write_text(filename, "\n".join(lines))


def fetch_plan(cursor: psycopg.Cursor) -> list[str]:
    cursor.execute(EXPLAIN_QUERY)
    return [row[0] for row in cursor.fetchall()]


def fetch_fts_rows(cursor: psycopg.Cursor) -> list[tuple[int, int]]:
    cursor.execute(FTS_QUERY)
    return cursor.fetchall()


def main() -> None:
    args = parse_args()

    with psycopg.connect(args.dsn, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP INDEX IF EXISTS c1_checkpoint.chunks_content_fts_gin"
            )
            cursor.execute("ANALYZE c1_checkpoint.chunks")

            before_plan = fetch_plan(cursor)
            before_rows = fetch_fts_rows(cursor)

            cursor.execute(
                """
                CREATE INDEX chunks_content_fts_gin
                ON c1_checkpoint.chunks
                USING GIN (to_tsvector('english', coalesce(content, '')))
                """
            )
            cursor.execute("ANALYZE c1_checkpoint.chunks")

            after_plan = fetch_plan(cursor)
            after_rows = fetch_fts_rows(cursor)
            if before_rows != after_rows:
                raise RuntimeError(
                    "FTS result rows or their order changed after index creation"
                )

            cursor.execute(
                """
                SELECT indexdef,
                       pg_relation_size(
                           'c1_checkpoint.chunks_content_fts_gin'::regclass
                       ),
                       pg_size_pretty(pg_relation_size(
                           'c1_checkpoint.chunks_content_fts_gin'::regclass
                       ))
                FROM pg_indexes
                WHERE schemaname = 'c1_checkpoint'
                  AND indexname = 'chunks_content_fts_gin'
                """
            )
            index_definition, index_bytes, index_pretty = cursor.fetchone()

            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM c1_checkpoint.documents),
                    (SELECT min(source_id) FROM c1_checkpoint.documents),
                    (SELECT max(source_id) FROM c1_checkpoint.documents),
                    (SELECT count(*) FROM c1_checkpoint.chunks),
                    (SELECT count(DISTINCT document_source_id)
                     FROM c1_checkpoint.chunks),
                    (SELECT count(*) FROM (
                        SELECT source_id
                        FROM c1_checkpoint.documents
                        GROUP BY source_id HAVING count(*) > 1
                    ) AS duplicate_documents),
                    (SELECT count(*) FROM (
                        SELECT source_id
                        FROM c1_checkpoint.chunks
                        GROUP BY source_id HAVING count(*) > 1
                    ) AS duplicate_chunks),
                    (SELECT count(*)
                     FROM c1_checkpoint.chunks AS c
                     LEFT JOIN c1_checkpoint.documents AS d
                       ON d.source_id = c.document_source_id
                     WHERE d.source_id IS NULL),
                    (SELECT convalidated
                     FROM pg_constraint
                     WHERE conname = 'chunks_document_fk'
                       AND conrelid = 'c1_checkpoint.chunks'::regclass)
                """
            )
            verification = cursor.fetchone()
            expected_verification = (1000, 1, 1000, 160, 157, 0, 0, 0, True)
            if verification != expected_verification:
                raise RuntimeError(
                    "Database verification failed: "
                    f"{verification} != {expected_verification}"
                )

            cursor.execute(LITERAL_QUERY)
            literal_rows = cursor.fetchall()

            cursor.execute(AI_CLAIM_QUERY)
            chunks_total, chunks_with_flight, chunks_with_floor = cursor.fetchone()

            cursor.execute("SELECT version()")
            postgres_version = cursor.fetchone()[0]

    write_pairs("fts_results_before.tsv", before_rows)
    write_pairs("fts_results_after.tsv", after_rows)
    write_text("explain_before.txt", "\n".join(before_plan))
    write_text("explain_after.txt", "\n".join(after_plan))
    write_text(
        "index_info.txt",
        "\n".join(
            [
                f"definition: {index_definition}",
                f"size_bytes: {index_bytes}",
                f"size_pretty: {index_pretty}",
            ]
        ),
    )

    verification_labels = (
        "document_count",
        "min_document_id",
        "max_document_id",
        "chunk_count",
        "referenced_document_count",
        "duplicate_document_ids",
        "duplicate_chunk_ids",
        "orphan_chunk_count",
        "foreign_key_validated",
    )
    verification_lines = [f"postgres_version: {postgres_version}"]
    verification_lines.extend(
        f"{label}: {value}"
        for label, value in zip(verification_labels, verification, strict=True)
    )
    verification_lines.extend(
        [
            f"fts_result_count_before: {len(before_rows)}",
            f"fts_result_count_after: {len(after_rows)}",
            f"fts_rows_and_order_identical: {before_rows == after_rows}",
        ]
    )
    write_text("verification.txt", "\n".join(verification_lines))

    literal_lines = [
        "value\tnormalized_fts\tnormalized_query\tfts_matches\tilike_matches"
    ]
    literal_lines.extend("\t".join(map(str, row)) for row in literal_rows)
    literal_lines.extend(
        [
            "",
            "Meaning:",
            "FTS compares normalized English lexemes (whole searchable words).",
            "Therefore flight and flights share the lexeme 'flight'.",
            "ILIKE '%flight%' performs a case-insensitive character-substring test.",
            "Therefore preflight contains the substring even though its FTS lexeme is",
            "not the separate lexeme 'flight'.",
        ]
    )
    write_text("literal_comparison.txt", "\n".join(literal_lines))

    claim_confirmed = chunks_with_flight == 0 and chunks_with_floor > 0
    claim_lines = [
        f"claim: {AI_CLAIM}",
        "test: " + " ".join(AI_CLAIM_QUERY.split()),
        f"chunks_total: {chunks_total}",
        f"chunks_with_flight_substring: {chunks_with_flight}",
        f"chunks_with_floor_substring (positive control): {chunks_with_floor}",
        f"verdict: {'confirmed' if claim_confirmed else 'NOT confirmed'}",
    ]
    write_text("ai_claim_check.txt", "\n".join(claim_lines))

    print(f"Evidence written to {EVIDENCE_DIR}")
    print(
        f"FTS rows before/after: {len(before_rows)}/{len(after_rows)}; "
        "content and order are identical."
    )
    print(f"AI claim {'confirmed' if claim_confirmed else 'NOT confirmed'}.")


if __name__ == "__main__":
    main()

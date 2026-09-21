"""Rebuild and populate the PostgreSQL schema for checkpoint C1."""

import argparse
import os
from pathlib import Path

import psycopg

from c1_sample import load_c1_sample


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DDL_PATH = PROJECT_ROOT / "sql" / "01_c1_schema.sql"
DEFAULT_DSN = "host=localhost port=5432 dbname=dbs2 user=postgres"


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
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Allow replacement of the dedicated c1_checkpoint schema.",
    )
    args = parser.parse_args()
    if not args.rebuild:
        parser.error(
            "Refusing to replace c1_checkpoint without the explicit --rebuild flag"
        )
    return args


def copy_rows(cursor: psycopg.Cursor, statement: str, rows: list[tuple]) -> None:
    with cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def assert_database_state(cursor: psycopg.Cursor) -> None:
    cursor.execute(
        """
        SELECT
            (SELECT count(*) FROM c1_checkpoint.documents),
            (SELECT min(source_id) FROM c1_checkpoint.documents),
            (SELECT max(source_id) FROM c1_checkpoint.documents),
            (SELECT count(*) FROM c1_checkpoint.chunks),
            (SELECT count(DISTINCT document_source_id)
             FROM c1_checkpoint.chunks),
            (SELECT count(*)
             FROM c1_checkpoint.chunks AS c
             LEFT JOIN c1_checkpoint.documents AS d
               ON d.source_id = c.document_source_id
             WHERE d.source_id IS NULL)
        """
    )
    actual = cursor.fetchone()
    expected = (1000, 1, 1000, 160, 157, 0)
    if actual != expected:
        raise RuntimeError(f"Post-import validation failed: {actual} != {expected}")

    cursor.execute(
        """
        SELECT convalidated
        FROM pg_constraint
        WHERE conname = 'chunks_document_fk'
          AND conrelid = 'c1_checkpoint.chunks'::regclass
        """
    )
    constraint = cursor.fetchone()
    if constraint != (True,):
        raise RuntimeError("chunks_document_fk is missing or not validated")


def main() -> None:
    args = parse_args()
    sample = load_c1_sample()
    ddl = DDL_PATH.read_text(encoding="utf-8")

    print(
        "Validated c1-sample-v1 locally: "
        f"{len(sample.documents)} documents, {len(sample.chunks)} chunks."
    )
    print("Rebuilding only PostgreSQL schema c1_checkpoint ...")

    with psycopg.connect(args.dsn, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(ddl)
            copy_rows(
                cursor,
                """
                COPY c1_checkpoint.documents
                    (source_id, file_key, dataset, document_type)
                FROM STDIN
                """,
                sample.documents,
            )
            copy_rows(
                cursor,
                """
                COPY c1_checkpoint.chunks
                    (source_id, document_source_id, chunk_index, content)
                FROM STDIN
                """,
                sample.chunks,
            )
            cursor.execute("ANALYZE c1_checkpoint.documents")
            cursor.execute("ANALYZE c1_checkpoint.chunks")
            assert_database_state(cursor)

    print("Import committed; counts and the validated foreign key are correct.")


if __name__ == "__main__":
    main()

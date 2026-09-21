from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
PREVIEW_LENGTH = 120


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def short_value(value: object) -> object:
    if isinstance(value, str) and len(value) > PREVIEW_LENGTH:
        return value[:PREVIEW_LENGTH].replace("\n", " ") + "..."
    if isinstance(value, str):
        return value.replace("\n", " ")
    return value


def main() -> None:
    parquet_files = sorted(DATA_ROOT.rglob("*.parquet"))
    if not parquet_files:
        raise SystemExit(f"No Parquet files found under {DATA_ROOT}")

    connection = duckdb.connect()
    try:
        for parquet_file in parquet_files:
            file_path = str(parquet_file)
            print(f"\n=== {parquet_file.relative_to(PROJECT_ROOT)} ===")
            row_count = connection.execute(
                "SELECT COUNT(*) FROM read_parquet(?)", [file_path]
            ).fetchone()[0]
            print(f"Rows: {row_count}")
            schema = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [file_path]
            ).fetchall()
            print("Schema:")
            for column in schema:
                print(f"  {column[0]}: {column[1]}")

            columns = [column[0] for column in schema]
            if "content" in columns:
                selected_columns = [
                    name for name in (
                        "id", "document_id", "chunk_index", "token_count", "content"
                    ) if name in columns
                ]
                print("Field roles: id=chunk ID; document_id=source document ID; "
                      "chunk_index=chunk order; content=text content")
            else:
                selected_columns = [
                    name for name in (
                        "id", "file_key", "document_type", "date", "char_count"
                    ) if name in columns
                ]
                print("Field roles: id=source document ID; file_key=document key")

            selected_sql = ", ".join(quote_identifier(name) for name in selected_columns)
            print("Sample (text shortened):")
            sample = connection.execute(
                f"SELECT {selected_sql} FROM read_parquet(?) LIMIT 3", [file_path]
            ).fetchall()
            for row in sample:
                print(dict(zip(selected_columns, map(short_value, row))))

        print("\nRelationship overview:")
        print("  chunks.id is the chunk ID, not its order.")
        print("  chunks.document_id links a chunk to documents.id.")
        print("  chunks.chunk_index stores the chunk order within a document.")
        print("Question to resolve before schema design:")
        print("  Is documents.file_key the stable external identifier, while documents.id "
              "is the database/source row ID, or are both required as identifiers?")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
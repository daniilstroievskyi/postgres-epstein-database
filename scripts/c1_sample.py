"""Build and validate the deterministic c1-sample-v1 in memory."""

from dataclasses import dataclass
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_ROOT = PROJECT_ROOT / "data"
DOCUMENT_RELATIVE_PATH = Path(
    "data/documents/documents-00000-of-00015.parquet"
)
CHUNK_RELATIVE_PATH = Path("data/chunks/chunks-00000-of-00011.parquet")

EXPECTED_DOCUMENT_COUNT = 1_000
EXPECTED_CHUNK_COUNT = 160
EXPECTED_CHUNKED_DOCUMENT_COUNT = 157


@dataclass(frozen=True)
class C1Sample:
    documents: list[tuple]
    chunks: list[tuple]


def source_path(relative_path: Path) -> Path:
    """Resolve files downloaded by this repository, with a legacy fallback."""
    candidates = (
        DOWNLOAD_ROOT / relative_path,
        PROJECT_ROOT / relative_path,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    searched = "\n  ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"Missing source file {relative_path}. Searched:\n  {searched}\n"
        "Run: python scripts/data_download.py"
    )


def load_c1_sample() -> C1Sample:
    """Select the exact checkpoint sample from the two Parquet shards."""
    document_path = source_path(DOCUMENT_RELATIVE_PATH)
    chunk_path = source_path(CHUNK_RELATIVE_PATH)

    connection = duckdb.connect()
    try:
        documents = connection.execute(
            """
            SELECT id, file_key, dataset, document_type
            FROM read_parquet(?)
            ORDER BY id
            LIMIT 1000
            """,
            [str(document_path)],
        ).fetchall()

        chunks = connection.execute(
            """
            WITH selected_documents AS (
                SELECT id
                FROM read_parquet(?)
                ORDER BY id
                LIMIT 1000
            )
            SELECT c.id, c.document_id, c.chunk_index, c.content
            FROM read_parquet(?) AS c
            INNER JOIN selected_documents AS d ON d.id = c.document_id
            ORDER BY c.id
            """,
            [str(document_path), str(chunk_path)],
        ).fetchall()
    finally:
        connection.close()

    sample = C1Sample(documents=documents, chunks=chunks)
    validate_c1_sample(sample)
    return sample


def validate_c1_sample(sample: C1Sample) -> None:
    """Reject a wrong revision, wrong shard, or accidental duplicate sample."""
    document_ids = [row[0] for row in sample.documents]
    chunk_ids = [row[0] for row in sample.chunks]
    chunk_document_ids = [row[1] for row in sample.chunks]
    chunk_positions = [(row[1], row[2]) for row in sample.chunks]

    checks = {
        "document count": len(sample.documents) == EXPECTED_DOCUMENT_COUNT,
        "document IDs 1..1000": document_ids == list(range(1, 1001)),
        "unique document IDs": len(set(document_ids)) == len(document_ids),
        "non-null document keys": all(
            row[0] is not None and row[1] is not None and row[2] is not None
            for row in sample.documents
        ),
        "chunk count": len(sample.chunks) == EXPECTED_CHUNK_COUNT,
        "unique chunk IDs": len(set(chunk_ids)) == len(chunk_ids),
        "157 referenced documents": (
            len(set(chunk_document_ids)) == EXPECTED_CHUNKED_DOCUMENT_COUNT
        ),
        "no orphan chunks": set(chunk_document_ids).issubset(document_ids),
        "unique chunk positions": len(set(chunk_positions)) == len(chunk_positions),
        "non-null chunk keys": all(
            row[0] is not None and row[1] is not None and row[2] is not None
            for row in sample.chunks
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Invalid c1-sample-v1: " + ", ".join(failed))

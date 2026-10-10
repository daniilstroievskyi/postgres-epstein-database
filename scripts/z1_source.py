"""Shared, fixed input contract for the complete Z1 assignment."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_ROOT = PROJECT_ROOT / "data"
MANIFEST_PATH = PROJECT_ROOT / "source-manifest.json"
REPO_ID = "kabasshouse/epstein-data"
REVISION = "133ef9f0a539fafc270cde8fa8638dc38d89968d"
DOCUMENTATION = ("README.md", "LICENSE", "PROVENANCE.md")
LAYERS = {
    "documents": (15, 1_424_673),
    "chunks": (11, 2_193_090),
    "entities": (18, 10_629_198),
    "persons": (1, 1_614),
    "kg_entities": (1, 467),
    "kg_relationships": (1, 2_198),
    "derived_events": (1, 3_038),
    "event_participants": (1, 5_751),
    "event_sources": (1, 21_910),
    "financial_transactions": (1, 49_770),
    "curated_docs": (1, 5_766),
    "provenance/runs": (1, 123),
    "provenance/files": (3, 1_387_775),
}


def expected_files() -> dict[str, str]:
    return {
        f"data/{layer}/{layer.rsplit('/', 1)[-1]}-{i:05d}-of-{count:05d}.parquet": layer
        for layer, (count, _) in LAYERS.items()
        for i in range(count)
    }


def validate_inventory(paths: list[str]) -> None:
    expected = set(expected_files())
    actual = set(paths)
    if len(paths) != len(actual):
        raise ValueError("Duplicate paths in the source inventory")
    if actual != expected:
        raise ValueError(
            f"Source inventory mismatch: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def sha256_of(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def source_path(relative: str) -> Path:
    if relative not in expected_files() and relative not in DOCUMENTATION:
        raise ValueError(f"Path outside the prescribed source: {relative}")
    return DOWNLOAD_ROOT / relative


def load_manifest(*, verify: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("repo_id") != REPO_ID or manifest.get("revision") != REVISION:
        raise ValueError("Manifest does not identify the prescribed repository/revision")
    files = manifest.get("files", [])
    validate_inventory([entry["path"] for entry in files])
    for entry in files:
        if entry.get("layer") != expected_files()[entry["path"]]:
            raise ValueError(f"Wrong layer for {entry['path']}")
        if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
            raise ValueError(f"Invalid SHA-256 for {entry['path']}")
        upstream_sha256 = entry.get("upstream_sha256")
        if upstream_sha256 is not None and upstream_sha256 != entry["sha256"]:
            raise ValueError(f"Manifest hash differs from pinned upstream hash: {entry['path']}")
        if entry.get("row_count", -1) < 0 or entry.get("bytes", -1) < 0:
            raise ValueError(f"Invalid count/size for {entry['path']}")
    for layer, (_, expected_rows) in LAYERS.items():
        actual_rows = sum(f["row_count"] for f in files if f["layer"] == layer)
        if actual_rows != expected_rows:
            raise ValueError(f"{layer}: {actual_rows} rows != {expected_rows}")
    documentation = manifest.get("documentation", [])
    if sorted(f["path"] for f in documentation) != sorted(DOCUMENTATION):
        raise ValueError("Manifest must include the three source documentation files")
    if verify:
        for entry in files + documentation:
            path = source_path(entry["path"])
            if path.stat().st_size != entry["bytes"] or sha256_of(path) != entry["sha256"]:
                raise ValueError(f"Source content does not match manifest: {entry['path']}")
        import duckdb

        with duckdb.connect() as connection:
            for entry in files:
                rows = connection.execute(
                    "SELECT count(*) FROM read_parquet(?)", [str(source_path(entry["path"]))]
                ).fetchone()[0]
                if rows != entry["row_count"]:
                    raise ValueError(f"Source row count changed: {entry['path']}")
    return manifest


def layer_paths(manifest: dict, layer: str) -> list[str]:
    return [str(source_path(f["path"])) for f in manifest["files"] if f["layer"] == layer]

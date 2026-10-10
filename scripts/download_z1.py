"""Download all prescribed Z1 inputs, or verify them entirely offline."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import duckdb
from huggingface_hub import HfApi, hf_hub_download

from z1_source import (
    DOCUMENTATION, DOWNLOAD_ROOT, LAYERS, MANIFEST_PATH, REPO_ID, REVISION,
    PROJECT_ROOT, expected_files, load_manifest, sha256_of, source_path, validate_inventory,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Verify files/hash/counts offline")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.verify_only:
        manifest = load_manifest(verify=True)
        evidence = PROJECT_ROOT / "evidence"
        evidence.mkdir(exist_ok=True)
        verification = {
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "mode": "offline; no Hub calls are made in this branch",
            "repo_id": REPO_ID, "revision": REVISION,
            "manifest_sha256": sha256_of(MANIFEST_PATH),
            "shards": len(manifest["files"]),
            "compressed_bytes": sum(entry["bytes"] for entry in manifest["files"]),
            "source_rows": sum(entry["row_count"] for entry in manifest["files"]),
            "checks": {"inventory": "passed", "sha256": "passed", "bytes": "passed", "row_counts": "passed", "documentation": "passed"},
            "layers": {
                layer: {
                    "files": sum(entry["layer"] == layer for entry in manifest["files"]),
                    "rows": sum(entry["row_count"] for entry in manifest["files"] if entry["layer"] == layer),
                }
                for layer in LAYERS
            },
        }
        (evidence / "source-validation.json").write_text(
            json.dumps(verification, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Verified offline: {len(manifest['files'])} shards, {len(LAYERS)} layers")
        return
    if args.workers < 1:
        parser.error("--workers must be positive")

    required = expected_files()
    tree = list(HfApi().list_repo_tree(
        REPO_ID, repo_type="dataset", revision=REVISION, recursive=True,
    ))
    selected = [
        entry for entry in tree
        if entry.path.rsplit("/", 1)[0] in {f"data/{layer}" for layer in LAYERS}
        and "-of-" in entry.path and entry.path.endswith(".parquet")
    ]
    validate_inventory([entry.path for entry in selected])
    upstream = {entry.path: entry for entry in selected}
    available = {entry.path for entry in tree}
    if not set(DOCUMENTATION).issubset(available):
        raise RuntimeError("Pinned source is missing required documentation")
    print(f"Fixed input: {len(selected)} shards, {sum(e.size for e in selected):,} bytes", flush=True)

    def download(relative: str) -> tuple[str, str]:
        path = hf_hub_download(
            repo_id=REPO_ID, repo_type="dataset", revision=REVISION,
            filename=relative, local_dir=DOWNLOAD_ROOT,
        )
        acquired = datetime.now(timezone.utc).isoformat()
        print(f"Available: {relative}", flush=True)
        return relative, acquired

    # Make documentation and small layers available early on a fresh download.
    paths = list(DOCUMENTATION) + sorted(required, key=lambda path: upstream[path].size)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        acquired = dict(pool.map(download, paths))

    files = []
    documentation = []
    with duckdb.connect() as connection:
        for relative in paths:
            path = source_path(relative)
            entry = {
                "path": relative, "bytes": path.stat().st_size,
                "sha256": sha256_of(path), "acquired_at": acquired[relative],
            }
            if relative in required:
                remote = upstream[relative]
                lfs = getattr(remote, "lfs", None)
                remote_hash = getattr(lfs, "sha256", None)
                if entry["bytes"] != remote.size or (remote_hash and entry["sha256"] != remote_hash):
                    raise RuntimeError(f"Downloaded content differs from pinned source: {relative}")
                entry.update({
                    "layer": required[relative], "upstream_sha256": remote_hash,
                    "row_count": connection.execute(
                        "SELECT count(*) FROM read_parquet(?)", [str(path)]
                    ).fetchone()[0],
                })
                files.append(entry)
            else:
                documentation.append(entry)
    for layer, (_, expected_rows) in LAYERS.items():
        actual_rows = sum(entry["row_count"] for entry in files if entry["layer"] == layer)
        if actual_rows != expected_rows:
            raise RuntimeError(f"{layer}: source rows {actual_rows} != prescribed {expected_rows}")
    manifest = {
        "format_version": 1, "repo_id": REPO_ID, "repo_type": "dataset",
        "revision": REVISION, "acquired_at": datetime.now(timezone.utc).isoformat(),
        "acquisition_note": "Time each pinned file was made available locally; cache reuse is possible.",
        "download_tool": {"name": "huggingface_hub", "version": importlib.metadata.version("huggingface_hub")},
        "files": sorted(files, key=lambda entry: entry["path"]),
        "documentation": sorted(documentation, key=lambda entry: entry["path"]),
    }
    temporary = MANIFEST_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # The full manifest is only published after every download and hash succeeds.
    os.replace(temporary, MANIFEST_PATH)
    load_manifest(verify=True)
    print(f"Verified and saved: {MANIFEST_PATH.name}", flush=True)


if __name__ == "__main__":
    main()

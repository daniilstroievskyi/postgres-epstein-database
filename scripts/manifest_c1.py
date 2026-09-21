"""Write the C1 source-file manifest: repo, revision, path, size and SHA-256."""

import hashlib
from pathlib import Path

from data_download import DOWNLOAD_ROOT, FILES, PROJECT_ROOT, REPO_ID, REPO_TYPE, REVISION


MANIFEST_PATH = PROJECT_ROOT / "C1" / "manifest.tsv"
HF_METADATA_ROOT = DOWNLOAD_ROOT / ".cache" / "huggingface" / "download"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def hub_recorded_sha256(relative_path: str) -> str | None:
    """SHA-256 that huggingface_hub stored for the LFS file at download time."""
    metadata = HF_METADATA_ROOT / f"{relative_path}.metadata"
    if not metadata.is_file():
        return None
    lines = metadata.read_text(encoding="utf-8").splitlines()
    # Line 1 is the commit hash, line 2 the etag (the LFS SHA-256 for large files).
    return lines[1].strip() if len(lines) >= 2 else None


def main() -> None:
    header = (
        "repo_id", "repo_type", "revision", "path", "size_bytes",
        "sha256", "hub_recorded_sha256", "hashes_match",
    )
    rows = []
    for relative_path in FILES:
        local_path = DOWNLOAD_ROOT / relative_path
        if not local_path.is_file():
            raise FileNotFoundError(
                f"Missing {local_path}. Run: python scripts/data_download.py"
            )
        digest = sha256_of(local_path)
        recorded = hub_recorded_sha256(relative_path)
        match = "n/a" if recorded is None else str(digest == recorded)
        rows.append((
            REPO_ID, REPO_TYPE, REVISION, relative_path,
            str(local_path.stat().st_size), digest, recorded or "n/a", match,
        ))

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(header)] + ["\t".join(row) for row in rows]
    MANIFEST_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for row in rows:
        print(f"{row[3]}: {row[4]} bytes, sha256={row[5]}, hub match={row[7]}")
    if any(row[7] == "False" for row in rows):
        raise SystemExit("SHA-256 mismatch against the Hugging Face record")
    print(f"Manifest written to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

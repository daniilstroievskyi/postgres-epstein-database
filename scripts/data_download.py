"""Download the two immutable source shards needed for checkpoint C1."""

from pathlib import Path

REPO_ID = "kabasshouse/epstein-data"
REPO_TYPE = "dataset"
REVISION = "133ef9f0a539fafc270cde8fa8638dc38d89968d"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_ROOT = PROJECT_ROOT / "data"

FILES = [
    "data/documents/documents-00000-of-00015.parquet",
    "data/chunks/chunks-00000-of-00011.parquet",
]


def main() -> None:
    from huggingface_hub import hf_hub_download

    for filename in FILES:
        path = hf_hub_download(
            repo_id=REPO_ID,
            repo_type=REPO_TYPE,
            filename=filename,
            revision=REVISION,
            local_dir=DOWNLOAD_ROOT,
        )
        print("Downloaded:", path)


if __name__ == "__main__":
    main()

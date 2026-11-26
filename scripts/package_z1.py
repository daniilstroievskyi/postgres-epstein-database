"""Build the source-only Z1 submission ZIP from a committed project version."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import tempfile
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ("README.md", "requirements.txt", "compose.yaml", ".env.example",
              ".gitignore", "source-manifest.json")
DIRECTORIES = {"scripts": {".py"}, "tests": {".py"}, "sql": {".sql"},
               "docs": {".md"}, "evidence": {".json", ".txt"}}
LOCAL_ONLY = {
    "scripts/package_z1.py",
    "docs/README.md",
    "docs/source-review.md",
    "evidence/benchmark-before-plan.txt",
    "evidence/benchmark-after-plan.txt",
    "evidence/benchmark-tests.txt",
    "evidence/extension-tests.txt",
    "evidence/import-tests.txt",
    "evidence/query-tests.txt",
}
REQUIRED = ("sql/schema.sql", "sql/queries.sql", "sql/query-indexes.sql",
            "sql/extension.sql", "docs/data-profile.md", "docs/data-mapping.md",
            "docs/schema-proposal.md", "docs/import-report.md", "docs/benchmark.md",
            "docs/ai-report.md", "docs/extension.md", "evidence/benchmark.json",
            "evidence/import-validation.json", "evidence/import-repeat.json",
            "evidence/extension.json", "evidence/ai-claim-check.json")


def git(*args):
    result = subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True)
    if result.returncode:
        raise RuntimeError("Git check failed; run this in the committed project.")
    return result.stdout


def project_files():
    files = list(ROOT_FILES)
    for directory, suffixes in DIRECTORIES.items():
        for path in (PROJECT_ROOT/directory).rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                relative = path.relative_to(PROJECT_ROOT)
                if relative.as_posix() in LOCAL_ONLY:
                    continue
                if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                    continue
                if "c1" in path.name.casefold():
                    continue
                if path.is_symlink():
                    raise RuntimeError(f"Unexpected linked source file: {relative}")
                files.append(relative.as_posix())
    if any(not (PROJECT_ROOT/name).is_file() for name in ROOT_FILES):
        raise RuntimeError("A required root file is missing.")
    if not set(REQUIRED).issubset(files):
        raise RuntimeError("A required report, SQL file or evidence file is missing.")
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Preview included files without creating a ZIP")
    parser.add_argument("--working-tree", action="store_true", help="Package current files without requiring a commit")
    args = parser.parse_args()
    files = project_files()
    if args.list:
        print("\n".join(files))
        print(f"{len(files)} files; {sum((PROJECT_ROOT/f).stat().st_size for f in files):,} source bytes")
        return
    if not args.working_tree and git("status", "--porcelain", "--untracked-files=all", "--", *files).strip():
        raise RuntimeError("Commit the full Z1 source first: git add -A; git commit -m \"Complete Z1\". No ZIP was created.")
    commit = "working tree (uncommitted)" if args.working_tree else git("rev-parse", "HEAD").decode().strip()
    tracked = set(files) if args.working_tree else set(git("ls-tree", "-r", "--name-only", "HEAD").decode().splitlines())
    if not set(files).issubset(tracked):
        raise RuntimeError("Some submission files are absent from the source commit.")
    output = PROJECT_ROOT/"dist"/"Z1_Stroievskyi_Daniil.zip"
    output.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in files:
                content = (PROJECT_ROOT / name).read_bytes() if args.working_tree else git("show", f"{commit}:{name}")
                if name == "README.md":
                    text = content.decode("utf-8")
                    marker = "**Submission commit:** populated from Git HEAD in the packaged README by `scripts/package_z1.py`."
                    if marker not in text and not args.working_tree:
                        raise RuntimeError("The committed README is missing its submission-commit marker.")
                    if marker in text:
                        content = text.replace(marker, f"**Submission commit:** `{commit}`.", 1).encode("utf-8")
                bundle.writestr(name, content)
        with zipfile.ZipFile(temporary) as bundle:
            if set(bundle.namelist()) != set(files) or bundle.testzip() is not None:
                raise RuntimeError("Archive contents or CRC verification failed.")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Saved {output} ({output.stat().st_size:,} bytes, {len(files)} files)")
    print(f"README records source commit {commit}; dataset, credentials, caches and C1 are excluded.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"Packaging stopped: {error}")

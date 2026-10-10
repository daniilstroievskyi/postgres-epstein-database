"""Produce metadata-only, reproducible profiling of all prescribed source layers."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

if __package__:
    from .z1_source import LAYERS, PROJECT_ROOT, REVISION, layer_paths, load_manifest
else:
    from z1_source import LAYERS, PROJECT_ROOT, REVISION, layer_paths, load_manifest

EVIDENCE = PROJECT_ROOT / "evidence"
DOCS = PROJECT_ROOT / "docs"


def identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_source_views(connection, manifest: dict) -> dict[str, list]:
    schemas = {}
    for layer in LAYERS:
        paths = layer_paths(manifest, layer)
        schema = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [paths[0]]
        ).fetchall()
        for path in paths[1:]:
            other = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [path]
            ).fetchall()
            if [(c[0], c[1]) for c in other] != [(c[0], c[1]) for c in schema]:
                raise ValueError(f"Inconsistent source schema in {path}")
        table = identifier(layer.replace("/", "_"))
        files = "[" + ",".join(literal(path) for path in paths) + "]"
        connection.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM read_parquet({files})")
        schemas[layer] = schema
    return schemas


def reference_check(connection, child: str, column: str, parent: str, parent_column: str) -> dict:
    child_table = identifier(child.replace("/", "_"))
    parent_table = identifier(parent.replace("/", "_"))
    c, p = identifier(column), identifier(parent_column)
    # This measures equality candidates only. It does not assert identity/namespace.
    counts = connection.execute(f"""
        WITH parents AS (
            SELECT CAST({p} AS VARCHAR) AS raw_key, count(*) AS candidates
            FROM {parent_table} WHERE {p} IS NOT NULL GROUP BY 1
        )
        SELECT count(*),
               count(*) FILTER (WHERE c.{c} IS NULL),
               count(*) FILTER (WHERE c.{c} IS NOT NULL AND p.raw_key IS NULL),
               count(*) FILTER (WHERE p.candidates = 1),
               count(*) FILTER (WHERE p.candidates > 1)
        FROM {child_table} c
        LEFT JOIN parents p ON CAST(c.{c} AS VARCHAR) = p.raw_key
    """).fetchone()
    return dict(zip(
        ("read", "missing", "unmatched", "single_equal_key", "ambiguous_equal_key"), counts
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-limit", default="512MB")
    args = parser.parse_args()
    manifest = load_manifest(verify=True)
    scratch = PROJECT_ROOT / "data" / "work" / "profile"
    scratch.mkdir(parents=True, exist_ok=True)
    report = {
        "revision": REVISION, "generated_at": datetime.now(timezone.utc).isoformat(),
        "layers": {}, "references": {},
    }
    with duckdb.connect() as connection:
        connection.execute(f"SET memory_limit = {literal(args.memory_limit)}")
        connection.execute("SET threads = 2")
        connection.execute(f"SET temp_directory = {literal(str(scratch))}")
        schemas = create_source_views(connection, manifest)
        for layer, schema in schemas.items():
            table = identifier(layer.replace("/", "_"))
            columns = []
            expressions = ["count(*)"]
            for name, datatype, *_ in schema:
                column = identifier(name)
                expressions.append(f"count(*) FILTER (WHERE {column} IS NULL)")
                if datatype == "VARCHAR":
                    expressions.append(f"count(*) FILTER (WHERE trim({column}) = '')")
                else:
                    expressions.append("0")
            counts = connection.execute(f"SELECT {','.join(expressions)} FROM {table}").fetchone()
            for i, (name, datatype, *_) in enumerate(schema):
                columns.append({
                    "name": name, "type": datatype,
                    "null": counts[1 + 2 * i], "empty_or_whitespace": counts[2 + 2 * i],
                })
            key_results = {}
            names = {row[0] for row in schema}
            for key in ("id", "file_key", "run_id"):
                if key in names:
                    column = identifier(key)
                    nonnull, distinct = connection.execute(
                        f"SELECT count({column}), count(DISTINCT {column}) FROM {table}"
                    ).fetchone()
                    key_results[key] = {
                        "nonnull": nonnull, "distinct": distinct,
                        "extra_occurrences": nonnull - distinct,
                    }
            if {"dataset", "file_key"}.issubset(names):
                groups = connection.execute(
                    f"SELECT count(*) FROM (SELECT dataset,file_key FROM {table} GROUP BY 1,2)"
                ).fetchone()[0]
                key_results["dataset,file_key"] = {"groups": groups, "extra_occurrences": counts[0] - groups}
            if {"output_name", "file_key"}.issubset(names):
                groups = connection.execute(
                    f"SELECT count(*) FROM (SELECT output_name,file_key FROM {table} GROUP BY 1,2)"
                ).fetchone()[0]
                key_results["output_name,file_key"] = {"groups": groups, "extra_occurrences": counts[0] - groups}
            value_checks = {}
            for name, datatype, *_ in schema:
                column = identifier(name)
                if datatype == "VARCHAR" and re.search(r"(^date$|_date$|^date_|_at$)", name):
                    value_checks[name] = dict(zip(
                        ("nonblank", "year_only", "month_only", "not_castable_as_timestamp"),
                        connection.execute(f"""
                            SELECT count(*) FILTER (WHERE trim({column}) <> ''),
                                   count(*) FILTER (WHERE regexp_full_match(trim({column}), '[0-9]{{4}}')),
                                   count(*) FILTER (WHERE regexp_full_match(trim({column}), '[0-9]{{4}}-[0-9]{{2}}')),
                                   count(*) FILTER (WHERE trim({column}) <> '' AND try_cast({column} AS TIMESTAMP) IS NULL)
                            FROM {table}
                        """).fetchone(),
                    ))
                if name == "email_fields":
                    value_checks[name] = dict(zip(
                        ("sql_null", "blank", "invalid_json_nonblank", "json_null", "valid_nonnull_json"),
                        connection.execute(f"""
                            SELECT count(*) FILTER (WHERE {column} IS NULL),
                                   count(*) FILTER (WHERE trim({column}) = ''),
                                   count(*) FILTER (WHERE trim({column}) <> '' AND NOT json_valid({column})),
                                   count(*) FILTER (WHERE json_type(try_cast({column} AS JSON)) = 'NULL'),
                                   count(*) FILTER (WHERE json_valid({column}) AND json_type(try_cast({column} AS JSON)) <> 'NULL')
                            FROM {table}
                        """).fetchone(),
                    ))
                if name == "amount":
                    value_checks[name] = dict(zip(
                        ("missing", "nonfinite", "negative", "zero", "positive"),
                        connection.execute(f"""
                            SELECT count(*) FILTER (WHERE {column} IS NULL),
                                   count(*) FILTER (WHERE {column} IS NOT NULL AND NOT isfinite({column})),
                                   count(*) FILTER (WHERE isfinite({column}) AND {column} < 0),
                                   count(*) FILTER (WHERE isfinite({column}) AND {column} = 0),
                                   count(*) FILTER (WHERE isfinite({column}) AND {column} > 0)
                            FROM {table}
                        """).fetchone(),
                    ))
            report["layers"][layer] = {
                "rows": counts[0], "expected_rows": LAYERS[layer][1],
                "schema": columns, "candidate_keys": key_results, "value_checks": value_checks,
            }
            print(f"Profiled {layer}: {counts[0]:,} rows", flush=True)

        # Add only references whose actual columns exist. The schema inventory is
        # retained so missing expected names cannot silently become claimed checks.
        references = [
            ("chunks", "document_id", "documents", "id"),
            ("entities", "document_id", "documents", "id"),
            ("event_participants", "event_id", "derived_events", "id"),
            ("event_sources", "event_id", "derived_events", "id"),
            ("event_sources", "file_key", "documents", "file_key"),
            ("financial_transactions", "document_id", "documents", "id"),
            ("financial_transactions", "file_key", "documents", "file_key"),
            ("curated_docs", "file_key", "documents", "file_key"),
            ("provenance/files", "run_id", "provenance/runs", "id"),
            ("provenance/files", "run_id", "provenance/runs", "run_id"),
            ("kg_relationships", "source_id", "kg_entities", "id"),
            ("kg_relationships", "target_id", "kg_entities", "id"),
            ("kg_relationships", "source_entity_id", "kg_entities", "id"),
            ("kg_relationships", "target_entity_id", "kg_entities", "id"),
        ]
        for child, column, parent, parent_column in references:
            if column not in {r[0] for r in schemas[child]} or parent_column not in {r[0] for r in schemas[parent]}:
                continue
            label = f"{child}.{column} -> {parent}.{parent_column}"
            report["references"][label] = reference_check(connection, child, column, parent, parent_column)
            print(f"Checked candidates: {label}", flush=True)

    EVIDENCE.mkdir(exist_ok=True)
    output = EVIDENCE / "source-profile.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Z1 source data profile", "", f"Fixed revision: `{REVISION}`.", "",
        "Generated from all 56 manifest-verified shards by `scripts/profile_z1.py`.",
        "Outputs contain schemas and aggregates, not document text or names.", "",
        "Equality candidate counts do not prove a shared ID namespace or identity.", "",
        "Date castability is a diagnostic; partial precision requires separate import rules.", "",
    ]
    for layer, profile in report["layers"].items():
        lines += [f"## {layer}", "", f"Rows: {profile['rows']:,} (expected {profile['expected_rows']:,}).", "",
                  "| Field | Source type | SQL NULL | Blank/whitespace |", "|---|---|---:|---:|"]
        lines += [f"| {c['name']} | {c['type']} | {c['null']} | {c['empty_or_whitespace']} |" for c in profile["schema"]]
        lines += ["", "Candidate keys:", "", "```json", json.dumps(profile["candidate_keys"], indent=2), "```", ""]
        if profile["value_checks"]:
            lines += ["Value checks:", "", "```json", json.dumps(profile["value_checks"], indent=2), "```", ""]
    lines += ["## Reference candidates", "", "| Candidate relationship | Missing | Unmatched | Single equality candidate | Ambiguous |", "|---|---:|---:|---:|---:|"]
    for label, counts in report["references"].items():
        lines.append(f"| {label} | {counts['missing']} | {counts['unmatched']} | {counts['single_equal_key']} | {counts['ambiguous_equal_key']} |")
    lines += ["", "## Reproduce offline", "", "```powershell", ".\\.venv\\Scripts\\python.exe .\\scripts\\download_z1.py --verify-only", ".\\.venv\\Scripts\\python.exe .\\scripts\\profile_z1.py", "```", ""]
    DOCS.mkdir(exist_ok=True)
    (DOCS / "data-profile.md").write_text("\n".join(lines), encoding="utf-8")
    print("Saved docs/data-profile.md and evidence/source-profile.json", flush=True)


if __name__ == "__main__":
    main()

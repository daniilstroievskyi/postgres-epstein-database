"""Pure Z1 transformations; raw values are retained, errors are explicit."""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import unicodedata
from datetime import date, datetime
from decimal import Decimal

TRANSFORM_VERSION = "z1-transform-v1"
NORMALIZATION_VERSION = "nfkc-casefold-space-v1"


def normalize(value):
    return None if value is None else " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def fingerprint(record: dict) -> bytes:
    """Sorted fields, typed tags, eight-byte lengths, UTF-8/surrogatepass, IEEE floats."""
    digest = hashlib.sha256()
    for name, value in sorted(record.items()):
        field = name.encode("utf-8")
        digest.update(struct.pack(">Q", len(field)) + field)
        if value is None:
            tag, content = b"N", b""
        elif isinstance(value, bool):
            tag, content = b"B", b"1" if value else b"0"
        elif isinstance(value, int):
            tag, content = b"I", str(value).encode("ascii")
        elif isinstance(value, float):
            tag, content = b"F", struct.pack(">d", value)
        elif isinstance(value, str):
            tag, content = b"S", value.encode("utf-8", errors="surrogatepass")
        else:
            raise TypeError(f"Unsupported source type for {name}: {type(value).__name__}")
        digest.update(tag + struct.pack(">Q", len(content)) + content)
    return digest.digest()


def text_representable(record):
    for name, value in record.items():
        if isinstance(value, str):
            if "\x00" in value:
                return name, "text_nul"
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return name, "text_surrogate"
    return None


def equal_records(left, right):
    if left.keys() != right.keys():
        return False
    for key, value in left.items():
        other = right[key]
        if type(value) is not type(other):
            return False
        if isinstance(value, float):
            if struct.pack(">d", value) != struct.pack(">d", other):
                return False
        elif value != other:
            return False
    return True


def parse_date(raw, *, timestamp_only=False):
    result = dict(raw=raw, state="missing", precision=None, year=None, month=None,
                  day=None, local_timestamp=None, instant=None)
    if raw is None:
        return result
    value = raw.strip()
    if not value:
        result["state"] = "empty"
        return result
    try:
        if not timestamp_only and re.fullmatch(r"\d{4}", value):
            year = int(value)
            date(year, 1, 1)  # calendar validation only; no invented date is stored
            result.update(state="parsed", precision="year", year=year)
        elif not timestamp_only and re.fullmatch(r"\d{4}-\d{2}", value):
            year, month = map(int, value.split("-"))
            date(year, month, 1)
            result.update(state="parsed", precision="month", year=year, month=month)
        elif not timestamp_only and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed = date.fromisoformat(value)
            result.update(state="parsed", precision="day", year=parsed.year,
                          month=parsed.month, day=parsed)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", value):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            # Reject nonexistent offset ranges rather than letting a permissive parser normalize them.
            offset = re.search(r"([+-])(\d{2}):(\d{2})$", value)
            if offset and (int(offset[2]) > 23 or int(offset[3]) > 59):
                raise ValueError("Invalid offset")
            aware = parsed.tzinfo is not None
            result.update(state="parsed", precision="zoned_timestamp" if aware else "local_timestamp",
                          **({"instant": parsed} if aware else {"local_timestamp": parsed}))
        else:
            result["state"] = "unparsed"
    except ValueError:
        result["state"] = "invalid"
    return result


def parse_json(raw, expected=None):
    """Return original valid JSON text for COPY: do not round JSON numbers through float."""
    if raw is None:
        return None, "missing", [], None
    if not raw.strip():
        return None, "empty", ["json_empty"], None
    issues = []
    def pairs(items):
        output = {}
        for key, value in items:
            representable(key)
            representable(value)
            if key in output:
                issues.append("json_duplicate_key")
            output[key] = value
        return output
    def constant(value):
        raise ValueError("Nonstandard JSON constant")
    def representable(value):
        if isinstance(value, str):
            if "\x00" in value:
                raise ValueError("JSONB cannot store NUL")
            value.encode("utf-8")
        elif isinstance(value, dict):
            for key, item in value.items():
                representable(key)
                representable(item)
        elif isinstance(value, list):
            for item in value:
                representable(item)
        elif isinstance(value, Decimal):
            # PostgreSQL unconstrained NUMERIC implementation bounds.
            if value and (value.adjusted() >= 131072 or -value.as_tuple().exponent > 16383):
                raise ValueError("JSON number exceeds PostgreSQL numeric bounds")
    try:
        decoded = json.loads(raw, parse_float=Decimal, parse_constant=constant, object_pairs_hook=pairs)
        representable(decoded)
    except (ValueError, UnicodeEncodeError, RecursionError):
        return None, "invalid", ["json_invalid_or_unrepresentable"], None
    if expected == "object" and not isinstance(decoded, dict):
        issues.append("json_unexpected_shape")
    if expected == "array" and not isinstance(decoded, list):
        issues.append("json_unexpected_shape")
    return raw, "json_null" if decoded is None else "valid", sorted(set(issues)), decoded


def parse_amount(value):
    if value is None:
        return None, "missing"
    if not math.isfinite(value):
        return None, "invalid"
    return Decimal.from_float(value), "valid"


def content_identity(manifest, schema_version):
    identity = {
        "repo": manifest["repo_id"], "revision": manifest["revision"],
        "files": sorted((f["path"], f["sha256"], f["row_count"]) for f in manifest["files"]),
        "schema_version": schema_version, "transform_version": TRANSFORM_VERSION,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def transform_record(layer, record):
    if __package__:
        from .z1_model import DATES, TIMES, JSON_FIELDS, NAMES
    else:
        from z1_model import DATES, TIMES, JSON_FIELDS, NAMES
    output, issues = {}, []
    def issue(field, code, severity="warning"):
        issues.append((field, code, severity))
    for name, value in record.items():
        if name in DATES.get(layer, []) or name in TIMES.get(layer, []):
            timestamp_only = name in TIMES.get(layer, [])
            parsed = parse_date(value, timestamp_only=timestamp_only)
            for part, result in parsed.items():
                if not timestamp_only or part in ("raw", "state", "local_timestamp", "instant"):
                    output[name+"_"+part] = result
            if parsed["state"] in ("empty", "invalid", "unparsed"):
                issue(name, "date_"+parsed["state"], "error" if parsed["state"] == "invalid" else "warning")
        elif name in JSON_FIELDS.get(layer, {}):
            parsed, state, problems, decoded = parse_json(value, JSON_FIELDS[layer][name])
            output.update({name+"_raw": value, name: parsed, name+"_state": state})
            for problem in problems:
                issue(name, problem, "error" if state == "invalid" else "warning")
            if name in ("aliases", "also_appears_as") and isinstance(decoded, list) and any(not isinstance(x, str) for x in decoded):
                issue(name, "json_array_nonstring_element")
        elif name in ("amount", "cost_usd"):
            parsed, state = parse_amount(value)
            output.update({name+"_raw": value, name: parsed, name+"_state": state})
            if state == "invalid": issue(name, "amount_nonfinite", "error")
        elif name == "currency":
            text = None if value is None else value.strip().upper()
            state = "missing" if value is None else "empty" if not text else "code_shaped" if re.fullmatch("[A-Z]{3}", text) else "unrecognized"
            output.update(currency_raw=value, currency=text if state == "code_shaped" else None, currency_state=state)
            if state != "code_shaped": issue(name, "currency_"+state)
        elif name == "id": output["source_id"] = value
        elif layer == "entities" and name == "document_id":
            output.update(raw_document_id=value, candidate_document_id=None, document_id=None, document_match_status="missing" if value is None else "unmatched")
        elif layer == "entities" and name in ("value", "normalized_value"):
            output[name+"_raw"] = value
        elif layer == "kg_relationships" and name in ("source_id", "target_id"):
            output["from_node_id" if name == "source_id" else "to_node_id"] = value
        elif layer == "provenance/files" and name == "run_id":
            output.update(raw_run_id=value, run_id=None, run_match_status="missing" if value is None else "unmatched")
        elif layer == "financial_transactions" and name == "extraction_confidence":
            output.update(extraction_confidence_raw=value, extraction_confidence=None,
                          extraction_confidence_state="missing" if value is None else "unverified")
            if value is not None: issue(name, "extraction_confidence_convention_unverified")
        else: output[name] = value
    if layer in NAMES:
        output.update(search_value=normalize(record[NAMES[layer]]), normalization_version=NORMALIZATION_VERSION)
    if layer not in ("documents", "entities") and "file_key" in record:
        output.update(document_id=None, document_match_status="missing" if record["file_key"] is None else "unmatched")
    if layer == "financial_transactions": output["dataset_match_status"] = "unresolved"
    if layer == "chunks": output["offset_status"] = "valid"
    return output, sorted(set(issues))

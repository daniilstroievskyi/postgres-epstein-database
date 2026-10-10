"""Explicit relational model and source mapping for all 13 frozen layers."""
from __future__ import annotations
import re

SCHEMA_VERSION = "z1-schema-v1"
SOURCES = {
    "documents": "id:b file_key:t dataset:t full_text:t document_type:t date:t is_photo:o has_handwriting:o has_stamps:o ocr_source:t additional_notes:t page_number:t document_number:t char_count:i created_at:t email_fields:t",
    "chunks": "id:b document_id:b chunk_index:i content:t token_count:i char_start:i char_end:i",
    "entities": "id:b document_id:b entity_type:t value:t normalized_value:t",
    "persons": "id:b canonical_name:t slug:t category:t aliases:t search_terms:t sources:t notes:t",
    "kg_entities": "id:b name:t entity_type:t description:t metadata:t",
    "kg_relationships": "id:b source_id:b target_id:b relationship_type:t weight:f evidence:t metadata:t",
    "derived_events": "id:b event_date:t event_end_date:t event_type:t track:t headline:t location:t amount:f currency:t payer:t payee:t route_from:t route_to:t aircraft:t time_of_day:t confidence:t narrative:t",
    "event_participants": "id:b event_id:b person_name:t role:t",
    "event_sources": "id:b event_id:b file_key:t",
    "financial_transactions": "id:b file_key:t dataset:t transaction_date:t amount:f currency:t merchant_name:t merchant_raw:t merchant_category:t location:t cardholder:t description:t card_type:t account_digits:t statement_date:t flight_from:t flight_to:t flight_carrier:t flight_departure:t flight_ticket:t flight_passenger:t source_page:i extraction_model:t extraction_confidence:f",
    "curated_docs": "id:b file_key:t subject:t status:t tier:t category:t doc_date:t doc_from:t doc_to:t headline:t key_quote:t detail:t thread_value:t also_appears_as:t",
    "provenance/runs": "run_id:t started_at:t completed_at:t status:t input_dir:t output_name:t model:t dpi:i workers:i rpm:i git_commit:t hostname:t total_files:i success_count:i fail_count:i input_tokens:b output_tokens:b cost_usd:f last_heartbeat:t",
    "provenance/files": "file_key:t output_name:t pdf_path:t pdf_sha256:t pdf_size_bytes:b status:t output_path:t output_sha256:t first_seen_at:t processed_at:t run_id:t input_tokens:b output_tokens:b api_latency_ms:b attempts:i error_message:t model_used:t validation_score:i",
}
TABLES = dict(zip(SOURCES, ("documents", "chunks", "mentions", "persons", "kg_nodes", "kg_edges", "events", "event_participants", "event_sources", "financial_transactions", "curated_annotations", "upstream_runs", "upstream_files")))
TYPES = {"b": "BIGINT", "i": "INTEGER", "t": "TEXT", "o": "BOOLEAN", "f": "DOUBLE PRECISION"}
DATES = {"documents": ["date"], "derived_events": ["event_date", "event_end_date"], "financial_transactions": ["transaction_date", "statement_date"], "curated_docs": ["doc_date"]}
TIMES = {"documents": ["created_at"], "provenance/runs": ["started_at", "completed_at", "last_heartbeat"], "provenance/files": ["first_seen_at", "processed_at"]}
JSON_FIELDS = {"documents": {"email_fields": "object"}, "persons": {"aliases": "array", "search_terms": "array", "sources": "array"}, "kg_entities": {"metadata": "object"}, "kg_relationships": {"metadata": "object"}, "curated_docs": {"also_appears_as": "array"}}
NAMES = {"entities": "value", "persons": "canonical_name", "kg_entities": "name", "event_participants": "person_name", "financial_transactions": "merchant_name"}
ORDER = ["documents", "persons", "kg_entities", "derived_events", "provenance/runs", "chunks", "entities", "kg_relationships", "event_participants", "event_sources", "financial_transactions", "curated_docs", "provenance/files"]


def ident(name):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("Invalid SQL identifier")
    return '"' + name + '"'


def source_columns(layer):
    return [(item.split(":")[0], TYPES[item.split(":")[1]]) for item in SOURCES[layer].split()]


def keys(layer):
    return ["run_id"] if layer == "provenance/runs" else ["output_name", "file_key"] if layer == "provenance/files" else ["source_id"]


def columns(layer):
    output = []
    for name, typ in source_columns(layer):
        if name in DATES.get(layer, []):
            output += [(name+"_raw", "TEXT"), (name+"_state", "TEXT"), (name+"_precision", "TEXT"),
                       (name+"_year", "SMALLINT"), (name+"_month", "SMALLINT"), (name+"_day", "DATE"),
                       (name+"_local_timestamp", "TIMESTAMP"), (name+"_instant", "TIMESTAMPTZ")]
        elif name in TIMES.get(layer, []):
            output += [(name+"_raw", "TEXT"), (name+"_state", "TEXT"), (name+"_local_timestamp", "TIMESTAMP"), (name+"_instant", "TIMESTAMPTZ")]
        elif name in JSON_FIELDS.get(layer, {}):
            output += [(name+"_raw", "TEXT"), (name, "JSONB"), (name+"_state", "TEXT")]
        elif name in ("amount", "cost_usd"):
            output += [(name+"_raw", "DOUBLE PRECISION"), (name, "NUMERIC"), (name+"_state", "TEXT")]
        elif name == "currency":
            output += [("currency_raw", "TEXT"), ("currency", "TEXT"), ("currency_state", "TEXT")]
        elif name == "id":
            output.append(("source_id", typ))
        elif layer == "entities" and name == "document_id":
            output += [("raw_document_id", typ), ("candidate_document_id", typ), ("document_id", typ), ("document_match_status", "TEXT")]
        elif layer == "entities" and name in ("value", "normalized_value"):
            output.append((name+"_raw", typ))
        elif layer == "kg_relationships" and name in ("source_id", "target_id"):
            output.append(("from_node_id" if name == "source_id" else "to_node_id", typ))
        elif layer == "provenance/files" and name == "run_id":
            output += [("raw_run_id", typ), ("run_id", typ), ("run_match_status", "TEXT")]
        elif layer == "financial_transactions" and name == "extraction_confidence":
            output += [("extraction_confidence_raw", typ), (name, typ), (name+"_state", "TEXT")]
        else:
            output.append((name, typ))
    if layer in NAMES:
        output += [("search_value", "TEXT"), ("normalization_version", "TEXT")]
    if layer not in ("documents", "entities") and any(n == "file_key" for n, _ in source_columns(layer)):
        output += [("document_id", "BIGINT"), ("document_match_status", "TEXT")]
    if layer == "financial_transactions":
        output.append(("dataset_match_status", "TEXT"))
    if layer == "chunks":
        output.append(("offset_status", "TEXT"))
    return output + [("input_file_id", "BIGINT"), ("source_row", "BIGINT"), ("loaded_by_run", "UUID"), ("raw_record_hash", "BYTEA")]


def raw_column(layer, name):
    if name in DATES.get(layer,[]) or name in TIMES.get(layer,[]) or name in JSON_FIELDS.get(layer,{}) or name in ("amount","cost_usd","currency"):
        return name+"_raw"
    if name=="id": return "source_id"
    if layer=="entities" and name=="document_id": return "raw_document_id"
    if layer=="entities" and name in ("value","normalized_value"): return name+"_raw"
    if layer=="kg_relationships" and name in ("source_id","target_id"): return "from_node_id" if name=="source_id" else "to_node_id"
    if layer=="provenance/files" and name=="run_id": return "raw_run_id"
    if layer=="financial_transactions" and name=="extraction_confidence": return "extraction_confidence_raw"
    return name


def raw_fingerprint_sql(layer):
    """Independent SQL reconstruction of Python's typed binary source fingerprint."""
    import struct
    parts=[]
    for name,typ in sorted(source_columns(layer)):
        encoded=name.encode('utf-8')
        prefix=struct.pack('>Q',len(encoded))+encoded
        column=ident(raw_column(layer,name))
        if typ=='DOUBLE PRECISION': tag='F';value=f'float8send({column})'
        elif typ=='BOOLEAN': tag='B';value=f"convert_to(CASE WHEN {column} THEN '1' ELSE '0' END,'UTF8')"
        elif typ in ('BIGINT','INTEGER'): tag='I';value=f"convert_to({column}::text,'UTF8')"
        else: tag='S';value=f"convert_to({column},'UTF8')"
        null=(b'N'+struct.pack('>Q',0)).hex()
        parts.append(f"decode('{prefix.hex()}','hex') || CASE WHEN {column} IS NULL THEN decode('{null}','hex') ELSE decode('{tag.encode().hex()}','hex') || int8send(octet_length({value})::bigint) || {value} END")
    return 'sha256('+' || '.join('('+p+')' for p in parts)+')'


def schema_sql(domain="z1", audit="z1_audit"):
    d, a = ident(domain), ident(audit)
    statements = [f"CREATE SCHEMA {d}", f"CREATE SCHEMA {a}"]
    statements += [f"""CREATE TABLE {a}.load_state (
        singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK(singleton), content_identity TEXT NOT NULL,
        schema_version TEXT NOT NULL, transform_version TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('loading','validating','complete','failed')))""",
        f"""CREATE TABLE {a}.import_runs (run_id UUID PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        completed_at TIMESTAMPTZ, status TEXT NOT NULL CHECK(status IN ('running','complete','failed','interrupted')),
        manifest_sha256 TEXT NOT NULL, content_identity TEXT NOT NULL, versions JSONB NOT NULL,
        options JSONB NOT NULL, failure_stage TEXT)""",
        f"""CREATE TABLE {a}.source_files (file_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        layer TEXT NOT NULL, path TEXT NOT NULL UNIQUE, repo_id TEXT NOT NULL, revision TEXT NOT NULL,
        bytes BIGINT NOT NULL CHECK(bytes>=0), sha256 TEXT NOT NULL, row_count BIGINT NOT NULL CHECK(row_count>=0))""",
        f"""CREATE TABLE {a}.import_batches (file_id BIGINT NOT NULL REFERENCES {a}.source_files,
        start_row BIGINT NOT NULL CHECK(start_row>0), end_row BIGINT NOT NULL CHECK(end_row>=start_row),
        n_read BIGINT NOT NULL CHECK(n_read=end_row-start_row+1), n_accepted BIGINT NOT NULL CHECK(n_accepted>=0),
        n_quarantined BIGINT NOT NULL CHECK(n_quarantined>=0), n_duplicate BIGINT NOT NULL CHECK(n_duplicate>=0),
        run_id UUID NOT NULL REFERENCES {a}.import_runs, committed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(file_id,start_row), CHECK(n_read=n_accepted+n_quarantined+n_duplicate))""",
        f"""CREATE TABLE {a}.import_issues (file_id BIGINT NOT NULL REFERENCES {a}.source_files,
        source_row BIGINT NOT NULL, field TEXT NOT NULL, code TEXT NOT NULL, severity TEXT NOT NULL,
        run_id UUID NOT NULL REFERENCES {a}.import_runs, PRIMARY KEY(file_id,source_row,field,code))""",
        f"""CREATE TABLE {a}.quarantined_rows (file_id BIGINT NOT NULL REFERENCES {a}.source_files,
        source_row BIGINT NOT NULL, field TEXT NOT NULL, reason TEXT NOT NULL,
        run_id UUID NOT NULL REFERENCES {a}.import_runs, PRIMARY KEY(file_id,source_row))""",
        f"""CREATE TABLE {a}.duplicate_rows (file_id BIGINT NOT NULL REFERENCES {a}.source_files,
        source_row BIGINT NOT NULL, existing_file_id BIGINT NOT NULL REFERENCES {a}.source_files,
        existing_source_row BIGINT NOT NULL, reason TEXT NOT NULL CHECK(reason='identical_source_identity_and_payload'),
        run_id UUID NOT NULL REFERENCES {a}.import_runs, PRIMARY KEY(file_id,source_row))"""]
    for layer in ORDER:
        cols = columns(layer)
        required = set(keys(layer) + ["input_file_id", "source_row", "loaded_by_run", "raw_record_hash"])
        if layer == "documents": required.add("file_key")
        if layer == "chunks": required |= {"document_id", "chunk_index", "token_count", "char_start", "char_end"}
        if layer == "kg_relationships": required |= {"from_node_id", "to_node_id"}
        if layer in ("event_participants", "event_sources"): required.add("event_id")
        required |= {name for name, _ in cols if name.endswith(("_state", "_match_status"))}
        definitions = [f"{ident(name)} {typ}" + (" NOT NULL" if name in required else "") for name, typ in cols]
        definitions += ["PRIMARY KEY(" + ",".join(map(ident, keys(layer))) + ")", "UNIQUE(input_file_id,source_row)",
                        f"FOREIGN KEY(input_file_id) REFERENCES {a}.source_files ON UPDATE RESTRICT ON DELETE RESTRICT",
                        f"FOREIGN KEY(loaded_by_run) REFERENCES {a}.import_runs ON UPDATE RESTRICT ON DELETE RESTRICT",
                        "CHECK(source_row>0)", "CHECK(octet_length(raw_record_hash)=32)"]
        def fk(column, parent, target="source_id"):
            definitions.append(f"FOREIGN KEY({column}) REFERENCES {d}.{parent}({target}) ON UPDATE RESTRICT ON DELETE RESTRICT")
        def status(column, state):
            definitions.append(f"CHECK({state} IN ('resolved','missing','unmatched','namespace_unverified'))")
            definitions.append(f"CHECK(({state}='resolved')=({column} IS NOT NULL))")
        if layer == "documents": definitions.append("UNIQUE(file_key)")
        if layer == "chunks":
            fk("document_id", "documents")
            definitions += ["UNIQUE(document_id,chunk_index)", "CHECK(chunk_index>=0 AND token_count>=0 AND char_start>=0 AND char_end>=char_start)",
                            "CHECK(offset_status IN ('valid','reported_length_disagreement','actual_length_exceeded'))"]
        if layer == "entities":
            fk("document_id", "documents"); fk("candidate_document_id", "documents")
            status("document_id", "document_match_status")
            definitions.append("CHECK((document_match_status='namespace_unverified')=(candidate_document_id IS NOT NULL))")
        if layer == "kg_relationships": fk("from_node_id", "kg_nodes"); fk("to_node_id", "kg_nodes")
        if layer in ("event_participants", "event_sources"): fk("event_id", "events")
        if layer not in ("documents", "entities") and "file_key" in [n for n, _ in source_columns(layer)]:
            fk("document_id", "documents"); status("document_id", "document_match_status")
        if layer == "provenance/files": fk("run_id", "upstream_runs", "run_id"); status("run_id", "run_match_status")
        if layer == "financial_transactions":
            definitions += ["CHECK(dataset_match_status IN ('consistent','disagreement','unresolved'))",
                            "CHECK(extraction_confidence_state IN ('missing','unverified'))", "CHECK(extraction_confidence IS NULL)"]
        for name in DATES.get(layer, []):
            definitions += [f"CHECK({name}_state IN ('missing','empty','parsed','invalid','unparsed'))",
                f"CHECK(({name}_state='missing')=({name}_raw IS NULL))",
                f"CHECK(({name}_state='parsed')=({name}_precision IS NOT NULL))",
                f"CHECK({name}_precision IS NULL OR {name}_precision IN ('year','month','day','local_timestamp','zoned_timestamp'))",
                f"CHECK({name}_year IS NULL OR {name}_year BETWEEN 1 AND 9999)",
                f"CHECK({name}_month IS NULL OR {name}_month BETWEEN 1 AND 12)",
                f"CHECK(({name}_precision IS NOT NULL AND {name}_precision='day')=({name}_day IS NOT NULL))",
                f"CHECK(({name}_precision IS NOT NULL AND {name}_precision='local_timestamp')=({name}_local_timestamp IS NOT NULL))",
                f"CHECK(({name}_precision IS NOT NULL AND {name}_precision='zoned_timestamp')=({name}_instant IS NOT NULL))",
                f"CHECK(({name}_precision IS NOT NULL AND {name}_precision IN ('year','month','day'))=({name}_year IS NOT NULL))",
                f"CHECK(({name}_precision IS NOT NULL AND {name}_precision IN ('month','day'))=({name}_month IS NOT NULL))",
                f"CHECK({name}_day IS NULL OR (EXTRACT(YEAR FROM {name}_day)={name}_year AND EXTRACT(MONTH FROM {name}_day)={name}_month))"]
        for name in TIMES.get(layer, []):
            definitions += [f"CHECK({name}_state IN ('missing','empty','parsed','invalid','unparsed'))",
                f"CHECK(({name}_state='missing')=({name}_raw IS NULL))",
                f"CHECK(({name}_state='parsed')=(({name}_local_timestamp IS NOT NULL) OR ({name}_instant IS NOT NULL)))",
                f"CHECK(NOT ({name}_local_timestamp IS NOT NULL AND {name}_instant IS NOT NULL))"]
        for name in JSON_FIELDS.get(layer, {}):
            definitions += [f"CHECK({name}_state IN ('missing','empty','invalid','json_null','valid'))",
                f"CHECK(({name}_state='missing')=({name}_raw IS NULL))",
                f"CHECK(({name}_state IN ('json_null','valid'))=({name} IS NOT NULL))",
                f"CHECK({name} IS NULL OR ({name}_state='json_null')=({name}='null'::jsonb))"]
        for name in ("amount", "cost_usd"):
            if (name, "NUMERIC") in cols:
                definitions += [f"CHECK({name}_state IN ('missing','invalid','valid'))",
                    f"CHECK(({name}_state='missing')=({name}_raw IS NULL))",
                    f"CHECK(({name}_state='valid')=({name} IS NOT NULL))",
                    f"CHECK({name} IS NULL OR {name} NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric))"]
        if ("currency_state", "TEXT") in cols:
            definitions += ["CHECK(currency_state IN ('missing','empty','code_shaped','unrecognized'))",
                            "CHECK((currency_state='code_shaped')=(currency IS NOT NULL))"]
        statements.append(f"CREATE TABLE {d}.{TABLES[layer]} (\n    " + ",\n    ".join(definitions) + ")")
    statements += [f"""CREATE TABLE {d}.person_aliases (person_id BIGINT NOT NULL REFERENCES {d}.persons(source_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
        alias_position INTEGER NOT NULL CHECK(alias_position>=0), alias_raw TEXT NOT NULL,
        search_value TEXT NOT NULL, normalization_version TEXT NOT NULL, PRIMARY KEY(person_id,alias_position))""",
        f"""CREATE TABLE {d}.curated_document_links (annotation_id BIGINT NOT NULL REFERENCES {d}.curated_annotations(source_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
        link_position INTEGER NOT NULL CHECK(link_position>=0), file_key TEXT NOT NULL,
        document_id BIGINT REFERENCES {d}.documents(source_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
        document_match_status TEXT NOT NULL CHECK(document_match_status IN ('resolved','unmatched')),
        PRIMARY KEY(annotation_id,link_position), CHECK((document_match_status='resolved')=(document_id IS NOT NULL)))"""]
    return ";\n\n".join(statements) + ";\n"

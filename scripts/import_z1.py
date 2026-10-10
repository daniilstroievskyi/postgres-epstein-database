"""Own bounded, transactional, resumable ETL for all prescribed Z1 layers."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import platform
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

import duckdb
from psycopg.types.json import Jsonb

if __package__:
    from .z1_db import connect
    from .z1_model import SCHEMA_VERSION, ORDER, TABLES, columns, keys, schema_sql, ident, source_columns
    from .z1_source import PROJECT_ROOT, MANIFEST_PATH, load_manifest, source_path, sha256_of
    from .z1_transform import TRANSFORM_VERSION, NORMALIZATION_VERSION, content_identity, fingerprint, equal_records, text_representable, transform_record, parse_json, normalize
else:
    from z1_db import connect
    from z1_model import SCHEMA_VERSION, ORDER, TABLES, columns, keys, schema_sql, ident, source_columns
    from z1_source import PROJECT_ROOT, MANIFEST_PATH, load_manifest, source_path, sha256_of
    from z1_transform import TRANSFORM_VERSION, NORMALIZATION_VERSION, content_identity, fingerprint, equal_records, text_representable, transform_record, parse_json, normalize


class InjectedFailure(RuntimeError):
    pass


def initialize(connection, manifest, domain="z1", audit="z1_audit"):
    d, a = ident(domain), ident(audit)
    identity = content_identity(manifest, SCHEMA_VERSION)
    exists = connection.execute("SELECT to_regnamespace(%s),to_regnamespace(%s)", (domain, audit)).fetchone()
    if exists == (None, None):
        with connection.transaction():
            connection.execute(schema_sql(domain, audit))
            connection.execute(f"INSERT INTO {a}.load_state VALUES(true,%s,%s,%s,'loading')", (identity, SCHEMA_VERSION, TRANSFORM_VERSION))
            with connection.cursor().copy(f"COPY {a}.source_files(layer,path,repo_id,revision,bytes,sha256,row_count) FROM STDIN") as copy:
                for f in sorted(manifest["files"], key=lambda f: f["path"]):
                    copy.write_row((f["layer"],f["path"],manifest["repo_id"],manifest["revision"],f["bytes"],f["sha256"],f["row_count"]))
    elif None in exists:
        raise RuntimeError("Only one working schema exists; do not overwrite it")
    else:
        actual = connection.execute(f"SELECT content_identity,schema_version,transform_version FROM {a}.load_state").fetchone()
        if actual != (identity, SCHEMA_VERSION, TRANSFORM_VERSION):
            raise RuntimeError("Existing schema has a different source/code identity; explicit isolated rebuild required")
    return identity


def start_run(connection, identity, manifest_hash, options, audit="z1_audit"):
    a = ident(audit)
    run = uuid.uuid4()
    versions = {"python": platform.python_version(), "duckdb": importlib.metadata.version("duckdb"), "psycopg": importlib.metadata.version("psycopg"),
                "server": connection.execute("SELECT version()").fetchone()[0], "schema": SCHEMA_VERSION, "transform": TRANSFORM_VERSION,
                "extensions": dict(connection.execute("SELECT extname,extversion FROM pg_extension").fetchall())}
    with connection.transaction():
        connection.execute(f"UPDATE {a}.import_runs SET status='interrupted',completed_at=clock_timestamp() WHERE status='running'")
        connection.execute(f"INSERT INTO {a}.import_runs(run_id,status,manifest_sha256,content_identity,versions,options) VALUES(%s,'running',%s,%s,%s,%s)",
                           (run,manifest_hash,identity,Jsonb(versions),Jsonb(options)))
        connection.execute(f"UPDATE {a}.load_state SET status='loading'")
    return run


def write_rows(connection, table, column_names, rows):
    if rows:
        names = ",".join(ident(c) for c in column_names)
        with connection.cursor().copy(f"COPY {table}({names}) FROM STDIN") as copy:
            for row in rows: copy.write_row(row)


def process_batch(connection, layer, file_id, records, run, domain="z1", audit="z1_audit", source_lookup=None, fail_at=None):
    """records: bounded list of (physical one-based row number, original field dict)."""
    if not records: raise ValueError("Empty batch")
    start, end = records[0][0], records[-1][0]
    if [n for n, _ in records] != list(range(start,end+1)):
        raise ValueError("Source row coverage is not contiguous")
    d, a = ident(domain), ident(audit)
    table = f"{d}.{TABLES[layer]}"
    names = [n for n, _ in columns(layer)]
    pk = keys(layer)
    staging, issues, quarantine = [], [], []
    raw = {n:r for n,r in records}
    for n, record in records:
        bad = text_representable(record)
        if bad:
            quarantine.append((file_id,n,bad[0],bad[1],run))
            continue
        values, problems = transform_record(layer, record)
        values.update(input_file_id=file_id,source_row=n,loaded_by_run=run,raw_record_hash=fingerprint(record))
        if any(values.get(k) is None for k in pk) or (layer=="documents" and not values.get("file_key")):
            quarantine.append((file_id,n,"identity","missing_required_identity",run)); continue
        if layer=="chunks" and any(values.get(k) is None or values[k]<0 for k in ("chunk_index","token_count","char_start","char_end")):
            quarantine.append((file_id,n,"offsets","invalid_chunk_bounds",run)); continue
        if layer=="chunks" and values["char_end"]<values["char_start"]:
            quarantine.append((file_id,n,"offsets","invalid_chunk_bounds",run)); continue
        staging.append(tuple(values[n] for n in names))
        issues += [(file_id,n,f,c,s,run) for f,c,s in problems]
    with connection.transaction():
        # Active target constraints are deliberately not copied to temporary staging.
        definitions=",".join(f"{ident(n)} {t}" for n,t in columns(layer))
        connection.execute(f"CREATE TEMP TABLE IF NOT EXISTS stage_{TABLES[layer]} ({definitions}) ON COMMIT PRESERVE ROWS")
        stage = f"pg_temp.stage_{TABLES[layer]}"
        connection.execute(f"TRUNCATE {stage}")
        write_rows(connection, stage, names, staging)
        statistics=[n for n in names if n in ("source_id","document_id","raw_document_id","file_key","event_id","from_node_id","to_node_id","raw_run_id","output_name","chunk_index")]
        connection.execute(f"ALTER TABLE {stage} ADD COLUMN IF NOT EXISTS disposition TEXT, ADD COLUMN IF NOT EXISTS reason TEXT")
        connection.execute(f"UPDATE {stage} SET disposition='accepted'")
        if layer in ("documents","chunks"):
            position_keys="file_key,source_row" if layer=="documents" else "document_id,chunk_index,source_row"
            connection.execute(f"CREATE INDEX IF NOT EXISTS stage_{TABLES[layer]}_position ON {stage}({position_keys})")
        connection.execute(f"ANALYZE {stage}({','.join(map(ident,statistics+['disposition','source_row']))})")
        def reject(condition, reason):
            connection.execute(f"UPDATE {stage} s SET disposition='quarantined',reason=%s WHERE disposition='accepted' AND ({condition})", (reason,))
        if layer=="chunks":
            reject(f"NOT EXISTS(SELECT 1 FROM {d}.documents p WHERE p.source_id=s.document_id)", "required_document_absent")
            if connection.execute("SELECT to_regclass('pg_temp.document_length_cache')").fetchone()[0] is None:
                connection.execute(f"CREATE TEMP TABLE document_length_cache ON COMMIT PRESERVE ROWS AS SELECT source_id,length(full_text) AS actual_length,char_count AS reported_length FROM {d}.documents")
                connection.execute("ALTER TABLE pg_temp.document_length_cache ADD PRIMARY KEY(source_id)")
                connection.execute("ANALYZE pg_temp.document_length_cache")
            connection.execute(f"""UPDATE {stage} s SET offset_status=CASE
                WHEN s.char_end>p.actual_length THEN 'actual_length_exceeded'
                WHEN s.char_end>p.reported_length THEN 'reported_length_disagreement' ELSE 'valid' END
                FROM pg_temp.document_length_cache p WHERE p.source_id=s.document_id""")
        if layer=="kg_relationships":
            for endpoint in ("from_node_id","to_node_id"):
                reject(f"NOT EXISTS(SELECT 1 FROM {d}.kg_nodes p WHERE p.source_id=s.{endpoint})", "required_graph_node_absent")
        if layer in ("event_participants","event_sources"):
            reject(f"NOT EXISTS(SELECT 1 FROM {d}.events p WHERE p.source_id=s.event_id)", "required_event_absent")
        if layer=="entities":
            connection.execute(f"UPDATE {stage} s SET candidate_document_id=p.source_id,document_match_status='namespace_unverified' FROM {d}.documents p WHERE p.source_id=s.raw_document_id")
        elif layer!="documents" and "file_key" in [n for n,_ in source_columns(layer)]:
            connection.execute(f"UPDATE {stage} s SET document_id=p.source_id,document_match_status='resolved' FROM {d}.documents p WHERE p.file_key=s.file_key")
        if layer=="provenance/files":
            connection.execute(f"UPDATE {stage} s SET run_id=p.run_id,run_match_status='resolved' FROM {d}.upstream_runs p WHERE p.run_id=s.raw_run_id")
        if layer=="financial_transactions":
            connection.execute(f"UPDATE {stage} s SET dataset_match_status=CASE WHEN s.dataset IS NOT DISTINCT FROM p.dataset THEN 'consistent' ELSE 'disagreement' END FROM {d}.documents p WHERE p.source_id=s.document_id")
        # Classify genuine key collisions. Equality of a digest alone is not enough.
        joined = " AND ".join(f"t.{ident(k)}=s.{ident(k)}" for k in pk)
        prior = connection.execute(f"SELECT s.source_row,t.input_file_id,t.source_row,t.raw_record_hash FROM {stage} s JOIN {table} t ON {joined} WHERE s.disposition='accepted'").fetchall()
        seen = {}
        duplicates = []
        for n, old_file, old_row, old_hash in prior:
            same = bytes(old_hash)==fingerprint(raw[n])
            if same:
                if source_lookup is None: raise RuntimeError("A duplicate needs immutable source comparison")
                same = equal_records(source_lookup(old_file, old_row),raw[n])
            disposition, reason = ("duplicate","identical_source_identity_and_payload") if same else ("quarantined","conflicting_source_identity")
            connection.execute(f"UPDATE {stage} SET disposition=%s,reason=%s WHERE source_row=%s", (disposition,reason,n))
            if same: duplicates.append((file_id,n,old_file,old_row,reason,run))
        for row in connection.execute(f"SELECT {','.join(ident(k) for k in pk)},source_row FROM {stage} WHERE disposition='accepted' ORDER BY source_row").fetchall():
            identity, n = tuple(row[:-1]), row[-1]
            if identity in seen:
                previous = seen[identity]
                same = fingerprint(raw[previous])==fingerprint(raw[n]) and equal_records(raw[previous],raw[n])
                disposition, reason = ("duplicate","identical_source_identity_and_payload") if same else ("quarantined","conflicting_source_identity")
                connection.execute(f"UPDATE {stage} SET disposition=%s,reason=%s WHERE source_row=%s", (disposition,reason,n))
                if same: duplicates.append((file_id,n,file_id,previous,reason,run))
            else: seen[identity]=n
        if layer=="documents":
            # A different ID with the same file key is a conflicting natural key, not an upsert.
            reject(f"EXISTS(SELECT 1 FROM {table} p WHERE p.file_key=s.file_key AND p.source_id<>s.source_id)", "conflicting_document_file_key")
            reject(f"EXISTS(SELECT 1 FROM {stage} p WHERE p.file_key=s.file_key AND p.source_row<s.source_row AND p.disposition='accepted')", "conflicting_document_file_key")
        if layer=="chunks":
            reject(f"EXISTS(SELECT 1 FROM {table} p WHERE p.document_id=s.document_id AND p.chunk_index=s.chunk_index)", "conflicting_chunk_position")
            reject(f"EXISTS(SELECT 1 FROM {stage} p WHERE p.document_id=s.document_id AND p.chunk_index=s.chunk_index AND p.source_row<s.source_row AND p.disposition='accepted')", "conflicting_chunk_position")
        # Relational diagnostics; IDs/row positions only, no raw source text in logs.
        if layer in ("entities","event_sources","financial_transactions","curated_docs","provenance/files"):
            for n, status in connection.execute(f"SELECT source_row,document_match_status FROM {stage} WHERE document_match_status<>'resolved'"):
                issues.append((file_id,n,"document_reference",status,"warning",run))
        if layer=="provenance/files":
            for n,status in connection.execute(f"SELECT source_row,run_match_status FROM {stage} WHERE run_match_status<>'resolved'"):
                issues.append((file_id,n,"run_reference",status,"warning",run))
        if layer=="financial_transactions":
            for (n,) in connection.execute(f"SELECT source_row FROM {stage} WHERE dataset_match_status='disagreement'"):
                issues.append((file_id,n,"dataset","document_dataset_disagreement","warning",run))
        if layer=="chunks":
            for n,status in connection.execute(f"SELECT source_row,offset_status FROM {stage} WHERE offset_status<>'valid'"):
                issues.append((file_id,n,"offsets",status,"warning",run))
        accepted = {r[0] for r in connection.execute(f"SELECT source_row FROM {stage} WHERE disposition='accepted'")}
        for n,reason in connection.execute(f"SELECT source_row,reason FROM {stage} WHERE disposition='quarantined'"):
            quarantine.append((file_id,n,"identity_or_reference",reason,run))
        names_sql = ",".join(ident(n) for n in names)
        connection.execute(f"INSERT INTO {table}({names_sql}) SELECT {names_sql} FROM {stage} WHERE disposition='accepted'")
        aliases, alternate = [], []
        if layer in ("persons","curated_docs"):
            field = "aliases" if layer=="persons" else "also_appears_as"
            for n in accepted:
                _,state,_,array = parse_json(raw[n][field],"array")
                if state=="valid" and isinstance(array,list):
                    for position,value in enumerate(array):
                        if isinstance(value,str):
                            if layer=="persons": aliases.append((raw[n]["id"],position,value,normalize(value),NORMALIZATION_VERSION))
                            else: alternate.append((raw[n]["id"],position,value))
        write_rows(connection, f"{d}.person_aliases", ["person_id","alias_position","alias_raw","search_value","normalization_version"], aliases)
        if alternate:
            connection.execute("CREATE TEMP TABLE IF NOT EXISTS stage_links(annotation_id BIGINT,link_position INTEGER,file_key TEXT) ON COMMIT PRESERVE ROWS")
            connection.execute("TRUNCATE pg_temp.stage_links")
            write_rows(connection,"pg_temp.stage_links",["annotation_id","link_position","file_key"],alternate)
            connection.execute(f"INSERT INTO {d}.curated_document_links SELECT s.*,p.source_id,CASE WHEN p.source_id IS NULL THEN 'unmatched' ELSE 'resolved' END FROM pg_temp.stage_links s LEFT JOIN {d}.documents p ON p.file_key=s.file_key")
            for (n,) in connection.execute(f"SELECT DISTINCT s.source_row FROM {stage} s JOIN pg_temp.stage_links l ON l.annotation_id=s.source_id LEFT JOIN {d}.documents p ON p.file_key=l.file_key WHERE p.source_id IS NULL"):
                issues.append((file_id,n,"also_appears_as","alternate_document_unmatched","warning",run))
        # A duplicate source disposition carries no new field-level issues.
        duplicate_positions = {r[1] for r in duplicates}
        issues = sorted(set(i for i in issues if i[1] not in duplicate_positions))
        write_rows(connection,f"{a}.import_issues",["file_id","source_row","field","code","severity","run_id"],issues)
        write_rows(connection,f"{a}.quarantined_rows",["file_id","source_row","field","reason","run_id"],quarantine)
        write_rows(connection,f"{a}.duplicate_rows",["file_id","source_row","existing_file_id","existing_source_row","reason","run_id"],duplicates)
        counts = (len(records),len(accepted),len(quarantine),len(duplicates))
        connection.execute(f"INSERT INTO {a}.import_batches(file_id,start_row,end_row,n_read,n_accepted,n_quarantined,n_duplicate,run_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (file_id,start,end,*counts,run))
        if fail_at=="before_commit": raise InjectedFailure("Injected before commit")
    if fail_at=="after_commit": raise InjectedFailure("Injected after commit")
    return counts


def committed_end(connection, file_id, audit="z1_audit"):
    expected=1
    for start,end in connection.execute(f"SELECT start_row,end_row FROM {ident(audit)}.import_batches WHERE file_id=%s ORDER BY start_row",(file_id,)):
        if start!=expected: raise RuntimeError("Overlapping or missing committed source range")
        expected=end+1
    return expected-1


def run_import(args,db_connection=None):
    manifest=load_manifest(verify=True)
    print("Verified source inventory, hashes, sizes and row counts",flush=True)
    connection_context=connect() if db_connection is None else nullcontext(db_connection)
    with connection_context as connection, duckdb.connect() as reader, duckdb.connect() as lookup:
        if not connection.execute("SELECT pg_try_advisory_lock(hashtextextended('z1-etl',0))").fetchone()[0]:
            raise RuntimeError("Another Z1 import is running")
        identity=initialize(connection,manifest)
        run=start_run(connection,identity,sha256_of(MANIFEST_PATH),vars(args))
        files=connection.execute("SELECT file_id,layer,path,row_count FROM z1_audit.source_files").fetchall()
        by_id={f[0]:f for f in files}
        def source_lookup(file_id,n):
            file=by_id[file_id]
            names=[name for name,_ in source_columns(file[1])]
            row=lookup.execute("SELECT * EXCLUDE(file_row_number) FROM read_parquet(?,file_row_number=true) WHERE file_row_number=?",[str(source_path(file[2])),n-1]).fetchone()
            return dict(zip(names,row))
        scratch=PROJECT_ROOT/"data"/"work"/"import"
        scratch.mkdir(parents=True,exist_ok=True)
        reader.execute("SET memory_limit='512MB'")
        reader.execute("SET threads=1")
        reader.execute("SET preserve_insertion_order=true")
        reader.execute("SET temp_directory=?",[str(scratch)])
        stage="initialization"
        try:
            for layer in ORDER:
                stage=layer
                for file_id,_,path,total in sorted((f for f in files if f[1]==layer),key=lambda f:f[2]):
                    done=committed_end(connection,file_id)
                    if done>total: raise RuntimeError("Checkpoint exceeds manifest row count")
                    if done==total:
                        print(f"Skipped committed file: {path}",flush=True);continue
                    # Single-file Parquet reader + SELECT/WHERE preserve source order.
                    # Do not sort/materialize full text shards merely to assign row positions.
                    # Every physical row number is checked below before any batch commits.
                    cursor=reader.execute("SELECT * FROM read_parquet(?,file_row_number=true) WHERE file_row_number>=?",[str(source_path(path)),done])
                    actual_names=[c[0] for c in cursor.description]
                    expected_names=[n for n,_ in source_columns(layer)]+["file_row_number"]
                    if actual_names!=expected_names: raise RuntimeError(f"Source schema mismatch: {path}")
                    batch=[];size=0;last=time.monotonic();expected=done+1
                    while rows:=cursor.fetchmany(min(args.batch_rows,256)):
                        for row in rows:
                            n=row[-1]+1
                            if n!=expected: raise RuntimeError("Source physical row positions are not contiguous")
                            expected+=1
                            record=dict(zip(actual_names[:-1],row[:-1]))
                            row_size=sum(len(v.encode('utf-8',errors='surrogatepass')) if isinstance(v,str) else 16 for v in row[:-1])
                            if batch and (len(batch)>=args.batch_rows or size+row_size>args.batch_bytes):
                                process_batch(connection,layer,file_id,batch,run,source_lookup=source_lookup)
                                done=batch[-1][0];batch=[];size=0
                                if time.monotonic()-last>15:
                                    print(f"Imported {layer}: file {file_id}, {done:,}/{total:,}",flush=True);last=time.monotonic()
                            batch.append((n,record));size+=row_size
                    if batch: process_batch(connection,layer,file_id,batch,run,source_lookup=source_lookup)
                    if expected-1!=total: raise RuntimeError("Actual physical row coverage differs from manifest")
                    print(f"Completed file: {path}, {total:,} source rows",flush=True)
                connection.execute(f"ANALYZE z1.{TABLES[layer]}")
            stage="validation"
            connection.execute("UPDATE z1_audit.load_state SET status='validating'")
            if __package__: from .validate_z1 import validate
            else: from validate_z1 import validate
            validate(connection,manifest,run_id=run,write_report=True)
            with connection.transaction():
                connection.execute("UPDATE z1_audit.import_runs SET status='complete',completed_at=clock_timestamp() WHERE run_id=%s",(run,))
                connection.execute("UPDATE z1_audit.load_state SET status='complete'")
            print("Full Z1 import and integrity validation complete",flush=True)
        except BaseException:
            # A real connection loss may prevent status updates; next locked run repairs stale state.
            try:
                with connection.transaction():
                    connection.execute("UPDATE z1_audit.import_runs SET status='failed',failure_stage=%s,completed_at=clock_timestamp() WHERE run_id=%s",(stage,run))
                    connection.execute("UPDATE z1_audit.load_state SET status='failed'")
            except Exception: pass
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-rows",type=int,default=2000)
    parser.add_argument("--batch-bytes",type=int,default=16*1024*1024)
    args=parser.parse_args()
    if args.batch_rows<1 or args.batch_bytes<1: parser.error("Batch limits must be positive")
    run_import(args)


if __name__=="__main__": main()

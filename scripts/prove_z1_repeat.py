"""Compare complete domain contents and issue dispositions before/after repeated ETL."""
from __future__ import annotations
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path

if __package__:
    from .z1_db import connect
    from .validate_z1 import domain_fingerprints
    from .import_z1 import run_import
    from .z1_source import PROJECT_ROOT
else:
    from z1_db import connect
    from validate_z1 import domain_fingerprints
    from import_z1 import run_import
    from z1_source import PROJECT_ROOT


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    with connect() as connection:
        if not connection.execute("SELECT pg_try_advisory_lock(hashtextextended('z1-etl',0))").fetchone()[0]:
            raise RuntimeError("Import is running")
        state=connection.execute("SELECT status FROM z1_audit.load_state").fetchone()
        if state!=("complete",): raise RuntimeError("First finish and validate the full import")
        before=domain_fingerprints(connection)
        run_import(argparse.Namespace(batch_rows=2000,batch_bytes=16*1024*1024),db_connection=connection)
        after=domain_fingerprints(connection)
        if before!=after: raise RuntimeError("Repeated import changed domain/disposition contents")
        run=connection.execute("SELECT run_id FROM z1_audit.import_runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]
        read=int(connection.execute("SELECT coalesce(sum(n_read),0) FROM z1_audit.import_batches WHERE run_id=%s",(run,)).fetchone()[0])
        if read!=0: raise RuntimeError("Completed load unexpectedly processed new ranges")
        identity,schema_version,transform_version=connection.execute('SELECT content_identity,schema_version,transform_version FROM z1_audit.load_state').fetchone()
        repo,revision=connection.execute('SELECT DISTINCT repo_id,revision FROM z1_audit.source_files').fetchone()
    report={"verified_at":datetime.now(timezone.utc).isoformat(),"run_id":str(run),"repo_id":repo,"revision":revision,
            "content_identity":identity,"schema_version":schema_version,"transform_version":transform_version,"same_complete_contents":True,
            "newly_read":read,"before":before,"after":after,
            "format":"PostgreSQL18 to_jsonb(row) minus input_file_id/source_row/loaded_by_run, canonical jsonb text UTF8, SHA256 per row; concatenate fixed 32-byte row hashes in PK order and SHA256 again. Audit issue/quarantine/duplicate rows: all non-run fields in column order, sorted by all fields, ASCII JSON arrays with length prefixes. UTC session; audit attempts/timestamps excluded."}
    (PROJECT_ROOT/"evidence"/"import-repeat.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("Repeat proof passed: all 15 domain tables and source dispositions unchanged; zero new source rows",flush=True)


if __name__=='__main__': main()

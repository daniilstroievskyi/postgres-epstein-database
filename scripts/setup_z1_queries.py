"""Install section-7 extension/indexes and record actual build costs and sizes."""
from __future__ import annotations
import argparse
import hashlib
import json
from time import perf_counter

if __package__:
    from .z1_db import connect
    from .z1_workload import INDEX_PATH,INDEX_SPECS,PROJECT_ROOT,blocks,environment,extension_ready,index_metadata,now,require_full_load,write_json
else:
    from z1_db import connect
    from z1_workload import INDEX_PATH,INDEX_SPECS,PROJECT_ROOT,blocks,environment,extension_ready,index_metadata,now,require_full_load,write_json


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    output=PROJECT_ROOT/'evidence'/'query-indexes.json'
    previous=json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}
    with connect() as db:
        manifest=require_full_load(db)
        db.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public')
        extension_ready(db)
        identity=db.execute('SELECT content_identity FROM z1_audit.load_state').fetchone()[0]
        report=dict(recorded_at=now(),revision=manifest['revision'],content_identity=identity,
            ddl_file_sha256=hashlib.sha256(INDEX_PATH.read_bytes()).hexdigest(),environment=environment(db),indexes={})
        changed_tables=set()
        for name,sql in blocks(INDEX_PATH).items():
            existing=index_metadata(db,name)
            created=existing is None
            build_seconds=None
            if created:
                changed_tables.add(INDEX_SPECS[name]['table'])
                print(f'Building {name}...',flush=True)
                started=perf_counter()
                db.execute(sql)
                build_seconds=perf_counter()-started
            metadata=index_metadata(db,name)
            old=previous.get('indexes',{}).get(name,{})
            if not created and previous.get('content_identity')==identity and old.get('ddl')==metadata['ddl']:
                build_seconds=old.get('build_seconds')
            metadata.update(created_this_invocation=created,build_seconds=build_seconds,
                build_measured_at=now() if created else old.get('build_measured_at'),
                target_rows=db.execute(f'SELECT count(*) FROM z1.{INDEX_SPECS[name]["table"]}').fetchone()[0])
            metadata['indexed_rows']=metadata['target_rows'] if metadata['predicate'] is None else db.execute(
                f'SELECT count(*) FROM z1.{INDEX_SPECS[name]["table"]} WHERE {metadata["predicate"]}').fetchone()[0]
            report['indexes'][name]=metadata
            write_json(output,report)
            print(f'{name}: {metadata["bytes"]:,} bytes; '+('created' if created else 'already present'),flush=True)
        if not previous.get('complete') or previous.get('content_identity')!=identity:
            changed_tables.update(s['table'] for s in INDEX_SPECS.values())
        for table in sorted(changed_tables):
            db.execute(f'ANALYZE z1.{table}')
        report['complete']=True
        write_json(output,report)
    print('Saved evidence/query-indexes.json; all four indexes are active',flush=True)


if __name__=='__main__': main()

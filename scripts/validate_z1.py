"""Validate full source coverage, accounting, actual constraints and transformations."""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .z1_db import connect
    from .z1_model import TABLES, ORDER, columns, keys, ident, SCHEMA_VERSION, raw_fingerprint_sql
    from .z1_source import PROJECT_ROOT, load_manifest
    from .z1_transform import content_identity, fingerprint, parse_amount
else:
    from z1_db import connect
    from z1_model import TABLES, ORDER, columns, keys, ident, SCHEMA_VERSION, raw_fingerprint_sql
    from z1_source import PROJECT_ROOT, load_manifest
    from z1_transform import content_identity, fingerprint, parse_amount


def domain_fingerprints(connection, domain="z1", audit="z1_audit"):
    """Hash ALL stored domain values in PK order, excluding bookkeeping fields only."""
    results={}
    for table in [TABLES[layer] for layer in ORDER]+["person_aliases","curated_document_links"]:
        layer=next((x for x in ORDER if TABLES[x]==table),None)
        pk=keys(layer) if layer else ["person_id","alias_position"] if table=="person_aliases" else ["annotation_id","link_position"]
        digest=hashlib.sha256();count=0
        with connection.transaction(),connection.cursor(name="z1_hash_cursor") as cursor:
            cursor.execute(f"SELECT sha256(convert_to((to_jsonb(t)-ARRAY['input_file_id','source_row','loaded_by_run'])::text,'UTF8')) FROM {ident(domain)}.{table} t ORDER BY {','.join(map(ident,pk))}")
            while rows:=cursor.fetchmany(2000):
                for (row_hash,) in rows:
                    digest.update(bytes(row_hash));count+=1
        results[table]={"rows":count,"sha256":digest.hexdigest()}
        print(f"Hashed complete table: {table}, {count:,} rows",flush=True)
    for table in ("import_issues","quarantined_rows","duplicate_rows"):
        names=[r[0] for r in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",(audit,table)) if r[0]!="run_id"]
        digest=hashlib.sha256();count=0
        with connection.transaction(),connection.cursor(name="z1_hash_cursor") as cursor:
            cursor.execute(f"SELECT {','.join(map(ident,names))} FROM {ident(audit)}.{table} ORDER BY {','.join(map(ident,names))}")
            while rows:=cursor.fetchmany(2000):
                for row in rows:
                    encoded=json.dumps(row,ensure_ascii=True,separators=(",",":"),default=str).encode()
                    digest.update(len(encoded).to_bytes(8,"big"));digest.update(encoded);count+=1
        results["audit."+table]={"rows":count,"sha256":digest.hexdigest()}
    return results


def validate(connection,manifest,domain="z1",audit="z1_audit",run_id=None,write_report=False):
    d,a=ident(domain),ident(audit)
    def require(condition,message):
        if not condition: raise RuntimeError("Validation failed: "+message)
    state=connection.execute(f"SELECT content_identity FROM {a}.load_state").fetchone()
    require(state==(content_identity(manifest,SCHEMA_VERSION),),"load identity differs")
    require(connection.execute("SHOW session_replication_role").fetchone()[0]=="origin","constraint triggers bypassed")
    report={"validated_at":datetime.now(timezone.utc).isoformat(),"revision":manifest["revision"],"run_id":str(run_id) if run_id else None,"layers":{},"files":[],"constraints":{},"derived":{},"issues":[]}
    manifest_paths={f["path"]:f for f in manifest["files"]}
    files=connection.execute(f"SELECT file_id,layer,path,row_count,sha256 FROM {a}.source_files ORDER BY path").fetchall()
    require({f[2] for f in files}==set(manifest_paths),"catalog inventory differs")
    for file_id,layer,path,total,hash_value in files:
        require((total,hash_value)==(manifest_paths[path]["row_count"],manifest_paths[path]["sha256"]),"catalog metadata differs")
        expected=1;totals=[0,0,0,0]
        for start,end,*counts in connection.execute(f"SELECT start_row,end_row,n_read,n_accepted,n_quarantined,n_duplicate FROM {a}.import_batches WHERE file_id=%s ORDER BY start_row",(file_id,)):
            require(start==expected and end>=start,"noncontiguous committed source ranges")
            require(counts[0]==end-start+1 and counts[0]==sum(counts[1:]),"batch equation differs")
            expected=end+1;totals=[x+y for x,y in zip(totals,counts)]
        require(expected==total+1 and totals[0]==total,"incomplete source coverage: "+path)
        table=f"{d}.{TABLES[layer]}"
        actual=[connection.execute(f"SELECT count(*) FROM {table} WHERE input_file_id=%s",(file_id,)).fetchone()[0],
                connection.execute(f"SELECT count(*) FROM {a}.quarantined_rows WHERE file_id=%s",(file_id,)).fetchone()[0],
                connection.execute(f"SELECT count(*) FROM {a}.duplicate_rows WHERE file_id=%s",(file_id,)).fetchone()[0]]
        require(actual==totals[1:],"target dispositions differ from ledger: "+path)
        invalid=connection.execute(f"""SELECT count(*) FROM (
            SELECT source_row FROM {table} WHERE input_file_id=%s
            UNION ALL SELECT source_row FROM {a}.quarantined_rows WHERE file_id=%s
            UNION ALL SELECT source_row FROM {a}.duplicate_rows WHERE file_id=%s
        ) p WHERE source_row<1 OR source_row>%s""",(file_id,file_id,file_id,total)).fetchone()[0]
        require(invalid==0,"out-of-range source locator")
        overlap=connection.execute(f"""SELECT count(*) FROM (
            SELECT source_row FROM {table} WHERE input_file_id=%s
            UNION ALL SELECT source_row FROM {a}.quarantined_rows WHERE file_id=%s
            UNION ALL SELECT source_row FROM {a}.duplicate_rows WHERE file_id=%s
        ) p GROUP BY source_row HAVING count(*)<>1 LIMIT 1""",(file_id,file_id,file_id)).fetchone()
        require(overlap is None,"overlapping dispositions")
        report["files"].append({"path":path,"read":totals[0],"accepted":totals[1],"quarantined":totals[2],"duplicate":totals[3]})
        current=report["layers"].setdefault(layer,dict(read=0,accepted=0,quarantined=0,duplicate=0,target_rows=0))
        for name,value in zip(("read","accepted","quarantined","duplicate"),totals): current[name]+=value
        current["target_rows"]+=actual[0]
    for layer in ORDER:
        actual_columns={r[0] for r in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",(domain,TABLES[layer]))}
        require({n for n,_ in columns(layer)}<=actual_columns,"target mapping columns missing")
        require(connection.execute(f"SELECT count(*) FROM {d}.{TABLES[layer]}").fetchone()[0]==report["layers"][layer]["target_rows"],"unaccounted target rows")
        mismatches=connection.execute(f"SELECT count(*) FROM {d}.{TABLES[layer]} WHERE raw_record_hash<>{raw_fingerprint_sql(layer)}").fetchone()[0]
        require(mismatches==0,"raw target values differ from verified source fingerprints: "+layer)
        print(f"Validated coverage and original-field fingerprints: {layer}",flush=True)
    constraints=connection.execute("""SELECT c.oid,c.conname,c.contype,c.convalidated,c.conenforced,n.nspname,t.relname
        FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname IN (%s,%s)""",(domain,audit)).fetchall()
    require(all(c[3] and c[4] for c in constraints),"inactive/unvalidated constraints")
    for table in [TABLES[x] for x in ORDER]+["person_aliases","curated_document_links"]:
        require(any(c[2]=="p" and c[6]==table and c[5]==domain for c in constraints),"primary key absent")
    fks=connection.execute("""SELECT c.oid,n.nspname,t.relname,pn.nspname,p.relname,
        ARRAY(SELECT attname FROM unnest(c.conkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num ORDER BY ord),
        ARRAY(SELECT attname FROM unnest(c.confkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.num ORDER BY ord)
        FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
        JOIN pg_class p ON p.oid=c.confrelid JOIN pg_namespace pn ON pn.oid=p.relnamespace
        WHERE c.contype='f' AND n.nspname IN (%s,%s)""",(domain,audit)).fetchall()
    for oid,child_ns,child,parent_ns,parent,child_cols,parent_cols in fks:
        require(connection.execute("SELECT count(*) FROM pg_trigger WHERE tgconstraint=%s AND tgenabled NOT IN ('O','A')",(oid,)).fetchone()[0]==0,"disabled FK trigger")
        join=" AND ".join(f"c.{ident(x)}=p.{ident(y)}" for x,y in zip(child_cols,parent_cols))
        nonnull=" AND ".join(f"c.{ident(x)} IS NOT NULL" for x in child_cols)
        invalid=connection.execute(f"SELECT count(*) FROM {ident(child_ns)}.{ident(child)} c WHERE {nonnull} AND NOT EXISTS(SELECT 1 FROM {ident(parent_ns)}.{ident(parent)} p WHERE {join})").fetchone()[0]
        require(invalid==0,"invalid nonnull FK: "+child)
    # Required relationships must actually be present, not merely all existing FKs valid.
    required={("chunks","document_id","documents"),("kg_edges","from_node_id","kg_nodes"),("kg_edges","to_node_id","kg_nodes"),("event_participants","event_id","events"),("event_sources","event_id","events")}
    found={(r[2],r[5][0],r[4]) for r in fks if r[1]==domain and len(r[5])==1}
    require(required<=found,"required domain foreign key absent")
    expected_fks=set()
    for layer in ORDER:
        table=TABLES[layer]
        expected_fks.add((domain,table,('input_file_id',),audit,'source_files',('file_id',)))
        expected_fks.add((domain,table,('loaded_by_run',),audit,'import_runs',('run_id',)))
        if 'document_id' in {n for n,_ in columns(layer)}:
            expected_fks.add((domain,table,('document_id',),domain,'documents',('source_id',)))
    expected_fks |= {(domain,'mentions',('candidate_document_id',),domain,'documents',('source_id',)),
        (domain,'kg_edges',('from_node_id',),domain,'kg_nodes',('source_id',)),
        (domain,'kg_edges',('to_node_id',),domain,'kg_nodes',('source_id',)),
        (domain,'event_participants',('event_id',),domain,'events',('source_id',)),
        (domain,'event_sources',('event_id',),domain,'events',('source_id',)),
        (domain,'upstream_files',('run_id',),domain,'upstream_runs',('run_id',)),
        (domain,'person_aliases',('person_id',),domain,'persons',('source_id',)),
        (domain,'curated_document_links',('annotation_id',),domain,'curated_annotations',('source_id',)),
        (domain,'curated_document_links',('document_id',),domain,'documents',('source_id',))}
    signatures={(r[1],r[2],tuple(r[5]),r[3],r[4],tuple(r[6])) for r in fks}
    require(expected_fks<=signatures,"modeled domain/lineage foreign key absent")
    report["constraints"]={"total":len(constraints),"foreign_keys":len(fks),"all_active_validated":True,"nonnull_fk_antijoins":"passed","required_relationships":"passed"}
    for parent,field,child in [("persons","aliases","person_aliases"),("curated_annotations","also_appears_as","curated_document_links")]:
        expected=connection.execute(f"SELECT count(*) FROM {d}.{parent} p CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(p.{field})='array' THEN p.{field} ELSE '[]'::jsonb END) e WHERE jsonb_typeof(e.value)='string'").fetchone()[0]
        actual=connection.execute(f"SELECT count(*) FROM {d}.{child}").fetchone()[0]
        require(expected==actual,"derived array count differs")
        report["derived"][child]={"expected":expected,"actual":actual}
        parent_key,position,raw=('person_id','alias_position','alias_raw') if child=='person_aliases' else ('annotation_id','link_position','file_key')
        invalid=connection.execute(f"SELECT count(*) FROM {d}.{child} c JOIN {d}.{parent} p ON p.source_id=c.{parent_key} WHERE jsonb_typeof(p.{field}->c.{position}) IS DISTINCT FROM 'string' OR c.{raw} IS DISTINCT FROM ((p.{field}->c.{position})#>>'{{}}')").fetchone()[0]
        require(invalid==0,'derived array values/positions differ')
    for layer in ('event_sources','financial_transactions','curated_docs','provenance/files'):
        table=TABLES[layer]
        invalid=connection.execute(f'SELECT count(*) FROM {d}.{table} c JOIN {d}.documents p ON p.source_id=c.document_id WHERE c.file_key IS DISTINCT FROM p.file_key').fetchone()[0]
        require(invalid==0,'resolved document lookup disagrees with raw file key')
    invalid=connection.execute(f'SELECT count(*) FROM {d}.mentions WHERE document_id IS NOT NULL OR (candidate_document_id IS NOT NULL AND candidate_document_id IS DISTINCT FROM raw_document_id)').fetchone()[0]
    require(invalid==0,'entity namespace policy differs')
    invalid=connection.execute(f"SELECT count(*) FROM {d}.upstream_files WHERE run_id IS NOT NULL AND run_id IS DISTINCT FROM raw_run_id").fetchone()[0]
    require(invalid==0,'upstream run lookup differs')
    for table in ("events","financial_transactions","upstream_runs"):
        field='cost_usd' if table=='upstream_runs' else 'amount'
        with connection.transaction(),connection.cursor(name='z1_money_validation') as cursor:
            cursor.execute(f'SELECT {field}_raw,{field},{field}_state FROM {d}.{table}')
            while rows:=cursor.fetchmany(2000):
                for raw,value,state in rows: require((value,state)==parse_amount(raw),'amount precision/state differs')
    report["issues"]=[dict(zip(("layer","field","code","count"),r)) for r in connection.execute(f"SELECT f.layer,i.field,i.code,count(*) FROM {a}.import_issues i JOIN {a}.source_files f ON f.file_id=i.file_id GROUP BY 1,2,3 ORDER BY 1,2,3")]
    report["quarantine_reasons"]=[dict(zip(("layer","field","reason","count"),r)) for r in connection.execute(f"SELECT f.layer,q.field,q.reason,count(*) FROM {a}.quarantined_rows q JOIN {a}.source_files f ON f.file_id=q.file_id GROUP BY 1,2,3 ORDER BY 1,2,3")]
    report["checks"]={"manifest":"passed","physical_source_coverage":"passed","row_accounting":"passed","disjoint_dispositions":"passed","mapping_columns":"passed","target_counts":"passed","derived_counts_and_values":"passed","resolved_reference_values":"passed","entity_namespace_policy":"passed","all_original_field_fingerprints":"passed","exact_amount_transformation":"passed"}
    if run_id:
        activity=connection.execute(f"SELECT coalesce(sum(n_read),0),coalesce(sum(n_accepted),0),coalesce(sum(n_quarantined),0),coalesce(sum(n_duplicate),0) FROM {a}.import_batches WHERE run_id=%s",(run_id,)).fetchone()
        report["attempt_activity"]=dict(zip(("read","accepted","quarantined","duplicate"),map(int,activity)))
        report["attempt_activity"]["previously_processed"]=sum(x["read"] for x in report["layers"].values())-int(activity[0])
    if write_report:
        evidence=PROJECT_ROOT/"evidence";evidence.mkdir(exist_ok=True)
        (evidence/"import-validation.json").write_text(json.dumps(report,indent=2,default=str)+"\n",encoding="utf-8")
        lines=["# Full Z1 import report","",f"Validated at {report['validated_at']}.","",f"Frozen revision: `{manifest['revision']}`.","","This report records actual database checks. Repeat/recovery evidence is recorded separately.","","| Layer | Read | Accepted | Quarantined | Duplicate | Target rows |","|---|---:|---:|---:|---:|---:|"]
        lines += [f"| {layer} | {v['read']:,} | {v['accepted']:,} | {v['quarantined']:,} | {v['duplicate']:,} | {v['target_rows']:,} |" for layer,v in report["layers"].items()]
        lines += ["",f"Actual active, validated foreign keys: {len(fks)}. Every nonnull FK passed an explicit anti-join check.","","Every file's physical row coverage, disjoint dispositions and target counts reconcile with the manifest.","","| Derived table | Expected string elements | Actual rows |","|---|---:|---:|"]
        lines += [f"| {t} | {x['expected']} | {x['actual']} |" for t,x in report['derived'].items()]
        lines += ["","| Layer | Field | Issue code | Source rows |","|---|---|---|---:|"]
        lines += [f"| {x['layer']} | {x['field']} | {x['code']} | {x['count']:,} |" for x in report['issues']]
        lines += ["","Multiple issues can concern one accepted row. Namespace-unverified entity links remain candidates, not confirmed resolutions.",
            "","All retained original fields passed independently reconstructed source fingerprints; exact monetary conversion and derived array values/positions were checked.",
            "","## Tests, repetition and recovery","",
            "[Synthetic test results](../evidence/import-tests.json) cover transformation edge cases, actual FK rejection, repeated/conflicting identities, and fresh-connection recovery before/after commit.",
            "","[Full repeat evidence](../evidence/import-repeat.json) records complete before/after content hashes and zero newly processed source rows. Audit attempt metadata is excluded; source issues/quarantine/duplicates are included.",
            "","[Recovery/runtime evidence](../evidence/import-recovery.json) records real interrupted attempts, resumed committed coverage, server/library/extension versions and storage. [Trace examples](../evidence/import-trace.json) demonstrate exact original-field equality for document and chunk ID 1.",
            "","Each quarantined record retains its source file/physical-position locator; source files are unchanged. Actual reasons and counts:",
            "","| Layer | Field | Reason | Rows |","|---|---|---|---:|"]
        lines += [f"| {r['layer']} | {r['field']} | {r['reason']} | {r['count']} |" for r in report['quarantine_reasons']]
        lines += [
            "","Commands from the project root:","","```powershell",".\\.venv\\Scripts\\python.exe scripts/import_z1.py",".\\.venv\\Scripts\\python.exe scripts/validate_z1.py",".\\.venv\\Scripts\\python.exe scripts/prove_z1_repeat.py","```",""]
        (PROJECT_ROOT/"docs"/"import-report.md").write_text("\n".join(lines),encoding="utf-8")
    return report


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    manifest=load_manifest(verify=True)
    with connect() as connection:
        if not connection.execute("SELECT pg_try_advisory_lock(hashtextextended('z1-etl',0))").fetchone()[0]: raise RuntimeError("Import is running")
        report=validate(connection,manifest,write_report=True)
    print(f"Validated all {len(report['layers'])} layers and {report['constraints']['foreign_keys']} actual foreign keys")


if __name__=="__main__": main()

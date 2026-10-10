"""Compare one imported row's retained original fields to its immutable source."""
from __future__ import annotations
import argparse
import json
import duckdb

if __package__:
    from .z1_db import connect
    from .z1_model import TABLES,source_columns,raw_column,ident
    from .z1_source import load_manifest,source_path
    from .z1_transform import fingerprint,equal_records
else:
    from z1_db import connect
    from z1_model import TABLES,source_columns,raw_column,ident
    from z1_source import load_manifest,source_path
    from z1_transform import fingerprint,equal_records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layer',required=True,choices=TABLES)
    parser.add_argument('--id',type=int,help='Original numeric ID for layers with id')
    parser.add_argument('--run-id',help='Original upstream run ID')
    parser.add_argument('--output-name',help='Provenance file-output composite key')
    parser.add_argument('--file-key',help='Provenance file-output composite key')
    args=parser.parse_args()
    load_manifest(verify=True)
    if args.layer=='provenance/runs': predicate='run_id=%s';parameters=(args.run_id,)
    elif args.layer=='provenance/files': predicate='output_name=%s AND file_key=%s';parameters=(args.output_name,args.file_key)
    else: predicate='source_id=%s';parameters=(args.id,)
    names=[n for n,_ in source_columns(args.layer)]
    with connect() as connection:
        selected=','.join('t.'+ident(raw_column(args.layer,n)) for n in names)
        row=connection.execute(f'SELECT {selected},t.source_row,f.path,t.raw_record_hash FROM z1.{TABLES[args.layer]} t JOIN z1_audit.source_files f ON f.file_id=t.input_file_id WHERE t.{predicate}',parameters).fetchone()
    if row is None: raise RuntimeError('Source identity has no accepted target row; inspect quarantine dispositions')
    retained=dict(zip(names,row[:-3]));position,path,digest=row[-3:]
    with duckdb.connect() as reader:
        original=reader.execute('SELECT * EXCLUDE(file_row_number) FROM read_parquet(?,file_row_number=true) WHERE file_row_number=?',[str(source_path(path)),position-1]).fetchone()
    original=dict(zip(names,original))
    if not equal_records(original,retained) or fingerprint(original)!=bytes(digest): raise RuntimeError('Source-to-target trace differs')
    # Deliberately print locators/field names, never document text or names.
    print(json.dumps({'layer':args.layer,'file':path,'physical_row':position,'original_fields_checked':names,'exact_raw_values_match':True,'stored_fingerprint_matches':True},indent=2))


if __name__=='__main__': main()

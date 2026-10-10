"""Run all section-7 SQL against the full load, or demonstrate one query."""
from __future__ import annotations
import argparse
import hashlib
import json

if __package__:
    from .z1_db import connect
    from .z1_workload import DEFAULTS,NORMALIZATION_VERSION,QUERY_PATH,PROJECT_ROOT,blocks,configure,environment,execute_verified,extension_ready,normalize,now,require_full_load,source_accounting,write_json
else:
    from z1_db import connect
    from z1_workload import DEFAULTS,NORMALIZATION_VERSION,QUERY_PATH,PROJECT_ROOT,blocks,configure,environment,execute_verified,extension_ready,normalize,now,require_full_load,source_accounting,write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query',choices=['all']+list(blocks(QUERY_PATH)),default='all')
    parser.add_argument('--fts',default=DEFAULTS['fts'])
    parser.add_argument('--name',default=DEFAULTS['name'])
    parser.add_argument('--threshold',type=float,default=DEFAULTS['threshold'])
    parser.add_argument('--kg-start',type=int,default=DEFAULTS['kg_start'])
    parser.add_argument('--currency',default=None)
    parser.add_argument('--merchant',default=None)
    parser.add_argument('--show-rows',type=int,default=0,help='Print up to N rows per query; hashes still cover the complete result')
    args=parser.parse_args()
    if args.show_rows<0: parser.error('--show-rows must be nonnegative')
    parameters={key:getattr(args,key) for key in DEFAULTS}
    queries=list(blocks(QUERY_PATH)) if args.query=='all' else [args.query]
    with connect() as db:
        manifest=require_full_load(db)
        extension_ready(db)
        report=dict(executed_at=now(),revision=manifest['revision'],environment=environment(db),parameters=parameters,
            queries_file_sha256=hashlib.sha256(QUERY_PATH.read_bytes()).hexdigest(),
            hash_format='SHA256: 8-byte big-endian byte length + UTF-8 compact JSON columns, then each ordered typed row; no LIMIT; float64 IEEE hex and Decimal text',queries={})
        report['source_accounting']=source_accounting(db)
        report['effective_inputs']=dict(fts=parameters['fts'],fuzzy_normalized=normalize(parameters['name']),
            normalization_version=NORMALIZATION_VERSION,threshold=parameters['threshold'],kg_start=parameters['kg_start'],
            q4_currency=parameters['currency'],q4_merchant=normalize(parameters['merchant']),
            q4_filter_currency=parameters['currency'] or 'USD',q4_filter_merchant=normalize(parameters['merchant']) or 'fedex')
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            configure(db,parameters)
            for name in queries:
                print(f'Running {name}...',flush=True)
                result,preview=execute_verified(db,name,preview_count=args.show_rows)
                report['queries'][name]=result
                print(f'{name}: {result["rows"]:,} complete result rows; SHA256 {result["sha256"]}',flush=True)
                for row in preview: print(json.dumps(row,ensure_ascii=False,default=str))
            if args.query=='all' and parameters==DEFAULTS:
                if report['queries']['Q4']['totals']['transaction_records']!=report['source_accounting']['financial_transactions']['accepted']:
                    raise RuntimeError('Full financial query does not cover all accepted transactions')
                if report['queries']['Q6']['totals']['document_records']!=report['source_accounting']['documents']['accepted']:
                    raise RuntimeError('Full email query does not cover all accepted documents')
                if report['queries']['Q6_JSON']['rows']!=report['queries']['Q6']['totals']['object_subject_json_null']:
                    raise RuntimeError('Email drill-down differs from full aggregate')
        if args.query=='all' and parameters==DEFAULTS:
            write_json(PROJECT_ROOT/'evidence'/'query-results.json',report)
            print('Saved evidence/query-results.json (verification durations are not a benchmark)',flush=True)


if __name__=='__main__': main()

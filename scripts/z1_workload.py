"""Shared section-7 SQL, parameters, evidence and bounded result verification."""
from __future__ import annotations
import hashlib
import json
import platform
import re
import struct
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter

if __package__:
    from .z1_model import SCHEMA_VERSION, ident
    from .z1_source import PROJECT_ROOT, load_manifest
    from .z1_transform import NORMALIZATION_VERSION, content_identity, normalize
else:
    from z1_model import SCHEMA_VERSION, ident
    from z1_source import PROJECT_ROOT, load_manifest
    from z1_transform import NORMALIZATION_VERSION, content_identity, normalize

QUERY_PATH = PROJECT_ROOT / 'sql' / 'queries.sql'
INDEX_PATH = PROJECT_ROOT / 'sql' / 'query-indexes.sql'
DEFAULTS = dict(fts='aircraft', name='Jeffrey Epstien', threshold=0.3,
                kg_start=1, currency=None, merchant=None)
INDEX_SPECS = {
    'chunks_fts_gin': dict(table='chunks', method='gin', keys=[None], opclasses=['tsvector_ops'],
        expression="to_tsvector('english'::regconfig, COALESCE(content, ''::text))", predicate=None),
    'persons_name_trgm_gin': dict(table='persons', method='gin', keys=['search_value'],
        opclasses=['gin_trgm_ops'], expression=None, predicate=None),
    'financial_currency_merchant_btree': dict(table='financial_transactions', method='btree',
        keys=['currency','search_value'], opclasses=['text_ops','text_ops'], expression=None, predicate=None),
    'documents_email_object_gin': dict(table='documents', method='gin', keys=['email_fields'],
        opclasses=['jsonb_path_ops'], expression=None,
        predicate="((email_fields_state = 'valid'::text) AND (jsonb_typeof(email_fields) = 'object'::text))"),
}


def blocks(path: Path):
    parts = re.split(r'^-- name: ([a-zA-Z0-9_]+)\s*$', path.read_text(encoding='utf-8'), flags=re.M)
    return dict(zip(parts[1::2], (text.strip() for text in parts[2::2])))


def query_sql(name, domain='z1'):
    return blocks(QUERY_PATH)[name].replace('"z1".', ident(domain)+'.')


def configure(connection, parameters):
    if not 0 <= parameters['threshold'] <= 1:
        raise ValueError('Similarity threshold must be between 0 and 1')
    if not normalize(parameters['name']):
        raise ValueError('Name must contain a non-whitespace character')
    values = {
        'z1.fts_input': parameters['fts'], 'z1.fuzzy_raw_input': parameters['name'],
        'z1.fuzzy_input': normalize(parameters['name']),
        'pg_trgm.similarity_threshold': str(parameters['threshold']),
        'z1.kg_start': str(parameters['kg_start']),
        'z1.currency': '' if parameters['currency'] is None else parameters['currency'].strip().upper(),
        'z1.merchant': '' if parameters['merchant'] is None else normalize(parameters['merchant']),
    }
    for key, value in values.items():
        connection.execute('SELECT set_config(%s,%s,true)', (key, value))


def require_full_load(connection):
    if not connection.execute("SELECT pg_try_advisory_lock(hashtextextended('z1-etl',0))").fetchone()[0]:
        raise RuntimeError('Another Z1 import/validation/workload operation is running')
    manifest = load_manifest(verify=True)
    state = connection.execute('SELECT status,content_identity FROM z1_audit.load_state').fetchone()
    if state != ('complete', content_identity(manifest, SCHEMA_VERSION)):
        raise RuntimeError('First complete and validate the full prescribed import')
    return manifest


def extension_ready(connection):
    row = connection.execute('SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE extname=%s', ('pg_trgm',)).fetchone()
    if row != ('public',):
        raise RuntimeError('Install pg_trgm in public using setup_z1_queries.py')


def environment(connection):
    return {
        'python': platform.python_version(),
        'server': connection.execute('SELECT version()').fetchone()[0],
        'extensions': dict(connection.execute('SELECT extname,extversion FROM pg_extension ORDER BY extname')),
        'database_locale': connection.execute('SELECT datcollate,datctype FROM pg_database WHERE datname=current_database()').fetchone(),
        'settings': {r[0]: dict(value=r[1], unit=r[2]) for r in connection.execute(
            "SELECT name,setting,unit FROM pg_settings WHERE name IN ('shared_buffers','work_mem','maintenance_work_mem','max_parallel_workers_per_gather') ORDER BY name")},
    }


def source_accounting(connection):
    rows=connection.execute('''SELECT f.layer,sum(b.n_read),sum(b.n_accepted),sum(b.n_quarantined),sum(b.n_duplicate)
        FROM z1_audit.source_files f JOIN z1_audit.import_batches b ON b.file_id=f.file_id
        GROUP BY f.layer ORDER BY f.layer''').fetchall()
    return {r[0]:dict(zip(['read','accepted','quarantined','duplicate'],map(int,r[1:]))) for r in rows}


def index_metadata(connection, name, domain='z1'):
    row = connection.execute('''SELECT t.relname,am.amname,i.indisvalid,i.indisready,i.indisunique,
        pg_get_indexdef(c.oid),pg_relation_size(c.oid),pg_get_expr(i.indexprs,i.indrelid),
        pg_get_expr(i.indpred,i.indrelid),
        ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(num,pos)
              LEFT JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.num ORDER BY k.pos),
        ARRAY(SELECT o.opcname FROM unnest(i.indclass) WITH ORDINALITY k(num,pos)
              JOIN pg_opclass o ON o.oid=k.num ORDER BY k.pos)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_index i ON i.indexrelid=c.oid JOIN pg_class t ON t.oid=i.indrelid
        JOIN pg_am am ON am.oid=c.relam WHERE n.nspname=%s AND c.relname=%s''', (domain,name)).fetchone()
    if row is None:
        return None
    fields = ['table','method','valid','ready','unique','ddl','bytes','expression','predicate','keys','opclasses']
    result = dict(zip(fields,row))
    for key, expected in INDEX_SPECS[name].items():
        if result[key] != expected:
            raise RuntimeError(f'Existing index {domain}.{name} has unexpected {key}; inspect its DDL')
    if not result['valid'] or not result['ready'] or result['unique']:
        raise RuntimeError(f'Index {domain}.{name} is not the expected active auxiliary index')
    return result


def typed(value):
    if value is None: return ['null']
    if isinstance(value,bool): return ['bool',value]
    if isinstance(value,int): return ['int',str(value)]
    if isinstance(value,float): return ['float64',struct.pack('>d',value).hex()]
    if isinstance(value,Decimal): return ['decimal',str(value)]
    if isinstance(value,str): return ['text',value]
    raise TypeError(f'Unsupported query result type: {type(value).__name__}')


def execute_verified(connection, name, domain='z1', preview_count=0):
    """Hash every returned row; verification duration is NOT section-8 timing."""
    sql = query_sql(name,domain)
    plan = connection.execute('EXPLAIN (FORMAT JSON) '+sql).fetchone()[0][0]['Plan']
    digest, count, preview, totals = hashlib.sha256(), 0, [], {}
    started = perf_counter()
    with connection.cursor(name='z1_query_result') as cursor:
        cursor.execute(sql)
        names = [c.name for c in cursor.description]
        header = json.dumps(names,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        digest.update(struct.pack('>Q',len(header))+header)
        while rows := cursor.fetchmany(2000):
            for row in rows:
                encoded = json.dumps([typed(v) for v in row],ensure_ascii=False,separators=(',',':')).encode('utf-8')
                digest.update(struct.pack('>Q',len(encoded))+encoded)
                count += 1
                values = dict(zip(names,row))
                if len(preview)<preview_count: preview.append(values)
                if name=='Q1' and values['relevance']<=0: raise RuntimeError('FTS result has no positive relevance')
                if name=='Q2' and values['similarity_score'] < values['threshold']:
                    raise RuntimeError('Fuzzy result is below its stated threshold')
                if name=='Q3' and len(set(row[:3]))!=3: raise RuntimeError('Two-hop query repeated a node')
                if name in ('Q4','Q4_FILTER'):
                    if values['transaction_records'] != sum(values[x] for x in ['valid_amount_records','missing_amount_records','invalid_amount_records']):
                        raise RuntimeError('Financial amount-state accounting differs')
                    for key in ['transaction_records','valid_amount_records','missing_amount_records','invalid_amount_records','negative_amount_records','zero_amount_records','positive_amount_records']:
                        totals[key]=totals.get(key,0)+values[key]
                if name=='Q6':
                    categories=['missing_sql_null','empty_raw','invalid_raw','whole_json_null','valid_objects','valid_arrays','valid_other_scalars']
                    if values['document_records'] != sum(values[x] for x in categories):
                        raise RuntimeError('Email-state accounting differs')
                    if values['valid_objects'] != sum(values[x] for x in ['object_subject_absent','object_subject_json_null','object_subject_nonnull']):
                        raise RuntimeError('Email subject accounting differs')
                    for key in ['document_records']+categories+['object_subject_absent','object_subject_json_null','object_subject_nonnull']:
                        totals[key]=totals.get(key,0)+values[key]
    return dict(rows=count, columns=names, sha256=digest.hexdigest(),
                sql_sha256=hashlib.sha256(sql.encode()).hexdigest(),
                verification_seconds=perf_counter()-started, totals=totals, plan=plan), preview


def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()

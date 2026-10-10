"""Section 9 R2: refresh/verify a financial materialized view, or show synthetic staleness."""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
import uuid
from time import perf_counter

if __package__:
    from .z1_db import connect
    from .z1_model import ident
    from .z1_workload import PROJECT_ROOT, blocks, environment, now, query_sql, require_full_load, source_accounting, typed, write_json
else:
    from z1_db import connect
    from z1_model import ident
    from z1_workload import PROJECT_ROOT, blocks, environment, now, query_sql, require_full_load, source_accounting, typed, write_json

SQL_PATH = PROJECT_ROOT/'sql'/'extension.sql'
NAME = 'financial_report'


def extension_sql(name, domain='z1'):
    return blocks(SQL_PATH)[name].replace('"z1".', ident(domain)+'.')


def report_metadata(db, domain='z1'):
    row = db.execute('''SELECT c.oid,c.relkind,c.relispopulated,
        CASE WHEN c.relkind='m' THEN pg_get_viewdef(c.oid,true) END,
        pg_total_relation_size(c.oid)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s AND c.relname=%s''', (domain,NAME)).fetchone()
    return None if row is None else dict(zip(['oid','kind','populated','definition','bytes'],row))


def ensure_report(db, domain='z1', create=True):
    """Reuse only the exact expected definition; never replace another object."""
    ddl = extension_sql('create_financial_report',domain)
    prefix = f'CREATE MATERIALIZED VIEW {ident(domain)}.{NAME} AS'
    suffix = 'WITH NO DATA;'
    if not ddl.startswith(prefix) or not ddl.endswith(suffix):
        raise RuntimeError('Unexpected materialized-view DDL format')
    select = ddl[len(prefix):-len(suffix)].strip()
    existing = report_metadata(db,domain)
    if existing and existing['kind'] != 'm':
        raise RuntimeError(f'{domain}.{NAME} already exists and is not a materialized view')
    if existing is None and not create:
        raise RuntimeError('Financial report is absent; run extend_z1.py first')
    # Let PostgreSQL canonicalize SQL instead of comparing hand-formatted strings.
    # This temporary ordinary view is only a definition check, removed immediately.
    db.execute('CREATE TEMP VIEW z1_r2_expected AS '+select)
    expected = db.execute("SELECT pg_get_viewdef('pg_temp.z1_r2_expected'::regclass,true)").fetchone()[0]
    if existing is None:
        db.execute(ddl)
        existing = report_metadata(db,domain)
        created = True
    else:
        created = False
    if existing['definition'] != expected:
        raise RuntimeError('Existing financial report definition differs; inspect it before rebuilding')
    db.execute('DROP VIEW pg_temp.z1_r2_expected')
    return created


def full_result(db, sql):
    """Bounded whole-result hash; all grouping keys, counts and exact sums participate."""
    digest, count, totals = hashlib.sha256(), 0, {}
    def add(value):
        encoded = json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        digest.update(struct.pack('>Q',len(encoded))+encoded)
    with db.cursor(name='z1_r2_result') as cursor:
        cursor.execute(sql)
        columns = [column.name for column in cursor.description]
        add(columns)
        while rows := cursor.fetchmany(2000):
            for row in rows:
                values = dict(zip(columns,row))
                if values['transaction_records'] != sum(values[key] for key in
                    ('valid_amount_records','missing_amount_records','invalid_amount_records')):
                    raise RuntimeError('Financial state counts do not reconcile')
                if values['currency'] is None and values['amount_sum'] is not None:
                    raise RuntimeError('Unknown currencies must not be summed')
                for key in columns[2:9]:
                    totals[key] = totals.get(key,0) + values[key]
                add([typed(value) for value in row])
                count += 1
    return dict(rows=count,columns=columns,sha256=digest.hexdigest(),totals=totals)


def compare_report(db, domain='z1'):
    # Q4 supports optional filters; this report always represents ALL groups.
    for setting in ('z1.currency','z1.merchant'):
        db.execute('SELECT set_config(%s,%s,true)', (setting,''))
    direct = full_result(db,query_sql('Q4',domain))
    stored = full_result(db,extension_sql('read_financial_report',domain))
    return dict(direct=direct,materialized=stored,equal=direct==stored)


def refresh_report(db, domain='z1'):
    started = perf_counter()
    db.execute(extension_sql('refresh_financial_report',domain))
    return perf_counter()-started


def create_synthetic_source(db, domain):
    """Only explicit, separate demonstration/test namespaces may contain fixtures."""
    if not domain.startswith(('z1_r2_demo_','z1_r2_test_')):
        raise ValueError('Synthetic records require a separate R2 demo/test schema')
    d = ident(domain)
    db.execute(f'CREATE SCHEMA {d}')
    db.execute(f'''CREATE TABLE {d}.financial_transactions (
        source_id BIGINT PRIMARY KEY, currency TEXT, search_value TEXT, amount NUMERIC,
        amount_state TEXT NOT NULL CHECK(amount_state IN ('valid','missing','invalid')))''')
    db.execute(f'''INSERT INTO {d}.financial_transactions VALUES
        (1,'USD','demo merchant',10.25,'valid'),
        (2,'USD','demo merchant',-0.25,'valid'),
        (3,'USD','demo merchant',NULL,'missing'),
        (4,'EUR','demo merchant',7,'valid'),
        (5,NULL,'unknown merchant',100,'valid'),
        (6,'USD','missing only',NULL,'missing'),
        (7,'USD','demo merchant',NULL,'invalid'),
        (8,'USD','demo merchant',0,'valid')''')


def demo_staleness(db):
    domain = 'z1_r2_demo_'+uuid.uuid4().hex[:12]
    d = ident(domain)
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        create_synthetic_source(db,domain)
        ensure_report(db,domain)
        refresh_report(db,domain)
        initial = compare_report(db,domain)
        initial_groups = db.execute(extension_sql('read_financial_report',domain)).fetchall()
        # Change a value, add a negative amount, and remove the EUR group. Total
        # source record count stays eight: count(*) alone cannot prove freshness.
        db.execute(f'UPDATE {d}.financial_transactions SET amount=15.25 WHERE source_id=1')
        db.execute(f"INSERT INTO {d}.financial_transactions VALUES (9,'USD','demo merchant',-2,'valid')")
        db.execute(f'DELETE FROM {d}.financial_transactions WHERE source_id=4')
        stale = compare_report(db,domain)
        refresh_report(db,domain)
        refreshed = compare_report(db,domain)
        refreshed_groups = db.execute(extension_sql('read_financial_report',domain)).fetchall()
        refresh_report(db,domain)
        repeated = compare_report(db,domain)
        # A failed update+refresh transaction must preserve both previous images.
        try:
            with db.transaction():
                db.execute(f'UPDATE {d}.financial_transactions SET amount=999 WHERE source_id=1')
                refresh_report(db,domain)
                raise RuntimeError('synthetic interruption after refresh')
        except RuntimeError as exc:
            if str(exc) != 'synthetic interruption after refresh':
                raise
        rolled_back = compare_report(db,domain)
        if not (initial['equal'] and not stale['equal'] and refreshed['equal']
                and refreshed==repeated==rolled_back and stale['materialized']==initial['materialized']):
            raise RuntimeError('Synthetic stale/refresh/repeat/rollback demonstration failed')
        result = dict(executed_at=now(),synthetic_schema=domain,
            source_records_before=initial['direct']['totals']['transaction_records'],
            source_records_after=refreshed['direct']['totals']['transaction_records'],
            initial=initial,stale=stale,refreshed=refreshed,
            repeated=repeated,rolled_back=rolled_back,
            initial_groups=[dict(zip(initial['direct']['columns'],row)) for row in initial_groups],
            refreshed_groups=[dict(zip(refreshed['direct']['columns'],row)) for row in refreshed_groups],
            corpus_modified=False,cleanup='Synthetic schema dropped in the same transaction')
        db.execute(f'DROP SCHEMA {d} CASCADE')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-only',action='store_true',help='Compare the existing stored report with current Q4 without refreshing')
    mode.add_argument('--demo',action='store_true',help='Show stale/refresh/repeat/rollback behavior in a separate synthetic schema; no dataset required')
    args = parser.parse_args()
    with connect() as db:
        if args.demo:
            report = demo_staleness(db)
            write_json(PROJECT_ROOT/'evidence'/'extension-staleness.json',report)
            print(f"Synthetic source stayed at {report['source_records_after']} records; changed sums and groups made the stored report stale.")
            print('Refresh restored complete equality; repeat and failed-update/refresh rollback passed.')
            print('Synthetic schema removed; saved evidence/extension-staleness.json.')
            return
        manifest = require_full_load(db)
        env = environment(db)
        accounting = source_accounting(db)
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            db.execute("SET LOCAL lock_timeout='5s'")
            created = ensure_report(db,create=not args.check_only)
            if not report_metadata(db)['populated'] and args.check_only:
                raise RuntimeError('Financial report is unpopulated; run extend_z1.py first')
            refresh_seconds = None if args.check_only else refresh_report(db)
            comparison = compare_report(db)
            if not comparison['equal']:
                raise RuntimeError('Financial report differs from current Q4; run extend_z1.py to refresh')
            if comparison['direct']['totals']['transaction_records'] != accounting['financial_transactions']['accepted']:
                raise RuntimeError('Financial report does not account for the full financial layer')
            report = dict(verified_at=now(),revision=manifest['revision'],repo_id=manifest['repo_id'],
                content_identity=db.execute('SELECT content_identity FROM z1_audit.load_state').fetchone()[0],
                environment=env,source_accounting=accounting['financial_transactions'],
                sql_file_sha256=hashlib.sha256(SQL_PATH.read_bytes()).hexdigest(),
                created_this_invocation=created,refresh_seconds=refresh_seconds,
                definition=extension_sql('create_financial_report'),refresh_sql=extension_sql('refresh_financial_report'),
                direct_sql=query_sql('Q4'),read_sql=extension_sql('read_financial_report'),
                comparison=comparison,materialized_view=report_metadata(db),
                hash_format='Section-7 SHA256: length-prefixed compact UTF-8 JSON columns and every ordered typed row; no LIMIT or deduplication',
                refresh_policy='Explicit full refresh after full validated import; same snapshot as Q4 verification; no automatic/incremental refresh')
        if not args.check_only:
            write_json(PROJECT_ROOT/'evidence'/'extension.json',report)
        print(f"R2 report matches full Q4: {comparison['direct']['rows']:,} groups, "
            f"{comparison['direct']['totals']['transaction_records']:,} transactions.")
        print('Complete-result SHA256: '+comparison['direct']['sha256'])
        if not args.check_only:
            print('Saved evidence/extension.json; materialized report is populated.')


if __name__=='__main__':
    main()

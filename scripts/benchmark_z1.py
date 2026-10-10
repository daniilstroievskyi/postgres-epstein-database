"""Section 8: one warm-up and three timed Q6 JSON runs, before/after one index."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import struct
from statistics import median
from time import perf_counter

import psycopg

if __package__:
    from .z1_db import connect
    from .z1_model import ident
    from .z1_workload import INDEX_SPECS, PROJECT_ROOT, environment, extension_ready, index_metadata, now, query_sql, require_full_load, source_accounting, typed, write_json
else:
    from z1_db import connect
    from z1_model import ident
    from z1_workload import INDEX_SPECS, PROJECT_ROOT, environment, extension_ready, index_metadata, now, query_sql, require_full_load, source_accounting, typed, write_json

QUERY = 'Q6_JSON'
INDEX = 'documents_email_object_gin'
EXPECTATION = (
    'The JSONB @> containment query should benefit from the partial jsonb_path_ops '
    'GIN index: it can locate subject JSON null within the sparse valid-object subset '
    'instead of scanning the full documents table. This is a hypothesis, not a forced plan.'
)
HASH_FORMAT = (
    'SHA256: columns as compact UTF-8 JSON, then every ordered row as compact UTF-8 '
    'JSON of typed values; each JSON block is prefixed by its 8-byte big-endian byte '
    'length. Types: null, bool, int (decimal string), text, float64 (IEEE hex), '
    'decimal (text). No deduplication or LIMIT; ORDER BY document source_id.'
)


def fingerprint_result(columns, rows):
    """Same format as section 7; called only AFTER the query timer stops."""
    digest = hashlib.sha256()
    for value in [columns] + [[typed(v) for v in row] for row in rows]:
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        digest.update(struct.pack('>Q', len(encoded)) + encoded)
    return dict(rows=len(rows), sha256=digest.hexdigest())


def timed_query(db, sql):
    # This fixed drill-down returns a small complete result (20 rows in this corpus).
    # An unnamed psycopg cursor receives the result normally, without DECLARE/FETCH.
    with db.cursor() as cursor:
        started = perf_counter()
        # Avoid psycopg auto-preparing this statement after five executions: both
        # variants must use the same client protocol rather than switching mid-run.
        cursor.execute(sql, prepare=False)
        rows = cursor.fetchall()
        seconds = perf_counter() - started
        columns = [column.name for column in cursor.description]
    return dict(seconds=seconds, **fingerprint_result(columns, rows)), columns, rows


def run_variant(db, sql):
    plan = db.execute('EXPLAIN (FORMAT JSON) ' + sql).fetchone()[0]
    plan_text = '\n'.join(row[0] for row in db.execute('EXPLAIN ' + sql))
    warmup, columns, rows = timed_query(db, sql)
    runs = [timed_query(db, sql)[0] for _ in range(3)]
    expected = {key: warmup[key] for key in ('rows', 'sha256')}
    if any({key: run[key] for key in expected} != expected for run in runs):
        raise RuntimeError('Complete result changed between repetitions')
    return dict(warmup=warmup, measured=runs,
        median_seconds=median(run['seconds'] for run in runs), columns=columns,
        document_source_ids=[row[0] for row in rows], plan=plan, plan_text=plan_text)


def inventory(db, domain, audit):
    """Check all constraints, FK triggers and other indexes, without scanning data."""
    constraints = db.execute('''SELECT c.oid,n.nspname,t.relname,c.conname,c.contype,
        c.convalidated,c.conenforced,pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname IN (%s,%s) ORDER BY c.oid''', (domain,audit)).fetchall()
    triggers = db.execute('''SELECT t.oid,t.tgconstraint,t.tgenabled
        FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=r.relnamespace
        WHERE n.nspname IN (%s,%s) AND t.tgconstraint<>0 ORDER BY t.oid''', (domain,audit)).fetchall()
    if not constraints or not all(row[5] and row[6] for row in constraints):
        raise RuntimeError('Inactive or unvalidated constraint')
    if any(row[2] not in ('O','A') for row in triggers):
        raise RuntimeError('A constraint trigger is disabled for normal writes')
    if db.execute('SHOW session_replication_role').fetchone()[0] != 'origin':
        raise RuntimeError('Constraint enforcement requires normal replication role')
    indexes = db.execute('''SELECT n.nspname,t.relname,c.relname,c.oid,
        pg_get_indexdef(c.oid),i.indisvalid,i.indisready,i.indisunique,i.indisprimary,
        pg_relation_size(c.oid)
        FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN (%s,%s) ORDER BY n.nspname,c.relname''', (domain,audit)).fetchall()
    if not all(row[5] and row[6] for row in indexes):
        raise RuntimeError('An existing index is inactive')
    return dict(constraints=constraints, triggers=triggers,
        other_indexes=[row for row in indexes if row[:3] != (domain,'documents',INDEX)])


def compare(db, domain='z1', audit='z1_audit'):
    """DDL and both variants share one snapshot; rollback restores the original index."""
    sql = query_sql(QUERY, domain)
    # Validate identifiers before using them in LOCK/DROP statements.
    d, _ = ident(domain), ident(audit)
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        db.execute("SET LOCAL lock_timeout='5s'")
        db.execute(f'LOCK TABLE {d}.documents IN SHARE MODE')
        initial = inventory(db, domain, audit)
        for name in INDEX_SPECS:
            if index_metadata(db, name, domain) is None:
                raise RuntimeError('First run setup_z1_queries.py: all section-7 indexes must exist')
        original = index_metadata(db, INDEX, domain)
        counts = db.execute(f'''SELECT count(*),count(*) FILTER (WHERE {original['predicate']})
            FROM {d}.documents''').fetchone()
        print('Before index: one warm-up, then three measured runs...', flush=True)
        db.execute(f'DROP INDEX {d}.{ident(INDEX)}')
        if index_metadata(db, INDEX, domain) is not None:
            raise RuntimeError('Benchmark index was not removed')
        if inventory(db, domain, audit) != initial:
            raise RuntimeError('Another index or constraint changed before baseline')
        before = run_variant(db, sql)
        print('Rebuilding the same index...', flush=True)
        started = perf_counter()
        db.execute(original['ddl'])
        build_seconds = perf_counter() - started
        rebuilt = index_metadata(db, INDEX, domain)
        if rebuilt is None or rebuilt['ddl'] != original['ddl']:
            raise RuntimeError('Rebuilt index differs from the original definition')
        print('After index: one warm-up, then three measured runs...', flush=True)
        after = run_variant(db, sql)
        if before['columns'] != after['columns'] or any(
            before['warmup'][key] != after['warmup'][key] for key in ('rows','sha256')):
            raise RuntimeError('Before/after complete results differ')
        if inventory(db, domain, audit) != initial:
            raise RuntimeError('Another index or constraint changed during comparison')
        constraint_bytes = json.dumps([initial['constraints'],initial['triggers']], separators=(',',':')).encode()
        report = dict(query=QUERY, expectation=EXPECTATION, sql=sql,
            sql_sha256=hashlib.sha256(sql.encode('utf-8')).hexdigest(),
            parameters=dict(subject_containment='{"subject":null}',email_fields_state='valid',json_type='object'),
            target_rows=counts[0], indexed_rows=counts[1], hash_format=HASH_FORMAT,
            index=dict(name=INDEX,original=original,rebuilt=rebuilt,build_seconds=build_seconds),
            before=before,after=after,result_equivalence=True,
            controls=dict(same_data_snapshot='Single REPEATABLE READ transaction; no INSERT/UPDATE/DELETE',
                import_exclusion='z1-etl advisory lock acquired by main',
                constraints_active_validated=True,foreign_keys=sum(row[4]=='f' for row in initial['constraints']),
                constraint_and_trigger_sha256=hashlib.sha256(constraint_bytes).hexdigest(),
                other_indexes_unchanged=True,other_indexes=initial['other_indexes'],
                planner_forced=False,client_auto_prepare=False,analyze_or_cache_reset_or_restart=False,
                repetitions_per_variant=dict(warmup=1,measured=3)),
            timing='perf_counter immediately before cursor.execute(SQL) through cursor.fetchall(); '
                'same unnamed psycopg cursor type with prepare=False for both variants; hashing, plans, index DDL, '
                'transaction setup/commit, rendering and file writes are outside query timing')
    # Successful commit leaves the index active. Any exception above rolls back DROP/CREATE.
    return report


def write_report(report):
    before, after = report['before'], report['after']
    env = report['environment']
    lines = [
        '# Section 8: one full-input index comparison', '',
        f"Recorded at {report['executed_at']}. Query **Q6_JSON**, the explicit-JSON-null drill-down of Q6.",
        'This is one benchmark of the existing own question, using the full documents layer.', '',
        '## Reproduce', '', 'Run after the complete import, validation and section-7 setup:', '',
        '```powershell', r'.\.venv\Scripts\python.exe scripts/benchmark_z1.py', '```', '',
        'The command verifies all frozen files offline and requires a completed full import. It obtains',
        'the importer advisory lock, changes only `z1.documents_email_object_gin`, and leaves it active',
        'when finished. DROP, CREATE and both variants run in one transaction: failure rolls back the',
        'index changes. Use an idle database; the index DDL locks the documents table during the run.',
        'Repeat the command to regenerate the evidence and this report; timings may change.', '',
        '## Expectation and fixed workload', '', report['expectation'], '',
        f"Frozen repository: `{report['repo_id']}`, revision `{report['revision']}`.",
        f"Source documents: **{report['source_accounting']['documents']['read']:,}**; accepted target documents: "
            f"**{report['target_rows']:,}**; quarantined: **{report['source_accounting']['documents']['quarantined']:,}**.",
        f"The index covers **{report['indexed_rows']:,}** valid objects. No corpus subset or copy is created.", '',
        'Fixed parameters: valid JSON objects containing `{"subject":null}`. No session inputs,',
        'LIMIT, ranking or parameters change between variants. SQL NULL and absent subject keys do',
        'not meet this containment condition. The output includes original document IDs and orders by',
        'the unique `source_id`, so ordering has no unresolved ties.', '',
        'Exact SQL, unchanged from `sql/queries.sql`:', '', '```sql', report['sql'], '```', '',
        'Exact index DDL captured from PostgreSQL and used for rebuilding:', '',
        '```sql', report['index']['rebuilt']['ddl']+';', '```', '',
        '## Environment and controls', '',
        f"- PostgreSQL: `{env['server']}`.",
        '- Extensions: '+', '.join(f'`{name} {version}`' for name,version in env['extensions'].items())+'.',
        f"- Client: Python {env['python']}, psycopg {env['psycopg']}; {env['client_os']}; "
            f"{env['client_logical_cpus']} client logical CPUs.",
        '- Docker configuration: `postgres:18.3-bookworm`, local TCP connection.',
        '- Database locale: '+', '.join(env['database_locale'])+'.',
    ]
    for name, setting in env['settings'].items():
        lines.append(f"- `{name}`: {setting['value']} {setting['unit'] or ''}.".replace(' .','.'))
    if env['resource_note']:
        lines.append('- Resource note (recorded by the operator): '+env['resource_note'])
    lines += ['',
        'Both variants use the same REPEATABLE READ snapshot and client; the script performs no',
        f"data writes. All **{report['controls']['foreign_keys']} foreign keys** and all PK/UNIQUE/CHECK constraints stay active",
        'and validated. Catalog comparison verifies unchanged constraint definitions/enforcement,',
        'FK trigger states, and every other index definition, identity, readiness and size.',
        'No concurrent project import, planner forcing, ANALYZE, cache flush or restart occurs.',
        'Client auto-preparation is disabled in both variants to keep the execution protocol fixed.',
        'The target index is absent in the baseline and recreated with its exact original DDL.', '',
        '## Complete-result equivalence', '',
        f"All eight executions (two warm-ups and six measured runs) returned **{before['warmup']['rows']:,} rows**",
        'and the same complete-result SHA-256:', '',
        '```text', before['warmup']['sha256'], '```', '', report['hash_format'], '',
        'Column names and every output value are included, including document IDs and repeated rows.',
        'The hash is computed after each timer stops. It is not a count-only or preview comparison.',
        'All returned document IDs are also saved in the JSON evidence.', '',
        '## Warm measurements', '', report['timing']+'.', '',
        'One warm-up followed by three measured runs per variant, in the order before then after.', '',
        '| Variant | Warm-up (s, excluded) | Run 1 (s) | Run 2 (s) | Run 3 (s) | Median (s) |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for label, variant in [('Before: index absent',before),('After: index present',after)]:
        times = [variant['warmup']['seconds']] + [run['seconds'] for run in variant['measured']] + [variant['median_seconds']]
        lines.append('| '+label+' | '+' | '.join(f'{seconds:.6f}' for seconds in times)+' |')
    lines += ['', '## Basic plans', '', 'Before:', '', '```text', before['plan_text'], '```', '',
        'After:', '', '```text', after['plan_text'], '```', '',
        'These are basic EXPLAIN plans, not EXPLAIN ANALYZE. The chosen access and any sorting are',
        'shown above; no planner method was disabled to make the index appear.', '',
        '## Interpretation and costs', '']
    ratio = before['median_seconds']/after['median_seconds']
    lines += [
        f"The observed median changed from **{before['median_seconds']:.6f} s** to "
            f"**{after['median_seconds']:.6f} s** (before/after ratio **{ratio:.2f}**).",
        'The baseline reads the documents relation to evaluate the predicate. With the index, the',
        'planner can use a bitmap index lookup for `@>`, followed by heap checks and source-ID sorting.',
        'The partial predicate excludes missing values and non-object JSON from the index while the',
        'query still runs against the complete table. `jsonb_path_ops` supports this containment',
        'operator; it does not provide the `?` key-existence lookup used elsewhere in Q6.', '',
        f"The rebuilt index occupies **{report['index']['rebuilt']['bytes']:,} bytes** "
            f"({report['index']['rebuilt']['bytes']/1024:.0f} KiB). Its separate build took "
            f"**{report['index']['build_seconds']:.6f} s**; this is excluded from query timings.",
        'Initial creation scans the table and evaluates the predicate even though few rows qualify.',
        'Later writes evaluate the partial predicate; qualifying inserts/updates maintain GIN',
        'entries, and deletes/changed entries require later index cleanup. These write costs are',
        'explained, not measured as another performance experiment.', '',
        'The three warm repetitions describe this local corpus, query and environment. Building',
        'the index may also warm caches; this prescribed warm comparison does not isolate all cache',
        'effects or establish general production performance.', '',
        'Primary references: [JSONB operators and index classes](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING),',
        '[CREATE INDEX and locking](https://www.postgresql.org/docs/18/sql-createindex.html),',
        '[REPEATABLE READ](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-REPEATABLE-READ).', '',
        '## Synthetic safety checks', '',
        'The isolated tests in `tests/test_z1_queries_db.py` verify complete before/after equality,',
        'identity/multiplicity-sensitive hashes, unchanged other indexes/constraints, and rollback',
        'that restores the original index after a synthetic interruption. They use separate test',
        'schemas and never change the corpus. Run the whole suite with:', '',
        '```powershell', "$env:Z1_DB_TESTS='1'",
        r'.\.venv\Scripts\python.exe -m unittest discover -s tests -v',
        'Remove-Item Env:Z1_DB_TESTS', '```', '',
        'Actual complete-suite results: [benchmark-tests.json](../evidence/benchmark-tests.json).', '',
        'Evidence: [benchmark.json](../evidence/benchmark.json), which contains the',
        'before/after plans and timing results.',
    ]
    path = PROJECT_ROOT/'docs'/'benchmark.md'
    path.write_text('\n'.join(lines)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resource-note', default='', help='Optional observed CPU/RAM or Docker resource limits, saved in evidence')
    args = parser.parse_args()
    executed_at = now()
    with connect() as db:
        manifest = require_full_load(db)
        extension_ready(db)
        env = dict(environment(db), psycopg=psycopg.__version__, client_os=platform.platform(),
            client_logical_cpus=os.cpu_count(), resource_note=args.resource_note)
        accounting = source_accounting(db)
        report = compare(db)
        if report['target_rows'] != accounting['documents']['accepted']:
            raise RuntimeError('Target document count differs from full import accounting')
        report.update(executed_at=executed_at,completed_at=now(),repo_id=manifest['repo_id'],
            revision=manifest['revision'],environment=env,source_accounting=accounting,
            content_identity=db.execute('SELECT content_identity FROM z1_audit.load_state').fetchone()[0])
        if index_metadata(db, INDEX) != report['index']['rebuilt']:
            raise RuntimeError('Index was not preserved after commit')
    write_json(PROJECT_ROOT/'evidence'/'benchmark.json', report)
    for label in ('before','after'):
        (PROJECT_ROOT/'evidence'/f'benchmark-{label}-plan.txt').write_text(report[label]['plan_text']+'\n', encoding='utf-8')
    write_report(report)
    print(f"Complete results match: {report['before']['warmup']['rows']:,} rows", flush=True)
    print(f"Median before: {report['before']['median_seconds']:.6f} s; after: {report['after']['median_seconds']:.6f} s", flush=True)
    print('Saved docs/benchmark.md and evidence/benchmark*.json/txt; index remains active', flush=True)


if __name__ == '__main__':
    main()

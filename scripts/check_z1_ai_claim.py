"""Section 10: refine an actual AI claim using separate synthetic financial data."""
from __future__ import annotations
import argparse
import uuid

if __package__:
    from .extend_z1 import compare_report, create_synthetic_source, ensure_report, refresh_report
    from .z1_db import connect
    from .z1_model import ident
    from .z1_workload import PROJECT_ROOT, now, write_json
else:
    from extend_z1 import compare_report, create_synthetic_source, ensure_report, refresh_report
    from z1_db import connect
    from z1_model import ident
    from z1_workload import PROJECT_ROOT, now, write_json

CLAIM = 'Source changes leave the stored report stale until refresh.'
REFINED_CLAIM = (
    'The stored materialized rows are not automatically recomputed. Source changes '
    'that alter the aggregate query result make the report result stale. Changes to '
    'unused columns, or offsetting changes preserving all reported aggregates, may '
    'leave the current report result equal without a refresh.'
)


def check_claim(db):
    domain = 'z1_r2_demo_ai_'+uuid.uuid4().hex[:12]
    d = ident(domain)
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        create_synthetic_source(db,domain)
        db.execute(f'ALTER TABLE {d}.financial_transactions ADD COLUMN demo_note TEXT')
        ensure_report(db,domain)
        refresh_report(db,domain)
        stages = {}

        def capture(label):
            result = compare_report(db,domain)
            # Record actual source values so an unchanged report cannot be mistaken
            # for an UPDATE that failed to change anything.
            observed = db.execute(f'''SELECT source_id,amount,demo_note
                FROM {d}.financial_transactions WHERE source_id IN (1,2) ORDER BY source_id''').fetchall()
            result['source_observations'] = [dict(source_id=row[0],amount=row[1],note=row[2]) for row in observed]
            stages[label] = result
            return result

        initial = capture('initial')
        db.execute(f'UPDATE {d}.financial_transactions SET demo_note=%s WHERE source_id=1',
            ('Unused description changed; financial aggregates are unchanged',))
        metadata = capture('unused_column_changed')
        db.execute(f'''UPDATE {d}.financial_transactions
            SET amount=amount+CASE source_id WHEN 1 THEN 5 ELSE -5 END
            WHERE source_id IN (1,2)''')
        cancelling = capture('offsetting_amount_changes')
        db.execute(f'UPDATE {d}.financial_transactions SET amount=amount+1 WHERE source_id=1')
        stale = capture('aggregate_changed')
        refresh_report(db,domain)
        refreshed = capture('after_refresh')
        if not (initial['equal'] and metadata['equal'] and cancelling['equal']
                and not stale['equal'] and refreshed['equal']
                and initial['direct']==metadata['direct']==cancelling['direct']
                and stale['materialized']==initial['materialized']
                and stale['direct']==refreshed['direct']):
            raise RuntimeError('The expected claim counterexample was not observed')
        if metadata['source_observations']==initial['source_observations'] or cancelling['source_observations']==metadata['source_observations']:
            raise RuntimeError('The counterexample did not actually change source values')
        report = dict(verified_at=now(),original_claim=CLAIM,disposition='substantially refined',
            refined_claim=REFINED_CLAIM,stages=stages,synthetic_schema=domain,
            corpus_modified=False,schema_removed=True,
            note='Result equality concerns Q4 aggregates, not equality of every underlying source field or snapshot age.',
            primary_sources=['https://www.postgresql.org/docs/18/rules-materializedviews.html',
                'https://www.postgresql.org/docs/18/sql-refreshmaterializedview.html'])
        db.execute(f'DROP SCHEMA {d} CASCADE')
    return report


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    with connect() as db:
        report = check_claim(db)
    write_json(PROJECT_ROOT/'evidence'/'ai-claim-check.json',report)
    for name,stage in report['stages'].items():
        print(f'{name}: current aggregate equals stored report = {stage["equal"]}')
    print('Actual AI claim substantially refined; synthetic schema removed; corpus unchanged.')
    print('Saved evidence/ai-claim-check.json.')


if __name__=='__main__':
    main()

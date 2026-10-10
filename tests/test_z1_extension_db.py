"""R2 semantics and repeat safety on synthetic schemas, with no corpus writes."""
import os
import unittest
import uuid
from decimal import Decimal

from scripts.z1_db import connect
from scripts.z1_model import ident
from scripts.extend_z1 import compare_report, create_synthetic_source, demo_staleness, ensure_report, report_metadata, refresh_report


@unittest.skipUnless(os.environ.get('Z1_DB_TESTS')=='1','Set Z1_DB_TESTS=1 for isolated database tests')
class ExtensionDatabaseTest(unittest.TestCase):
    def test_stale_full_results_refresh_repeat_and_failed_transaction(self):
        with connect() as db:
            report=demo_staleness(db)
            self.assertIsNone(db.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s',(report['synthetic_schema'],)).fetchone())
        initial=report['initial']
        stale=report['stale']
        refreshed=report['refreshed']
        self.assertTrue(initial['equal'])
        self.assertFalse(stale['equal'])
        self.assertEqual(initial['direct']['totals']['transaction_records'],8)
        self.assertEqual(stale['direct']['totals']['transaction_records'],8)
        self.assertEqual(stale['materialized'],initial['materialized'])
        self.assertEqual(refreshed,report['repeated'])
        self.assertEqual(refreshed,report['rolled_back'])
        initial_usd=next(row for row in report['initial_groups'] if row['currency']=='USD' and row['merchant_search_value']=='demo merchant')
        refreshed_usd=next(row for row in report['refreshed_groups'] if row['currency']=='USD' and row['merchant_search_value']=='demo merchant')
        self.assertEqual(initial_usd['amount_sum'],Decimal('10.00'))
        self.assertEqual(refreshed_usd['amount_sum'],Decimal('13.00'))
        self.assertEqual(refreshed_usd['negative_amount_records'],2)
        self.assertTrue(any(row['currency']=='EUR' for row in report['initial_groups']))
        self.assertFalse(any(row['currency']=='EUR' for row in report['refreshed_groups']))
        self.assertTrue(all(row['amount_sum'] is None for row in report['initial_groups']
            if row['currency'] is None or row['merchant_search_value']=='missing only'))

    def test_existing_report_reused_and_session_filters_do_not_change_scope(self):
        domain='z1_r2_test_'+uuid.uuid4().hex[:12]
        with connect() as db, db.transaction():
            create_synthetic_source(db,domain)
            self.assertTrue(ensure_report(db,domain))
            self.assertFalse(report_metadata(db,domain)['populated'])
            refresh_report(db,domain)
            oid=report_metadata(db,domain)['oid']
            first=compare_report(db,domain)
            self.assertFalse(ensure_report(db,domain))
            refresh_report(db,domain)
            db.execute("SELECT set_config('z1.currency','EUR',true),set_config('z1.merchant','unrelated filter',true)")
            second=compare_report(db,domain)
            self.assertEqual(first,second)
            self.assertTrue(second['equal'])
            self.assertEqual(second['direct']['rows'],4)
            self.assertEqual(report_metadata(db,domain)['oid'],oid)
            db.execute(f'DROP SCHEMA {ident(domain)} CASCADE')

    def test_rejects_wrong_object_or_changed_definition_without_replacing_it(self):
        domain='z1_r2_test_'+uuid.uuid4().hex[:12]
        d=ident(domain)
        with connect() as db, db.transaction():
            create_synthetic_source(db,domain)
            db.execute(f'CREATE TABLE {d}.financial_report(marker TEXT)')
            with db.transaction():
                with self.assertRaisesRegex(RuntimeError,'not a materialized view'):
                    ensure_report(db,domain)
            self.assertEqual(report_metadata(db,domain)['kind'],'r')
            db.execute(f'DROP TABLE {d}.financial_report')
            db.execute(f'CREATE MATERIALIZED VIEW {d}.financial_report AS SELECT count(*) AS wrong_result FROM {d}.financial_transactions')
            original=report_metadata(db,domain)
            with self.assertRaisesRegex(RuntimeError,'definition differs'):
                with db.transaction():
                    ensure_report(db,domain)
            self.assertEqual(report_metadata(db,domain),original)
            db.execute(f'DROP SCHEMA {d} CASCADE')


if __name__=='__main__':
    unittest.main()

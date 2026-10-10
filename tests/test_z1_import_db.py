"""Opt-in integration tests use only temporary, explicitly named synthetic schemas."""
import os
import unittest
import uuid
import psycopg
from scripts.z1_db import connect
from scripts.z1_model import ORDER, source_columns, JSON_FIELDS, DATES, TIMES
from scripts.z1_transform import content_identity
from scripts.import_z1 import initialize,start_run,process_batch,committed_end,InjectedFailure
from scripts.validate_z1 import validate,domain_fingerprints


def fixture_record(layer,source_id=1):
    r={n:(source_id if n=='id' else 1 if t in ('BIGINT','INTEGER') else False if t=='BOOLEAN' else 1.25 if t=='DOUBLE PRECISION' else 'synthetic') for n,t in source_columns(layer)}
    for f in DATES.get(layer,[]): r[f]='2020-01-01'
    for f in TIMES.get(layer,[]): r[f]='2020-01-01T00:00:00'
    for f,shape in JSON_FIELDS.get(layer,{}).items(): r[f]='[]' if shape=='array' else '{}'
    if 'file_key' in r: r['file_key']='synthetic-doc'
    if 'run_id' in r: r['run_id']='synthetic-run'
    if layer=='documents': r.update(full_text='synthetic',char_count=9,date='2020-02-30',email_fields='{bad')
    if layer=='chunks': r.update(chunk_index=0,char_start=0,char_end=9,token_count=1,content='synthetic')
    if layer=='persons': r['aliases']='["Alias","Alias"]'
    if layer=='curated_docs': r['also_appears_as']='["synthetic-doc","absent-doc"]'
    if layer in ('derived_events','financial_transactions'): r['currency']='USD'
    if layer=='financial_transactions': r['extraction_confidence']=None
    return r


@unittest.skipUnless(os.environ.get('Z1_DB_TESTS')=='1','Set Z1_DB_TESTS=1 for isolated database tests')
class DatabaseImportTest(unittest.TestCase):
    def setUp(self):
        suffix=uuid.uuid4().hex[:12]
        self.domain='z1_test_'+suffix;self.audit=self.domain+'_audit'
        self.db=connect()
        self.manifest={"repo_id":"synthetic-fixture","revision":"synthetic-v1","files":[{"path":layer,"layer":layer,"sha256":"0"*64,"bytes":0,"row_count":1} for layer in ORDER]}
        self.identity=initialize(self.db,self.manifest,self.domain,self.audit)
        self.run=start_run(self.db,self.identity,'synthetic',{},self.audit)
        self.files={r[1]:r[0] for r in self.db.execute(f'SELECT file_id,layer FROM {self.audit}.source_files')}
        self.original={}

    def tearDown(self):
        # Exact random test schema names created by setUp; never domain z1/public/archive.
        self.assertTrue(self.domain.startswith('z1_test_'))
        self.db.execute(f'DROP SCHEMA {self.domain} CASCADE')
        self.db.execute(f'DROP SCHEMA {self.audit} CASCADE')
        self.db.close()

    def batch(self,layer,rows,**kwargs):
        for n,r in rows: self.original[(self.files[layer],n)]=r
        return process_batch(self.db,layer,self.files[layer],rows,self.run,self.domain,self.audit,
            source_lookup=lambda f,n:self.original[(f,n)],**kwargs)

    def test_full_fixture_validation_and_database_fk_rejection(self):
        for layer in ORDER: self.batch(layer,[(1,fixture_record(layer))])
        report=validate(self.db,self.manifest,self.domain,self.audit)
        self.assertEqual(len(report['layers']),13)
        self.assertEqual(report['derived']['person_aliases']['actual'],2)
        self.assertEqual(report['derived']['curated_document_links']['actual'],2)
        states=self.db.execute(f'SELECT date_state,email_fields_state FROM {self.domain}.documents').fetchone()
        self.assertEqual(states,('invalid','invalid'))
        self.assertEqual(self.db.execute(f'SELECT document_match_status,document_id FROM {self.domain}.mentions').fetchone(),('namespace_unverified',None))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation),self.db.transaction():
            self.db.execute(f'UPDATE {self.domain}.chunks SET document_id=999')

    def test_before_after_commit_recovery_and_no_duplicate_derived_rows(self):
        record=fixture_record('persons')
        with self.assertRaises(InjectedFailure): self.batch('persons',[(1,record)],fail_at='before_commit')
        self.db.close()
        self.db=connect()  # recovery observes a new connection, not cached client state
        self.assertEqual(committed_end(self.db,self.files['persons'],self.audit),0)
        self.assertEqual(self.db.execute(f'SELECT count(*) FROM {self.domain}.persons').fetchone()[0],0)
        with self.assertRaises(InjectedFailure): self.batch('persons',[(1,record)],fail_at='after_commit')
        self.db.close()
        self.db=connect()
        self.assertEqual(committed_end(self.db,self.files['persons'],self.audit),1)
        self.assertEqual(self.db.execute(f'SELECT count(*) FROM {self.domain}.person_aliases').fetchone()[0],2)

    def test_invalid_optional_reference_is_retained_and_json_states_stay_distinct(self):
        self.batch('derived_events',[(1,fixture_record('derived_events'))])
        unresolved=fixture_record('event_sources')
        self.assertEqual(self.batch('event_sources',[(1,unresolved)]),(1,1,0,0))
        self.assertEqual(self.db.execute(f'SELECT file_key,document_id,document_match_status FROM {self.domain}.event_sources').fetchone(),('synthetic-doc',None,'unmatched'))
        rows=[]
        for n,value in enumerate([None,'null','{}','{"subject":null}','[]'],1):
            record=fixture_record('documents',n)
            record.update(file_key='synthetic-'+str(n),email_fields=value)
            rows.append((n,record))
        self.assertEqual(self.batch('documents',rows),(5,5,0,0))
        states=self.db.execute(f"SELECT email_fields_state,email_fields IS NULL,email_fields='null'::jsonb,email_fields ? 'subject' FROM {self.domain}.documents ORDER BY source_id").fetchall()
        self.assertEqual(states[0][0:2],('missing',True))
        self.assertEqual(states[1][0:3],('json_null',False,True))
        self.assertFalse(states[2][3])
        self.assertTrue(states[3][3])
        self.assertEqual(states[4][0],'valid')

    def test_identical_repeat_conflict_and_missing_document_accounting(self):
        record=fixture_record('persons')
        self.assertEqual(self.batch('persons',[(1,record)]),(1,1,0,0))
        self.assertEqual(self.batch('persons',[(2,record)]),(1,0,0,1))
        conflicting=dict(record,canonical_name='different synthetic value')
        self.assertEqual(self.batch('persons',[(3,conflicting)]),(1,0,1,0))
        missing=fixture_record('chunks')
        self.assertEqual(self.batch('chunks',[(1,missing)]),(1,0,1,0))
        self.assertEqual(self.db.execute(f'SELECT count(*) FROM {self.domain}.person_aliases').fetchone()[0],2)


if __name__=='__main__': unittest.main()

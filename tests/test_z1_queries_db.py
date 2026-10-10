"""Section-7 semantics on synthetic schemas, never on the frozen corpus."""
import os
import unittest
import uuid
from decimal import Decimal, localcontext
from unittest.mock import patch

from scripts.z1_db import connect
from scripts.z1_model import ORDER, source_columns, ident
from scripts.import_z1 import initialize, start_run, process_batch
from scripts.z1_workload import DEFAULTS, INDEX_PATH, INDEX_SPECS, blocks, configure, index_metadata, query_sql
from scripts.benchmark_z1 import compare, fingerprint_result, inventory


@unittest.skipUnless(os.environ.get('Z1_DB_TESTS')=='1','Set Z1_DB_TESTS=1 for isolated database tests')
class QueryDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect() as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public')

    def setUp(self):
        self.domain='z1_query_test_'+uuid.uuid4().hex[:12]
        self.audit=self.domain+'_audit'
        self.db=connect()
        manifest=dict(repo_id='synthetic-queries',revision='synthetic-v1',files=[
            dict(path=layer,layer=layer,sha256='0'*64,bytes=0,row_count=100) for layer in ORDER])
        identity=initialize(self.db,manifest,self.domain,self.audit)
        self.run=start_run(self.db,identity,'synthetic',{},self.audit)
        self.files=dict((layer,file_id) for file_id,layer in self.db.execute(f'SELECT file_id,layer FROM {ident(self.audit)}.source_files'))
        self.positions={layer:0 for layer in ORDER}

    def tearDown(self):
        self.assertTrue(self.domain.startswith('z1_query_test_'))
        self.db.execute(f'DROP SCHEMA {ident(self.domain)} CASCADE')
        self.db.execute(f'DROP SCHEMA {ident(self.audit)} CASCADE')
        self.db.close()

    def add(self,layer,*overrides):
        rows=[]
        for values in overrides:
            self.positions[layer]+=1
            n=self.positions[layer]
            record={name:None for name,_ in source_columns(layer)}
            if 'id' in record: record['id']=n
            if layer=='documents': record.update(file_key='synthetic-'+str(n),dataset='synthetic',full_text='synthetic text',char_count=14)
            record.update(values)
            rows.append((n,record))
        result=process_batch(self.db,layer,self.files[layer],rows,self.run,self.domain,self.audit)
        self.assertEqual(result,(len(rows),len(rows),0,0))

    def select(self,query_name,**parameters):
        with self.db.transaction():
            configure(self.db,dict(DEFAULTS,**parameters))
            return self.db.execute(query_sql(query_name,self.domain)).fetchall()

    def create_index(self,name):
        self.db.execute(blocks(INDEX_PATH)[name].replace('"z1".',ident(self.domain)+'.'))
        return index_metadata(self.db,name,self.domain)

    def test_fts_word_stemming_and_identical_results_with_index(self):
        self.add('documents',dict(full_text='aircraft aircrafts aircraftmanship',char_count=34))
        self.add('chunks',*[dict(document_id=1,chunk_index=n,char_start=0,char_end=0,token_count=1,content=text)
            for n,text in enumerate(['aircraft aircraft','aircrafts','aircraftmanship',None])])
        before=self.select('Q1')
        self.assertEqual({r[0] for r in before},{1,2})
        self.create_index('chunks_fts_gin')
        self.assertEqual(before,self.select('Q1'))
        self.assertEqual(self.select('Q1',fts=''),[])  # empty web search has no lexemes

    def test_fuzzy_input_normalization_threshold_and_tie_order(self):
        self.add('persons',dict(canonical_name='Alice Smith'),dict(canonical_name='Alice Smith'),
                 dict(canonical_name='Alice Smyth'),dict(canonical_name='Bob Jones'))
        exact=self.select('Q2',name='  ＡＬＩＣＥ　Smith ',threshold=1.0)
        self.assertEqual([r[0] for r in exact],[1,2])
        self.assertTrue(all(r[-1]==1.0 for r in exact))
        self.assertTrue(all(r[4]=='alice smith' for r in exact))
        approximate=self.select('Q2',name='Alice Smith',threshold=0.3)
        self.assertEqual({r[0] for r in approximate},{1,2,3})
        self.create_index('persons_name_trgm_gin')
        self.assertEqual(approximate,self.select('Q2',name='Alice Smith',threshold=0.3))

    def test_two_directed_edges_preserve_parallel_paths_and_exclude_repeated_nodes(self):
        self.add('kg_entities',*[dict(id=n,name='Synthetic node '+str(n)) for n in range(1,5)])
        self.add('kg_relationships',*[dict(id=n,source_id=a,target_id=b) for n,a,b in
            [(11,1,2),(12,1,2),(13,2,3),(14,2,1),(15,2,2),(16,1,1),(17,2,4)]])
        self.assertEqual(self.select('Q3'),[(1,2,3,11,13),(1,2,4,11,17),(1,2,3,12,13),(1,2,4,12,17)])
        self.assertEqual(self.select('Q3',kg_start=999),[])

    def test_financial_precision_missing_invalid_sign_and_currency_separation(self):
        values=[dict(currency='USD',merchant_name='Merchant',amount=a) for a in [0.1,-0.125,0.0,None,float('nan')]]
        values += [dict(currency='EUR',merchant_name='Merchant',amount=100.0),
                   dict(currency=None,merchant_name='Merchant',amount=200.0),
                   dict(currency='??',merchant_name='Merchant',amount=50.0),
                   dict(currency='USD',merchant_name='Missing Only',amount=None)]
        self.add('financial_transactions',*values)
        rows=self.select('Q4')
        usd=next(r for r in rows if r[:2]==('USD','merchant'))
        self.assertEqual(usd[2:9],(5,3,1,1,1,1,1))
        with localcontext() as context:
            context.prec=100
            expected=Decimal.from_float(0.1)+Decimal.from_float(-0.125)
        self.assertEqual(usd[9],expected)
        self.assertEqual(next(r[9] for r in rows if r[1]=='missing only'),None)
        self.assertEqual({r[0] for r in rows},{None,'EUR','USD'})
        unknown=next(r for r in rows if r[0] is None)
        self.assertEqual(unknown[2:4],(2,2))
        self.assertIsNone(unknown[9])  # unknown currencies cannot be assumed compatible
        filtered=self.select('Q4',currency='usd',merchant=' MERCHANT ')
        self.assertEqual(filtered,[usd])
        self.create_index('financial_currency_merchant_btree')
        self.assertEqual(filtered,self.select('Q4',currency='USD',merchant='Merchant'))
        self.assertEqual(filtered,self.select('Q4_FILTER',currency='USD',merchant='Merchant'))

    def test_upstream_file_output_counts_do_not_claim_chronological_attempts(self):
        self.add('provenance/files',dict(file_key='same',output_name='A'),dict(file_key='same',output_name='B'),
                 dict(file_key='other',output_name='A'))
        self.assertEqual(self.select('Q5'),[('same',2,2,0,2)])

    def test_json_null_missing_key_invalid_array_and_partial_index(self):
        values=[None,'','{','null','{}','{"subject":null}','{"subject":"Hi"}','[]','true']
        self.add('documents',*[dict(email_fields=value) for value in values])
        self.assertEqual(self.select('Q6'),[('synthetic',9,1,1,1,1,3,1,1,1,1,1)])
        drilldown=self.select('Q6_JSON')
        self.assertEqual(drilldown,[(6,'synthetic','synthetic-6',True,False,True,'null')])
        self.create_index('documents_email_object_gin')
        self.assertEqual(drilldown,self.select('Q6_JSON'))

    def test_index_definitions_ready_and_safe_repeated_creation(self):
        for name in INDEX_SPECS:
            first=self.create_index(name)
            second=self.create_index(name)
            self.assertEqual(first['ddl'],second['ddl'])
            self.assertTrue(second['valid'] and second['ready'])

    def test_benchmark_full_results_and_only_one_index_change(self):
        self.add('documents',dict(email_fields='{"subject":null}'),
                 dict(email_fields='{"subject":null}'),dict(email_fields='{}'),
                 dict(email_fields=None),dict(email_fields='{"subject":"Hi"}'))
        for name in INDEX_SPECS:
            self.create_index(name)
        expected=self.select('Q6_JSON')
        original=inventory(self.db,self.domain,self.audit)
        report=compare(self.db,self.domain,self.audit)
        self.assertEqual(report['target_rows'],5)
        self.assertEqual(report['indexed_rows'],4)
        self.assertEqual(report['before']['document_source_ids'],[1,2])
        expected_hash=fingerprint_result(report['before']['columns'],expected)
        for variant in ('before','after'):
            runs=[report[variant]['warmup']]+report[variant]['measured']
            self.assertEqual(len(runs),4)
            self.assertTrue(all({key:run[key] for key in expected_hash}==expected_hash for run in runs))
        self.assertEqual(inventory(self.db,self.domain,self.audit),original)
        self.assertEqual(self.select('Q6_JSON'),expected)
        self.assertTrue(index_metadata(self.db,'documents_email_object_gin',self.domain)['valid'])
        # Same count but another identity, or another occurrence, must change the hash.
        changed=[(999,)+expected[0][1:],expected[1]]
        self.assertNotEqual(fingerprint_result(report['before']['columns'],changed),expected_hash)
        self.assertNotEqual(fingerprint_result(report['before']['columns'],expected+[expected[0]]),expected_hash)

    def test_benchmark_failure_rolls_back_index_drop(self):
        self.add('documents',dict(email_fields='{"subject":null}'))
        for name in INDEX_SPECS:
            self.create_index(name)
        ddl=index_metadata(self.db,'documents_email_object_gin',self.domain)
        oid=self.db.execute('SELECT %s::regclass::oid',(self.domain+'.documents_email_object_gin',)).fetchone()[0]
        with patch('scripts.benchmark_z1.run_variant',side_effect=RuntimeError('synthetic interruption')):
            with self.assertRaisesRegex(RuntimeError,'synthetic interruption'):
                compare(self.db,self.domain,self.audit)
        self.assertEqual(index_metadata(self.db,'documents_email_object_gin',self.domain),ddl)
        self.assertEqual(self.db.execute('SELECT %s::regclass::oid',(self.domain+'.documents_email_object_gin',)).fetchone()[0],oid)
        self.assertEqual(len(self.select('Q6_JSON')),1)


if __name__=='__main__': unittest.main()

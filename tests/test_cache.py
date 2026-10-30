import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from incremental_cache import review_cards
from review_prefilter import check_card


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name)/'cache.sqlite3')
        self.cards = [{'id':'A','en':'Hello friend','de':'Hallo Freund'},
                      {'id':'B','en':'Save game','de':'Spiel speichern'}]
        self.kw = dict(cards=self.cards, glossary=[], corpus={}, groups={},
                       run_fuzzy=False, rules_version='v1', cache_path=self.db)
        self.checker = Mock(side_effect=check_card)

    def run_cache(self, **updates):
        return review_cards(checker=self.checker, **{**self.kw, **updates})

    def test_warm_matches_uncached(self):
        first, stats = self.run_cache()
        self.assertEqual(stats['misses'], 2)
        second, stats = self.run_cache()
        self.assertEqual(first, second)
        self.assertEqual(stats['hits'], 2)
        self.assertEqual(self.checker.call_count, 2)
        plain, stats = self.run_cache(cache_path=None)
        self.assertEqual(plain, second)

    def test_card_text_context_and_limits_invalidate(self):
        self.run_cache()
        for field,value in [('de','Anders'),('context_before','new'),('limit_px_per_line',10),('locked_terms',['Neu']),('source_sha256','new')]:
            cards = copy.deepcopy(self.cards)
            cards[0][field] = value
            _, stats = self.run_cache(cards=cards)
            self.assertEqual(stats['hits'], 1, field)

    def test_shared_dependencies_invalidate(self):
        self.run_cache()
        variants = [dict(rules_version='v2'), dict(run_fuzzy=True),
                    dict(glossary=[{'en':'Hello','de':'Hallo'}]),
                    dict(corpus={'unused':{}}),dict(groups={'hello':['a','b']})]
        for change in variants:
            _, stats = self.run_cache(**change)
            self.assertEqual(stats['hits'], 0)

    def test_corruption_is_recomputed(self):
        expected,_ = self.run_cache()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE results SET payload='broken'")
        result,stats = self.run_cache()
        self.assertEqual(stats['misses'], 2)
        self.assertEqual(result,expected)

    def test_llm_mutation_not_persisted(self):
        results,_ = self.run_cache()
        results[0]['llm'] = {'suggestion_de':'something'}
        results,_ = self.run_cache()
        self.assertNotIn('llm', results[0])

    def test_group_change_rechecks_other_cards(self):
        self.run_cache()
        _,stats = self.run_cache(groups={'hello friend':['hallo','guten tag']})
        self.assertEqual(stats['misses'],2)

    def corrupt_a(self, column, value):
        with sqlite3.connect(self.db) as db:
            rows = db.execute('SELECT key,payload FROM results').fetchall()
            key = next(key for key, payload in rows if json.loads(payload)['id'] == 'A')
            if column == 'payload':
                db.execute('UPDATE results SET payload=? WHERE key=?', (value,key))
            else:
                db.execute('UPDATE results SET digest=? WHERE key=?', (value,key))

    def assert_one_entry_repaired(self, expected):
        self.checker.reset_mock()
        result, stats = self.run_cache()
        self.assertEqual(result, expected)
        self.assertEqual(stats, {'enabled':True,'hits':1,'misses':1})
        self.assertEqual(self.checker.call_count,1)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT DISTINCT typeof(payload),typeof(digest) FROM results').fetchall(),[('text','text')])
        _, warm = self.run_cache()
        self.assertEqual(warm['hits'],2)

    def test_blob_payload_is_repaired_without_flushing_other_card(self):
        expected, _ = self.run_cache()
        for value in (b'broken', b'\xff', json.dumps(expected[0]).encode('utf-8')):
            with self.subTest(value_type='BLOB', size=len(value)):
                self.corrupt_a('payload', sqlite3.Binary(value))
                self.assert_one_entry_repaired(expected)

    def test_blob_digest_is_a_miss_and_repaired(self):
        expected, _ = self.run_cache()
        self.corrupt_a('digest', sqlite3.Binary(b'0'*64))
        self.assert_one_entry_repaired(expected)

    def test_hash_matching_invalid_json_or_result_shape_is_repaired(self):
        expected, _ = self.run_cache()
        for payload in ('not json', '[]', json.dumps({'id':'B','verdict':'pass','flags':[]}),
                        json.dumps({'id':'A','verdict':'pass','flags':None})):
            with self.subTest(payload=payload):
                with sqlite3.connect(self.db) as db:
                    rows=db.execute('SELECT key,payload FROM results').fetchall()
                    key=next(key for key,value in rows if json.loads(value)['id']=='A')
                    db.execute('UPDATE results SET payload=?,digest=? WHERE key=?',
                               (payload,hashlib.sha256(payload.encode()).hexdigest(),key))
                self.assert_one_entry_repaired(expected)


class CacheCliTest(unittest.TestCase):
    def test_cli_cold_and_warm(self):
        import subprocess
        import sys
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            cards=tmp/'cards.json'
            cards.write_text(json.dumps([{'id':'T','en':'Hello','de':'Hallo'}]))
            cmd=[sys.executable,str(root/'review_prefilter.py'),'--cards',str(cards),
                 '--no-fuzzy','--cache',str(tmp/'cache.sqlite3'),'--out-dir',str(tmp/'output')]
            results=[]
            for hits in (0,1):
                run= subprocess.run(cmd,capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stderr)
                out=json.loads((tmp/'output/prefilter_results.json').read_text())
                self.assertEqual(out['summary']['layer1_cache']['hits'],hits)
                results.append(out['results'])
            self.assertEqual(*results)

    def test_cli_recovers_blob_payload_and_retains_warm_neighbor(self):
        import subprocess
        import sys
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory)
            cards=tmp/'cards.json'
            cards.write_text(json.dumps([{'id':'A','en':'Hello','de':'Hallo'},
                                         {'id':'B','en':'Save','de':'Speichern'}]))
            db_path=tmp/'cache.sqlite3';out=tmp/'output'
            cmd=[sys.executable,str(root/'review_prefilter.py'),'--cards',str(cards),
                 '--no-fuzzy','--cache',str(db_path),'--out-dir',str(out)]
            first=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            expected=json.loads((out/'prefilter_results.json').read_text())['results']
            with sqlite3.connect(db_path) as db:
                rows=db.execute('SELECT key,payload FROM results').fetchall()
                key=next(key for key,value in rows if json.loads(value)['id']=='A')
                db.execute('UPDATE results SET payload=? WHERE key=?',(sqlite3.Binary(b'broken'),key))
            repaired=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(repaired.returncode,0,repaired.stderr)
            self.assertNotIn('Traceback',repaired.stderr)
            report=json.loads((out/'prefilter_results.json').read_text())
            self.assertEqual(report['results'],expected)
            self.assertEqual(report['summary']['layer1_cache'],{'enabled':True,'hits':1,'misses':1})

    def test_cli_invalid_cache_inputs_have_no_traceback(self):
        import subprocess
        import sys
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cards = tmp/'cards.json'
            for value, cache in [(float('nan'), tmp/'cache.sqlite3'),
                                 (1, tmp/'missing'/'cache.sqlite3')]:
                cards.write_text(json.dumps([{'id':'T','en':'Hello','de':'Hallo','limit_px_per_line':value}]))
                out = tmp/('out-nan' if value != value else 'out-path')
                run = subprocess.run([sys.executable,str(root/'review_prefilter.py'),
                    '--cards',str(cards),'--no-fuzzy','--cache',str(cache),
                    '--out-dir',str(out)],capture_output=True,text=True)
                self.assertEqual(run.returncode,1)
                self.assertNotIn('Traceback',run.stderr)
                self.assertFalse((out/'prefilter_results.json').exists())

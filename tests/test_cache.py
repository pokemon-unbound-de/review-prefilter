import copy
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

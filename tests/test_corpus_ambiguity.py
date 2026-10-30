"""Conflicting corpus entries must not yield an arbitrary DE winner."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from incremental_cache import review_cards
from review_prefilter import check_card, load_corpus


TOOL = Path(__file__).resolve().parents[1] / 'review_prefilter.py'
ROWS = [
    {'id': 'synthetic-A', 'en_raw': 'Hello friend', 'de_raw': 'Hallo Freund'},
    {'id': 'synthetic-B', 'en_raw': 'Hello friend', 'de_raw': 'Guten Tag'},
]
CARD = {'id': 'synthetic-card', 'en': 'Hello friend', 'de': 'Hallo Freund'}


class CorpusAmbiguityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def index(self, rows):
        path = self.root / 'corpus.json'
        path.write_text(json.dumps({'entries': rows}), encoding='utf-8')
        return load_corpus(str(path))

    def test_conflicts_review_without_winner_in_either_order_or_mode(self):
        reports = []
        for rows in (ROWS, list(reversed(ROWS))):
            index = self.index(rows)
            self.assertNotIn('de_raw', index['hello friend'])
            for fuzzy in (False, True):
                result = check_card(CARD, [], index, {}, fuzzy)
                self.assertEqual(result['verdict'], 'review')
                self.assertIsNone(result['corpus_match'])
                self.assertEqual([f['check'] for f in result['flags']], ['corpus_ambiguity'])
                reports.append(result)
        self.assertTrue(all(r == reports[0] for r in reports))

    def test_fuzzy_hit_to_conflicted_key_also_has_no_winner(self):
        result = check_card({**CARD, 'en': 'Hello friends'}, [], self.index(ROWS), {}, True)
        self.assertEqual(result['verdict'], 'review')
        self.assertIsNone(result['corpus_match'])
        self.assertEqual(result['flags'][0]['check'], 'corpus_ambiguity')

    def test_unique_and_identical_duplicates_keep_existing_suggestion(self):
        for rows in ([ROWS[0]], [ROWS[0], {**ROWS[0], 'id': 'synthetic-C'}]):
            for fuzzy in (False, True):
                with self.subTest(duplicates=len(rows), fuzzy=fuzzy):
                    result = check_card(CARD, [], self.index(rows), {}, fuzzy)
                    self.assertEqual(result['verdict'], 'pass')
                    self.assertEqual(result['corpus_match']['de_raw'], 'Hallo Freund')
                    self.assertEqual(result['flags'], [])

    def test_normalized_en_collisions_and_raw_de_differences_are_visible(self):
        rows = [ROWS[0], {**ROWS[1], 'en_raw': 'HELLO\\nfriend', 'de_raw': 'HALLO FREUND'}]
        result = check_card(CARD, [], self.index(rows), {}, False)
        self.assertIsNone(result['corpus_match'])
        self.assertEqual(result['verdict'], 'review')

    def test_same_variant_count_changed_content_invalidates_cache(self):
        db = str(self.root / 'review.sqlite3')
        def run(rows):
            return review_cards([CARD], [], self.index(rows), {}, False,
                                check_card, cache_path=db, rules_version='test-fixed')
        first, cold = run(ROWS)
        same, warm = run(list(reversed(ROWS)))
        self.assertEqual(cold['misses'], 1)
        self.assertEqual(warm['hits'], 1)
        self.assertEqual(first, same)
        changed = copy.deepcopy(ROWS)
        changed[1]['de_raw'] = 'Anderer Dialog'
        _, invalidated = run(changed)
        self.assertEqual(invalidated['misses'], 1)
        resolved, _ = run([ROWS[0]])
        self.assertEqual(resolved[0]['verdict'], 'pass')
        self.assertIsNotNone(resolved[0]['corpus_match'])

    def test_cli_reports_conflict_alongside_positive_control_and_warm_replay(self):
        cards = [CARD, {'id': 'synthetic-unique-card', 'en': 'Save game', 'de': 'Spiel speichern'}]
        rows = ROWS + [{'id': 'synthetic-unique', 'en_raw': 'Save game', 'de_raw': 'Spiel speichern'}]
        self.index(rows)
        path = self.root / 'cards.json'
        path.write_text(json.dumps(cards), encoding='utf-8')
        results = []
        for attempt, hits in enumerate((0, 2)):
            out = self.root / ('out-' + str(attempt))
            run = subprocess.run([
                sys.executable, str(TOOL), '--cards', str(path),
                '--corpus', str(self.root / 'corpus.json'), '--no-fuzzy',
                '--cache', str(self.root / 'cli.sqlite3'), '--out-dir', str(out)],
                capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads((out / 'prefilter_results.json').read_text(encoding='utf-8'))
            self.assertEqual(report['summary']['layer1_cache']['hits'], hits)
            self.assertEqual(report['summary']['verdicts'], {'review': 1, 'pass': 1})
            self.assertIsNone(report['results'][0]['corpus_match'])
            self.assertEqual(report['results'][1]['corpus_match']['id'], 'synthetic-unique')
            results.append(report['results'])
        self.assertEqual(*results)


if __name__ == '__main__':
    unittest.main()

"""Corpus adapter regressions with synthetic inputs, no external services."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from review_prefilter import load_corpus


TOOL = Path(__file__).resolve().parents[1] / 'review_prefilter.py'
ENTRIES = [{'id': 'synthetic-source', 'en_raw': 'Hello friend',
            'de_raw': 'Hallo Freund', 'pointer': 'synthetic-pointer'}]


class CorpusInputTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'corpus.json'
        self.cards = self.root / 'cards.json'
        self.cards.write_text(json.dumps([
            {'id': 'synthetic-card', 'en': 'Hello friend', 'de': 'Hallo Kamerad'}]),
            encoding='utf-8')

    def save(self, data):
        self.source.write_text(json.dumps(data), encoding='utf-8')
        return self.source

    def cli(self, name, corpus=True, cache=False):
        out = self.root / name
        args = [sys.executable, str(TOOL), '--cards', str(self.cards),
                '--no-fuzzy', '--out-dir', str(out)]
        if corpus:
            args += ['--corpus', str(self.source)]
        if cache:
            args += ['--cache', str(self.root / 'cache.sqlite3')]
        run = subprocess.run(args, text=True, capture_output=True)
        return run, out / 'prefilter_results.json'

    def test_list_and_wrapped_entries_preserve_exact_match_and_metadata(self):
        first = load_corpus(self.save(ENTRIES))
        second = load_corpus(self.save({'entries': ENTRIES, 'schema': 1}))
        self.assertEqual(first, second)
        self.assertEqual(first['hello friend'], {
            'de_raw': 'Hallo Freund', 'id': 'synthetic-source',
            'pointer': 'synthetic-pointer', 'status': None})

    def test_valid_empty_inventory_and_existing_clean_entry_filter(self):
        for data in ([], {'entries': []}, {'entries': [
                {'en_raw': '', 'de_raw': 'Skipped'},
                {'en_raw': 'Missing DE'},
                {'en_raw': 'Empty DE', 'de_raw': None},
                {'en_raw': 'Bad escape', 'de_raw': '\\!synthetic'}]}):
            with self.subTest(data=data):
                self.assertEqual(load_corpus(self.save(data)), {})

    def test_bad_shape_or_text_type_is_rejected(self):
        for data in (None, 3, 'text', {}, {'entries': None}, {'entries': {}},
                     [None], ['entry'], [{'en_raw': 0, 'de_raw': 'text'}],
                     [{'en_raw': 'text', 'de_raw': ['wrong']}],
                     [{'en_raw': False, 'de_raw': 'text'}]):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    load_corpus(self.save(data))

    def test_cli_list_and_object_match_with_warm_cache(self):
        results = []
        for name, data, hits in (
                ('list', ENTRIES, 0), ('wrapped', {'entries': ENTRIES}, 1)):
            self.save(data)
            run, path = self.cli(name, cache=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(report['summary']['layer1_cache']['hits'], hits)
            match = report['results'][0]['corpus_match']
            self.assertEqual(match['id'], 'synthetic-source')
            self.assertEqual(match['match'], 'exact')
            self.assertEqual(match['de_raw'], 'Hallo Freund')
            results.append(report['results'])
        self.assertEqual(*results)

    def test_explicit_missing_file_errors_but_omitting_corpus_still_works(self):
        run, path = self.cli('missing')
        self.assertEqual(run.returncode, 1)
        self.assertNotIn('Traceback', run.stderr)
        self.assertFalse(path.exists())
        run, path = self.cli('omitted', corpus=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIsNone(json.loads(path.read_text())['results'][0]['corpus_match'])

    def test_cli_invalid_source_never_writes_success_or_opens_cache(self):
        values = [b'{invalid', b'\xff', b'null', b'{}', b'{"entries":{}}',
                  b'[null]', b'[{"en_raw":7,"de_raw":"PRIVATE_TEST_MARKER"}]']
        for index, value in enumerate(values):
            with self.subTest(value=value):
                self.source.write_bytes(value)
                run, path = self.cli('invalid-' + str(index), cache=True)
                self.assertEqual(run.returncode, 1)
                self.assertNotIn('Traceback', run.stderr)
                self.assertNotIn('PRIVATE_TEST_MARKER', run.stderr)
                self.assertFalse(path.exists())
                self.assertFalse((self.root / 'cache.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()

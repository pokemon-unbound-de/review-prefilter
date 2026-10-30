import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from review_prefilter import check_card, exact_token_in_text, name_in_text


class IdentityGuardTest(unittest.TestCase):
    def test_names_after_known_literal_breaks(self):
        for marker in ('\\n','\\p','\\l','\n'):
            with self.subTest(marker=marker):
                self.assertTrue(name_in_text('Example','Before'+marker+'Example'))

    def test_multiword_name_accepts_display_whitespace(self):
        for text in ('Example Team','Example\\nTeam','Example\nTeam','Example\tTeam','Example  Team'):
            self.assertTrue(name_in_text('Example Team',text))

    def test_existing_case_and_inflection_rules_preserved(self):
        for text in ('Example','example','Examples','Examplees'):
            self.assertTrue(name_in_text('Example',text))
        for text in ('PreExample','Exampleville'):
            self.assertFalse(name_in_text('Example',text))

    def test_breaks_do_not_join_partial_name_or_strip_unknown_markers(self):
        self.assertFalse(name_in_text('Example','Exa\\nmple'))
        self.assertFalse(name_in_text('Example',r'\xExample'))

    def test_exact_roman_token_has_no_case_or_inflection_aliases(self):
        self.assertTrue(exact_token_in_text('III','Regent Example\\nIII.'))
        for suffix in ('3.','II.','IIIs.','IIIes.','iii.'):
            self.assertFalse(exact_token_in_text('III','Regent Example '+suffix))

    def test_card_checks_are_additive_and_leave_original_strings_unchanged(self):
        card=dict(id='synthetic',en='Regent Example III.',de='Herrscher\\nExample IIIs.',
                  locked_terms=['Example'],locked_exact_tokens=['III'])
        before=copy.deepcopy(card)
        result=check_card(card,[],{},{},False)
        self.assertEqual(card,before)
        self.assertEqual(result['verdict'],'fix')
        self.assertEqual([f['check'] for f in result['flags']],['locked_exact_tokens'])

    def test_no_roman_inference_without_explicit_token_metadata(self):
        result=check_card(dict(id='synthetic',en='I am here, room IV.',de='Ich bin hier, Raum vier.'),[],{},{},False)
        self.assertNotIn('locked_exact_tokens',[f['check'] for f in result['flags']])

    def test_glossary_lookup_uses_same_break_aware_name_view(self):
        result=check_card(dict(id='synthetic',en='Hello\\nEnglishName',de='Hallo\\nDeutscherName'),
                          [{'en':'EnglishName','de':'DeutscherName'}],{},{},False)
        self.assertEqual(result['flags'],[])
        leak=check_card(dict(id='synthetic',en='Hello\\nEnglishName',de='Hallo\\nEnglishName'),
                          [{'en':'EnglishName','de':'DeutscherName'}],{},{},False)
        self.assertIn('glossary_leak',[f['check'] for f in leak['flags']])

    def test_cli_positive_and_invalid_numeral_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cards=root/'cards.json';output=root/'out'
            cards.write_bytes(json.dumps([
                dict(id='valid',en='Regent Example III.',de='Herrscher\\nExample III.',locked_terms=['Example'],locked_exact_tokens=['III']),
                dict(id='invalid',en='Regent Example III.',de='Herrscher\\nExample IIIs.',locked_terms=['Example'],locked_exact_tokens=['III'])]).encode())
            result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'review_prefilter.py'),
                '--cards',str(cards),'--no-fuzzy','--out-dir',str(output)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads((output/'prefilter_results.json').read_bytes())
            # The two synthetic translations share an EN string, so the
            # existing consistency warning remains active for the valid row.
            self.assertEqual(report['summary']['verdicts'],{'review':1,'fix':1})
            self.assertFalse(any(f['check'].startswith('locked_') for f in report['results'][0]['flags']))
            self.assertIn('locked_exact_tokens',[f['check'] for f in report['results'][1]['flags']])
            cards.write_bytes(json.dumps({'cards':json.loads(cards.read_bytes())}).encode())
            result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'review_prefilter.py'),
                '--cards',str(cards),'--no-fuzzy','--out-dir',str(root/'wrapped')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            wrapped=json.loads((root/'wrapped/prefilter_results.json').read_bytes())
            self.assertEqual(wrapped['results'],report['results'])

"""Read-only artifact checks: selected originals, citations, safe packaging and brand."""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
import zipfile

WEB=Path(__file__).resolve().parents[1]
ROOT=WEB.parents[1]
DIST=WEB/'showcase/dist'


class ShowcaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(DIST/'index.html').read_text(encoding='utf-8')
        cls.data=json.loads(re.search(r'<script id="showcase-data" type="application/json">(.*?)</script>',cls.html,re.S).group(1))

    def test_selected_real_originals_are_hash_identical(self):
        expected={'CUAD-001_d0873843':5,'CUAD-004_7afb02da':41,'CUAD-008_ba9c81fe':5}
        self.assertEqual({c['identity']['document_id']:len(c['report']['checks']) for c in self.data['cases'].values()},expected)
        for case in self.data['cases'].values():
            original=(ROOT/case['report']['source_file']).read_bytes()
            self.assertEqual(base64.b64decode(case['native_report_base64']),original)
            self.assertEqual(hashlib.sha256(original).hexdigest(),case['report']['report_sha256'])

    def test_text_hashes_and_recorded_positions(self):
        for case in self.data['cases'].values():
            text=case['text'];self.assertTrue(text['available'])
            self.assertEqual(hashlib.sha256(text['normalized_text'].encode()).hexdigest(),text['normalized_sha256'])
            if text['raw_mapping_available']:
                self.assertEqual(hashlib.sha256(text['raw_text'].encode()).hexdigest(),text['raw_sha256'])
            for pieces in text['quotes'].values():
                for p in pieces:
                    if p['position_matches']:
                        self.assertEqual(text['normalized_text'][p['normalized_start']:p['normalized_end']],p['text'])

    def test_zip_is_only_the_expected_files_and_verified_txt_samples(self):
        with zipfile.ZipFile(WEB/'showcase/MingQi_HTML_Showcase.zip') as bundle:
            self.assertEqual(set(bundle.namelist()),{'明契_HTML展示版/'+n for n in ('index.html','README.txt','source_manifest.json')}|{'明契_HTML展示版/sample_contracts/'+n+'.txt' for n in ('CUAD-001','CUAD-004','CUAD-008')})
            for case in self.data['cases'].values():
                name=case['identity']['sample']+'.txt'
                self.assertEqual(hashlib.sha256(bundle.read('明契_HTML展示版/sample_contracts/'+name)).hexdigest(),case['text']['raw_sha256'])
            for name in ('index.html','README.txt','source_manifest.json'):
                self.assertEqual(bundle.read('明契_HTML展示版/'+name),(DIST/name).read_bytes())

    def test_no_external_resource_dependency_or_login_dialog(self):
        self.assertNotRegex(self.html,r'<script[^>]+src=')
        self.assertNotIn('href="/static/',self.html)
        self.assertNotIn('<dialog id="access-dialog"',self.html)
        self.assertIn("connect-src 'none'",self.html)
        self.assertFalse(self.data['system']['model_api_calls_enabled'])

    def test_live_and_showcase_branding(self):
        self.assertIn('<strong>明契</strong>',(WEB/'templates/index.html').read_text(encoding='utf-8'))
        for relative in ('templates/index.html','templates/print.html','static/app.js'):
            source=(WEB/relative).read_text(encoding='utf-8');self.assertNotIn('衡契',source);self.assertIn('明契',source)

    def test_no_server_user_records_or_auth_snapshot(self):
        self.assertFalse(self.data['system']['access']['authenticated'])
        self.assertEqual(self.data['manifest']['model_api_calls'],0)
        self.assertEqual(self.data['manifest']['case_count'],3)
        for case in self.data['cases'].values():
            self.assertNotIn('reviews',case)
            self.assertFalse(case['provenance']['annotation_files_included'])


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ShowcaseTests))
    (WEB/'qa/showcase_artifact_results.json').write_text(json.dumps({'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'model_api_calls':0},indent=2),encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())

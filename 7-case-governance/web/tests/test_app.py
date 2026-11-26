"""Offline web adapter tests against existing real reports; no model API calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))
from app import create_app
from report_store import ingestion_module, reasons, digest, ROOT
from auth_helpers import login_as


class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (WEB / "qa").mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="isolated_review_test_", dir=WEB / "qa")
        cls.app = create_app(Path(cls.temp.name))
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        login_as(cls.app, cls.client)
        cls.bootstrap = cls.client.get("/api/bootstrap").get_json()
        cls.id = next(r["id"] for r in cls.bootstrap["reports"] if r["sample"] == "CUAD-004")
        cls.store = cls.app.extensions["report_store"]
        cls.path = cls.store.entries[cls.id]["path"]
        cls.raw_bytes = cls.path.read_bytes()
        cls.headers = {"X-Workbench-Token": cls.bootstrap["review_token"]}

    @classmethod
    def tearDownClass(cls):
        assert cls.path.read_bytes() == cls.raw_bytes
        cls.temp.cleanup()

    def test_bootstrap_catalog_policy_and_no_model_initialization(self):
        self.assertEqual(len(self.bootstrap["catalog"]), 41)
        self.assertEqual(self.bootstrap["mode_counts"], {"FLAG_IF_CONDITION":23,"REQUIRE_PRESENT":3,"CONTEXT_REVIEW":5,"INFORMATION_ONLY":5})
        self.assertTrue(self.bootstrap["realtime_enabled"])
        self.assertTrue(self.bootstrap["model_api_calls_enabled"])
        self.assertNotIn("openai", sys.modules)
        self.assertNotIn("sentence_transformers", sys.modules)

    def test_offline_mode_blocks_tasks_before_any_launch(self):
        client=create_app(offline=True).test_client()
        bootstrap=client.get('/api/bootstrap').get_json()
        self.assertTrue(bootstrap['offline_mode'])
        self.assertFalse(bootstrap['model_api_calls_enabled'])
        self.assertFalse(bootstrap['realtime_enabled'])
        with patch('task_manager.TaskManager.create',side_effect=AssertionError('must not launch')):
            response=client.post('/api/tasks',json={},headers={'X-Workbench-Token':bootstrap['review_token']})
        self.assertEqual(response.status_code,503)
        self.assertIn('离线回放',response.get_json()['error'])

    def test_real_report_statistics(self):
        r = self.client.get(f"/api/reports/{self.id}").get_json()
        for key, value in {"reviewed":41,"accepted":25,"manual":16,"passed":38,"failed":1,"uncertain":2,"triggered":9,"retries":21}.items():
            self.assertEqual(r["stats"][key], value, key)
        self.assertEqual(len(r["supplemental"]), 1)
        self.assertEqual(r["supplemental"][0]["question_id"], "Q35")
        self.assertEqual(r["playback_mode"], "HISTORY")

    def test_explicit_enable_realtime_requires_token_and_never_launches(self):
        app = create_app(data_dir=Path(self.temp.name)/"enable", offline=True)
        client = app.test_client()
        login_as(app, client)
        bootstrap = client.get('/api/bootstrap').get_json()
        self.assertEqual(client.post('/api/runtime/enable-realtime', json={}).status_code, 403)
        headers = {'X-Workbench-Token': bootstrap['review_token']}
        with patch.object(app.extensions['task_manager'], 'create', side_effect=AssertionError('must not launch')):
            response = client.post('/api/runtime/enable-realtime', json={}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(client.get('/api/bootstrap').get_json()['realtime_enabled'])
            self.assertFalse(client.get('/api/bootstrap').get_json()['offline_mode'])
            self.assertEqual(client.post('/api/tasks', json={}, headers=headers).status_code, 400)
        app.extensions['task_manager'].close()

    def test_isolated_audit_cannot_enable_realtime(self):
        app = create_app(data_dir=Path(self.temp.name)/"locked", offline=True)
        app.config['ALLOW_LIVE_MODE_SWITCH'] = False
        client = app.test_client()
        bootstrap = client.get('/api/bootstrap').get_json()
        self.assertFalse(bootstrap['can_enable_realtime'])
        headers = {'X-Workbench-Token': bootstrap['review_token']}
        self.assertEqual(client.post('/api/runtime/enable-realtime', json={}, headers=headers).status_code, 403)
        self.assertTrue(client.get('/api/bootstrap').get_json()['offline_mode'])
        app.extensions['task_manager'].close()

    def test_basic_information_rules_not_executed(self):
        r = self.client.get(f"/api/reports/{self.id}").get_json()
        for c in r["checks"][:5]:
            self.assertFalse(c["rule_executed"])
            self.assertEqual(c["mode"], "NOT_EXECUTED")
            self.assertEqual(c["risk_levels"], [])

    def test_evidence_coordinates_in_both_texts(self):
        for entry in self.bootstrap["reports"]:
            if not entry["sample"]:
                continue
            text = self.client.get(f"/api/reports/{entry['id']}/text").get_json()
            self.assertTrue(text["available"])
            self.assertTrue(text["raw_mapping_available"])
            for pieces in text["quotes"].values():
                for p in pieces:
                    self.assertEqual(text["normalized_text"][p["normalized_start"]:p["normalized_end"]], p["text"])
                    self.assertTrue(p["position_matches"])
                    if p["raw_start"] is not None:
                        raw = text["raw_text"][p["raw_start"]:p["raw_end"]]
                        self.assertEqual(ingestion_module().normalize_text(raw).strip(), p["text"].strip())
            self.assertIn("TXT无原始PDF页码", text["page_note"])

    def test_changed_normalized_text_is_not_highlighted(self):
        with patch.object(ingestion_module(), "ingest") as ingest:
            ingest.return_value.text = "CONTROLLED altered text; not a natural report"
            value = self.store.text(self.id)
            self.assertFalse(value["available"])
            self.assertIsNone(value["normalized_text"])

    def test_controlled_technical_error_reason_classification(self):
        # A small controlled input, not a replacement for the deleted natural report.
        result=reasons({"verification_status":"UNCERTAIN","processing_status":"COMPLETED",
                        "attempt_history":[{"diagnostic_codes":["MODEL_ERROR"]}]})
        self.assertIn("technical",result)

    def test_removed_run_cannot_be_loaded_and_kept_runs_remain(self):
        deleted=['CUAD-001_0d3c8517','demo_contract_7a798dfd','demo_contract_e57f60d1',
                 'demo_contract_dfd465c1','demo_contract_b48b4904',
                 '002_CENTRACKINTERNATIONALINC_10_29_1999-EX-10.3-WEB SITE HOSTING AGREEMENT_1f27ab3b']
        ids={r['document_id'] for r in self.bootstrap['reports']}
        self.assertTrue({'CUAD-001_d0873843','CUAD-004_7afb02da','CUAD-008_ba9c81fe','demo_contract_4bb14120'}<=ids)
        for doc in deleted:
            self.assertNotIn(doc,ids)
            relative=str(Path('4-agent/code/outputs/reports')/(doc+'.json'))
            key=digest(relative.encode())[:20]
            self.assertEqual(self.client.get('/api/reports/'+key).status_code,404)

    def test_unknown_policy_reason(self):
        r = self.client.get(f"/api/reports/{self.id}").get_json()
        for qid in ("Q32","Q34","Q39"):
            c = next(c for c in r["checks"] if c["qid"] == qid)
            self.assertIn("incomplete_policy", c["manual_reasons"])

    def test_review_is_separate_and_requires_real_user_fields(self):
        url = f"/api/reports/{self.id}/reviews"
        self.assertEqual(self.client.post(url,json={"qid":"Q16","action":"accept"}).status_code,403)
        self.assertEqual(self.client.post(url,json={"qid":"Q16","action":"accept","reviewer":"","note":""},headers=self.headers).status_code,400)
        response = self.client.post(url,json={"qid":"Q16","action":"materials","reviewer":"CONTROLLED_WEB_TEST","note":"Synthetic UI record in isolated test directory; no human adjudication."},headers=self.headers)
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.get_json()["record"]["original_agent_report_modified"],False)
        self.assertEqual(self.path.read_bytes(), self.raw_bytes)
        self.assertTrue(self.client.get(url).get_json()["records"])

    def test_reject_cross_origin_and_arbitrary_category_review(self):
        url = f"/api/reports/{self.id}/reviews"
        fields = {"qid":"Q1","action":"accept","reviewer":"TEST","note":"not a genuine review"}
        self.assertEqual(self.client.post(url,json=fields,headers=self.headers).status_code,400)
        self.assertEqual(self.client.post(url,json=fields,headers={**self.headers,"Origin":"https://untrusted.invalid"}).status_code,403)
        self.assertEqual(self.client.get("/api/bootstrap",headers={"Host":"untrusted.invalid"}).status_code,403)

    def test_original_download_and_print(self):
        response = self.client.get(f"/api/reports/{self.id}/download")
        self.assertEqual(response.data, self.raw_bytes)
        self.assertEqual(hashlib.sha256(response.data).hexdigest(),self.client.get(f"/api/reports/{self.id}").get_json()["report_sha256"])
        printed = self.client.get(f"/print/{self.id}")
        self.assertEqual(printed.status_code,200)
        self.assertIn("未执行",printed.get_data(as_text=True))

    def test_task_requires_upload_and_paths_are_restricted(self):
        self.assertEqual(self.client.post("/api/tasks",json={},headers=self.headers).status_code,400)
        self.assertEqual(self.client.get("/api/reports/not-a-report").status_code,404)
        self.assertEqual(self.client.get("/.env").status_code,404)
        self.assertEqual(self.client.get("/static/../app.py").status_code,404)

    def test_pages_and_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code,200)
        self.assertIn("证据溯源", response.get_data(as_text=True))
        self.assertIn("frame-ancestors 'none'",response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"],"nosniff")
        self.assertEqual(self.client.get("/static/app.js").status_code,200)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WorkbenchTests))
    (WEB / "qa").mkdir(exist_ok=True)
    (WEB / "qa/unit_results.json").write_text(json.dumps({"tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
        "real_model_calls":0,"scope":"web adapter tests using real saved reports; review submissions isolated"},ensure_ascii=False,indent=2),encoding="utf-8")
    raise SystemExit(not result.wasSuccessful())

"""Controlled access-control tests. Fake launcher only; zero model calls."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

WEB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(WEB))
from app import create_app
from access_control import AccessControl, COOKIE
from task_manager import TaskManager, TaskError
from sharing_network import eligible_address


class FakeProcess:
    returncode=None
    def poll(self): return self.returncode
    def terminate(self): self.returncode=-15
    def wait(self,timeout=None): return self.returncode


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='controlled_access_',dir=WEB/'qa')
        self.root=Path(self.temp.name);self.launches=[]
        def launch(command,**kwargs):self.launches.append(command);return FakeProcess()
        self.tasks=TaskManager(self.root/'tasks',launch)
        self.app=create_app(self.root/'data',self.tasks,trusted_hosts=['192.168.50.10'])
        self.app.config['TESTING']=True
        self.access=self.app.extensions['access_control']
        self.a=self.access.create_invite('CONTROLLED member A',daily_limit=2)
        self.b=self.access.create_invite('CONTROLLED member B')
        self.admin=self.access.create_invite('CONTROLLED admin',role='admin')
        self.client=self.app.test_client()
        self.headers={'X-Workbench-Token':self.client.get('/api/bootstrap').get_json()['review_token']}
        self.thread=patch.object(self.tasks,'_monitor',return_value=None);self.thread.start()

    def tearDown(self):
        self.tasks.close();self.thread.stop();self.temp.cleanup()

    def login(self, record=None, client=None):
        client=client or self.client;record=record or self.a
        response=client.post('/api/auth/login',json={'code':record['code']},headers=self.headers)
        self.assertEqual(response.status_code,200)
        return response

    def submit(self, client=None, qids=None, request_id=None, content=b'CONTROLLED boundary fixture, not a real review.'):
        return (client or self.client).post('/api/tasks',headers=self.headers,data={
            'file':(io.BytesIO(content),'controlled.txt'),'clauses':json.dumps(qids or ['Q5']),
            'request_id':request_id or uuid4().hex,'top_k':'5','max_retries':'2','large_scope_confirmed':'true'})

    def test_guest_can_read_history_but_cannot_start(self):
        data=self.client.get('/api/bootstrap').get_json()
        self.assertTrue(data['reports']);self.assertFalse(data['access']['authenticated'])
        self.assertFalse(data['realtime_enabled'])
        key=data['reports'][0]['id']
        for suffix in ('','/text','/download'):
            self.assertEqual(self.client.get('/api/reports/'+key+suffix).status_code,200)
        self.assertEqual(self.submit().status_code,401);self.assertEqual(self.launches,[])

    def test_login_requires_csrf_and_never_launches(self):
        self.assertEqual(self.client.post('/api/auth/login',json={'code':self.a['code']}).status_code,403)
        response=self.login();cookie=response.headers['Set-Cookie']
        self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie)
        self.assertTrue(self.client.get('/api/bootstrap').get_json()['realtime_enabled'])
        self.assertEqual(self.launches,[])

    def test_codes_and_sessions_are_not_stored_as_plaintext(self):
        self.login()
        with self.access.db() as db:
            code=db.execute('SELECT code_digest FROM invites WHERE id=?',(self.a['id'],)).fetchone()[0]
            sid=db.execute('SELECT digest FROM sessions').fetchone()[0]
        self.assertEqual(len(code),64);self.assertNotEqual(code,self.a['code'])
        self.assertEqual(len(sid),64);self.assertNotEqual(sid,self.client.get_cookie(COOKIE).value)
        self.assertNotIn('code_digest',self.access.list_invites()[0])

    def test_wrong_expired_revoked_codes_fail(self):
        for value in ('wrong',None,{'unexpected':'object'}):
            self.assertEqual(self.client.post('/api/auth/login',json={'code':value},headers=self.headers).status_code,401)
        with self.access.db() as db:db.execute('UPDATE invites SET expires=? WHERE id=?',(time.time()-1,self.a['id']))
        self.assertEqual(self.client.post('/api/auth/login',json={'code':self.a['code']},headers=self.headers).status_code,401)
        self.access.revoke(self.b['id'])
        self.assertEqual(self.client.post('/api/auth/login',json={'code':self.b['code']},headers=self.headers).status_code,401)

    def test_eight_login_failures_trigger_throttle(self):
        for _ in range(8):
            self.assertEqual(self.client.post('/api/auth/login',json={'code':'wrong'},headers=self.headers).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'code':self.a['code']},headers=self.headers).status_code,429)

    def test_member_clause_limit_and_no_launch_on_rejection(self):
        self.login()
        self.assertEqual(self.submit(qids=['Q1','Q2','Q3','Q4','Q5','Q8']).status_code,403)
        self.assertEqual(self.launches,[])
        self.assertEqual(self.client.get('/api/bootstrap').get_json()['access']['used_today'],0)

    def test_created_task_has_owner_and_duplicate_does_not_recharge(self):
        self.login();request_id=uuid4().hex
        first=self.submit(request_id=request_id);self.assertEqual(first.status_code,202)
        second=self.submit(request_id=request_id);self.assertEqual(second.status_code,200)
        self.assertEqual(len(self.launches),1)
        self.assertEqual(first.get_json()['task']['owner_id'],self.a['id'])
        self.assertEqual(self.client.get('/api/bootstrap').get_json()['access']['used_today'],1)

    def test_invalid_upload_does_not_consume_allowance(self):
        self.login();self.assertEqual(self.submit(content=b'').status_code,400)
        self.assertEqual(self.access.status(self.access.principal(self.client.get_cookie(COOKIE).value))['used_today'],0)

    def test_daily_allowance_and_shanghai_rollover(self):
        self.login();principal=self.access.principal(self.client.get_cookie(COOKIE).value)
        for _ in range(2):
            request_id=uuid4().hex;self.access.reserve(principal,{'request_id':request_id,'clauses':'["Q5"]'})
            self.access.finish(principal,request_id,'CONTROLLED-only')
        self.assertEqual(self.submit().status_code,429)
        with patch.object(self.access,'today',return_value='2099-01-02'):
            self.assertEqual(self.access.status(principal)['remaining_today'],2)

    def test_concurrent_reservations_cannot_exceed_limit(self):
        self.login();principal=self.access.principal(self.client.get_cookie(COOKIE).value)
        def reserve(_):
            try:return self.access.reserve(principal,{'request_id':uuid4().hex,'clauses':'["Q5"]'})
            except TaskError as exc:return exc.status
        with ThreadPoolExecutor(max_workers=8) as executor:results=list(executor.map(reserve,range(8)))
        self.assertEqual(results.count(True),2);self.assertEqual(results.count(429),6)

    def test_other_member_cannot_read_cancel_or_reuse_task(self):
        self.login();request_id=uuid4().hex;task=self.submit(request_id=request_id).get_json()['task']
        other=self.app.test_client();self.login(self.b,other)
        self.assertEqual(other.get('/api/tasks/'+task['task_id']).status_code,404)
        self.assertEqual(other.post('/api/tasks/'+task['task_id']+'/cancel',json={},headers=self.headers).status_code,404)
        self.assertNotIn(task['task_id'],[t['task_id'] for t in other.get('/api/tasks').get_json()['tasks']])
        self.assertEqual(self.submit(client=other,request_id=request_id).status_code,409)
        self.assertEqual(len(self.launches),1)

    def test_private_report_routes_all_enforce_owner(self):
        self.login();task=self.submit().get_json()['task'];store=self.app.extensions['report_store']
        original=dict(next(iter(store.entries.values())));original['run_dir']=self.tasks.root/task['task_id']
        key='controlled_private_key';store.entries[key]=original
        other=self.app.test_client();self.login(self.b,other)
        with patch.object(store,'refresh',return_value=[]),patch.object(store,'get',return_value={'controlled_fixture':True}):
            for client in (other,self.app.test_client()):
                for suffix in ('','/text','/download','/reviews'):
                    self.assertEqual(client.get('/api/reports/'+key+suffix).status_code,404)
                self.assertEqual(client.get('/print/'+key).status_code,404)
            self.assertEqual(self.client.get('/api/reports/'+key).status_code,200)
        store.entries.pop(key)

    def test_logout_session_expiry_and_revocation_remove_access(self):
        self.login();self.client.post('/api/auth/logout',json={},headers=self.headers)
        self.assertFalse(self.client.get('/api/bootstrap').get_json()['access']['authenticated'])
        self.login()
        with self.access.db() as db:db.execute('UPDATE sessions SET expires=?',(time.time()-1,))
        self.assertEqual(self.submit().status_code,401)
        self.login();self.access.revoke(self.a['id']);self.assertEqual(self.submit().status_code,401)

    def test_only_admin_can_enable_offline_runtime(self):
        self.app.config['OFFLINE_PLAYBACK']=True;self.login()
        self.assertEqual(self.client.post('/api/runtime/enable-realtime',json={},headers=self.headers).status_code,403)
        self.login(self.admin)
        self.assertEqual(self.client.post('/api/runtime/enable-realtime',json={},headers=self.headers).status_code,200)
        self.assertEqual(self.launches,[])

    def test_admin_can_choose_41_and_view_member_task(self):
        self.login();task=self.submit().get_json()['task'];self.login(self.admin)
        self.assertEqual(self.client.get('/api/tasks/'+task['task_id']).status_code,200)
        principal=self.access.principal(self.client.get_cookie(COOKIE).value)
        self.assertTrue(self.access.reserve(principal,{'request_id':uuid4().hex,'clauses':json.dumps(['Q'+str(i) for i in range(1,42)])}))

    def test_lan_host_and_origin_checks(self):
        self.assertEqual(self.client.get('/api/bootstrap',base_url='http://192.168.50.10:8766').status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap',base_url='http://untrusted.invalid').status_code,403)
        self.assertEqual(self.client.post('/api/auth/login',json={'code':self.a['code']},headers={**self.headers,'Origin':'http://untrusted.invalid'}).status_code,403)

    def test_public_snapshot_does_not_automatically_publish_later_reports(self):
        before=self.access.public_ids();self.access.seed_public(['CONTROLLED_later_report'])
        self.assertEqual(self.access.public_ids(),before)

    def test_candidate_addresses_exclude_public_loopback_and_link_local(self):
        for ip in ('192.168.1.23','10.0.0.8','172.16.1.2','100.65.59.182'):
            self.assertTrue(eligible_address(ip))
        for ip in ('127.0.0.1','0.0.0.0','169.254.1.2','8.8.8.8','224.0.0.1','invalid','::1'):
            self.assertFalse(eligible_address(ip))

    def test_anonymous_review_submission_is_rejected(self):
        key=self.client.get('/api/bootstrap').get_json()['reports'][0]['id']
        self.assertEqual(self.client.post('/api/reports/'+key+'/reviews',json={},headers=self.headers).status_code,401)


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(AccessTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    (WEB/'qa/sharing_access_results.json').write_text(json.dumps({'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'model_api_calls':0},indent=2),encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())

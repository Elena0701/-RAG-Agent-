"""Controlled boundary tests; fake subprocess only, never represented as Agent runs."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

WEB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(WEB))
from app import create_app
from task_manager import TaskManager, dump
from agent_worker import Observer, StopService
from auth_helpers import login_as


class Process:
    def __init__(self): self.returncode=None
    def poll(self): return self.returncode
    def terminate(self): self.returncode=-15
    def wait(self,timeout=None): return self.returncode


class TaskTests(unittest.TestCase):
    def setUp(self):
        (WEB/'qa').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='controlled_task_test_',dir=WEB/'qa')
        self.base=Path(self.temp.name)
        self.commands=[]
        def launch(command,**kwargs):
            self.commands.append(command)
            return Process()
        self.manager=TaskManager(self.base/'tasks',launch)
        self.app=create_app(self.base/'reviews',self.manager)
        self.client=self.app.test_client()
        login_as(self.app,self.client)
        self.headers={'X-Workbench-Token':self.client.get('/api/bootstrap').get_json()['review_token']}
        self.threads=patch('task_manager.threading.Thread')
        self.threads.start()

    def tearDown(self):
        self.manager.close()
        self.threads.stop()
        self.temp.cleanup()

    def post(self,content=b'CONTROLLED interface input, not a real Agent result.',name='contract.txt',**values):
        fields={'file':(io.BytesIO(content),name),'clauses':'["Q5","Q8"]','top_k':'5','max_retries':'2','request_id':'a'*32,**values}
        return self.client.post('/api/tasks',data=fields,headers=self.headers,content_type='multipart/form-data')

    def test_request_requires_csrf(self):
        self.assertEqual(self.client.post('/api/tasks',data={}).status_code,403)
        self.assertEqual(self.commands,[])

    def test_status_atomic_replace_retries_transient_windows_sharing_error(self):
        target = self.base/'state.json'
        target.write_text('{"status":"STARTING"}', encoding='utf-8')
        original_replace = Path.replace
        attempts = []
        def sharing_error_then_success(source, destination):
            attempts.append(source)
            if len(attempts) <= 2:
                raise PermissionError('CONTROLLED transient Windows sharing violation')
            return original_replace(source, destination)
        with patch.object(Path, 'replace', sharing_error_then_success), patch('task_manager.time.sleep'):
            dump(target, {'status':'COMPLETED'})
        self.assertEqual(len(attempts), 3)
        self.assertEqual(json.loads(target.read_bytes()), {'status':'COMPLETED'})
        self.assertEqual(list(self.base.glob('*.tmp')), [])

    def test_permanent_status_write_error_is_not_reported_as_success(self):
        target = self.base/'state.json'
        target.write_text('{"status":"STARTING"}', encoding='utf-8')
        with patch.object(Path, 'replace', side_effect=PermissionError('CONTROLLED permanent denial')), patch('task_manager.time.sleep'):
            with self.assertRaises(PermissionError):
                dump(target, {'status':'COMPLETED'})
        self.assertEqual(json.loads(target.read_bytes()), {'status':'STARTING'})
        self.assertEqual(list(self.base.glob('*.tmp')), [])

    def test_upload_validation_blocks_before_launch(self):
        for content,name in ((b'bad','a.exe'),(b'not pdf','fake.pdf'),(b'','empty.txt'),(b'\xff','latin.txt'),(b'\x00','binary.txt')):
            self.assertEqual(self.post(content,name).status_code,400)
        self.assertEqual(self.post(b'x'*(10*1024*1024+1),'large.txt').status_code,413)
        self.assertEqual(self.commands,[])

    def test_clause_and_parameter_validation(self):
        for values in ({'clauses':'["Q42"]'},{'clauses':'[]'},{'clauses':'["Q8","Q8"]'},
                       {'clauses':'[{}]'},{'top_k':'0'},{'max_retries':'3'},{'request_id':'../bad'}):
            self.assertEqual(self.post(**values).status_code,400,values)
        self.assertEqual(self.commands,[])

    def test_large_scope_needs_explicit_confirmation(self):
        self.assertEqual(self.post(clauses=json.dumps(['Q'+str(i) for i in range(1,7)])).status_code,400)
        self.assertEqual(self.commands,[])

    def test_pdf_upload_and_existing_parser_without_model(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        from report_store import ingestion_module
        writer=PdfWriter()
        page=writer.add_blank_page(width=612,height=792)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 72 720 Td (CONTROLLED PDF parser fixture, not an Agent case.) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
        buffer=io.BytesIO();writer.write(buffer)
        response=self.post(buffer.getvalue(),'controlled.pdf')
        self.assertEqual(response.status_code,202)
        folder=self.manager.path(response.get_json()['task']['task_id'])
        parsed=ingestion_module().ingest(next((folder/'input').iterdir()))
        self.assertIn('CONTROLLED PDF parser fixture',parsed.text)
        self.assertEqual(parsed.method,'pypdf')
        self.assertEqual(parsed.pages[0]['page'],1)

    def test_launch_uses_existing_interpreter_and_safe_file(self):
        response=self.post(name='../../合同 name.txt')
        self.assertEqual(response.status_code,202)
        task=response.get_json()['task']
        folder=self.manager.path(task['task_id'])
        self.assertEqual(len(list((folder/'input').iterdir())),1)
        self.assertTrue(self.commands[0][0].endswith('.venv\\Scripts\\python.exe'))
        self.assertEqual(json.loads((folder/'task.json').read_bytes())['clauses'],['Q5','Q8'])
        self.assertEqual(task['completed'],0)
        self.assertIsNone(task['report_id'])

    def test_dedup_and_concurrent_request_protection(self):
        first=self.post().get_json()['task']
        duplicate=self.post()
        self.assertEqual(duplicate.status_code,200)
        self.assertTrue(duplicate.get_json()['duplicate'])
        self.assertEqual(duplicate.get_json()['task']['task_id'],first['task_id'])
        self.assertEqual(self.post(b'different').status_code,409)
        self.assertEqual(self.post(request_id='b'*32).status_code,409)
        self.assertEqual(len(self.commands),1)

    def test_progress_reads_real_lines_and_partial_line_is_ignored(self):
        task=self.post().get_json()['task'];folder=self.manager.path(task['task_id'])
        (folder/'events.jsonl').write_text(json.dumps({'sequence':1,'completed':1,'stage':'decision','message':'CONTROLLED event, not natural run'})+'\n'+ '{"sequence":',encoding='utf-8')
        response=self.client.get('/api/tasks/'+task['task_id']).get_json()['task']
        self.assertEqual(len(response['events']),1)
        self.assertEqual(response['completed'],1)
        self.assertEqual(self.client.get('/api/tasks/'+task['task_id']+'?after=1').get_json()['task']['events'],[])
        with (folder/'events.jsonl').open('ab') as stream:
            stream.write(b'\xe8\xaf')  # Incomplete UTF-8 from an in-flight trailing write.
        self.assertEqual(len(self.client.get('/api/tasks/'+task['task_id']).get_json()['task']['events']),1)
        self.assertEqual(self.client.get('/api/tasks/'+task['task_id']+'?after=-1').status_code,400)
        self.assertEqual(self.client.get('/api/tasks/not-a-task').status_code,404)

    def test_cancel_preserves_input_and_metadata(self):
        task=self.post().get_json()['task'];folder=self.manager.path(task['task_id'])
        before=(folder/'task.json').read_bytes()
        response=self.client.post('/api/tasks/'+task['task_id']+'/cancel',json={},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()['task']['status'],'CANCELLED')
        self.assertEqual((folder/'task.json').read_bytes(),before)
        self.assertEqual(self.client.post('/api/tasks/'+task['task_id']+'/cancel',json={},headers=self.headers).status_code,409)

    def test_restarted_server_does_not_rerun_dead_worker(self):
        task=self.post().get_json()['task'];folder=self.manager.path(task['task_id'])
        (folder/'process.json').write_text('{"pid":123456789}',encoding='utf-8')
        self.manager.processes[task['task_id']].terminate()
        del self.manager.processes[task['task_id']]
        with patch('task_manager.pid_alive',return_value=False):
            result=self.manager.status(task['task_id'])
        self.assertEqual(result['status'],'INTERRUPTED')
        self.assertEqual(len(self.commands),1)

    def test_two_service_errors_stop_and_redact_controlled_secret(self):
        folder=self.base/'observer';folder.mkdir()
        observer=Observer(folder,{'clauses':['Q8'],'max_retries':2},['CONTROLLED_PRIVATE_VALUE'])
        class AuthError(Exception): status_code=401
        def failing(): raise AuthError('CONTROLLED injected auth error')
        with self.assertRaises(AuthError): observer.observe_api('extraction',[],failing,lambda x:{})
        with self.assertRaises(StopService): observer.observe_api('extraction',[],failing,lambda x:{})
        observer.emit('extraction','CONTROLLED_PRIVATE_VALUE')
        self.assertNotIn('CONTROLLED_PRIVATE_VALUE',(folder/'events.jsonl').read_text(encoding='utf-8'))
        self.assertEqual(observer.stats['failed_calls'],2)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TaskTests))
    (WEB/'qa/task_test_results.json').write_text(json.dumps({'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
       'real_model_calls':0,'scope':'controlled fake subprocess/interface tests; excluded from natural Agent results'},indent=2),encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())

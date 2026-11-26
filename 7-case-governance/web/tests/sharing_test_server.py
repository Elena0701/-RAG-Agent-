"""Isolated browser fixture: real auth/routes, fake subprocess, no model/network."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading

WEB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(WEB))
from app import create_app
from task_manager import TaskManager
from flask import jsonify
from werkzeug.serving import make_server


class ControlledProcess:
    returncode=None
    def poll(self):return self.returncode
    def terminate(self):self.returncode=-15
    def wait(self,timeout=None):return self.returncode


if __name__=='__main__':
    original=socket.socket.connect
    def connect(self,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','localhost','::1'):
            raise OSError('CONTROLLED_AUTH_QA: outbound network blocked')
        return original(self,address)
    socket.socket.connect=connect
    qa=WEB/'qa';qa.mkdir(exist_ok=True);stop=threading.Event();launches=[]
    with tempfile.TemporaryDirectory(prefix='controlled_sharing_browser_',dir=qa) as directory:
        temporary=Path(directory)
        def fake_launch(command,**kwargs):launches.append(command);return ControlledProcess()
        manager=TaskManager(temporary/'tasks',fake_launch)
        manager._monitor=lambda *args:None
        app=create_app(temporary/'data',manager)
        app.config['ISOLATED_AUDIT']=True
        access=app.extensions['access_control']
        fixture={role:access.create_invite('CONTROLLED UI '+role,role='admin' if role=='admin' else 'member') for role in ('member_a','member_b','admin')}
        fixture['temporary_directory']=str(temporary)
        (qa/'sharing_test_fixture.json').write_text(json.dumps(fixture,indent=2),encoding='utf-8')
        @app.get('/api/qa/state')
        def state():return jsonify(controlled_subprocess_launches=len(launches),model_api_calls=0)
        @app.post('/api/qa/shutdown')
        def shutdown():stop.set();return jsonify(stopping=True)
        server=make_server('127.0.0.1',8774,app,threaded=True);server.timeout=1
        print('CONTROLLED_AUTH_QA_URL=http://127.0.0.1:8774; fake launcher; zero model calls',flush=True)
        try:
            while not stop.is_set():server.handle_request()
        finally:
            manager.close();server.server_close()
            (qa/'sharing_test_fixture.json').unlink(missing_ok=True)
            print('CONTROLLED_AUTH_QA_STOPPED; fixture credentials and temporary data removed',flush=True)

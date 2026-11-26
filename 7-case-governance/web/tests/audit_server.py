"""Isolated OFFLINE browser-audit server. Review writes are temporary controlled tests."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading

WEB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(WEB))
from app import create_app
from flask import jsonify
from werkzeug.serving import make_server


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8770)
    args=parser.parse_args()
    qa=WEB/'qa';qa.mkdir(exist_ok=True)
    original_connect=socket.socket.connect
    def local_connect(self,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','localhost','::1'):
            raise OSError('OFFLINE_QA: outbound network forbidden')
        return original_connect(self,address)
    socket.socket.connect=local_connect
    stop=threading.Event()
    with tempfile.TemporaryDirectory(prefix='isolated_visual_audit_',dir=qa) as temporary:
        app=create_app(data_dir=Path(temporary),offline=True)
        app.config['ISOLATED_AUDIT']=True
        app.config['ALLOW_LIVE_MODE_SWITCH']=False
        invitation=app.extensions['access_control'].create_invite('CONTROLLED isolated audit admin',role='admin')
        (qa/'audit_login.json').write_text(json.dumps({'code':invitation['code']}),encoding='utf-8')
        @app.post('/api/qa/shutdown')
        def shutdown():
            stop.set()
            return jsonify(stopping=True)
        server=make_server('127.0.0.1',args.port,app,threaded=True)
        server.timeout=1
        (qa/'audit_server.json').write_text(json.dumps({'pid':os.getpid(),'port':args.port,'temporary_reviews':temporary,
          'mode':'offline','outbound_network':'blocked','review_semantics':'controlled UI tests only; removed on shutdown'},indent=2),encoding='utf-8')
        print(f'OFFLINE_AUDIT_URL=http://127.0.0.1:{args.port}',flush=True)
        try:
            while not stop.is_set():server.handle_request()
        finally:
            app.extensions['task_manager'].close()
            server.server_close()
            (qa/'audit_login.json').unlink(missing_ok=True)
            print('OFFLINE_AUDIT_STOPPED temporary review records removed',flush=True)

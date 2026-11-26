"""Export selected REAL reports into one self-contained, network-free HTML.

Read-only: no Agent/client imports, no credentials or gold annotations in output.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

sys.dont_write_bytecode = True
HERE=Path(__file__).resolve().parent
WEB=HERE.parent
ROOT=WEB.parents[1]
sys.path.insert(0,str(WEB))
from report_store import ReportStore, clean

SELECTED=("CUAD-001_d0873843","CUAD-004_7afb02da","CUAD-008_ba9c81fe")


def sha(content):
    return hashlib.sha256(content).hexdigest()


def safe_json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')


def replace_once(source,old,new):
    if source.count(old)!=1:
        raise ValueError('Source integration anchor changed; inspect exporter: '+old[:65])
    return source.replace(old,new,1)


def verify_no_credentials(text):
    # Read values only for a private equality scan; never print or export them.
    from dotenv import dotenv_values
    for path in (ROOT/'4-agent/code/.env',ROOT/'4-agent/code/agents/.env',ROOT/'4-agent/code/tools/rag_tool/deepseek.local.env'):
        if path.is_file():
            for name,value in dotenv_values(path).items():
                if name.endswith('API_KEY') and value and value in text:
                    raise ValueError('Credential scan blocked export; no credential was printed')
    if clean(text)!=text:
        raise ValueError('Possible credential pattern in selected source; original preserved, export stopped')


def build():
    store=ReportStore();rows=store.list();cases={};sources=[]
    for document_id in SELECTED:
        found=[r for r in rows if r['document_id']==document_id]
        if len(found)!=1:
            raise ValueError('Missing or ambiguous selected real report: '+document_id)
        identity=found[0];key=identity['id'];entry=store.entries[key]
        report=store.get(key);text=store.text(key);raw=entry['path'].read_bytes()
        if not text['available']:
            raise ValueError('Required source text/hash unavailable: '+document_id)
        if report['report_sha256']!=sha(raw):
            raise ValueError('Report changed while exporting: '+document_id)
        verify_no_credentials(raw.decode('utf-8'))
        case={'schema':'mingqi-case-v1','identity':identity,'report':report,'text':text,
              'native_report_base64':base64.b64encode(raw).decode('ascii'),
              'provenance':{'kind':'existing_real_agent_run','sample_split':'train / development',
                  'source_report':report['source_file'],'report_sha256':sha(raw),
                  'raw_contract_sha256':text['raw_sha256'],'normalized_contract_sha256':text['normalized_sha256'],
                  'annotation_files_included':False,'model_api_called_during_export':False}}
        verify_no_credentials(json.dumps(case,ensure_ascii=False))
        cases[key]=case
        sources.append({'id':key,'document_id':document_id,'sample':identity.get('sample'),
            'source_report':report['source_file'],'report_sha256':sha(raw),'reviewed_tasks':len(report['checks']),
            'raw_contract_sha256':text['raw_sha256'],'normalized_contract_sha256':text['normalized_sha256'],
            'sample_contract_file':'sample_contracts/'+identity['sample']+'.txt'})
    system={**store.system(),'reports':[case['identity'] for case in cases.values()],
            'offline_mode':True,'realtime_enabled':False,'model_api_calls_enabled':False,
            'can_enable_realtime':False,'showcase_mode':True,'access':{'authenticated':False}}
    manifest={'format':'mingqi-showcase-v1','built_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
              'name':'明契 · 交互式HTML展示版','purpose':'真实历史案例回放，不执行新合同AI审查',
              'case_count':len(cases),'sources':sources,
              'excluded':['model credentials','invitation codes and database','gold annotations','virtual environment','model cache','private uploads'],
              'model_api_calls':0}
    payload={'system':system,'cases':cases,'manifest':manifest}
    app=(WEB/'static/app.js').read_text(encoding='utf-8')
    begin=app.index('async function api(');end=app.index('\nfunction go(',begin)
    app=app[:begin]+'async function api(path,options={}){return showcaseApi(path,options);}\n'+app[end:]
    app=replace_once(app,'function renderWorkbench(){','function renderUnusedRealtimeWorkbench(){')
    app=replace_once(app,'async function loadCase(id){','async function loadRecordedCase(id){')
    app=app.replace('loadCase.ticket','loadRecordedCase.ticket')
    app=replace_once(app,'function renderOverview(){','function renderRecordedOverview(){')
    app=replace_once(app,'function filterTable(){','function filterRecordedTable(){')
    app=replace_once(app,'):state.report.checks;','):scScopedRows();')
    app=replace_once(app,'function renderSystem(){','function renderUnusedRealtimeSystem(){')
    app=replace_once(app,'function renderExecution(){','function renderRecordedExecution(){')
    app=replace_once(app,'function renderReview(){','function renderRecordedReview(){')
    app=replace_once(app,'function bindView(){','function bindRecordedView(){')
    app=replace_once(app,'function updateRuntimeMode(){','function updateUnusedRuntimeMode(){')
    app=replace_once(app,'if(!accessInfo().authenticated){e.preventDefault();openAccessDialog();return;}','/* Offline local notes have no server login or authority claim. */')
    app=replace_once(app,'history.replaceState(null,"",`?report=${encodeURIComponent(id)}${location.hash||`#/${state.view}`}`);','showcaseUrl(id);')
    app=replace_once(app,'\ninit();','\n')
    app=replace_once(app,':(state.system.offline_mode||requested?"overview":"workbench");',':(requested?"overview":"workbench");')
    app=app.replace('本次实际审查','原始报告实际审查')
    app=app.replace('读取既有及网页新生成的原始JSON报告；受控测试输出不混入真实案例。历史日志不完整时仅展示实际保存的内容。',
                    '此处展示内置真实报告及明确导入的案例包，不创建新的Agent任务。缺失的日志、时间或坐标不会补造。')
    app=app.replace('保存独立复核记录','保存本地意见').replace('已保存的本项操作','本浏览器中的本地意见')
    app=app.replace('已保存独立复核记录，原始Agent报告未修改。','已保存本地意见；未提交服务器，原始Agent报告未修改。')
    app=app.replace('未执行业务规则核验','未执行业务规则核验')
    scripts='\n'.join([(WEB/'static/reader.js').read_text(encoding='utf-8'),app,(HERE/'showcase.js').read_text(encoding='utf-8')])
    scripts=re.sub(r'</script',r'<\\/script',scripts,flags=re.I)
    styles=(WEB/'static/style.css').read_text(encoding='utf-8')+'\n'+(HERE/'showcase.css').read_text(encoding='utf-8')
    html=(WEB/'templates/index.html').read_text(encoding='utf-8')
    html=re.sub(r'<link rel="stylesheet"[^>]+>','',html)
    html=re.sub(r'<script\b[^>]*>.*?</script>','',html,flags=re.S)
    html=re.sub(r'<dialog\b[^>]*\bid="access-dialog"[^>]*>.*?</dialog>','',html,flags=re.S)
    html=html.replace('<title>明契 · 合同初审工作台</title>','<title>明契 · 交互式HTML展示版</title>')
    policy="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    html=html.replace('</head>',f'<meta http-equiv="Content-Security-Policy" content="{policy}"><style>{styles}</style></head>')
    html=html.replace('</body>',f'<script id="showcase-data" type="application/json">{safe_json(payload)}</script><script>{scripts}</script></body>')
    verify_no_credentials(html)
    output=HERE/'dist';output.mkdir(exist_ok=True)
    (output/'index.html').write_bytes(html.encode('utf-8'))
    (output/'source_manifest.json').write_bytes(json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8'))
    sample_directory=output/'sample_contracts';sample_directory.mkdir(exist_ok=True)
    for case in cases.values():
        text=case['text']
        if not text['raw_mapping_available'] or not isinstance(text['raw_text'],str):
            raise ValueError('A verified original TXT sample is required for upload demonstration')
        raw_contract=text['raw_text'].encode('utf-8')
        if sha(raw_contract)!=text['raw_sha256']:
            raise ValueError('Original TXT sample hash mismatch; original preserved')
        (sample_directory/(case['identity']['sample']+'.txt')).write_bytes(raw_contract)
    (output/'README.txt').write_bytes((
        '明契 · 交互式HTML展示版\n\n解压后双击index.html，使用Chrome或Edge打开。\n无需Python、服务器、网络、登录或API密钥。\n'
        '内置CUAD-001/004/008真实历史案例，CUAD-004含41类审查。\n'
        '审查工作台支持本地选择或拖入PDF/TXT、TXT正文预览、41类条款选择，并按完整文件哈希匹配真实历史报告。\n'
        '先选择sample_contracts中的TXT样本，再点击“匹配并查看真实审查记录”；所选条款只限定查看范围，原报告统计不改写。\n'
        '支持筛选、证据高亮、逐条日志回放、原生JSON下载、打印、本地意见及案例包导入导出。\n'
        '本展示版不对新合同进行AI审查。日志属于已保存运行，不是实时进度。\n'
        '本地意见不提交服务器，不修改原始Agent报告，未填写时不会生成任何复核记录。\n'
        '请不要把静态展示版内置材料当作受邀请码保护的数据；复制文件即能读取材料。\n'
        '未部署公网；如需发布链接，应先确认材料适合公开，再选择静态托管服务。\n'
        '来源、哈希和审查数量见source_manifest.json。\n').encode('utf-8'))
    archive=HERE/'MingQi_HTML_Showcase.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for name in ('index.html','README.txt','source_manifest.json'):
            bundle.write(output/name,arcname='明契_HTML展示版/'+name)
        for sample in (sample_directory/(case['identity']['sample']+'.txt') for case in cases.values()):
            bundle.write(sample,arcname='明契_HTML展示版/sample_contracts/'+sample.name)
    (WEB/'qa/showcase_build_result.json').write_text(json.dumps({'html':str(output/'index.html'),'zip':str(archive),
        'html_bytes':len(html.encode('utf-8')),'sources':sources,'model_api_calls':0},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Built MingQi self-contained HTML:',len(html.encode('utf-8')),'bytes;',len(cases),'real cases; zero model calls')
    return manifest


if __name__=='__main__':
    build()

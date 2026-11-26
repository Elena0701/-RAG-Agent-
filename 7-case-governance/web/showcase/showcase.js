"use strict";
// Browser-only presentation adapter. No network, Agent, model or login implementation.
const SC_DATA=JSON.parse(document.getElementById('showcase-data').textContent);
const SC_CASES=new Map(Object.entries(SC_DATA.cases));
const SC_NOTE_KEY='mingqi.showcase.local-notes.v1';
let scNotes={};try{scNotes=JSON.parse(localStorage.getItem(SC_NOTE_KEY)||'{}');if(!scNotes||Array.isArray(scNotes)||typeof scNotes!=='object')scNotes={};}catch{}
let scStep=0,scStepCase='',scStorageSaved=true;
let scContract=null,scReading=false,scFileVersion=0,scViewSelection=null;
const taskActive=()=>false;
const livePanel=()=>'';
const bindLive=()=>{};
const bindAccess=()=>{};
const restoreTask=async()=>{};
const accessInfo=()=>({authenticated:false});
const taskHistory=()=>'';
views.workbench=['审查工作台','本地读取合同、选择条款，并匹配该合同已经完成的真实审查记录。'];
views.execution=['运行记录回放','逐条查看已保存日志与实际补查，不运行模型，不模拟实时进度。'];
views.review=['人工复核与本地意见','查看真实升级事项；本地填写的意见单独保存，不回写Agent报告。'];

function scClone(value){return JSON.parse(JSON.stringify(value));}
function scCase(id=state.caseId){const c=SC_CASES.get(id);if(!c)throw new Error('该案例未包含在展示包中');return c;}
function scRows(){return [...SC_CASES.values()].map(c=>c.identity);}
async function loadCase(id){scViewSelection=null;return loadRecordedCase(id);}
function showcaseUrl(id){try{const url=new URL(location.href);url.searchParams.set('report',id);if(!url.hash)url.hash='/'+state.view;history.replaceState(null,'',url);}catch{/* file:// history may be restricted; navigation and case switch still work. */}}
function scSaveNotes(){try{localStorage.setItem(SC_NOTE_KEY,JSON.stringify(scNotes));scStorageSaved=true;}catch{scStorageSaved=false;}}
function scLocalNotes(c){const rows=scNotes[c.report.report_sha256];return Array.isArray(rows)?rows:[];}
async function showcaseApi(path,options={}){
  const method=options.method||'GET';
  if(path==='/api/bootstrap')return scClone({...SC_DATA.system,reports:scRows()});
  if(path==='/api/reports')return {reports:scClone(scRows())};
  const match=path.match(/^\/api\/reports\/([a-zA-Z0-9_-]+)(?:\/(text|reviews))?$/);
  if(!match||!SC_CASES.has(match[1]))throw new Error('展示版只读取内置或明确导入的案例，不调用服务器或模型');
  const c=scCase(match[1]);
  if(method==='GET')return scClone(match[2]==='text'?c.text:match[2]==='reviews'?{records:scLocalNotes(c)}:c.report);
  if(method==='POST'&&match[2]==='reviews'){
    const body=JSON.parse(options.body||'{}');const valid=c.report.checks.some(x=>x.qid===body.qid&&x.next_action==='ESCALATE')||c.report.supplemental.some(x=>x.question_id===body.qid);
    if(!valid||!['accept','correct','reject','materials'].includes(body.action)||typeof body.reviewer!=='string'||!body.reviewer.trim()||body.reviewer.length>80||typeof body.note!=='string'||!body.note.trim()||body.note.length>5000||typeof body.corrected_answer!=='string'||body.corrected_answer.length>2000||(body.action==='correct'&&!body.corrected_answer.trim()))throw new Error('请完整填写本地意见及必要的修正答案');
    const record={id:crypto.randomUUID?.()||'local-'+Date.now(),created_at:new Date().toISOString(),
      source:'member7_showcase_local_user_note',status:'LOCAL_USER_NOTE_NOT_SUBMITTED',
      report_sha256:c.report.report_sha256,document_id:c.identity.document_id,qid:body.qid,action:body.action,
      reviewer:body.reviewer.trim(),note:body.note.trim(),corrected_answer:body.corrected_answer,
      original_agent_report_modified:false,submitted_to_server:false};
    scNotes[c.report.report_sha256]=[...scLocalNotes(c),record];scSaveNotes();return {record};
  }
  throw new Error('独立HTML不执行新的Agent审查，也不提交服务器记录');
}

function updateRuntimeMode(){
  $('#connection-state').textContent='独立HTML · 真实案例回放';
  $('#account-controls').innerHTML='<span class="pill neutral">无需登录 / 不调用API</span>';
  $('.local-label').textContent='明契 · 离线交互展示';
  $('#page-subtitle').textContent=views[state.view]?.[1]||'';
}

function renderWorkbench(){
  const groups=state.system.task_groups.map(group=>{const clauses=state.system.catalog.filter(c=>c.group===group);return `<section class="clause-group"><div class="group-head"><label><input type="checkbox" class="group-check" data-group="${esc(group)}" ${clauses.every(c=>state.selected.has(c.id))?'checked':''}>${esc(group)}</label><span>${clauses.length}类</span></div><div class="clause-options">${clauses.map(c=>`<label class="clause-option"><input type="checkbox" class="clause-check" value="${c.id}" ${state.selected.has(c.id)?'checked':''}><span><strong>${c.id}　${esc(c.label)}</strong><small>${esc(c.name)}</small></span></label>`).join('')}</div></section>`;}).join('');
  const selected=[...SC_CASES.values()],cfg=state.report?.configuration||{};
  return `<section class="access-banner section-gap"><span class="access-mark">${icon('history')}</span><div><strong>离线回放模式 · 文件读取和条款选择均可交互</strong><p>按合同文件SHA-256匹配已有真实报告，不重新调用Agent。新合同需要使用完整实时版审查。</p></div><span class="pill blue">本地读取 / 不调用API</span></section>
  <div class="workbench-grid section-gap"><div><section class="panel"><div class="panel-head"><h2 class="step-heading"><span class="step-number">1</span>选择合同文件</h2><span class="meta">PDF / TXT · 本地读取</span></div><div class="panel-body"><label class="upload-zone" id="upload-zone" for="contract-file"><span class="upload-symbol">${icon('upload')}</span><strong>点击选择，或将合同拖放到这里</strong><p>支持PDF、UTF-8 TXT，单个文件不超过10 MB</p><p>文件只在浏览器中读取；TXT预览正文，PDF核对文件信息与指纹。</p></label><input id="contract-file" type="file" accept=".pdf,.txt" hidden><div id="file-meta">${scFileMeta()}</div>${scFilePreview()}<div id="showcase-match-state">${scMatchState()}</div></div></section>
  <section class="panel section-gap"><div class="panel-head"><h2 class="step-heading"><span class="step-number">2</span>选择条款</h2><span class="meta" id="selected-total">已选 ${state.selected.size} / 41 类</span></div><div class="panel-body"><div class="shortcut-bar"><span>快捷选择</span><button class="shortcut" data-preset="basic">基础信息 Q1–Q5</button><button class="shortcut" data-preset="focus">五类重点条款</button><button class="shortcut" data-preset="all">全部41类</button><button class="shortcut" data-preset="none">清空</button></div><p class="metadata-caption">选择只限定查看范围，不改变原报告的实际审查范围；没有审查过的类别仍显示未审查。</p>${groups}</div></section>
  <section class="panel section-gap"><div class="panel-head"><h2>展示案例包与本地意见</h2><span class="pill neutral">本地文件</span></div><div class="panel-body"><p class="detail-prose">也可加载此前导出的完整JSON展示案例包。原生Agent JSON单独通常不含合同全文。</p><input id="showcase-import" type="file" accept=".json,application/json"><div class="showcase-aux-actions"><button class="btn" id="showcase-export-case">导出当前展示案例包</button><button class="btn" id="showcase-export-notes">导出本地复核意见</button></div><p class="metadata-caption">案例包上限20 MB；不向服务器上传。新导入的来源仍需由提供者确认。</p></div></section></div>
  <aside><section class="panel"><div class="panel-head"><h2>审查参数</h2><span class="pill neutral">已保存参数</span></div><div class="panel-body"><p class="metadata-caption">当前已存案例：${esc(state.report?.identity.title||'未选择')}。参数来自这份历史报告，不会用于重跑。</p><label class="settings-field"><span><strong>检索候选数 top-k</strong><small>原运行参数，只读</small></span><input id="top-k" type="number" disabled value="${esc(cfg.top_k??'')}" placeholder="未记录"></label><label class="settings-field"><span><strong>最大补查次数</strong><small>原运行参数，只读</small></span><input id="retry-limit" type="number" disabled value="${esc(cfg.max_retries??'')}" placeholder="未记录"></label><div class="side-kv"><span>条款目录</span><strong>41类目录快照</strong></div><div class="side-kv"><span>原系统检索</span><strong>Embedding + BM25</strong></div><div class="side-kv"><span>规则接口</span><strong>Q6–Q41 · 36类</strong></div><div class="section-gap">${notice('先选择合同和条款，再按文件字节哈希查找真实历史报告。匹配不会生成新答案、新风险判断或新的审查时间。')}</div><button class="btn primary full-width section-gap" id="match-review" ${scReading?'disabled':''}>${icon('search')}${scReading?'正在读取本地文件':'匹配并查看真实审查记录'}</button><p class="metadata-caption">无法匹配时不展示其他合同的结果，也不模拟审查进度。</p></div></section>
  <section class="panel section-gap"><div class="panel-head"><h2>从真实案例开始</h2><span class="meta">${selected.length}份</span></div><div class="panel-body">${selected.map(c=>`<div class="showcase-sample"><button class="quick-case showcase-case" data-load-case="${esc(c.identity.id)}"><span class="case-id">${esc(c.identity.sample||'导入')}</span><span><strong>${esc(c.identity.label||c.identity.title)}</strong><small>${c.report.stats.reviewed}项原始审查 · ${c.report.stats.manual}项人工升级</small></span>${icon('arrow')}</button>${c.text.raw_mapping_available?`<button class="btn small full-width" data-download-contract="${esc(c.identity.id)}">${icon('download')}下载TXT样本后选择</button>`:'<p class="metadata-caption">未包含可核对的原始TXT文件</p>'}</div>`).join('')}</div></section></aside></div>`;
}

function scFileMeta(){
  if(!scContract)return scReading?'<p class="metadata-caption">正在读取所选文件的实际字节…</p>':'';
  return `<div class="file-picked">${icon('document')}<div><strong>${esc(scContract.name)}</strong><small>${esc(scContract.format)} · ${(scContract.size/1024).toFixed(1)} KB · ${scReading?'正在读取':scContract.error?'读取失败，未上传':'已在本地读取，未上传'}</small></div><button class="btn small" id="clear-contract" type="button">移除</button></div>${scContract.sha?`<p class="showcase-file-hash">SHA-256 <code>${esc(scContract.sha)}</code></p>`:''}`;
}
function scFilePreview(){
  if(!scContract||scContract.error)return '';
  if(scContract.format==='PDF')return '<div class="notice section-gap">已读取PDF文件信息与字节指纹；本展示版不解析PDF正文，也不生成引文位置。只有存在相同文件的历史报告时才能回放。</div>';
  if(scContract.preview==null)return '';
  return `<details id="showcase-file-preview" class="showcase-file-preview section-gap" ${scContract.previewOpen?'open':''}><summary>TXT原文预览 · ${scContract.characters.toLocaleString()}个Unicode字符${scContract.truncated?' · 仅预览前20,000字符':''}</summary><pre id="local-contract-preview">${esc(scContract.preview)}</pre><p class="metadata-caption">预览为所选文件原文，未规范化；匹配使用整个文件的原始字节哈希，不混用Agent证据偏移。</p></details>`;
}
function scMatchState(){
  if(!scContract)return '';
  if(scContract.error)return notice(scContract.error);
  if(scContract.outcome==='NONE')return notice('未找到对应历史报告。本展示版不对新合同执行AI审查，请使用完整实时版；不会套用其他合同结果。文件名相同也不能代替字节哈希一致。');
  if(scContract.outcome==='CHOICES')return `<div class="section-gap">${notice('同一合同有多份已保存报告，请选择要查看的真实运行，再点击匹配按钮。')}<label class="access-label" for="showcase-report-choice">选择已存报告</label><select id="showcase-report-choice"><option value="">请选择运行记录</option>${scContract.matches.map(id=>{const c=scCase(id);return `<option value="${esc(id)}" ${scContract.chosen===id?'selected':''}>${esc(c.identity.document_id)} · ${esc(c.identity.date||'时间未记录')} · ${c.report.stats.reviewed}项</option>`;}).join('')}</select></div>`;
  if(scContract.outcome==='MATCHED'){const c=scCase(scContract.chosen);return notice(`已按完整文件哈希匹配：${c.identity.title}。原报告实际审查${c.report.stats.reviewed}类，原运行时间${c.identity.date||'未记录'}；这是历史结果，不是新审查。`);}
  return scContract.sha?'<p class="metadata-caption section-gap">文件读取和SHA-256计算已完成，等待点击“匹配并查看真实审查记录”。</p>':'';
}
async function scChooseContract(file){
  if(!file)return;
  const version=++scFileVersion;scReading=true;scViewSelection=null;scContract={name:file.name,size:file.size,format:file.name.split('.').pop().toUpperCase(),preview:null};render();
  try{
    if(!/\.(pdf|txt)$/i.test(file.name))throw new Error('请选择PDF或UTF-8 TXT合同');
    if(file.size===0||file.size>10*1024*1024)throw new Error('文件须大于0且不超过10 MB');
    const bytes=new Uint8Array(await file.arrayBuffer());if(version!==scFileVersion)return;
    if(scContract.format==='PDF'){
      if(new TextDecoder().decode(bytes.slice(0,5))!=='%PDF-')throw new Error('PDF文件头无效，请选择真实PDF');
    }else{
      let text;try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{throw new Error('TXT须为UTF-8编码，请另存为UTF-8后选择');}
      if(!text.trim()||text.includes('\0'))throw new Error('TXT为空或包含二进制字符');
      const characters=Array.from(text);Object.assign(scContract,{preview:characters.slice(0,20000).join(''),characters:characters.length,truncated:characters.length>20000});
    }
    const hash=await scSha(bytes);if(version!==scFileVersion)return;scContract.sha=hash;
  }catch(error){if(version===scFileVersion)scContract.error=error.message;}
  finally{if(version===scFileVersion){scReading=false;if(state.view==='workbench')render();}}
}
async function scMatchContract(){
  if(scReading)return;
  if(!scContract||scContract.error||!scContract.sha){notify('请先选择并成功读取PDF或UTF-8 TXT合同');return;}
  if(!state.selected.size){notify('请至少选择一个查看条款');return;}
  const ids=[...SC_CASES].filter(([,c])=>c.text.raw_sha256===scContract.sha).map(([id])=>id);
  if(!ids.length){scContract.outcome='NONE';scContract.chosen=null;scViewSelection=null;render();return;}
  if(ids.length>1&&!ids.includes(scContract.chosen)){scContract.outcome='CHOICES';scContract.matches=ids;render();return;}
  const id=ids.length===1?ids[0]:scContract.chosen;scContract.chosen=id;scContract.outcome='MATCHED';
  scViewSelection={caseId:id,qids:[...state.selected],fileName:scContract.name,sha:scContract.sha};
  try{await loadRecordedCase(id);go('overview');render();notify('已匹配并加载该合同的真实历史报告，没有启动新的AI审查。');}catch(error){scViewSelection=null;notify(error.message);}
}
async function scDownloadContract(id){
  try{const c=scCase(id);if(!c.text.raw_mapping_available||typeof c.text.raw_text!=='string')throw new Error('没有可核对的原始TXT材料');const bytes=new TextEncoder().encode(c.text.raw_text);if(await scSha(bytes)!==c.text.raw_sha256)throw new Error('原始TXT哈希不一致，停止导出');scDownload((c.identity.sample||c.identity.document_id)+'.txt',bytes,'text/plain;charset=utf-8');}catch(error){notify(error.message);}
}
function scScopeNotice(){
  if(!scViewSelection||scViewSelection.caseId!==state.caseId)return '';
  const count=scViewSelection.qids.filter(id=>state.report.checks.some(c=>c.qid===id)).length;
  return `<section class="panel showcase-scope section-gap" id="showcase-selection-scope"><div><strong>文件哈希已匹配 · 当前按所选条款查看历史结果</strong><p>文件：${esc(scViewSelection.fileName)}。所选${scViewSelection.qids.length}类中，原报告已审查${count}类、未审查${scViewSelection.qids.length-count}类。下方统计仍是原报告完整的${state.report.stats.reviewed}项结果；没有重新调用Agent。</p></div><button class="btn small" id="showcase-full-report">查看完整原始报告</button></section>`;
}
function renderOverview(){return scScopeNotice()+renderRecordedOverview();}
function scScopedRows(){
  if(!scViewSelection||scViewSelection.caseId!==state.caseId)return state.report.checks;
  const qids=new Set(scViewSelection.qids);
  const missing=state.system.catalog.filter(c=>qids.has(c.id)&&!check(c.id)).map(c=>({qid:c.id,label:c.label,category:c.name,group:c.group,unreviewed:true,risk_levels:[]}));
  return [...state.report.checks,...missing].sort((a,b)=>Number(a.qid.slice(1))-Number(b.qid.slice(1)));
}
function filterTable(){
  filterRecordedTable();if(!scViewSelection||scViewSelection.caseId!==state.caseId)return;
  const qids=new Set(scViewSelection.qids);document.querySelectorAll('#report-rows tr[data-evidence]').forEach(row=>{if(!qids.has(row.dataset.evidence))row.remove();});
  const count=document.querySelectorAll('#report-rows tr[data-evidence]').length;
  if(!count)$('#report-rows').innerHTML='<tr><td colspan="7" class="empty-state">所选条款中没有符合当前筛选条件的项目</td></tr>';
  $('#report-count').textContent=`本次选择${qids.size}类 · 当前符合筛选${count}类 · 原始报告实际审查${state.report.stats.reviewed}项（未重新审查）`;
}

function renderExecution(){
  const logs=taskLogs(state.qid);
  const stamp=state.caseId+':'+state.qid;if(stamp!==scStepCase){scStep=0;scStepCase=stamp;}
  scStep=Math.max(0,Math.min(scStep,logs.length-1));const current=logs[scStep];
  return `<section class="panel showcase-stepper"><div class="panel-head"><div><h2>逐条查看真实日志</h2><p>按钮只切换保存的记录，不代表新的运行或真实耗时。</p></div><span class="pill blue">${logs.length?scStep+1:0} / ${logs.length}条</span></div><div class="panel-body"><div class="showcase-step-controls"><button class="btn small" id="sc-first" ${!logs.length||scStep===0?'disabled':''}>回到首条</button><button class="btn small" id="sc-prev" ${!logs.length||scStep===0?'disabled':''}>上一条记录</button><button class="btn primary small" id="sc-next" ${!logs.length||scStep===logs.length-1?'disabled':''}>下一条记录</button><button class="btn small" id="sc-retry" ${!logs.some(x=>/补查|重试/.test(x.content))?'disabled':''}>定位补查记录</button></div><p class="metadata-caption">${current?`原始记录 ${esc(current.index??scStep+1)} · ${esc(current.timestamp||'时间未记录')}`:'没有可用的逐条记录'}</p><pre class="showcase-log-slice">${esc(current?.content||'未记录')}</pre></div></section><div class="section-gap">${renderRecordedExecution()}</div>`;
}

function renderReview(){
  return `${notice('本页可查看原始人工升级事项。下方填写的内容是本浏览器的本地意见，不提交服务器、不改变Agent统计，也不自动成为论文中的已确认人工复核结果。')}
  <div class="showcase-note-actions section-gap"><button class="btn" id="showcase-export-notes">${icon('download')}导出本地意见JSON</button><button class="btn" id="showcase-clear-notes">清除本地意见</button><span class="metadata-caption">${scStorageSaved?'支持时保存在本浏览器；换电脑请先导出。':'浏览器禁止持久存储，请务必导出，关闭页面会丢失。'}</span></div>${renderRecordedReview()}`;
}

function renderSystem(){
  return `<section class="panel"><div class="panel-head"><h2>明契 · 交互式HTML展示版</h2><span class="pill blue">${esc(SC_DATA.manifest.format)}</span></div><div class="panel-body prose"><p>本文件将既有网页的报告、证据阅读和日志展示功能，与选定真实运行快照打包。打开和交互无需Python、Flask、模型服务、邀请码或网络，不会启动Agent。</p><p>现有完整系统支持41类条款事实抽取与证据核验。Q1–Q5不执行业务规则核验；Q6–Q41共36类提供统一规则接口。单份报告只展示实际运行过的类别，未审查项不是No。</p><p>真实运行链路：合同解析 → 任务规划 → Embedding与BM25混合检索 → LLM事实抽取 → 证据核验 → 业务规则 → Agent决策 → 补查或人工升级 → 原生报告。这里只回放已有记录。</p><p>原始报告、引用、字符位置和规则结果保持不变。规范化文本和原始TXT坐标分别核对；没有映射时不进行错误定位。TXT不虚构PDF页码。</p></div></section><div class="two-columns section-gap"><section class="panel"><div class="panel-head"><h2>构建时的政策快照</h2></div><div class="panel-body">${['FLAG_IF_CONDITION','REQUIRE_PRESENT','CONTEXT_REVIEW','INFORMATION_ONLY'].map(key=>`<div class="mode-row"><strong class="mode-count">${SC_DATA.system.mode_counts[key]||0}</strong><div><strong>${esc(SC_DATA.system.mode_names[key]||key)}</strong><small>${esc(key)}</small></div></div>`).join('')}<p class="metadata-caption">并非每类条款都具有风险评级。演示政策不构成正式法律结论。</p></div></section><section class="panel"><div class="panel-head"><h2>材料与使用边界</h2></div><div class="panel-body prose"><p>默认包含CUAD-001、CUAD-004、CUAD-008训练侧开发样本的既有真实报告及必要文本。未加入CUAD人工标注、完整数据集、模型缓存或私有上传。</p><p>文件不包含API密钥、邀请码、访问数据库或服务器复核记录。静态材料随文件分发即可被阅读，不提供访问权限保护。</p><p>导入案例包仅检查文件与报告、文本的一致性，不证明外部报告的真实性或评价正确性。外部来源由提供者确认。</p><p>本地意见单独导出，不覆盖原始报告，也不代表专业法律复核。系统用于商业合同辅助初审。</p></div></section></div><section class="panel section-gap"><div class="panel-head"><h2>可追溯来源</h2><button class="btn small" id="showcase-manifest">下载来源清单</button></div><div class="panel-body"><p class="metadata-caption">展示包构建时间：${esc(SC_DATA.manifest.built_at)}</p>${SC_DATA.manifest.sources.map(s=>`<article class="showcase-source"><strong>${esc(s.document_id)}</strong><p>${esc(s.source_report)}</p><code>SHA-256 ${esc(s.report_sha256)}</code><p>${s.reviewed_tasks}项实际审查 · ${esc('train / development')}</p></article>`).join('')}</div></section>`;
}

function bindView(){
  if(state.view==='workbench'){
    bindEvidenceLinks($('#main-view'));
    document.querySelectorAll('[data-load-case]').forEach(b=>b.addEventListener('click',async()=>{try{await loadCase(b.dataset.loadCase);go('overview');}catch(e){notify(e.message);}}));
    $('#showcase-import').addEventListener('change',event=>scImport(event.target.files[0]));
    $('#showcase-export-case').addEventListener('click',scExportCase);
    $('#showcase-export-notes').addEventListener('click',scExportNotes);
    $('#contract-file').addEventListener('change',event=>scChooseContract(event.target.files[0]));
    $('#clear-contract')?.addEventListener('click',()=>{scFileVersion++;scReading=false;scContract=null;scViewSelection=null;render();});
    const zone=$('#upload-zone');
    zone.addEventListener('dragover',event=>{event.preventDefault();zone.classList.add('dragging');});
    zone.addEventListener('dragleave',()=>zone.classList.remove('dragging'));
    zone.addEventListener('drop',event=>{event.preventDefault();zone.classList.remove('dragging');if(event.dataTransfer.files.length!==1){notify('一次请选择一份合同');return;}scChooseContract(event.dataTransfer.files[0]);});
    document.querySelectorAll('[data-preset]').forEach(button=>button.addEventListener('click',()=>{
      const preset=button.dataset.preset;state.selected=new Set(preset==='all'?state.system.catalog.map(c=>c.id):preset==='basic'?['Q1','Q2','Q3','Q4','Q5']:preset==='focus'?['Q16','Q18','Q19','Q35','Q36']:[]);render();
    }));
    document.querySelectorAll('.clause-check').forEach(input=>input.addEventListener('change',()=>{input.checked?state.selected.add(input.value):state.selected.delete(input.value);$('#selected-total').textContent=`已选 ${state.selected.size} / 41 类`;updateGroupChecks();}));
    document.querySelectorAll('.group-check').forEach(input=>input.addEventListener('change',()=>{for(const c of state.system.catalog.filter(c=>c.group===input.dataset.group)){input.checked?state.selected.add(c.id):state.selected.delete(c.id);}render();}));
    $('#showcase-report-choice')?.addEventListener('change',event=>scContract.chosen=event.target.value);
    const preview=$('#showcase-file-preview'),contract=scContract;if(preview)preview.addEventListener('toggle',()=>{if(contract===scContract)contract.previewOpen=preview.open;});
    $('#match-review').addEventListener('click',scMatchContract);
    document.querySelectorAll('[data-download-contract]').forEach(button=>button.addEventListener('click',()=>scDownloadContract(button.dataset.downloadContract)));
    updateGroupChecks();
    return;
  }
  bindRecordedView();
  if(state.view==='overview')$('#showcase-full-report')?.addEventListener('click',()=>{scViewSelection=null;state.filters={search:'',status:'',risk:'',group:''};render();});
  if(state.view==='execution'){
    $('#sc-first').addEventListener('click',()=>{scStep=0;render();});
    $('#sc-prev').addEventListener('click',()=>{scStep--;render();});
    $('#sc-next').addEventListener('click',()=>{scStep++;render();});
    $('#sc-retry').addEventListener('click',()=>{scStep=taskLogs(state.qid).findIndex(x=>/补查|重试/.test(x.content));render();});
  }
  if(state.view==='review'){
    $('#showcase-export-notes').addEventListener('click',scExportNotes);
    $('#showcase-clear-notes').addEventListener('click',()=>{if(!confirm('只清除当前浏览器中所有明契本地意见？原始Agent报告和服务器记录不会改变。'))return;scNotes={};scSaveNotes();state.reviews=[];render();notify('已清除本浏览器的本地意见。');});
  }
  if(state.view==='system')$('#showcase-manifest').addEventListener('click',()=>scDownloadJson('明契_来源清单.json',SC_DATA.manifest));
}

function scBytes(encoded){return Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));}
function scDownload(name,content,type){const url=URL.createObjectURL(new Blob([content],{type}));const anchor=document.createElement('a');anchor.href=url;anchor.download=name;document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function scDownloadJson(name,data){scDownload(name,JSON.stringify(data,null,2),'application/json;charset=utf-8');}
function scExportCase(){if(!state.caseId){notify('请先选择一份案例');return;}scDownloadJson(scCase().identity.document_id+'_明契案例包.json',scCase());}
function scExportNotes(){scDownloadJson('明契_本地复核意见.json',{format:'mingqi-local-notes-v1',exported_at:new Date().toISOString(),status:'LOCAL_NOTES_NOT_SUBMITTED',records:Object.values(scNotes).filter(Array.isArray).flat(),original_agent_reports_modified:false});}
async function scSha(bytes){if(!crypto.subtle)throw new Error('浏览器无法进行SHA-256核对，请使用本机Chrome/Edge或HTTPS打开');return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');}
function scCanonical(value){if(Array.isArray(value))return value.map(scCanonical);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,scCanonical(value[k])]));return value;}
function scEqual(a,b){return JSON.stringify(scCanonical(a))===JSON.stringify(scCanonical(b));}
async function scImport(file){
  if(!file)return;
  try{
    if(!file.name.toLowerCase().endsWith('.json')||file.size>20*1024*1024)throw new Error('请选择不超过20 MB的JSON展示案例包');
    const c=JSON.parse(await file.text());
    if(c.schema!=='mingqi-case-v1'||!c.native_report_base64||!Array.isArray(c.report?.checks)||!c.text)throw new Error('这是原生报告或其他文件，请选择由“导出当前展示案例包”生成的JSON');
    const bytes=scBytes(c.native_report_base64),hash=await scSha(bytes),raw=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    if(hash!==c.report.report_sha256||!Array.isArray(raw.checks)||raw.checks.length!==c.report.checks.length)throw new Error('原生报告哈希或条款数量不一致，导入已拒绝');
    const keys=['question_id','category','category_answer','predicted_answers','verification_status','processing_status','next_action','review_results','retry_count','attempt_history','retrieval_history','context_sha256'];
    raw.checks.forEach((record,i)=>{for(const key of keys)if(!scEqual(record[key]??null,c.report.checks[i][key]??null))throw new Error('展示字段与原生报告不一致，导入已拒绝');});
    for(const item of c.report.checks){
      const catalog=SC_DATA.system.catalog.find(x=>x.name===item.category);
      if(!catalog||catalog.id!==item.qid)throw new Error('类别与现有条款目录不一致');
      const levels=[...new Set((item.review_results||[]).filter(x=>x.risk_level).map(x=>x.risk_level))].sort();
      if(!scEqual(levels,item.risk_levels))throw new Error('风险评级与原生规则结果不一致');
      const pieces=c.text.quotes?.[item.qid]||[],answers=item.predicted_answers||[];
      if(pieces.length!==answers.length)throw new Error('引用数量与原生报告不一致');
      for(let i=0;i<answers.length;i++)if(pieces[i].text!==answers[i].text||pieces[i].normalized_start!==answers[i].answer_start)throw new Error('阅读引文与原生报告不一致');
    }
    const expected={reviewed:raw.checks.length,accepted:raw.checks.filter(x=>x.next_action==='ACCEPT').length,manual:raw.checks.filter(x=>x.next_action==='ESCALATE').length,
      passed:raw.checks.filter(x=>x.verification_status==='PASSED').length,failed:raw.checks.filter(x=>x.verification_status==='FAILED').length,uncertain:raw.checks.filter(x=>x.verification_status==='UNCERTAIN').length,
      triggered:raw.checks.reduce((n,x)=>n+(x.review_results||[]).filter(r=>r.status==='TRIGGERED').length,0),retries:raw.checks.reduce((n,x)=>n+(x.retry_count||0),0)};
    for(const [key,value]of Object.entries(expected))if(c.report.stats[key]!==value)throw new Error('统计与原生报告不一致，导入已拒绝');
    if(c.text.available){
      if(typeof c.text.normalized_text!=='string'||await scSha(new TextEncoder().encode(c.text.normalized_text))!==c.text.normalized_sha256)throw new Error('规范化文本哈希不一致');
      for(const check of raw.checks)if(check.context_sha256&&check.context_sha256!==c.text.normalized_sha256)throw new Error('合同文本与原生报告坐标系不一致');
      for(const pieces of Object.values(c.text.quotes||{}))for(const quote of pieces)if(quote.position_matches&&Array.from(c.text.normalized_text).slice(quote.normalized_start,quote.normalized_end).join('')!==quote.text)throw new Error('引用位置不匹配，导入已拒绝');
      if(c.text.raw_mapping_available){
        if(typeof c.text.raw_text!=='string'||await scSha(new TextEncoder().encode(c.text.raw_text))!==c.text.raw_sha256)throw new Error('原始TXT哈希不一致');
        for(const pieces of Object.values(c.text.quotes||{}))for(const q of pieces)if(q.raw_start!=null){const selected=Array.from(c.text.raw_text).slice(q.raw_start,q.raw_end).join('');if(selected.replace(/\s+/g,' ').trim()!==q.text.replace(/\s+/g,' ').trim())throw new Error('原始TXT引文映射不能可靠核对');}
      }
    }
    const existing=[...SC_CASES.values()].find(x=>x.report.report_sha256===hash);
    if(existing){await loadCase(existing.identity.id);go('overview');notify('该原始报告已存在，已打开现有案例。');return;}
    if(SC_CASES.size>=10)throw new Error('当前最多加载10份案例，请重新打开页面后选择需要的材料');
    const id='import_'+hash.slice(0,20);c.identity={...c.identity,id,sample:null,web_task_id:null,document_id:raw.document_id,title:'外部导入 · '+String(raw.filename||raw.document_id),label:String(raw.filename||raw.document_id),source:'外部导入，来源由提供者确认',count:expected.reviewed,manual_count:expected.manual};
    c.report.identity=c.identity;c.provenance={...c.provenance,kind:'user_imported_not_independently_authenticated'};
    SC_CASES.set(id,c);state.reports=scRows();fillCases();await loadCase(id);go('overview');notify('已核对文件一致性并加载；外部运行来源仍需由提供者确认。');
  }catch(error){notify('导入失败：'+error.message);}
}

function scPrint(){
  const report=state.report;if(!report)return;
  const target=window.open('','_blank');if(!target){notify('浏览器阻止了打印窗口，请允许弹出窗口后重试。');return;}
  const rows=report.checks.map(c=>`<tr><td>${esc(c.qid)} ${esc(c.label)}</td><td>${esc(formatAnswer(c.category_answer))}</td><td>${esc(statusMap[c.verification_status]?.[0]||c.verification_status||'未记录')}</td><td>${esc(Number(c.qid.slice(1))<=5?'未执行业务规则核验':c.mode_label||'未记录')}</td><td>${esc(c.risk_levels?.length?c.risk_levels.map(x=>statusMap[x]?.[0]||x).join(' / '):'未评级')}</td><td>${esc(statusMap[c.next_action]?.[0]||c.next_action)}</td></tr>`).join('');
  const evidence=report.checks.filter(c=>c.next_action==='ESCALATE').map(c=>`<article><h3>${esc(c.qid)} ${esc(c.label)}</h3><p>${esc(manualReason(c))}</p>${(c.predicted_answers||[]).map(a=>`<blockquote>${esc(a.text)}<small>规范化字符起点：${esc(a.answer_start??'未记录')}；不推测原PDF页码。</small></blockquote>`).join('')}</article>`).join('')||'<p>该报告原始人工队列为空，自动接收不等于人工确认正确。</p>';
  target.document.write(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>明契 · ${esc(report.identity.document_id)} · 打印报告</title><style>body{font:15px/1.7 Arial,"Microsoft YaHei",sans-serif;color:#142e4c;max-width:1100px;margin:35px auto;padding:0 20px}h1{font-size:25px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{border:1px solid #d7e1ed;padding:9px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#eef3f9}blockquote{white-space:pre-wrap;border-left:3px solid #3975c6;padding-left:16px}small{display:block;color:#64748b}code{overflow-wrap:anywhere}button{padding:10px 18px;background:#3975c6;border:0;border-radius:6px;color:white;cursor:pointer}@media print{button{display:none}body{margin:0;padding:0}thead{display:table-header-group}article{break-inside:avoid}}</style><header><p>明契 · 独立HTML真实案例回放</p><h1>${esc(report.identity.title)}</h1><p>实际运行时间：${esc(report.identity.date)}；抽取模型：${esc(report.configuration.extraction_model||'未记录')}</p><button id="showcase-print-now">打印 / 另存PDF</button><p>原生报告SHA-256：<code>${esc(report.report_sha256)}</code></p></header><p>实际审查${report.stats.reviewed}项，自动接收${report.stats.accepted}项，原始人工升级${report.stats.manual}项，证据核验通过${report.stats.passed}项、失败${report.stats.failed}项、不确定${report.stats.uncertain}项；补查${report.stats.retries}次。</p><h2>真实条款结果</h2><table><thead><tr><th>条款</th><th>候选答案</th><th>证据核验</th><th>规则模式</th><th>风险评级</th><th>决策</th></tr></thead><tbody>${rows}</tbody></table><h2>原始人工复核事项及证据</h2>${evidence}<footer><p>此处打印已保存的真实Agent结果，不是本次新运行。本地意见不计入原始结果。候选、证据、业务规则、风险和决策分别解释；辅助初审不构成正式法律意见。</p></footer></html>`);
  target.document.close();target.document.getElementById('showcase-print-now').addEventListener('click',()=>target.print());
}

function initAccess(){
  document.addEventListener('click',event=>{
    const anchor=event.target.closest('a');if(!anchor)return;const href=anchor.getAttribute('href')||'';
    if(href===`/api/reports/${state.caseId}/download`){event.preventDefault();const c=scCase();scDownload(c.identity.document_id+'.json',scBytes(c.native_report_base64),'application/json');}
    else if(href===`/print/${state.caseId}`){event.preventDefault();scPrint();}
  });
}

init();

"use strict";
// Native Agent events, not simulated percentages or timers.
const LIVE_STAGES=[['parsing','合同解析 / 索引','document'],['planning','任务规划','grid'],['retrieval','RAG混合检索','search'],['extraction','LLM事实抽取','document'],['verification','证据核验','search'],['rules','业务规则核验','balance'],['decision','Agent决策','shield'],['report','报告生成','document']];
const TASK_END=new Set(['COMPLETED','FAILED','STOPPED','CANCELLED','INTERRUPTED']);
const taskLabel=s=>({STARTING:'正在启动',RUNNING:'审查中',COMPLETED:'审查完成',FAILED:'运行失败',STOPPED:'已保护性停止',CANCELLED:'已停止',INTERRUPTED:'运行中断'}[s]||s);
const taskActive=()=>state.task&&!TASK_END.has(state.task.status);

function livePanel(){
  const t=state.task;
  if(!t)return '<div id="live-task-panel"></div>';
  const events=state.taskEvents||[],latest=events.at(-1),usage=t.api_usage||{};
  const own=!state.system?.offline_mode&&state.sessionStartedTaskId===t.task_id;
  const stageEvents=events.filter(e=>!e.qid||e.qid===t.qid);
  return `<section class="panel live-panel section-gap" id="live-task-panel"><div class="panel-head"><div><h2>${esc(t.original_filename)} · ${esc(taskLabel(t.status))}</h2><p>任务 ${esc(t.task_id)} · ${own?'本次真实审查':'已保存任务回放 / 状态读取'}</p></div><span class="pill ${t.status==='COMPLETED'?'green':taskActive()?'blue':'orange'}">${esc(taskLabel(t.status))}</span></div><div class="panel-body"><div class="live-summary"><div><span>实际完成条款</span><strong id="live-completed">${t.completed} / ${t.total}</strong></div><div><span>当前类别 / 轮次</span><strong>${esc(t.qid||'未进入条款')} / ${t.round?`第${t.round}轮`:'未记录'}</strong></div><div><span>该任务观测模型请求</span><strong>${(usage.extraction_calls||0)+(usage.verification_calls||0)} 次</strong></div><div><span>该任务已记录token</span><strong>${usage.total_tokens||0}</strong></div></div><div class="pipeline live-pipeline">${LIVE_STAGES.map(([key,label,name])=>{
    const entries=stageEvents.filter(e=>e.stage===key),last=entries.at(-1),outcome=entries.filter(e=>e.state).at(-1);
    const current=taskActive()&&t.stage===key;
    const skipped=outcome?.state==='NOT_EXECUTED';
    const status=skipped?'未执行':outcome?.state==='FAILED'?'未完成':current?'进行中':outcome?.state==='DONE'?'已记录完成':last?'已有记录':'未执行';
    return `<div class="pipeline-node">${icon(name)}<strong>${label}</strong><span class="pill ${skipped?'gray':outcome?.state==='FAILED'?'red':current?'blue':outcome?.state==='DONE'?'green':'gray'}">${status}</span></div>`;
  }).join('')}</div>${latest?`<p class="live-current">${esc(latest.timestamp)}　${esc(latest.message)}</p>`:''}${t.error?notice(t.error,'orange'):''}
  ${t.reconnected?notice('当前服务未持有该任务进程，仅显示已保存状态；如进度停滞，请检查原启动终端。不会自动重跑。'):''}<div class="live-actions">${taskActive()&&!t.reconnected?'<button class="btn" id="cancel-live-task">停止后续审查</button>':''}${t.report_id?`<button class="btn primary" id="open-live-report">${own?'查看本次真实报告':'查看已保存报告'}</button>`:''}<span class="metadata-caption">1.5秒读取实际事件；任务完成数来自Agent条款返回结果。SDK内部重试可能增加HTTP请求。</span></div>
  <details class="section-gap" id="live-log-details"><summary>展开实际执行日志（${events.length}条已读取事件）</summary><div class="log-window section-gap">${events.slice(-150).map(e=>`<div class="log-entry"><span class="log-number">${e.sequence} · ${esc(e.timestamp)} · ${esc(e.qid||'合同级')} · ${esc(e.stage)}${e.candidate_count!=null?` · 候选${e.candidate_count}段`:''}${e.verification_status?` · ${esc(e.verification_status)}`:''}${e.decision?` · ${esc(e.decision)}`:''}</span>${esc(e.message)}</div>`).join('')}</div></details><p class="metadata-caption">输出目录：${esc(t.output_directory||'未记录')}。未完成时保留已写入的原生断点；不会伪造完整报告。</p></div></section>`;
}

function updateLivePanel(){
  const target=$('#live-task-panel');
  if(target){const opened=$('#live-log-details')?.open;target.outerHTML=livePanel();if(opened&&$('#live-log-details'))$('#live-log-details').open=true;bindLive();}
  const button=$('#start-review');if(button)button.disabled=!!state.system?.offline_mode||!!state.submitting||!!taskActive();
}

function bindLive(){
  $('#start-review')?.addEventListener('click',startLive,{once:true});
  $('#cancel-live-task')?.addEventListener('click',async()=>{if(!confirm('停止该任务的后台工作进程？已发出的模型请求可能计费，已完成条款断点将保留。'))return;try{await api(`/api/tasks/${state.task.task_id}/cancel`,{method:'POST',body:'{}'});await pollTask();}catch(e){notify(e.message);}});
  $('#open-live-report')?.addEventListener('click',openLiveReport);
  document.querySelectorAll('[data-open-task]').forEach(b=>b.addEventListener('click',()=>watchTask(b.dataset.openTask)));
}

async function startLive(){
  if(state.system?.offline_mode){notify('离线回放模式不启动模型审查');return;}
  if(!accessInfo().authenticated){openAccessDialog();updateLivePanel();return;}
  if(state.submitting||taskActive())return;
  if(!state.file||!state.selected.size){notify('请选择合同文件及至少一个条款');updateLivePanel();return;}
  const n=state.selected.size,rounds=state.retries+1;
  if(n>accessInfo().max_clauses){notify(`当前邀请码每次最多${accessInfo().max_clauses}类，请减少选择或联系管理员。`);updateLivePanel();return;}
  if(accessInfo().remaining_today<=0){notify('今日任务额度已用完，历史回放仍可使用。');updateLivePanel();return;}
  const message=`将上传“${state.file.name}”并使用小组后台配置的模型服务，审查${n}类条款。首轮通常约${2*n}次模型请求；最多${rounds}轮，No覆盖核验和SDK重试可能增加请求。是否开始？`;
  if(!confirm(message)){updateLivePanel();return;}
  state.submitting=true;const button=$('#start-review');if(button)button.disabled=true;
  state.requestId=state.requestId||crypto.randomUUID();
  const form=new FormData();form.append('file',state.file);form.append('request_id',state.requestId);
  form.append('clauses',JSON.stringify([...state.selected]));form.append('top_k',state.topK);form.append('max_retries',state.retries);form.append('large_scope_confirmed',n>5?'true':'false');
  try{const data=await api('/api/tasks',{method:'POST',body:form});state.task=data.task;state.sessionStartedTaskId=data.task.task_id;state.taskEvents=[];state.finishedNotice=false;state.executionMode='live';state.requestId=null;localStorage.setItem('contract-workbench-task',state.task.task_id);render();await pollTask();}
  catch(e){notify(e.message+'。如网络返回不明，重试沿用同一请求ID，不会重复启动。');}
  finally{state.submitting=false;try{const current=await api('/api/bootstrap');Object.assign(state.system,current);updateRuntimeMode();}catch{}updateLivePanel();}
}

async function watchTask(id){
  clearTimeout(state.pollTimer);state.taskEvents=[];
  const data=await api(`/api/tasks/${id}`);state.task=data.task;state.sessionStartedTaskId=null;state.taskEvents=data.task.events;state.finishedNotice=false;state.executionMode='live';
  if(!TASK_END.has(state.task.status))localStorage.setItem('contract-workbench-task',id);go('workbench');render();await pollTask();
}

async function pollTask(){
  clearTimeout(state.pollTimer);if(!state.task)return;
  try{
    const after=state.taskEvents?.at(-1)?.sequence||0;
    const {task}=await api(`/api/tasks/${state.task.task_id}?after=${after}`);
    state.task=task;state.taskEvents=[...(state.taskEvents||[]),...task.events];state.taskEvents=state.taskEvents.slice(-3000);
    updateLivePanel();
    if(!TASK_END.has(task.status))state.pollTimer=setTimeout(pollTask,1500);
    else if(!state.finishedNotice){state.finishedNotice=true;state.reports=(await api('/api/reports')).reports;fillCases();notify(state.sessionStartedTaskId===task.task_id?(task.status==='COMPLETED'?'真实审查已完成，可查看本次报告。':task.error||taskLabel(task.status)):'已读取保存的实际任务结果，没有重新调用模型。');}
  }catch(e){notify('进度读取暂时失败：'+e.message+'，不会重新启动审查');if(e.status===401||e.status===404){await refreshAccess();return;}if(accessInfo().authenticated)state.pollTimer=setTimeout(pollTask,3500);}
}

async function openLiveReport(){
  if(!state.task?.report_id)return;
  const own=!state.system?.offline_mode&&state.sessionStartedTaskId===state.task.task_id;
  state.reports=(await api('/api/reports')).reports;fillCases();
  state.filters={search:'',status:'',risk:'',group:''};await loadCase(state.task.report_id);state.liveReportId=own?state.task.report_id:null;go('overview');
}

function taskHistory(){return `<section class="panel section-gap"><div class="panel-head"><h2>网页审查任务</h2><button class="btn small" id="refresh-tasks">刷新任务</button></div><div class="panel-body" id="task-history-list">点击刷新，读取工作台主机保存的任务及真实状态。</div></section>`;}
async function refreshTasks(){try{const {tasks}=await api('/api/tasks');$('#task-history-list').innerHTML=tasks.length?tasks.map(t=>`<div class="task-history-row"><div><strong>${esc(t.original_filename)}</strong><small>${esc(t.task_id)} · ${esc(taskLabel(t.status))} · ${t.completed}/${t.total}项</small></div><button class="btn small" data-open-task="${t.task_id}">查看任务</button></div>`).join(''):empty('暂无网页审查任务');bindLive();}catch(e){notify(e.message);}}

async function restoreTask(){const id=localStorage.getItem('contract-workbench-task');if(!id)return;try{const {task}=await api(`/api/tasks/${id}`);state.task=task;state.taskEvents=task.events;if(!TASK_END.has(task.status)){notify('已恢复对原任务的进度读取，没有重新调用Agent');render();await pollTask();}}catch{localStorage.removeItem('contract-workbench-task');}}

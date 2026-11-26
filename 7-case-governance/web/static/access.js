"use strict";
// Invitation sessions are HttpOnly cookies; no model keys or login tokens in storage.
function accessInfo(){return state.system?.access||{authenticated:false};}
function canStartReview(){return !!state.system?.realtime_enabled&&!!accessInfo().authenticated;}
function accessBanner(){
  const a=accessInfo();
  if(!a.authenticated)return `<section class="access-banner section-gap"><span class="access-mark">${icon('shield')}</span><div><strong>历史案例可直接回放，实时审查需要邀请码登录</strong><p>向小组管理员领取个人邀请码。登录后使用小组后台模型服务，无需输入API密钥。</p></div><button class="btn primary" data-login>邀请码登录</button></section>`;
  return `<section class="access-banner section-gap"><span class="access-mark">${icon('shield')}</span><div><strong>${esc(a.display_name)} · ${a.role==='admin'?'管理员':'已授权成员'}</strong><p>每次最多${a.max_clauses}类 · 今日剩余${a.remaining_today}/${a.daily_limit}次 · 登录有效期8小时。新合同及报告仅本人和管理员可见。</p></div><button class="btn" data-account>查看权限</button></section>`;
}
function renderAccessAccount(){
  const a=accessInfo(),box=$('#account-controls');
  box.replaceChildren();const button=document.createElement('button');button.className='btn small account-button';
  button.textContent=a.authenticated?`${a.display_name} · ${a.role==='admin'?'管理员':'成员'}`:'邀请码登录';
  button.addEventListener('click',openAccessDialog);box.append(button);
  const label=$('.local-label');if(label)label.textContent=(state.system.workspace_label||'本地工作区')+' · '+location.hostname;
}
function openAccessDialog(){
  const dialog=$('#access-dialog'),a=accessInfo();
  $('#access-error').textContent='';
  $('#access-dialog-title').textContent=a.authenticated?'登录与审查权限':'使用邀请码登录';
  $('#invite-login-form').classList.toggle('hidden',a.authenticated);
  $('#account-details').classList.toggle('hidden',!a.authenticated);
  if(a.authenticated){
    $('#account-name').textContent=a.display_name;
    $('#account-role').textContent=a.role==='admin'?'管理员':'普通成员';
    $('#account-allowance').textContent=`每次最多${a.max_clauses}类；今日剩余${a.remaining_today}/${a.daily_limit}次`;
  }else $('#invite-code').value='';
  dialog.showModal();if(!a.authenticated)$('#invite-code').focus();
}
async function refreshAccess(){
  const oldId=state.caseId;state.system=await api('/api/bootstrap');state.reports=state.system.reports;
  if(!state.system.access.authenticated){
    clearTimeout(state.pollTimer);state.task=null;state.taskEvents=[];state.sessionStartedTaskId=null;state.liveReportId=null;
    localStorage.removeItem('contract-workbench-task');
  }
  updateRuntimeMode();fillCases();
  if(!state.reports.some(r=>r.id===oldId)){
    state.report=null;state.text=null;state.reviews=[];state.caseId=null;state.task=null;state.taskEvents=[];
    clearTimeout(state.pollTimer);state.sessionStartedTaskId=null;state.liveReportId=null;
    if(state.reports.length)await loadCase(state.reports.find(r=>r.sample==='CUAD-004')?.id||state.reports[0].id);
  }
  render();
}
function bindAccess(){
  document.querySelectorAll('[data-login],[data-account]').forEach(b=>b.addEventListener('click',openAccessDialog));
}
function initAccess(){
  $('#close-access').addEventListener('click',()=>$('#access-dialog').close());
  $('#invite-login-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=$('#invite-login-submit');button.disabled=true;$('#access-error').textContent='';
    try{
      await api('/api/auth/login',{method:'POST',body:JSON.stringify({code:$('#invite-code').value})});
      $('#invite-code').value='';$('#access-dialog').close();await refreshAccess();
      notify('登录成功。上传合同并点击启动后，才会产生模型调用。');
    }catch(error){$('#access-error').textContent=error.message;}
    finally{button.disabled=false;}
  });
  $('#logout-account').addEventListener('click',async()=>{
    try{
      await api('/api/auth/logout',{method:'POST',body:'{}'});clearTimeout(state.pollTimer);
      state.task=null;state.taskEvents=[];state.sessionStartedTaskId=null;localStorage.removeItem('contract-workbench-task');
      state.file=null;state.reviewDrafts={};
      $('#access-dialog').close();await refreshAccess();notify('已退出。已提交的后台任务继续运行，重新登录后可查看。');
    }catch(error){$('#access-error').textContent=error.message;}
  });
}

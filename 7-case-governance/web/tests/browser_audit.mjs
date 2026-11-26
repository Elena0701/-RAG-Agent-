import {loginBrowser} from './browser_access_helper.mjs';
// OFFLINE acceptance. Natural reports are read-only; form writes go to audit_server.py's temporary directory.
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),qa=path.join(web,'qa');
const base=process.env.WORKBENCH_URL||'http://127.0.0.1:8770';
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--disable-background-networking','--no-first-run']});
const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
const checks=[],errors=[],requests=[],screenshots=[];
await context.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
context.on('request',r=>requests.push({method:r.method(),url:r.url()}));
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push({check:label,status:'PASS'});console.log('PASS',label);};
const view=async name=>{await page.locator(`.nav-item[data-view="${name}"]`).click();await page.waitForTimeout(80);};
const go=async (name,qid)=>{await page.evaluate(([v,q])=>go(v,q),[name,qid]);await page.waitForTimeout(100);};
const shot=async name=>{const file='audit_'+name+'.png';await page.screenshot({path:path.join(qa,file)});screenshots.push(file);};
const noOverflow=async label=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),label);
const load=async id=>{await page.selectOption('#case-select',id);await page.waitForFunction(id=>state.caseId===id,id);};
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
let bootstrap,main,mainReport;
try{
  await loginBrowser(context,base,{fixturePath:path.join(web,'qa/audit_login.json')});
  await page.goto(base,{waitUntil:'networkidle'});await page.waitForSelector('#report-rows tr');
  bootstrap=await (await context.request.get(base+'/api/bootstrap')).json();
  if(!bootstrap.audit_environment)throw new Error('Use audit_server.py with isolated temporary review storage, not the production workbench');
  assert(bootstrap.offline_mode&&!bootstrap.realtime_enabled&&!bootstrap.model_api_calls_enabled,'offline mode disables model execution at backend and frontend');
  main=bootstrap.reports.find(r=>r.sample==='CUAD-004');mainReport=await (await context.request.get(`${base}/api/reports/${main.id}`)).json();
  const rawReports=new Map();
  for(const entry of bootstrap.reports){
    const response=await context.request.get(`${base}/api/reports/${entry.id}`);
    assert(response.status()===200,`load saved real report ${entry.document_id}`);
    const data=await response.json(),download=await context.request.get(`${base}/api/reports/${entry.id}/download`),bytes=await download.body();
    assert(download.status()===200&&sha(bytes)===data.report_sha256,`native JSON unchanged on download ${entry.document_id}`);
    const raw=JSON.parse(bytes.toString('utf8'));rawReports.set(entry.id,raw);
    assert(data.stats.reviewed===raw.checks.length&&data.stats.manual===raw.checks.filter(c=>c.next_action==='ESCALATE').length,`statistics match native checks ${entry.document_id}`);
    assert((await context.request.get(`${base}/print/${entry.id}`)).status()===200,`print page works ${entry.document_id}`);
    const text=await context.request.get(`${base}/api/reports/${entry.id}/text`);
    assert(text.status()===200,`source availability handled honestly ${entry.document_id}`);
  }
  await view('overview');
  const q5=page.locator('tr[data-evidence="Q5"]');
  assert((await q5.innerText()).includes('未执行业务规则核验')&&!(await q5.innerText()).match(/低风险|高风险|安全/),'Q5 shows unexecuted business rules and no invented risk rating');
  assert((await page.locator('.metadata-cell').last().innerText()).includes('无法确认'),'basic date candidate exposes its uncertainty');
  const native=rawReports.get(main.id);
  for(const risk of ['HIGH','MEDIUM','LOW']){
    await page.selectOption('#risk-filter',risk);
    const expected=native.checks.filter(c=>(c.review_results||[]).some(r=>r.risk_level===risk)).length;
    assert(await page.locator('#report-rows tr[data-evidence]').count()===expected,`risk filter ${risk} equals native policy labels`);
  }
  await page.click('#reset-filters');
  await page.selectOption('#status-filter','ESCALATE');assert(await page.locator('#report-rows tr[data-evidence]').count()===16,'manual escalation filter is independent of high-risk filter');
  await page.click('#reset-filters');await page.fill('#report-search','Q36');
  assert(await page.locator('#report-rows tr[data-evidence]').count()===1,'clause search button/input isolates Q36');await page.click('#reset-filters');
  await page.selectOption('#group-filter',bootstrap.task_groups[1]);
  assert(await page.locator('#report-rows tr[data-evidence]').count()===bootstrap.catalog.filter(c=>c.group===bootstrap.task_groups[1]).length,'category group filter works');
  const negative=bootstrap.reports.find(r=>r.sample==='CUAD-008');await load(negative.id);
  assert(await page.locator('#report-rows tr[data-evidence]').count()===5&&await page.locator('#group-filter').inputValue()==='','switching reports clears stale filters');
  await load(main.id);await page.locator('.report-scroll').evaluate(n=>n.scrollTop=420);
  assert(await page.locator('.report-scroll').evaluate(n=>Math.abs(n.querySelector('thead th').getBoundingClientRect().top-n.getBoundingClientRect().top)<3),'long table header stays visible while scrolling');
  await page.locator('.report-scroll').evaluate(n=>n.scrollTop=0);await shot('overview_1440');
  const downloaded=page.waitForEvent('download');await page.locator('#heading-actions a').first().click();const download=await downloaded;
  assert(sha(await fs.readFile(await download.path()))===mainReport.report_sha256,'export button downloads original report bytes');

  await go('evidence','Q36');await page.waitForSelector('#contract-reader');
  const source=await (await context.request.get(`${base}/api/reports/${main.id}/text`)).json();
  assert(source.normalized_text.length>50000,'long real contract loads in full');
  await page.fill('#contract-search','WGT');await page.waitForTimeout(250);
  const count=(source.normalized_text.match(/WGT/gi)||[]).length;
  assert((await page.locator('#source-match-count').innerText())===`1 / ${count}`,'full-contract search count matches the actual text');
  await page.click('#source-next');assert((await page.locator('#source-match-count').innerText()).startsWith('2 /'),'next search result locates the next occurrence');
  await page.click('#source-prev');assert((await page.locator('#source-match-count').innerText()).startsWith('1 /'),'previous search result works');
  await page.locator('#contract-search').press('Enter');assert((await page.locator('#source-match-count').innerText()).startsWith('2 /'),'Enter navigates source search');
  await page.locator('#contract-search').press('Shift+Enter');assert((await page.locator('#source-match-count').innerText()).startsWith('1 /'),'Shift+Enter navigates backwards');
  await page.fill('#contract-search','LIABILITY');await page.waitForTimeout(220);
  const expected=mainReport.checks.find(c=>c.qid==='Q36').predicted_answers[0].text;
  assert(await page.locator('#active-evidence').innerText()===expected,'search overlapping evidence does not alter the quoted span');
  await page.click('#reader-recenter');
  assert(await page.evaluate(()=>{const a=document.querySelector('#active-evidence').getBoundingClientRect(),b=document.querySelector('#contract-reader').getBoundingClientRect();return a.top>=b.top&&a.top<b.bottom;}),'return-to-quote button reliably scrolls to actual evidence');
  await page.click('#font-larger');assert(await page.locator('#contract-reader').evaluate(n=>getComputedStyle(n).fontSize)==='17px','font enlargement changes contract text');
  await page.click('#font-smaller');assert(await page.locator('#contract-reader').evaluate(n=>getComputedStyle(n).fontSize)==='16px','font reduction restores text size');
  await page.click('#reading-mode');assert(await page.locator('body').evaluate(n=>n.classList.contains('reader-focus')),'focus reading opens a larger contract workspace');
  await noOverflow('focus workspace does not overflow viewport');await shot('evidence_focus_1440');
  await page.keyboard.press('Escape');assert(!await page.locator('body').evaluate(n=>n.classList.contains('reader-focus')),'Escape exits focus reading');
  await page.click('[data-text-mode="raw"]');
  const mapping=source.quotes.Q36[0],rawQuote=Array.from(source.raw_text).slice(mapping.raw_start,mapping.raw_end).join('');
  assert(await page.locator('#active-evidence').innerText()===rawQuote,'raw TXT tab uses validated mapped offsets with search enabled');
  await page.click('[data-text-mode="normalized"]');
  await page.fill('#contract-search','literal-no-match-[.*]');await page.waitForTimeout(220);
  assert((await page.locator('#source-match-count').innerText())==='未找到'&&await page.locator('#source-next').isDisabled(),'literal search handles regex characters and missing matches');
  await page.fill('#contract-search','');await page.waitForTimeout(220);await shot('evidence_1440');
  const unicode=await page.evaluate(()=>{const before=state.sourceQuery;state.sourceQuery='Alpha';state.readerCache=null;const v=searchPositions('😀 Alpha / Alpha');state.sourceQuery=before;state.readerCache=null;return v;});
  assert(unicode[0].start===2&&unicode[1].start===10,'controlled Unicode helper test uses code points, not UTF-16 offsets');
  await page.fill('#directory-search','Q36');assert(await page.locator('.directory-item:not(.hidden)').count()===1,'clause directory search filters entries');await page.fill('#directory-search','');
  const multi=mainReport.checks.find(c=>c.predicted_answers.length>1);
  await go('evidence',multi.qid);
  for(let i=0;i<multi.predicted_answers.length;i++){await page.click(`[data-locate="${i}"]`);assert(await page.locator('#active-evidence').innerText()===multi.predicted_answers[i].text,`${multi.qid} evidence ${i+1} button locates its actual quote`);}
  await go('evidence','Q5');assert((await page.locator('.detail-body').innerText()).includes('不执行业务规则核验'),'Q5 evidence panel explicitly separates rules from fact uncertainty');
  await go('evidence','Q35');assert(await page.locator('#active-evidence').count()===0,'No answer with no citation does not invent source coordinates');

  await view('execution');await page.selectOption('#execution-clause','Q16');
  assert(await page.locator('.round-table tbody tr').count()===2,'execution page preserves the two real Q16 attempts');
  const details=page.locator('.panel details').first();await details.locator('summary').click();assert(!await details.evaluate(n=>n.open),'log collapse button works');await details.locator('summary').click();await shot('execution_1440');
  await view('review');await shot('review_1440');
  await page.locator('[data-review-qid="Q5"]').click();
  await page.fill('#reviewer','CONTROLLED_UI_QA');await page.fill('#review-note','受控界面测试，不属于真实人工复核结论。');await page.selectOption('#disposition','correct');
  assert(await page.locator('#corrected-answer').evaluate(n=>n.required),'correction requires a corrected answer');
  const other=mainReport.checks.find(c=>c.next_action==='ESCALATE'&&c.qid!=='Q5');await page.click(`[data-review-qid="${other.qid}"]`);await page.click('[data-review-qid="Q5"]');
  assert(await page.locator('#reviewer').inputValue()==='CONTROLLED_UI_QA'&&await page.locator('#disposition').inputValue()==='correct','review drafts survive switching clauses');
  await page.locator('.panel-body button[data-evidence="Q5"]').click();await view('review');
  assert((await page.locator('#review-note').inputValue()).includes('受控界面测试'),'review draft survives checking original evidence');
  await page.fill('#corrected-answer','CONTROLLED: abstain pending materials');
  const beforeHash=mainReport.report_sha256;
  for(const action of ['correct','accept','reject','materials']){
    await page.fill('#reviewer','CONTROLLED_UI_QA');await page.fill('#review-note','受控界面测试，不属于真实人工复核结论。');await page.selectOption('#disposition',action);
    if(action==='correct')await page.fill('#corrected-answer','CONTROLLED: abstain pending materials');
    const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/reviews'));
    await page.locator('#review-form button[type="submit"]').click();assert((await response).status()===201,`isolated review action ${action} saves through the real endpoint`);
    await page.waitForFunction(()=>!document.querySelector('#review-form button[type="submit"]')?.disabled);
  }
  assert((await (await context.request.get(`${base}/api/reports/${main.id}`)).json()).report_sha256===beforeHash,'controlled review actions leave original Agent report unchanged');
  await page.check('#include-suggestions');assert(await page.locator('.review-item').count()===17,'supplemental suggestion toggle remains separate from 16 native escalations');

  await view('history');
  for(const filter of ['CUAD','demo','web','all']){
    if(!await page.locator(`[data-history-filter="${filter}"]`).count()){assert(filter==='demo'&&!bootstrap.reports.some(r=>!r.sample&&!r.web_task_id),'empty removed demo group is hidden');continue;}
    await page.click(`[data-history-filter="${filter}"]`);
    const expected=bootstrap.reports.filter(r=>filter==='all'||(filter==='CUAD'?r.sample:filter==='web'?r.web_task_id:!r.sample&&!r.web_task_id)).length;
    assert(await page.locator('.history-card').count()===expected,`history filter ${filter} uses actual saved sources`);
    assert(await page.locator(`[data-history-filter="${filter}"]`).getAttribute('aria-pressed')==='true',`history filter ${filter} visibly marks its selection`);
  }
  await page.click('#refresh-reports');assert(await page.locator('.history-card').count()===bootstrap.reports.length,'refresh reports does not rerun any review');
  await page.click('#refresh-tasks');await page.waitForSelector('.task-history-row');assert(await page.locator('[data-open-task]').count()>0,'saved real web tasks load for offline playback');await shot('history_1440');
  const priorWebRun=bootstrap.reports.find(r=>r.document_id==='demo_contract_4bb14120');
  if(!priorWebRun?.web_task_id)throw new Error('Expected protected Q5/Q8 integration task is missing');
  await page.locator(`[data-open-task="${priorWebRun.web_task_id}"]`).click();await page.waitForSelector('#live-completed');assert((await page.locator('#live-completed').innerText())==='2 / 2','opening completed web task replays its actual completion count');
  await page.click('#open-live-report');await page.waitForSelector('tr[data-evidence="Q8"]');assert(await page.locator('#report-rows tr[data-evidence]').count()===2,'completed task opens its original two-clause report');assert((await page.locator('.playback-badge').innerText()).includes('历史案例回放'),'opening a saved task never masquerades as a new live review');
  await go('evidence','Q8');assert(await page.locator('[data-text-mode="raw"]').isDisabled(),'uploaded TXT without raw mapping does not enable false raw positioning');
  await view('overview');const current=await page.locator('#case-select').inputValue();
  const popup=page.waitForEvent('popup');await page.locator('a[href^="/print/"]').click();const printed=await popup;await printed.waitForLoadState('networkidle');
  assert(await printed.locator('header a').getAttribute('href')===`/?report=${current}#/overview`,'print return link preserves the selected report');
  await printed.evaluate(()=>{window.print=()=>window.__printRequested=true;});await printed.click('#print-page');assert(await printed.evaluate(()=>window.__printRequested),'print button invokes the browser print action');
  await printed.emulateMedia({media:'print'});assert(await printed.locator('.print-actions').evaluate(n=>getComputedStyle(n).display)==='none','print controls are excluded from printed output');await printed.emulateMedia({media:'screen'});
  await printed.locator('header a').click();await printed.waitForSelector('#report-rows tr');assert(await printed.locator('#case-select').inputValue()===current,'returning from print opens the same actual report');await printed.close();
  await view('system');assert((await page.locator('.mode-count').allTextContents()).join(',')==='23,3,5,5','system page policy distribution comes from real local policy');await shot('system_1440');

  await view('workbench');assert(await page.locator('#start-review').isDisabled(),'offline start button is intentionally disabled');
  await page.setInputFiles('#contract-file',path.resolve(web,'../contracts/CUAD-004.txt'));await page.click('#clear-contract');assert(await page.locator('#file-meta').innerText()==='','remove upload button clears the chosen file');
  await page.setInputFiles('#contract-file',{name:'invalid.exe',mimeType:'application/octet-stream',buffer:Buffer.from('CONTROLLED')});assert(await page.locator('#file-meta').innerText()==='','invalid format does not leave an old valid upload selected');await page.click('.toast-close');assert(!await page.locator('#toast').isVisible(),'notification close button dismisses feedback');
  await page.click('[data-preset="none"]');const group=page.locator('.group-check').first();await group.check();assert(await page.locator('.clause-check:checked').count()===8,'group checkbox selects its eight catalog clauses');await group.uncheck();assert(await page.locator('.clause-check:checked').count()===0,'group checkbox deselects its clauses');
  await page.click('[data-preset="basic"]');await page.fill('#top-k','999');await page.locator('#top-k').blur();assert(await page.locator('#top-k').inputValue()==='20','top-k input clamps to documented maximum');
  await page.fill('#retry-limit','999');await page.locator('#retry-limit').blur();assert(await page.locator('#retry-limit').inputValue()==='2','retry input clamps to documented maximum');await shot('workbench_1440');
  const blocked=await context.request.post(base+'/api/tasks',{headers:{'X-Workbench-Token':bootstrap.review_token},data:{}});assert(blocked.status()===503,'offline backend rejects task creation even if called directly');

  for(const [width,height]of [[1920,1080],[1280,800],[1024,768],[768,1024],[390,844]]){
    await page.setViewportSize({width,height});
    for(const name of ['overview','workbench','evidence','execution','review','history','system']){
      await page.evaluate(v=>go(v),name);await page.waitForTimeout(70);await noOverflow(`${width}px ${name} has no horizontal page overflow`);
    }
    if(width===390){await go('overview');await shot('overview_mobile');await page.click('#menu-button');assert(await page.locator('#sidebar').evaluate(n=>n.classList.contains('open')),'mobile navigation menu opens');await page.locator('.nav-item[data-view="evidence"]').click();assert(!await page.locator('#sidebar').evaluate(n=>n.classList.contains('open')),'mobile navigation closes after selecting a page');await shot('evidence_mobile');}
  }
  assert(errors.length===0,'all audited page interactions have no JavaScript errors');
  assert(!requests.some(r=>r.method==='POST'&&r.url.endsWith('/api/tasks')),'browser never submits a new Agent task during this audit');
  assert(requests.every(r=>['127.0.0.1','localhost'].includes(new URL(r.url).hostname)),'browser requests only localhost');
  await fs.writeFile(path.join(qa,'visual_audit_results.json'),JSON.stringify({status:'PASS',checks,errors,screenshots,requests,model_api_calls:0,
    scope:'real saved reports; controlled Unicode and isolated review form tests; no natural review result modified',report_count:bootstrap.reports.length},null,2));
  console.log(`VISUAL_AUDIT_PASS ${checks.length} checks; zero new model calls`);
}catch(e){await shot('failure');await fs.writeFile(path.join(qa,'visual_audit_results.json'),JSON.stringify({status:'FAIL',error:e.message,checks,errors,screenshots,model_api_calls:0},null,2));throw e;}
finally{await browser.close();}

import {loginBrowser} from './browser_access_helper.mjs';
// One explicitly authorized real Q8 upload; saved ID prevents accidental paid reruns.
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),qa=path.join(web,'qa');
const base=process.env.WORKBENCH_URL||'http://127.0.0.1:8766';
const optionIndex=process.argv.indexOf('--clause');
const qid=optionIndex>=0?process.argv[optionIndex+1]:'Q8';
if(!['Q1','Q8'].includes(qid))throw new Error('This small test only allows Q1 or Q8.');
const prefix=qid==='Q8'?'realtime_restore':'realtime_restore_q1';
const saved=path.join(qa,prefix+'_created.json');
let prior;try{prior=JSON.parse(await fs.readFile(saved,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
const replay=!!prior;
if(!prior&&!process.argv.includes('--execute-small-review'))throw new Error('Pass --execute-small-review to authorize this single paid clause test.');
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--disable-background-networking','--no-first-run']});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.route('**/*',route=>['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname)?route.continue():route.abort());
const page=await context.newPage(),checks=[],errors=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('dialog',dialog=>dialog.accept());
const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push({check:label,status:'PASS'});console.log('PASS',label);};
const screenshot=name=>page.screenshot({path:path.join(qa,`${prefix}_${replay?'replay_':''}${name}.png`)});
let task,report;
try{
  await loginBrowser(context,base);
  await page.goto(base,{waitUntil:'networkidle'});await page.waitForSelector('#start-review');
  const bootstrap=await(await context.request.get(base+'/api/bootstrap')).json();
  assert(!bootstrap.offline_mode&&bootstrap.realtime_enabled,'normal server enables actual Agent tasks');
  assert(await page.locator('#page-title').innerText()==='审查工作台','fresh normal landing opens upload workbench');
  assert((await page.locator('#connection-state').innerText()).includes('实时审查 · 已启用'),'top bar explicitly shows real-time availability');
  assert(await page.locator('#start-review').isEnabled(),'real review button is enabled');
  if(prior){
    console.log('Read saved real task, no new Agent launch:',prior.task_id);
    await page.evaluate(id=>watchTask(id),prior.task_id);
  }else{
    await page.click('[data-preset="none"]');await page.check(`.clause-check[value="${qid}"]`);
    await page.setInputFiles('#contract-file',path.resolve(web,'../contracts/upload_demo/CUAD-010.txt'));
    assert(await page.locator('.clause-check:checked').count()===1,`exactly ${qid} is selected`);
    assert(await page.locator('#top-k').inputValue()==='5'&&await page.locator('#retry-limit').inputValue()==='2','native default top-k 5 and two supplementary searches are retained');
    await screenshot('upload');
    const created=page.waitForResponse(r=>r.url()===base+'/api/tasks'&&r.request().method()==='POST');
    await page.click('#start-review');const response=await created;const data=await response.json();
    if(response.status()!==202)throw new Error('Task creation failed: '+JSON.stringify(data));
    prior={task_id:data.task.task_id,created_at:new Date().toISOString(),clauses:[qid],input_file:'contracts/upload_demo/CUAD-010.txt',source:'real browser upload and start button'};
    await fs.writeFile(saved,JSON.stringify(prior,null,2));
    assert(data.task.total===1,'backend accepted one native review task');
    assert(await page.locator('#start-review').isDisabled(),'active task prevents a second click');
  }
  await page.waitForSelector('#live-task-panel .live-summary');
  let last='',captured=false;
  const deadline=Date.now()+15*60*1000;
  while(Date.now()<deadline){
    task=(await(await context.request.get(`${base}/api/tasks/${prior.task_id}`)).json()).task;
    const status=[task.status,task.stage,task.qid,task.round,task.completed].join('|');
    if(status!==last){console.log('ACTUAL_PROGRESS',status);last=status;}
    if(!captured&&task.events.some(e=>e.model_call_status==='REQUEST')){await screenshot('progress');captured=true;}
    if(['COMPLETED','FAILED','STOPPED','CANCELLED','INTERRUPTED'].includes(task.status))break;
    await page.waitForTimeout(1500);
  }
  assert(task.status==='COMPLETED','existing Agent completed the real uploaded contract');
  assert(task.completed===1&&task.total===1,'real progress completed exactly 1/1 clauses');
  assert(task.events.some(e=>e.stage==='retrieval'&&e.candidate_count>0),'events contain real retrieved candidate counts');
  assert(task.events.some(e=>e.stage==='extraction'&&e.model_call_status==='SUCCESS'),'actual extraction model responded');
  assert(task.events.some(e=>e.stage==='verification'&&e.model_call_status==='SUCCESS'),'actual semantic verification model responded');
  assert(task.report_id,'native generated report is linked to its task');
  if(qid==='Q1')assert(task.events.some(e=>e.stage==='rules'&&e.state==='NOT_EXECUTED'&&e.qid===qid),'Q1 rule stage is actually marked not executed');
  report=await(await context.request.get(`${base}/api/reports/${task.report_id}`)).json();
  const text=await(await context.request.get(`${base}/api/reports/${task.report_id}/text`)).json();
  assert(report.checks.map(c=>c.qid).join(',')===qid,`native report contains precisely the selected ${qid}`);
  assert(text.available,'saved normalized source matches report hash');
  const quote=text.quotes[qid]?.[0];assert(quote?.position_matches,`${qid} citation matches its actual normalized source offsets`);
  const download=await context.request.get(`${base}/api/reports/${task.report_id}/download`);
  assert(crypto.createHash('sha256').update(await download.body()).digest('hex')===report.report_sha256,'download preserves the exact native report bytes');
  await page.waitForFunction(()=>state.task?.status==='COMPLETED'&&!!document.querySelector('#open-live-report'));
  await screenshot('completed');await page.click('#open-live-report');await page.waitForSelector(`#report-rows tr[data-evidence="${qid}"]`);
  assert((await page.locator('.playback-badge').innerText()).includes(replay?'历史案例回放':'本次真实审查'),'new results and saved-task playback have distinct labels');
  await screenshot('report');await page.locator(`tr[data-evidence="${qid}"]`).click();await page.waitForSelector('[data-locate="0"]');await page.click('[data-locate="0"]');
  assert(await page.locator('#active-evidence').innerText()===quote.text,'clicking evidence highlights the exact quoted contract text');
  await screenshot('evidence');
  await page.locator('.nav-item[data-view="history"]').click();await page.waitForSelector('.history-card');
  const card=page.locator(`.history-card:has([data-load-case="${task.report_id}"])`);
  await card.locator('[data-load-case]').click();await page.waitForSelector('#report-rows tr');
  assert((await page.locator('.playback-badge').innerText()).includes('历史案例回放'),'reopening saved report is explicitly marked playback');
  assert(errors.length===0,'real-time UI has no JavaScript errors');
  await fs.writeFile(path.join(qa,prefix+(replay?'_replay_result.json':'_result.json')),JSON.stringify({status:'PASS',scope:replay?'saved actual task replay; no new launch':'actual paid single-clause browser integration',additional_model_calls:replay?0:undefined,
    task_id:task.task_id,output_directory:task.output_directory,report_id:task.report_id,report_source:report.source_file,report_stats:report.stats,api_usage:task.api_usage,model:report.configuration.extraction_model,checks,errors},null,2));
  console.log('REALTIME_INTEGRATION_PASS',JSON.stringify({task_id:task.task_id,api_usage:task.api_usage,stats:report.stats}));
}catch(error){
  await screenshot('failure');
  await fs.writeFile(path.join(qa,prefix+'_failure.json'),JSON.stringify({status:'FAIL',error:error.message,task_id:prior?.task_id,actual_status:task?.status,checks,errors},null,2));throw error;
}finally{await browser.close();}

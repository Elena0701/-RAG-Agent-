import {loginBrowser} from './browser_access_helper.mjs';
// Explicitly authorized SMALL paid integration. Saved task ID prevents accidental reruns.
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),qa=path.join(web,'qa');
const base=process.env.WORKBENCH_URL||'http://127.0.0.1:8765';
let prior;try{prior=JSON.parse(await fs.readFile(path.join(qa,'live_run_created.json'),'utf8'));}catch{}
const replay=!!prior,outputName=replay?'live_replay_result.json':'live_integration_result.json';
if(!prior&&!process.argv.includes('--execute-small-review'))throw new Error('Explicit --execute-small-review is required. This test can incur model charges.');
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--disable-background-networking','--no-first-run']});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.route('**/*',route=>['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname)?route.continue():route.abort());
const page=await context.newPage(),checks=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('dialog',dialog=>dialog.accept());
const assert=(condition,label)=>{if(!condition)throw new Error(label);checks.push({check:label,status:'PASS'});console.log('PASS',label);};
const screenshot=async name=>page.screenshot({path:path.join(qa,(replay?name.replace(/^live_/,'replay_'):name)+'.png')});
let task;
try{
  await loginBrowser(context,base);
  await page.goto(base+'/#/overview',{waitUntil:'networkidle'});await page.waitForSelector('#report-rows tr');
  await page.evaluate(()=>location.hash='/workbench');await page.waitForSelector('#start-review');
  if(prior){
    console.log('Reusing saved real task; no new Agent run:',prior.task_id);
    await page.evaluate(id=>watchTask(id),prior.task_id);
  }else{
    await page.click('[data-preset="none"]');await page.check('.clause-check[value="Q5"]');await page.check('.clause-check[value="Q8"]');
    await page.setInputFiles('#contract-file',path.resolve(web,'../../4-agent/code/contracts/demo_contract.txt'));
    assert(await page.locator('.clause-check:checked').count()===2,'only Q5 and Q8 selected for the paid integration');
    const created=page.waitForResponse(r=>r.url()===base+'/api/tasks'&&r.request().method()==='POST');
    await page.click('#start-review');const response=await created;const data=await response.json();
    if(response.status()!==202)throw new Error('Task creation failed: '+JSON.stringify(data));
    prior={task_id:data.task.task_id,created_at:new Date().toISOString(),clauses:['Q5','Q8'],source:'real browser upload and button click'};
    await fs.writeFile(path.join(qa,'live_run_created.json'),JSON.stringify(prior,null,2));
    assert(data.task.total===2,'server accepted exactly two actual review tasks');
  }
  await page.waitForSelector('#live-task-panel .live-summary');await screenshot('live_started_1440');
  let previous='',captured=false;
  const deadline=Date.now()+15*60*1000;
  while(Date.now()<deadline){
    const response=await context.request.get(`${base}/api/tasks/${prior.task_id}`);task=(await response.json()).task;
    const key=[task.status,task.stage,task.qid,task.round,task.completed].join('|');
    if(key!==previous){console.log('ACTUAL_PROGRESS',key);previous=key;}
    if(!captured&&task.events.some(e=>e.model_call_status==='REQUEST')){await screenshot('live_model_progress_1440');captured=true;}
    if(['COMPLETED','FAILED','STOPPED','CANCELLED','INTERRUPTED'].includes(task.status))break;
    await page.waitForTimeout(1200);
  }
  assert(task.status==='COMPLETED','native Agent process completed the real uploaded contract');
  assert(task.completed===2&&task.total===2,'actual completed count is 2/2');
  assert(task.events.some(e=>e.stage==='retrieval'&&e.candidate_count>0),'progress records actual nonempty retrieval candidates');
  assert(task.events.some(e=>e.stage==='rules'&&e.state==='NOT_EXECUTED'&&e.qid==='Q5'),'Q5 business rule phase is explicitly not executed');
  assert(task.events.some(e=>e.stage==='verification'&&e.model_call_status==='SUCCESS'),'semantic model verification actually responded');
  assert(task.report_id,'task links to a generated native JSON report');
  const report=(await (await context.request.get(`${base}/api/reports/${task.report_id}`)).json());
  const text=(await (await context.request.get(`${base}/api/reports/${task.report_id}/text`)).json());
  assert(report.checks.map(c=>c.qid).join(',')==='Q5,Q8','generated report contains exactly Q5/Q8');
  assert(report.checks.find(c=>c.qid==='Q5').rule_executed===false,'report preserves Q5 rule-not-executed semantics');
  assert(text.available,'new uploaded contract normalized text matches report hash');
  const quote=text.quotes.Q8?.[0];assert(quote?.position_matches,'Q8 evidence position matches newly uploaded contract');
  const download=await context.request.get(`${base}/api/reports/${task.report_id}/download`);
  assert(crypto.createHash('sha256').update(await download.body()).digest('hex')===report.report_sha256,'download is the exact native report');
  await page.waitForTimeout(1800);await screenshot('live_completed_1440');
  await page.click('#open-live-report');await page.waitForSelector('#report-rows tr[data-evidence="Q8"]');
  assert((await page.locator('.playback-badge').innerText()).includes(replay?'历史案例回放':'本次真实审查'),'live result and saved-task replay are correctly distinguished');await screenshot('live_report_1440');
  await page.locator('tr[data-evidence="Q8"]').click();await page.waitForSelector('[data-locate="0"]');await page.click('[data-locate="0"]');
  assert(await page.locator('#active-evidence').innerText()===report.checks.find(c=>c.qid==='Q8').predicted_answers[0].text,'new Q8 evidence highlights the actual normalized source quote');await screenshot('live_evidence_q8_1440');
  assert(errors.length===0,'live UI has no JavaScript errors');
  await fs.writeFile(path.join(qa,outputName),JSON.stringify({status:'PASS',scope:replay?'saved real task replay, no new Agent calls':'actual paid two-clause browser integration',additional_model_calls:replay?0:undefined,task_id:task.task_id,
    output_directory:task.output_directory,report_id:task.report_id,report_source:report.source_file,report_stats:report.stats,api_usage:task.api_usage,
    model:report.configuration.extraction_model,checks,errors},null,2));
  console.log(replay?'REAL_TASK_REPLAY_PASS':'REAL_INTEGRATION_PASS',JSON.stringify({task_id:task.task_id,api_usage:task.api_usage,stats:report.stats}));
}catch(error){await screenshot('live_integration_failure');await fs.writeFile(path.join(qa,outputName),JSON.stringify({status:'FAIL',task_id:prior?.task_id,
  error:error.message,actual_status:task?.status,checks,errors},null,2));throw error;}
finally{await browser.close();}

// User-requested cleanup verification; only existing-report GETs, no model calls.
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),base=process.env.WORKBENCH_URL||'http://127.0.0.1:8770';
const expected=['CUAD-001_d0873843','CUAD-004_7afb02da','CUAD-008_ba9c81fe','demo_contract_4bb14120'];
const checks=[],errors=[],requests=[];
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
context.on('request',r=>requests.push({method:r.method(),url:r.url()}));
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push({check:label,status:'PASS'});console.log('PASS',label);};
try{
  await page.goto(base+'/#/overview',{waitUntil:'networkidle'});await page.waitForSelector('#report-rows tr');
  const data=await(await context.request.get(base+'/api/bootstrap')).json();
  assert(data.offline_mode,'cleanup verification runs with model calls disabled');
  assert(data.reports.length>=4&&expected.every(id=>data.reports.some(r=>r.document_id===id)),'all four protected reports remain, with any later genuine uploads');
  assert(await page.locator('#case-select option').count()===data.reports.length,'report dropdown matches the actual saved reports');
  const labels=await page.locator('#case-select option').allTextContents();
  assert(labels.filter(t=>t.includes('CUAD-001')).length===1,'CUAD-001 appears once in the dropdown');
  assert(!labels.some(t=>/网站托管|演示合同|认证失败|0d3c8517/.test(t)),'all explicitly removed labels are gone');
  for(const report of data.reports){
    await page.selectOption('#case-select',report.id);await page.waitForFunction(({id,count})=>state.caseId===id&&document.querySelectorAll('#report-rows tr[data-evidence]').length===count,{id:report.id,count:report.count});
    assert(await page.locator('#report-rows tr[data-evidence]').count()===report.count,`${report.document_id} opens its actual result rows`);
  }
  await page.locator('.nav-item[data-view="history"]').click();await page.waitForSelector('.history-card');
  assert(await page.locator('.history-card').count()===data.reports.length,'history cards match the actual saved reports');
  assert(await page.locator('[data-history-filter="demo"]').count()===0,'empty legacy demo filter is not shown');
  await page.screenshot({path:path.join(web,'qa/history_cleanup_history.png'),fullPage:true});
  // Controlled stale-memory ID only; no deleted report is recreated.
  await page.evaluate(()=>state.caseId='CONTROLLED_REMOVED_REPORT_ID');
  await page.click('#refresh-reports');await page.waitForFunction(()=>state.report?.identity.document_id==='CUAD-004_7afb02da');
  assert(await page.locator('#case-select').inputValue()===data.reports.find(r=>r.document_id==='CUAD-004_7afb02da').id,'refresh safely replaces a missing cached selection');
  await page.screenshot({path:path.join(web,'qa/history_cleanup_refreshed.png'),fullPage:true});
  assert(errors.length===0,'cleanup interactions have no JavaScript errors');
  assert(!requests.some(r=>r.method!=='GET'),'cleanup playback never submits or starts a review');
  await fs.writeFile(path.join(web,'qa/history_cleanup_browser.json'),JSON.stringify({status:'PASS',checks,errors,requests,
    remaining_reports:data.reports.map(r=>({document_id:r.document_id,title:r.title})),model_api_calls:0,
    controlled_test:'stale browser selection only; no files recreated'},null,2));
}catch(error){await fs.writeFile(path.join(web,'qa/history_cleanup_browser.json'),JSON.stringify({status:'FAIL',checks,errors,error:error.message,model_api_calls:0},null,2));throw error;}
finally{await browser.close();}

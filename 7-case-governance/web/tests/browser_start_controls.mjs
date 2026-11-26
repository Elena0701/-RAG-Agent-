import {loginBrowser} from './browser_access_helper.mjs';
// CONTROLLED frontend capability flag test against an OFFLINE backend. No Agent can start.
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),base=process.env.WORKBENCH_URL||'http://127.0.0.1:8770';
const initial=await(await fetch(base+'/api/bootstrap')).json();
if(!initial.offline_mode)throw new Error('This controlled test requires an OFFLINE backend');
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),checks=[],errors=[];
await context.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
// This only exposes the normal-mode button for frontend validation. The actual server remains offline.
await context.route('**/api/bootstrap',async r=>{const response=await r.fetch();const data=await response.json();await r.fulfill({response,json:{...data,offline_mode:false,realtime_enabled:true,model_api_calls_enabled:true}});});
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push({check:label,status:'PASS'});console.log('PASS',label);};
try{
  await loginBrowser(context,base,{fixturePath:path.join(web,'qa/audit_login.json')});
  await page.goto(base+'/#/overview',{waitUntil:'networkidle'});await page.waitForSelector('#report-rows tr');
  await page.click('.nav-item[data-view="workbench"]');await page.waitForSelector('#start-review');
  await page.click('#start-review');assert((await page.locator('#toast').innerText()).includes('请选择合同文件'),'normal start button validates missing contract');
  await page.click('[data-preset="none"]');await page.setInputFiles('#contract-file',path.resolve(web,'../../4-agent/code/contracts/demo_contract.txt'));
  await page.click('#start-review');assert((await page.locator('#toast').innerText()).includes('至少一个条款'),'start validates an empty clause selection');
  await page.check('.clause-check[value="Q5"]');await page.check('.clause-check[value="Q8"]');
  let dialogText='';page.once('dialog',async d=>{dialogText=d.message();await d.dismiss();});
  await page.click('#start-review');assert(dialogText.includes('2类条款')&&dialogText.includes('模型请求'),'scope confirmation states actual selected task count and model calls');
  assert(await page.locator('#start-review').isEnabled(),'cancelling confirmation leaves start button usable');
  page.once('dialog',d=>d.accept());const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url()===base+'/api/tasks');
  await page.click('#start-review');assert((await response).status()===503,'offline server blocks task creation even when normal UI button is exercised');
  await page.waitForFunction(()=>document.querySelector('#toast')?.innerText.includes('离线回放模式'));
  await page.waitForFunction(()=>!document.querySelector('#start-review').disabled);
  assert(await page.locator('#start-review').isEnabled(),'server rejection does not leave the button stuck disabled');
  assert((await page.locator('#toast').innerText()).includes('离线回放模式'),'backend failure reason appears as real feedback');
  // Exercise the actual drag/drop handler, without submitting the file to a model.
  const transfer=await page.evaluateHandle(()=>{const dt=new DataTransfer();dt.items.add(new File(['CONTROLLED drag-and-drop only'], 'controlled_drop.txt',{type:'text/plain'}));return dt;});
  await page.dispatchEvent('#upload-zone','drop',{dataTransfer:transfer});
  assert((await page.locator('#file-meta').innerText()).includes('controlled_drop.txt'),'drag/drop updates the actual selected file');
  await page.click('#clear-contract');assert(await page.locator('#file-meta').innerText()==='','remove button clears dragged file');
  const id=await page.locator('.quick-case').first().getAttribute('data-load-case');await page.locator('.quick-case').first().click();
  await page.waitForSelector('#report-rows tr');assert(await page.locator('#case-select').inputValue()===id,'workbench quick-case button opens the selected saved report');
  assert(errors.length===0,'controlled normal-mode frontend validation has no JavaScript errors');
  await fs.writeFile(path.join(web,'qa/start_control_results.json'),JSON.stringify({status:'PASS',checks,errors,model_api_calls:0,
    scope:'controlled frontend capability flag; actual backend offline; one task request intentionally rejected, no worker spawned'},null,2));
}catch(e){await fs.writeFile(path.join(web,'qa/start_control_results.json'),JSON.stringify({status:'FAIL',error:e.message,checks,errors,model_api_calls:0},null,2));throw e;}
finally{await context.unrouteAll({behavior:'ignoreErrors'});await browser.close();}

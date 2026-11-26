// Same-host LAN-address smoke check. Uses an existing admin invitation, no task POST.
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),qa=path.join(web,'qa');
const base=process.env.WORKBENCH_URL;
if(!base)throw new Error('WORKBENCH_URL must be the running LAN address');
const handover=await fs.readFile(path.join(web,'data/access/初始邀请码_仅管理员查看.txt'),'utf8');
const code=handover.match(/邀请码：(HQ-[A-Z2-7-]+)/)?.[1];
if(!code)throw new Error('Initial admin invitation not found');
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),checks=[],errors=[],requests=[];
const host=new URL(base).hostname;
await context.route('**/*',r=>[host,'127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));context.on('request',r=>requests.push({method:r.method(),url:r.url()}));
const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push({check:label,status:'PASS'});console.log('PASS',label);};
try{
  const response=await page.goto(base,{waitUntil:'networkidle'});await page.waitForSelector('#start-review');
  assert(response.status()===200,'real Flask service responds on its own LAN address');
  assert((await page.locator('.local-label').innerText()).includes('小组共享工作区'),'shared workspace uses actual browser host');
  await page.click('#account-controls button');await page.fill('#invite-code',code);await page.click('#invite-login-submit');
  await page.waitForFunction(()=>state.system.access.authenticated);
  assert((await page.locator('.access-banner').innerText()).includes('管理员'),'initial administrator invitation works on real LAN endpoint');
  const status=await(await context.request.get(base+'/api/bootstrap')).json();
  assert(status.access.max_clauses===41&&status.access.daily_limit===5,'production administrator limits match issued invitation');
  assert(status.access.used_today===0,'login alone consumes no review allowance');
  await page.locator('[data-view="overview"]').click();await page.waitForSelector('#report-rows tr');
  assert(await page.locator('#report-rows tr[data-evidence]').count()===41,'CUAD-004 actual report opens over LAN address');
  await page.locator('tr[data-evidence="Q16"]').click();await page.waitForSelector('[data-locate="0"]');await page.click('[data-locate="0"]');
  assert((await page.locator('#active-evidence').innerText()).includes('for convenience'),'actual evidence highlights over LAN address');
  await page.screenshot({path:path.join(qa,'sharing_lan_evidence_1440.png')});
  await page.click('#account-controls button');await page.click('#logout-account');await page.waitForFunction(()=>!state.system.access.authenticated);
  assert(!requests.some(r=>r.method==='POST'&&r.url.endsWith('/api/tasks')),'LAN smoke check never submits a paid Agent task');
  assert(errors.length===0,'LAN page has no browser JavaScript errors');
  await fs.writeFile(path.join(qa,'sharing_lan_results.json'),JSON.stringify({status:'PASS',base,scope:'same host accessing its actual LAN interface; not a second physical computer',model_api_calls:0,checks,errors},null,2));
}catch(error){await fs.writeFile(path.join(qa,'sharing_lan_results.json'),JSON.stringify({status:'FAIL',base,checks,errors,error:error.message,model_api_calls:0},null,2));throw error;}
finally{await browser.close();}

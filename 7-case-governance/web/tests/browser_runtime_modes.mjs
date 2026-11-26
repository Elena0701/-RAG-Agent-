import {loginBrowser} from './browser_access_helper.mjs';
// UI mode switching only; never POST /api/tasks or invoke a model.
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const base=process.env.WORKBENCH_URL||'http://127.0.0.1:8772';
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.route('**/*',route=>['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname)?route.continue():route.abort());
const page=await context.newPage(),checks=[],requests=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));context.on('request',r=>requests.push({method:r.method(),url:r.url()}));
const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push({check:label,status:'PASS'});console.log('PASS',label);};
try{
  await loginBrowser(context,base);
  await page.goto(base,{waitUntil:'networkidle'});await page.waitForSelector('#report-rows tr');
  const initial=await(await context.request.get(base+'/api/bootstrap')).json();
  assert(initial.offline_mode&&initial.can_enable_realtime,'explicit offline startup initially blocks new review');
  await page.locator('[data-view="workbench"]').click();await page.waitForSelector('#start-review');
  assert(await page.locator('#start-review').isDisabled(),'offline start button is actually disabled');
  assert(await page.locator('#enable-realtime').isVisible(),'offline page offers an explicit real-time enable control');
  await page.click('#enable-realtime');await page.waitForFunction(()=>state.system.realtime_enabled&&!state.system.offline_mode);
  assert(await page.locator('#start-review').isEnabled(),'mode switch enables the real upload review button');
  assert((await page.locator('#connection-state').innerText()).includes('实时审查 · 已启用'),'mode switch updates the visible availability label');
  const switched=await(await context.request.get(base+'/api/bootstrap')).json();
  assert(switched.realtime_enabled&&!switched.offline_mode,'backend availability changes together with UI');
  await page.goto(base,{waitUntil:'networkidle'});await page.waitForSelector('#start-review');
  assert(await page.locator('#page-title').innerText()==='审查工作台','fresh URL now opens the live upload page');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'1440 desktop mode controls have no horizontal overflow');
  await page.screenshot({path:path.join(web,'qa/runtime_mode_enabled_1440.png')});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'390 mobile mode controls have no horizontal overflow');
  await page.screenshot({path:path.join(web,'qa/runtime_mode_enabled_390.png')});
  assert(!requests.some(r=>r.method==='POST'&&r.url.endsWith('/api/tasks')),'enabling real-time availability never starts an Agent task');
  assert(errors.length===0,'mode switching produces no browser JavaScript errors');
  await fs.writeFile(path.join(web,'qa/runtime_modes_result.json'),JSON.stringify({status:'PASS',model_api_calls:0,checks,errors,requests},null,2));
}catch(error){await fs.writeFile(path.join(web,'qa/runtime_modes_result.json'),JSON.stringify({status:'FAIL',model_api_calls:0,checks,errors,error:error.message},null,2));throw error;}
finally{await browser.close();}

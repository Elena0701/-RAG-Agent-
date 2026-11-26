// Controlled authentication/upload UI tests; server launcher is fake, zero model calls.
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),qa=path.join(web,'qa');
const fixture=JSON.parse(await fs.readFile(path.join(qa,'sharing_test_fixture.json'),'utf8'));
const base='http://127.0.0.1:8774',checks=[],errors=[];
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push({check:label,status:'PASS'});console.log('PASS',label);};
const shot=name=>page.screenshot({path:path.join(qa,'sharing_'+name+'.png')});
const login=async role=>{await page.click('#account-controls button');await page.fill('#invite-code',fixture[role].code);await page.click('#invite-login-submit');await page.waitForFunction(()=>state.system.access.authenticated);};
const logout=async()=>{await page.click('#account-controls button');await page.click('#logout-account');await page.waitForFunction(()=>!state.system.access.authenticated);};
try{
  await page.goto(base,{waitUntil:'networkidle'});await page.waitForSelector('#start-review');
  assert((await page.locator('#connection-state').innerText()).includes('实时需登录'),'guest sees live review requires login');
  assert(await page.locator('.access-banner').innerText().then(t=>t.includes('无需输入API密钥')),'guest sees invitation is distinct from model API key');
  await page.click('#start-review');await page.waitForSelector('#access-dialog[open]');
  assert(await page.locator('#invite-code').getAttribute('type')==='password','invitation input is masked');
  await page.fill('#invite-code','CONTROLLED invalid code');await page.click('#invite-login-submit');await page.waitForFunction(()=>document.querySelector('#access-error').textContent.length>0);
  assert((await page.locator('#access-error').innerText()).includes('邀请码无效'),'invalid invitation receives actual backend error');
  await shot('login_1440');await page.click('#close-access');
  await login('member_a');assert((await page.locator('.access-banner').innerText()).includes('每次最多5类'),'member allowance is read from server');
  assert((await page.locator('#connection-state').innerText()).includes('实时审查 · 已启用'),'authorized member sees live review available');
  await page.setInputFiles('#contract-file',path.resolve(web,'../contracts/CUAD-001.txt'));
  await page.click('[data-preset="all"]');await page.click('#start-review');
  assert((await page.locator('#toast').innerText()).includes('最多5类'),'member cannot submit 41-clause task from UI');
  assert((await(await context.request.get(base+'/api/qa/state')).json()).controlled_subprocess_launches===0,'login and rejected scope never launch subprocess');
  await page.click('[data-preset="none"]');await page.check('.clause-check[value="Q5"]');
  page.once('dialog',d=>d.accept());const created=page.waitForResponse(r=>r.url()===base+'/api/tasks'&&r.request().method()==='POST');
  await page.click('#start-review');const result=await(await created).json();
  assert(result.task?.owner_id===fixture.member_a.id,'controlled upload is bound to logged-in member on server');
  await page.waitForSelector('#live-task-panel .live-summary');
  assert(await page.locator('#start-review').isDisabled(),'running controlled task blocks repeated starts');
  assert((await(await context.request.get(base+'/api/bootstrap')).json()).access.used_today===1,'created task consumes exactly one allowance');
  page.once('dialog',d=>d.accept());await page.click('#cancel-live-task');await page.waitForFunction(()=>state.task.status==='CANCELLED');
  assert(await page.locator('#start-review').isEnabled(),'owner cancellation restores upload availability');
  await shot('member_1440');await logout();
  assert((await page.locator('#connection-state').innerText()).includes('实时需登录'),'logout closes live authorization');
  assert(await page.locator('#file-meta').innerText()==='','logout clears selected contract from shared browser UI');
  await login('member_b');
  assert((await context.request.get(base+'/api/tasks/'+result.task.task_id)).status()===404,'member B cannot retrieve member A task');
  await page.locator('[data-view="history"]').click();await page.waitForSelector('.history-card');await page.click('#refresh-tasks');
  await page.waitForFunction(()=>document.querySelector('#task-history-list').textContent.includes('暂无'));
  assert(await page.locator('[data-open-task]').count()===0,'member B task history excludes member A upload');
  await logout();await login('admin');await page.locator('[data-view="workbench"]').click();await page.click('[data-preset="all"]');
  assert(await page.locator('.clause-check:checked').count()===41,'admin retains all 41 catalog choices');
  assert((await page.locator('.access-banner').innerText()).includes('每次最多41类'),'admin allowance correctly differs from member');
  await page.click('#account-controls button');await shot('admin_account');await page.click('#close-access');
  for(const width of [1920,1280,390]){
    await page.setViewportSize({width,height:width===390?844:1000});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${width}px authenticated workbench has no horizontal overflow`);
  }
  await shot('mobile_authenticated');await logout();
  await page.click('#account-controls button');assert(await page.locator('#access-dialog').isVisible(),'login modal works on mobile');await shot('mobile_login');await page.click('#close-access');
  const start=await(await context.request.get(base+'/api/qa/state')).json();
  assert(start.controlled_subprocess_launches===1&&start.model_api_calls===0,'one controlled fake launch; zero actual model calls');
  assert(errors.length===0,'authentication interactions have no JavaScript errors');
  await fs.writeFile(path.join(qa,'sharing_browser_results.json'),JSON.stringify({status:'PASS',scope:'controlled auth/upload boundary tests; fake subprocess, not an Agent result',model_api_calls:0,checks,errors},null,2));
}catch(error){await shot('failure');await fs.writeFile(path.join(qa,'sharing_browser_results.json'),JSON.stringify({status:'FAIL',checks,errors,error:error.message,model_api_calls:0},null,2));throw error;}
finally{await browser.close();}

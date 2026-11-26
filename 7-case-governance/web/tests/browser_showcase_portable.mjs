// Independent file location and static HTTP subdirectory checks. No model/backend.
import {createRequire} from 'node:module';
import http from 'node:http';
import path from 'node:path';
import fs from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),qa=path.join(web,'qa');
const html=await fs.readFile(path.join(web,'showcase/dist/index.html'));
const folder=await fs.mkdtemp(path.join(qa,'showcase_portable_')),copied=path.join(folder,'明契 展示.html');
await fs.writeFile(copied,html);
const requests=[],checks=[],errors=[];
const server=http.createServer((request,response)=>{requests.push({method:request.method,url:request.url});if(request.url.split('?')[0]==='/course/index.html'){response.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});response.end(html);}else{response.writeHead(404);response.end('Not part of static showcase');}});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push({check:label,status:'PASS'});console.log('PASS',label);};
try{
  const local=await browser.newContext({viewport:{width:1440,height:1000}});await local.setOffline(true);
  const page=await local.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(pathToFileURL(copied).href+'#/overview');await page.waitForSelector('#report-rows tr[data-evidence]');
  assert(await page.locator('#report-rows tr[data-evidence]').count()===41,'renamed HTML in a different Chinese/spaced directory opens offline');
  await page.locator('[data-view="workbench"]').click();await page.waitForSelector('.showcase-case');
  assert(await page.locator('.showcase-case').count()===3,'portable copy retains all three embedded cases');
  await local.close();
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  const hosted=await context.newPage();hosted.on('pageerror',e=>errors.push(e.message));
  await hosted.goto(`http://127.0.0.1:${server.address().port}/course/index.html#/overview`);await hosted.waitForSelector('#report-rows tr[data-evidence]');
  assert(await hosted.locator('#report-rows tr[data-evidence]').count()===41,'static HTTP hosting under a project subdirectory works');
  await hosted.locator('tr[data-evidence="Q16"]').click();await hosted.waitForSelector('[data-locate="0"]');await hosted.click('[data-locate="0"]');
  assert((await hosted.locator('#active-evidence').innerText()).includes('for convenience'),'static hosting preserves true evidence locating');
  const start=hosted.waitForEvent('download');await hosted.locator('a[href$="/download"]').click();const download=await start;
  assert((await fs.readFile(await download.path())).length>0,'native JSON download works without a backend route');
  assert(requests.every(r=>r.method==='GET'&&r.url.startsWith('/course/index.html')),'host only serves the static document; no API requests');
  assert(errors.length===0,'portable and hosted editions have no browser JavaScript errors');
  await fs.writeFile(path.join(qa,'showcase_portable_results.json'),JSON.stringify({status:'PASS',checks,errors,requests,model_api_calls:0,scope:'relocated file and temporary localhost static hosting; not a public deployment'},null,2));
}finally{
  await browser.close();await new Promise(resolve=>server.close(resolve));
  const resolved=path.resolve(folder),boundary=path.resolve(qa)+path.sep;
  if(!resolved.startsWith(boundary)||!path.basename(resolved).startsWith('showcase_portable_'))throw new Error('Unsafe cleanup path');
  await fs.rm(resolved,{recursive:true});
}

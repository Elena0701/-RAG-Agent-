import fs from 'node:fs/promises';
export async function loginBrowser(context,base,{fixturePath,required=true}={}){
  let code;
  if(process.env.WORKBENCH_INVITE_FILE)code=(await fs.readFile(process.env.WORKBENCH_INVITE_FILE,'utf8')).trim();
  else if(fixturePath){
    const bootstrap=await(await context.request.get(base+'/api/bootstrap')).json();
    if(!bootstrap.audit_environment)throw new Error('Test credentials are only for the isolated audit server');
    code=JSON.parse(await fs.readFile(fixturePath,'utf8')).code;
  }
  if(!code){if(required)throw new Error('Invite login required. Set WORKBENCH_INVITE_FILE to a private file containing one invitation code. No model task was started.');return;}
  const initial=await(await context.request.get(base+'/api/bootstrap')).json();
  const response=await context.request.post(base+'/api/auth/login',{headers:{'X-Workbench-Token':initial.review_token},data:{code}});
  if(response.status()!==200)throw new Error('Test invite login failed; no model task was started.');
}

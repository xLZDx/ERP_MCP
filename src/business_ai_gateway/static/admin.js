const state={me:null,csrf:null,page:'overview'};
const pages={
 overview:['Overview','Live control-plane status and administrative activity.'],
 sources:['1C sources','Registered read-only 1C endpoints and capability health.'],
 companies:['Companies','Business organizations registered inside technical 1C sources.'],
 identities:['Users & groups','Resolve stable IdP subject/group IDs and inspect effective policy.'],
 access:['Access policies','Subject/group grants. Explicit deny overrides allow.'],
 roles:['Roles & capabilities','Platform roles and business capability templates.'],
 profiles:['Semantic profiles','Evidence-backed semantic profile lifecycle.'],
 audit:['Audit & evidence','Immutable runtime and administration evidence.']
};
async function api(path,opts={}){
 const headers={'Accept':'application/json',...(opts.headers||{})};
 if(opts.body){headers['Content-Type']='application/json'}
 if(state.csrf && (opts.method||'GET')!=='GET'){headers['X-CSRF-Token']=state.csrf}
 if((opts.method||'GET')!=='GET' && !headers['Idempotency-Key']){headers['Idempotency-Key']=crypto.randomUUID()}
 const res=await fetch(path,{credentials:'same-origin',...opts,headers});
 let body={};try{body=await res.json()}catch{}
 if(res.status===401){showLogin();throw new Error('AUTH_REQUIRED')}
 if(!res.ok){throw new Error(res.status===409?'Conflict: '+(body.error||'the record changed; reload and retry'):(body.error||('HTTP_'+res.status)))}
 return body
}
function showLogin(){
 document.getElementById('root').innerHTML='<div class="login"><div class="loginbox"><div class="logo" style="margin-bottom:16px">E</div><h1>ERP_MCP Admin Control Center</h1><p class="muted">Sign in through your corporate identity provider. ERP_MCP does not store local passwords.</p><a class="btn primary" style="display:inline-block;text-decoration:none;margin-top:10px" href="/admin/login">Sign in with OIDC</a></div></div>'
}
function shell(content,actions=''){
 const p=pages[state.page];
 return '<div class="app"><aside class="side"><div class="brand"><div class="logo">E</div><div><b>ERP_MCP</b><small>Admin Control Center</small></div></div><nav class="nav">'+Object.keys(pages).map(k=>'<button data-page="'+k+'" class="'+(state.page===k?'active':'')+'">◫ <span>'+pages[k][0]+'</span></button>').join('')+'</nav><div class="sidefoot">Authenticated as<br><b>'+esc(state.me.subject)+'</b></div></aside><main class="main"><header class="top"><div>ERP_MCP / <b>'+p[0]+'</b></div><div style="display:flex;gap:8px;align-items:center"><span class="chip">'+state.me.roles.map(r=>r.role).join(', ')+'</span><button class="btn" data-act="logout">Sign out</button></div></header><section class="content"><div class="head"><div><h1>'+p[0]+'</h1><p>'+p[1]+'</p></div><div class="actions">'+actions+'</div></div>'+content+'</section></main></div>'
}
function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function tag(v,c=''){return '<span class="tag '+c+'">'+esc(v)+'</span>'}
function rows(items,cols){
 if(!items.length)return '<tr><td colspan="'+cols.length+'" class="empty">No records</td></tr>';
 return items.map(x=>'<tr>'+cols.map(c=>'<td>'+c.f(x)+'</td>').join('')+'</tr>').join('')
}
function table(title,items,cols){
 return '<div class="card"><div class="cardhead"><div><h2>'+title+'</h2><small>'+items.length+' records</small></div></div><div class="tablewrap"><table><thead><tr>'+cols.map(c=>'<th>'+c.h+'</th>').join('')+'</tr></thead><tbody>'+rows(items,cols)+'</tbody></table></div></div>'
}
async function render(){
 try{
  if(state.page==='overview'){
   const x=await api('/admin/v1/overview');
   document.getElementById('root').innerHTML=shell('<div class="grid"><div class="metric"><label>Sources</label><strong>'+x.sources+'</strong></div><div class="metric"><label>Companies</label><strong>'+x.companies+'</strong></div><div class="metric"><label>Metadata drift</label><strong>'+x.drifted_sources+'</strong></div><div class="metric"><label>Mutations</label><strong>'+(state.me.mutations_enabled?'ON':'OFF')+'</strong></div></div><div class="banner">Live values come from the server. Generic company-scope mappings are recorded as candidates only and do not authorize OData reads. Company-aware access uses fixed canonical operations.</div>');
  } else if(state.page==='sources'){
   const x=await api('/admin/v1/sources');
   document.getElementById('root').innerHTML=shell(table('Registered sources',x.items,[{h:'Source',f:i=>'<b>'+esc(i.display_name)+'</b><span class="muted"><br>'+esc(i.source_id)+'</span>'},{h:'Kind',f:i=>esc(i.kind)},{h:'Read-only',f:i=>tag(i.read_only?'Yes':'No',i.read_only?'ok':'deny')},{h:'Enabled',f:i=>tag(i.enabled?'Enabled':'Disabled',i.enabled?'ok':'warn')},{h:'Version',f:i=>esc(i.row_version)}]),'<button class="btn primary" data-act="sourceModal">＋ Connect source</button>');
  } else if(state.page==='companies'){
   const x=await api('/admin/v1/companies');
   document.getElementById('root').innerHTML=shell(table('Registered companies',x.items,[{h:'Company',f:i=>'<b>'+esc(i.display_name)+'</b><span class="muted"><br>'+esc(i.company_id)+'</span>'},{h:'Source',f:i=>esc(i.source_id)},{h:'External ref',f:i=>esc(i.external_ref)},{h:'State',f:i=>tag(i.enabled?'Active':'Disabled',i.enabled?'ok':'warn')},{h:'Version',f:i=>esc(i.row_version)}]),'<button class="btn primary" data-act="companyModal">＋ Register company</button>');
  } else if(state.page==='identities'){
   document.getElementById('root').innerHTML=shell('<div class="banner">ERP_MCP does not create users or passwords. Use a stable IdP subject/group ID. Directory search can be added server-side later; exact-ID mode is always explicit.</div><div class="card"><div class="cardhead"><div><h2>Resolve principal</h2><small>Exact-ID fallback</small></div></div><div class="form"><div class="row2"><div class="field"><label>Kind</label><select id="p_kind"><option>subject</option><option>group</option></select></div><div class="field"><label>Stable ID</label><input id="p_id" placeholder="user-847293 or finance-reviewers"></div></div><button class="btn primary" data-act="resolvePrincipal">Resolve</button><div id="principal_result"></div></div></div>');
  } else if(state.page==='access'){
   const x=await api('/admin/v1/grants');
   document.getElementById('root').innerHTML=shell(table('Access grants',x.items,[{h:'Principal',f:i=>'<b>'+esc(i.principal_id)+'</b><br>'+tag(i.principal_kind)},{h:'Source',f:i=>esc(i.source_id)},{h:'Company scope',f:i=>esc(i.company_id||'Source-wide')},{h:'Effect',f:i=>tag(i.effect,i.effect==='deny'?'deny':'ok')},{h:'Expires',f:i=>esc(i.expires_at||'No expiry')},{h:'Version',f:i=>esc(i.row_version)},{h:'Action',f:i=>i.revoked_at?tag('Revoked','warn'):'<button class="btn danger" data-act="revokeGrant" data-id="'+esc(i.grant_id)+'" data-version="'+esc(i.row_version)+'">Revoke</button>'}]),'<button class="btn primary" data-act="grantModal">＋ Create grant</button>');
  } else if(state.page==='roles'){
   const r=await api('/admin/v1/business-roles'); const a=await api('/admin/v1/business-role-assignments'); const o=await api('/admin/v1/capability-overrides');
   let p={items:[]}; try{p=await api('/admin/v1/platform-role-bindings')}catch{}
   const body=table('Platform role bindings',p.items,[{h:'Principal',f:i=>esc(i.principal_id)},{h:'Role',f:i=>tag(i.role_name,'ok')},{h:'Source scope',f:i=>esc(i.source_id||'global')},{h:'State',f:i=>i.revoked_at?tag('Revoked','warn'):tag('Active','ok')},{h:'Version',f:i=>esc(i.row_version)}])+'<div style="height:14px"></div>'+table('Business role templates',r.items,[{h:'Role',f:i=>'<b>'+esc(i.display_name)+'</b><br>'+esc(i.role_id)},{h:'Capabilities',f:i=>(i.capabilities||[]).map(x=>tag(x,'ok')).join(' ')},{h:'Policy',f:i=>esc(i.policy_version)}])+'<div style="height:14px"></div>'+table('Assignments',a.items,[{h:'Principal',f:i=>esc(i.principal_id)},{h:'Role',f:i=>esc(i.role_id)},{h:'Source',f:i=>esc(i.source_id)},{h:'Company',f:i=>esc(i.company_id||'all in source')},{h:'State',f:i=>i.revoked_at?tag('Revoked','warn'):tag('Active','ok')}])+'<div style="height:14px"></div>'+table('Capability overrides',o.items,[{h:'Principal',f:i=>esc(i.principal_id)},{h:'Capability',f:i=>esc(i.capability_key)},{h:'Effect',f:i=>tag(i.effect,i.effect==='deny'?'deny':'ok')},{h:'Source',f:i=>esc(i.source_id)}]);
   document.getElementById('root').innerHTML=shell(body);
  } else if(state.page==='profiles'){
   const x=await api('/admin/v1/semantic-profiles');
   document.getElementById('root').innerHTML=shell(table('Semantic profiles',x.items,[{h:'Profile',f:i=>'<b>'+esc(i.profile_name)+'</b><br>'+esc(i.profile_id)},{h:'Source',f:i=>esc(i.source_id)},{h:'Company',f:i=>esc(i.company_id||'source-wide')},{h:'Status',f:i=>tag(i.status,i.status==='VALIDATED'?'ok':i.status==='STALE'?'warn':'')},{h:'Version',f:i=>esc(i.profile_version)}]));
  } else if(state.page==='audit'){
   const x=await api('/admin/v1/audit'); const all=[...(x.admin||[]).map(i=>({...i,stream:'admin'})),...(x.access||[]).map(i=>({...i,stream:'runtime'}))];
   document.getElementById('root').innerHTML=shell(table('Audit events',all,[{h:'Time',f:i=>esc(i.occurred_at)},{h:'Stream',f:i=>tag(i.stream)},{h:'Actor',f:i=>esc(i.actor_subject||i.principal_subject)},{h:'Action',f:i=>esc(i.action||i.tool_name)},{h:'Source',f:i=>esc(i.source_id||'—')},{h:'Outcome',f:i=>tag(i.outcome,i.outcome==='success'?'ok':i.outcome==='denied'?'deny':'warn')}]));
  }
  document.querySelectorAll('.nav button').forEach(b=>b.onclick=()=>{state.page=b.dataset.page;render()});
 }catch(e){if(e.message!=='AUTH_REQUIRED')document.getElementById('root').innerHTML=shell('<div class="banner warn" role="alert">'+(e.message==='PLATFORM_ROLE_DENIED'?'Forbidden: your platform role does not permit this screen.':'Dependency unavailable or request failed. ')+esc(e.message)+'</div><button class="btn" data-act="render">Retry</button>')}
}
async function resolvePrincipal(){const out=document.getElementById('principal_result');out.innerHTML='<p class="muted">Resolving?</p>';try{const x=await api('/admin/v1/principals/resolve?kind='+encodeURIComponent(val('p_kind'))+'&id='+encodeURIComponent(val('p_id')));out.innerHTML='<div class="banner" style="margin-top:12px"><b>'+esc(x.principal_kind)+' ? '+esc(x.principal_id)+'</b><br>Directory: '+esc(x.directory_status)+'<br>Platform roles: '+(x.platform_roles||[]).map(i=>tag(i.role_name,'ok')).join(' ')+'<br>Grants: '+(x.grants||[]).length+' ? Business assignments: '+(x.business_role_assignments||[]).length+' ? Capability overrides: '+(x.capability_overrides||[]).length+'</div>'}catch(e){out.innerHTML='<p class="error">'+esc(e.message)+'</p>'}}
function modal(title,body,submit){document.getElementById('overlay').innerHTML='<div class="modalback"><section class="modal"><div class="modalh"><h2>'+title+'</h2><button class="btn" data-act="closeModal">×</button></div><div class="form">'+body+'</div><div class="modalf"><button class="btn" data-act="closeModal">Cancel</button><button class="btn primary" data-act="'+submit+'">Submit</button></div></section></div>'}
function closeModal(){document.getElementById('overlay').innerHTML=''}
function val(id){return document.getElementById(id).value.trim()}
function sourceModal(){modal('Connect 1C source','<div class="row2"><div class="field"><label>Source ID</label><input id="s_id"></div><div class="field"><label>Display name</label><input id="s_name"></div></div><div class="field"><label>OData URL</label><input id="s_url"><small>Must pass server-side egress policy.</small></div><div class="row2"><div class="field"><label>Username secret ref</label><input id="s_user"></div><div class="field"><label>Password secret ref</label><input id="s_pass"></div></div><div class="field"><label>Reason</label><textarea id="s_reason"></textarea></div>','createSource')}
async function createSource(){try{await api('/admin/v1/sources',{method:'POST',body:JSON.stringify({source_id:val('s_id'),display_name:val('s_name'),base_url:val('s_url'),username_secret_ref:val('s_user'),password_secret_ref:val('s_pass'),tags:[],reason:val('s_reason')})});closeModal();toast('Source registered');render()}catch(e){toast(e.message,true)}}
function companyModal(){modal('Register company','<div class="field"><label>Source ID</label><input id="c_source"></div><div class="field"><label>External reference</label><input id="c_ref"></div><div class="field"><label>Display name</label><input id="c_name"></div><div class="field"><label>Reason</label><textarea id="c_reason"></textarea></div>','createCompany')}
async function createCompany(){try{await api('/admin/v1/companies',{method:'POST',body:JSON.stringify({source_id:val('c_source'),external_ref:val('c_ref'),display_name:val('c_name'),reason:val('c_reason')})});closeModal();toast('Company registered');render()}catch(e){toast(e.message,true)}}
function grantModal(){modal('Create access grant','<div class="row2"><div class="field"><label>Principal kind</label><select id="g_kind"><option>subject</option><option>group</option></select></div><div class="field"><label>Principal ID</label><input id="g_principal"></div></div><div class="row2"><div class="field"><label>Source ID</label><input id="g_source"></div><div class="field"><label>Company UUID (optional)</label><input id="g_company"></div></div><div class="field"><label>Effect</label><select id="g_effect"><option>allow</option><option>deny</option></select></div><div class="field"><label>Reason</label><textarea id="g_reason"></textarea></div>','createGrant')}
async function createGrant(){try{await api('/admin/v1/grants',{method:'POST',body:JSON.stringify({principal_kind:val('g_kind'),principal_id:val('g_principal'),source_id:val('g_source'),company_id:val('g_company')||null,effect:val('g_effect'),reason:val('g_reason')})});closeModal();toast('Grant created');render()}catch(e){toast(e.message,true)}}
async function revokeGrant(id,version){const reason=prompt('Reason for revoke:');if(!reason)return;try{await api('/admin/v1/grants/'+encodeURIComponent(id)+'/revoke',{method:'POST',body:JSON.stringify({expected_version:version,reason})});toast('Grant revoked');render()}catch(e){toast(e.message,true)}}
async function logout(){try{await api('/admin/logout',{method:'POST'});location.href='/admin/'}catch{location.href='/admin/'}}
function toast(msg,bad=false){document.getElementById('toast').innerHTML='<div class="toast" style="'+(bad?'border-color:#82474a;background:#3a2023;color:#ffc0c0':'')+'">'+esc(msg)+'</div>';setTimeout(()=>document.getElementById('toast').innerHTML='',3000)}
(async()=>{try{state.me=await api('/admin/v1/me');state.csrf=state.me.csrf_token;await render()}catch(e){if(e.message!=='AUTH_REQUIRED')document.getElementById('root').innerHTML='<div class="login"><div class="loginbox"><h2>'+ (e.message==='PLATFORM_ROLE_DENIED'?'Access forbidden':'Administration unavailable')+'</h2><p role="alert">'+esc(e.message)+'</p><p>Contact your platform administrator if access is missing.</p><button class="btn" data-act="reload">Retry</button><a class="btn" href="/admin/login">Sign in</a></div></div>'}})();
;
// Structured lifecycle workflows reuse the same domain API and opaque session.
state.offset=0;state.more=false;state.records=[];state.workflow=null;state.renderGeneration=0;
const baseApi=api,baseRender=render,baseTable=table,baseModal=modal,baseShowLogin=showLogin;
showLogin=function(){state.me=null;state.csrf=null;state.workflow=null;document.getElementById('overlay').innerHTML='';baseShowLogin()};
const listPaths=new Set(['/admin/v1/sources','/admin/v1/companies','/admin/v1/grants','/admin/v1/platform-role-bindings','/admin/v1/business-role-assignments','/admin/v1/capability-overrides','/admin/v1/semantic-profiles','/admin/v1/capabilities','/admin/v1/company-scope-mappings','/admin/v1/audit']);
api=async function(path,opts={}){
 if(!opts.method&&listPaths.has(path)){path+='?limit=50&offset='+state.offset}
 const data=await baseApi(path,opts);if(data.next_offset!==null&&data.next_offset!==undefined)state.more=true;return data;
};
function permitted(role,source){return state.me?.mutations_enabled&&state.me.roles.some(r=>(r.role==='PLATFORM_ADMIN'||r.role===role)&&(!source||!r.source_id||r.source_id===source))}
function globalSourceAdmin(){return state.me?.roles.some(r=>['PLATFORM_ADMIN','SOURCE_ADMIN'].includes(r.role)&&!r.source_id)}
function operationButton(label,op,item,role,gate=true){
 if(!permitted(role,item.source_id)||!gate)return '';
 const index=state.records.push(item)-1;return '<button class="btn" data-op="'+op+'" data-record="'+index+'">'+label+'</button> ';
}
function policyState(item){return item.revoked_at?'Revoked':item.expires_at&&Date.parse(item.expires_at)<=Date.now()?'Expired':'Active'}
table=function(title,items,cols){
 if(['Access grants','Platform role bindings','Assignments','Capability overrides'].includes(title)){
  cols=cols.filter(c=>c.h!=='State');cols=[...cols,{h:'State',f:i=>tag(policyState(i),policyState(i)==='Active'?'ok':'warn')},{h:'Expiry',f:i=>esc(i.expires_at||'No expiry')}];
 }
 const actions={
 'Access grants':i=>i.revoked_at?'':operationButton('Revoke','grant-revoke',i,'ACCESS_ADMIN'),
 'Registered sources':i=>operationButton('Edit / disable','source',i,'SOURCE_ADMIN')+operationButton('Refresh metadata','refresh',i,'SOURCE_ADMIN'),
 'Registered companies':i=>operationButton('Edit / disable','company',i,'SOURCE_ADMIN'),
 'Platform role bindings':i=>i.revoked_at?'':operationButton('Revoke','platform-revoke',i,'PLATFORM_ADMIN',state.me.platform_role_step_up_configured),
 'Assignments':i=>i.revoked_at?'':operationButton('Revoke','assignment-revoke',i,'ACCESS_ADMIN',state.me.business_capability_enforcement_enabled),
 'Capability overrides':i=>i.revoked_at?'':operationButton('Revoke','override-revoke',i,'ACCESS_ADMIN',state.me.business_capability_enforcement_enabled),
 'Semantic profiles':i=>evidenceButton(i)+operationButton('Add mapping','profile-mapping',i,'PROFILE_ADMIN',['DRAFT','NEEDS_VALIDATION'].includes(i.status))+operationButton('Validate','profile-validate',i,'PROFILE_ADMIN',['DRAFT','NEEDS_VALIDATION'].includes(i.status))+operationButton('Retire','profile-retire',i,'PROFILE_ADMIN',i.status!=='RETIRED')+operationButton('Company mapping','company-mapping',i,'PROFILE_ADMIN',i.status==='VALIDATED'),
 'Metadata & drift':i=>operationButton('Acknowledge drift','drift',i,'SOURCE_ADMIN',i.drift_status==='DRIFTED')
 };
 if(actions[title])cols=[...cols.filter(c=>c.h!=='Action'),{h:'Operations',f:actions[title]}];
 return baseTable(title,items,cols);
};
render=async function(){
 if(state.renderBusy){state.renderRequested=true;return}state.renderBusy=true;const requestedPage=state.page;
 const generation=++state.renderGeneration;state.records=[];state.more=false;
 const root=document.getElementById('root');if(state.me)root.innerHTML=shell('<div role="status" class="loading">Loading…</div>');
 await baseRender();state.renderBusy=false;if(state.renderRequested||requestedPage!==state.page){state.renderRequested=false;return render()}if(generation!==state.renderGeneration||!document.querySelector('.content'))return;
 const content=document.querySelector('.content'),actions=document.querySelector('.actions');
 if(state.page==='sources'){
  try{const x=await api('/admin/v1/capabilities');content.insertAdjacentHTML('beforeend','<div style="height:14px"></div>'+table('Metadata & drift',x.items,[{h:'Source',f:i=>esc(i.source_id)},{h:'Fingerprint',f:i=>esc(i.metadata_fingerprint)},{h:'State',f:i=>tag(i.drift_status,i.drift_status==='DRIFTED'?'warn':'ok')},{h:'Adapter',f:i=>esc(i.adapter_profile)}]))}catch(e){content.insertAdjacentHTML('beforeend','<p role="alert">Metadata dependency unavailable: '+esc(e.message)+'</p>')}
 }
 if(state.page==='roles'){
  const disabled=!state.me.business_capability_enforcement_enabled;
  content.insertAdjacentHTML('afterbegin','<div class="banner warn">'+(disabled?'Business capability enforcement is OFF. Assignment controls are disabled until backend enforcement is active.':'Business capability enforcement is ON. Roles and overrides never widen data scope.')+' '+(!state.me.platform_role_step_up_configured?'Platform role changes require configured IdP step-up; browser changes are disabled.':'Platform role changes require an approved authentication level from the last five minutes.')+'</div>');
  if(permitted('PLATFORM_ADMIN')&&state.me.platform_role_step_up_configured)actions.insertAdjacentHTML('beforeend','<a class="btn" href="/admin/login?step_up=1">Authenticate for role change</a><button class="btn" data-act="platformRoleModal">Assign platform role</button>');
  if(permitted('ACCESS_ADMIN')&&!disabled)actions.insertAdjacentHTML('beforeend','<button class="btn" data-act="businessRoleModal">Assign business role</button><button class="btn" data-act="overrideModal">Capability override</button>');
 }
 if(state.page==='profiles'&&permitted('PROFILE_ADMIN'))actions.insertAdjacentHTML('beforeend','<button class="btn" data-act="profileModal">Create profile</button>');
 if(state.page==='identities')content.insertAdjacentHTML('beforeend',accessForm());
 document.querySelectorAll('[data-op]').forEach(b=>b.onclick=()=>operate(b.dataset.op,state.records[Number(b.dataset.record)]));
 document.querySelectorAll('.nav button').forEach(b=>{b.setAttribute('aria-label',pages[b.dataset.page][0]);b.onclick=()=>{state.page=b.dataset.page;state.offset=0;render()}});
 if(!state.me.mutations_enabled)content.insertAdjacentHTML('afterbegin','<div class="banner warn">Read-only mode: administrative mutations are disabled.</div>');
 const pageRole={sources:'SOURCE_ADMIN',companies:'SOURCE_ADMIN',access:'ACCESS_ADMIN'}[state.page];
 document.querySelectorAll('.actions button').forEach(b=>{if(!state.me.mutations_enabled||(pageRole&&!permitted(pageRole))||(state.page==='sources'&&!globalSourceAdmin()))b.disabled=true});
 if(listPaths.size&&state.page!=='identities'&&state.page!=='overview')content.insertAdjacentHTML('beforeend','<div class="actions" style="margin-top:14px"><button class="btn" data-act="pageBack" '+(state.offset?'':'disabled')+'>Previous</button><span>Page '+(state.offset/50+1)+'</span><button class="btn" data-act="pageNext" '+(state.more?'':'disabled')+'>Next</button></div>');
 labelForms();
 focusMainHeading();
};
function focusMainHeading(){const a=document.activeElement;if(document.querySelector('.modal')||(a&&a!==document.body&&a.isConnected))return;const h=document.querySelector('.content h1');if(h){h.tabIndex=-1;h.focus()}}
function pageBack(){state.offset=Math.max(0,state.offset-50);render()}function pageNext(){state.offset+=50;render()}
function labelForms(){document.querySelectorAll('.field').forEach(f=>{const label=f.querySelector('label'),input=f.querySelector('input,select,textarea');if(label&&input){if(!input.id)input.id='field-'+crypto.randomUUID();label.htmlFor=input.id}})}
function inputField(name,label,type='text',options=null){return {name,label,type,options}}
function evidenceButton(item){const index=state.records.push(item)-1;return '<button class="btn" data-op="profile-evidence" data-record="'+index+'">Evidence</button> '}
const principalFields=()=>[inputField('principal_kind','Principal kind','select',['subject','group']),inputField('principal_id','Stable IdP principal ID')];
const scopeFields=()=>[inputField('source_id','Source ID'),inputField('company_id','Company UUID (optional)')];
const expiryField=()=>inputField('expires_at','Expiry (optional, ISO timestamp with timezone)');
function workflow(title,path,fields,initial={},method='POST',help='',confirmValue=''){
 state.workflow={path,fields,initial,method,key:crypto.randomUUID(),payload:null,busy:false,confirmValue};
 let body=help?'<p class="workflow-help">'+esc(help)+'</p>':'';
 for(const f of [...fields,inputField('reason','Reason','textarea')]){
  const value=initial[f.name]??(f.type==='json'?'{}':'');
  const options=f.type==='boolean'?['true','false']:(f.options||[]);
  body+='<div class="field"><label for="wf_'+f.name+'">'+esc(f.label)+'</label>'+(f.type==='select'||f.type==='boolean'?'<select id="wf_'+f.name+'">'+options.map(x=>'<option '+(String(value)===String(x)?'selected':'')+'>'+esc(x)+'</option>').join('')+'</select>':(f.type==='textarea'||f.type==='json'?'<textarea id="wf_'+f.name+'">'+esc(typeof value==='object'?JSON.stringify(value,null,2):value)+'</textarea>':'<input id="wf_'+f.name+'" value="'+esc(value)+'">'))+'</div>';
 }
 if(confirmValue)body+='<div class="field"><label for="wf_confirm">Type '+esc(confirmValue)+' to confirm the exact target</label><input id="wf_confirm" autocomplete="off"></div>';
 body+='<div id="workflow_error" class="form-error error" role="alert"></div>';
 modal(title,body,'saveWorkflow');
 if(path==='/admin/v1/sources')document.querySelector('.modalf').insertAdjacentHTML('afterbegin','<button class="btn" data-act="probeWorkflow">Probe connection</button>');
}
function workflowBody(){
 const w=state.workflow,body={...w.initial};
 for(const f of w.fields){const raw=val('wf_'+f.name);body[f.name]=f.type==='json'?JSON.parse(raw):f.type==='boolean'?raw==='true':f.type==='number'?Number(raw):raw;}
 for(const key of ['company_id','expires_at'])if(key in body&&!body[key])body[key]=null;
 if(w.path==='/admin/v1/platform-role-bindings'&&!body.source_id)body.source_id=null;
 body.reason=val('wf_reason');if(!body.reason)throw new Error('A reason is required.');
 if(w.confirmValue&&val('wf_confirm')!==w.confirmValue)throw new Error('Exact target confirmation does not match.');
 return body;
}
async function saveWorkflow(){const w=state.workflow;if(!w||w.busy)return;const focusedBefore=document.activeElement;try{
 const body=workflowBody(),payload=JSON.stringify(body);w.payload=payload;w.busy=true;
 document.querySelectorAll('.modalf button').forEach(b=>b.disabled=true);
 await api(w.path,{method:w.method,headers:{'Idempotency-Key':w.key},body:payload});w.busy=false;closeModal();toast('Success: operation recorded in audit.');await render();
 }catch(e){const box=document.getElementById('workflow_error');if(box)box.textContent=(e.message==='POLICY_VERSION_CONFLICT'?'Conflict: refresh the screen and review the current version. ':e.message==='STEP_UP_REQUIRED'?'Step-up required: sign in again using your approved IdP authentication level. ':'')+e.message;}finally{w.busy=false;document.querySelectorAll('.modalf button').forEach(b=>b.disabled=false);const dlg=document.querySelector('.modal');if(dlg&&!dlg.contains(document.activeElement)){const target=focusedBefore&&dlg.contains(focusedBefore)?focusedBefore:dlg.querySelector('.modalf button.primary');target?.focus()}}}
async function probeWorkflow(){try{const body=workflowBody();const x=await api('/admin/v1/source-probes',{method:'POST',body:JSON.stringify(body)});document.getElementById('workflow_error').textContent='Probe succeeded. Metadata fingerprint: '+x.capabilities.metadata_fingerprint}catch(e){document.getElementById('workflow_error').textContent=e.message}}
sourceModal=function(){workflow('Connect 1C source','/admin/v1/sources',[inputField('source_id','Source ID'),inputField('display_name','Display name'),inputField('base_url','Approved OData URL'),inputField('username_secret_ref','Username secret reference'),inputField('password_secret_ref','Password secret reference')],{tags:[]},'POST','This registers a technical connection. Register business companies separately. Secrets stay server-side.')};
companyModal=function(){workflow('Register company','/admin/v1/companies',[inputField('source_id','Source ID'),inputField('external_ref','External reference'),inputField('display_name','Display name')])};
grantModal=function(){workflow('Create access grant','/admin/v1/grants',[...principalFields(),...scopeFields(),inputField('effect','Effect','select',['allow','deny']),expiryField()],{},'POST','A source-wide grant affects every company in this source. A group grant applies to all trusted IdP members. Deny takes precedence.')};
revokeGrant=function(id,version){workflow('Revoke exact grant','/admin/v1/grants/'+encodeURIComponent(id)+'/revoke',[],{expected_version:version},'POST','Only this exact grant is revoked.',id)};
function platformRoleModal(){workflow('Assign platform role','/admin/v1/platform-role-bindings',[...principalFields(),inputField('role_name','Platform role','select',['PLATFORM_ADMIN','SOURCE_ADMIN','ACCESS_ADMIN','PROFILE_ADMIN','AUDITOR']),inputField('source_id','Delegated source (blank means global)'),expiryField()],{},'POST','Platform roles grant administration rights, independently of business roles and data grants. Global administration has platform-wide impact.','ASSIGN PLATFORM ROLE')}
function businessRoleModal(){workflow('Assign business role','/admin/v1/business-role-assignments',[...principalFields(),...scopeFields(),inputField('role_id','Business role template','select',['VIEWER','ACCOUNTANT','SENIOR_ACCOUNTANT','TAX_REVIEWER','AUDITOR_BUSINESS','EXECUTIVE','PAYROLL_REVIEWER']),expiryField()])}
function overrideModal(){workflow('Capability override','/admin/v1/capability-overrides',[...principalFields(),...scopeFields(),inputField('capability_key','Capability key'),inputField('effect','Effect','select',['allow','deny']),expiryField()],{},'POST','An explicit deny overrides role and direct allows. Data grants remain required.')}
function profileModal(){workflow('Create semantic profile','/admin/v1/semantic-profiles',[...scopeFields(),inputField('preset_id','Configuration preset','select',['bp30','ut11','erp2','zup31']),inputField('profile_name','Profile name'),inputField('profile_definition','Profile definition','json')],{},'POST','Presets are advisory candidates. Validation requires native reconciliation evidence.')}
async function operate(op,item){
 const id=encodeURIComponent(item.source_id||''),profile=encodeURIComponent(item.profile_id||'');
 try{
 if(op==='profile-evidence'){const x=await api('/admin/v1/semantic-profiles/'+profile);modal('Profile evidence','<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+esc(JSON.stringify(x,null,2))+'</pre>','closeModal');document.querySelector('.modalf button:last-child').textContent='Close';return}
 if(op==='source'){const x=await api('/admin/v1/sources/'+id);workflow('Edit source','/admin/v1/sources/'+id,[inputField('display_name','Display name'),inputField('base_url','Approved OData URL'),inputField('username_secret_ref','Username secret reference'),inputField('password_secret_ref','Password secret reference'),inputField('enabled','Enabled (true / false)','boolean')],{...x,expected_version:x.row_version},'PATCH','Disabling removes runtime access to this source. Connection target and secret-reference changes require global source administration.');document.getElementById('wf_enabled').value=String(x.enabled);if(!globalSourceAdmin())['base_url','username_secret_ref','password_secret_ref'].forEach(k=>document.getElementById('wf_'+k).readOnly=true)}
 if(op==='company'){const x=await api('/admin/v1/companies/'+encodeURIComponent(item.company_id));workflow('Edit company','/admin/v1/companies/'+encodeURIComponent(item.company_id),[inputField('display_name','Display name'),inputField('legal_name','Legal name'),inputField('country_code','Country code'),inputField('enabled','Enabled (true / false)','boolean')],{...x,expected_version:x.row_version},'PATCH','Source and external reference are immutable. Disabling removes runtime access to this company.');document.getElementById('wf_enabled').value=String(x.enabled)}
 if(op==='refresh')workflow('Refresh capabilities','/admin/v1/sources/'+id+'/capability-refresh',[],{},'POST','Refresh live metadata using the approved read-only connection.');
 if(op==='drift')workflow('Acknowledge current drift','/admin/v1/sources/'+id+'/drift-acknowledgements',[],{metadata_fingerprint:item.metadata_fingerprint},'POST','Only the exact current fingerprint is acknowledged. Stale semantic profiles still require revalidation.',item.metadata_fingerprint);
 const revoke={ 'grant-revoke':['grants','grant_id'],'platform-revoke':['platform-role-bindings','binding_id'],'assignment-revoke':['business-role-assignments','assignment_id'],'override-revoke':['capability-overrides','override_id'] };
 if(revoke[op]){const [route,key]=revoke[op];workflow('Revoke exact assignment','/admin/v1/'+route+'/'+encodeURIComponent(item[key])+'/revoke',[],{expected_version:item.row_version},'POST','Only this exact assignment is revoked.',item[key])}
 if(op==='profile-mapping')workflow('Add semantic mapping','/admin/v1/semantic-profiles/'+profile+'/mappings',[inputField('canonical_concept','Canonical concept','select',['receivable','payable','sales','cash','inventory','vat']),inputField('mapping','Mapping definition','json'),inputField('evidence','Evidence references and notes','json')]);
 if(op==='profile-validate')workflow('Validate semantic profile','/admin/v1/semantic-profiles/'+profile+'/validate',[inputField('validation_evidence','Native reconciliation evidence manifest','json')],{},'POST','At least ten unique PASS native-report cases are mandatory. A stale metadata fingerprint is rejected.');
 if(op==='profile-retire')workflow('Retire semantic profile','/admin/v1/semantic-profiles/'+profile+'/retire',[],{},'POST','Retirement removes this profile from runtime eligibility.',item.profile_id);
 if(op==='company-mapping')workflow('Record candidate scope mapping','/admin/v1/company-scope-mappings',[inputField('entity_set','Entity set'),inputField('company_property','Company property'),inputField('literal_kind','Organization key type','select',['guid','string'])],{profile_id:item.profile_id},'POST','This candidate is not used to authorize reads. Runtime company access is limited to fixed canonical operations until independent positive and negative cross-company evidence is available.');
 }catch(e){toast(e.message,true)}
}
function accessForm(){return '<div class="card" style="margin-top:16px"><div class="cardhead"><h2>Effective data-access explanation</h2></div><div class="form"><p>Uses the principal kind and ID above. For another subject, group membership is unknown without a directory provider; results explicitly show that limitation.</p><div class="field"><label>Source ID</label><input id="ea_source"></div><div class="field"><label>Entity set (optional)</label><input id="ea_entity"></div><div class="row2"><div class="field"><label>Effect</label><select id="ea_effect"><option value="">All</option><option>allow</option><option>deny</option><option>none</option></select></div><div class="field"><label>Grant origin</label><select id="ea_inheritance"><option value="">All</option><option>direct</option><option>inherited</option></select></div></div><button class="btn" data-act="explainAccess" data-offset="0">Explain access</button><div id="access_explanation" role="status"></div></div></div>'}
async function explainAccess(offset){const out=document.getElementById('access_explanation');out.textContent='Loading…';try{
 const params=new URLSearchParams({kind:val('p_kind'),id:val('p_id'),source_id:val('ea_source'),entity_set:val('ea_entity'),effect:val('ea_effect'),inheritance:val('ea_inheritance'),limit:'50',offset:String(offset)});
 const x=await api('/admin/v1/effective-access?'+params);
 out.innerHTML='<p>Identity mode: '+esc(x.mode)+'; group membership: '+esc(x.group_membership)+'. Capability authorization and live metadata checks remain separate runtime gates.</p>'+baseTable('Company policy results',x.items,[{h:'Company',f:i=>esc(i.display_name)},{h:'ACL',f:i=>tag(i.data_acl)},{h:'Why',f:i=>esc(i.detail_code)},{h:'Grant evidence',f:i=>i.matching_grants.map(g=>esc(g.grant_id)+' / '+esc(g.effect)+' / '+esc(g.inheritance)+' / '+esc(g.scope)).join('<br>')+(i.grant_evidence_truncated?'<br>Evidence limited to 50; all '+esc(i.matching_grant_count)+' grants were evaluated. Denies are prioritized.':'')},{h:'Company operation',f:i=>esc(i.company_operation)}])+(x.next_offset!==null?'<button class="btn" data-act="explainAccess" data-offset="'+esc(x.next_offset)+'">Next results</button>':'');
 }catch(e){out.textContent=e.message}}
let previousFocus=null;
modal=function(title,body,submit){previousFocus=document.activeElement;baseModal(title,body,submit);const d=document.querySelector('.modal');d.setAttribute('role','dialog');d.setAttribute('aria-modal','true');d.querySelector('h2').id='dialog_title';d.setAttribute('aria-labelledby','dialog_title');d.querySelector('.modalh button').setAttribute('aria-label','Close dialog');labelForms();d.querySelector('input,select,textarea,button')?.focus()};
closeModal=function(){if(state.workflow?.busy)return;document.getElementById('overlay').innerHTML='';state.workflow=null;previousFocus?.focus()};
document.addEventListener('keydown',e=>{const d=document.querySelector('.modal');if(!d)return;if(e.key==='Escape'){e.preventDefault();closeModal()}if(e.key==='Tab'){const nodes=[...d.querySelectorAll('button:not(:disabled),input,select,textarea,a[href]')];const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}});
document.getElementById('toast').setAttribute('role','status');

// Delegated handlers: the page CSP forbids inline on* attributes, so every control carries
// data-act and is dispatched here (functions are looked up at call time; several are overridden).
const ACTIONS={
 logout:()=>logout(),sourceModal:()=>sourceModal(),companyModal:()=>companyModal(),grantModal:()=>grantModal(),
 platformRoleModal:()=>platformRoleModal(),businessRoleModal:()=>businessRoleModal(),overrideModal:()=>overrideModal(),
 profileModal:()=>profileModal(),resolvePrincipal:()=>resolvePrincipal(),probeWorkflow:()=>probeWorkflow(),
 pageBack:()=>pageBack(),pageNext:()=>pageNext(),render:()=>render(),reload:()=>location.reload(),
 closeModal:()=>closeModal(),saveWorkflow:()=>saveWorkflow(),createSource:()=>createSource(),
 createCompany:()=>createCompany(),createGrant:()=>createGrant(),
 revokeGrant:el=>revokeGrant(el.dataset.id,Number(el.dataset.version)),
 explainAccess:el=>explainAccess(Number(el.dataset.offset))
};
document.addEventListener('click',e=>{const el=e.target.closest('[data-act]');if(!el||el.disabled)return;const fn=ACTIONS[el.dataset.act];if(fn)fn(el)});

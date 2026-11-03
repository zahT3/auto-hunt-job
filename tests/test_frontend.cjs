'use strict';
// DOM-free safety contract tests: no browser, recruitment site, or network access.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const JS_DIR=path.join(__dirname,'../static/js');
// A named import may span lines inside its braces; a side-effect import ("import './x.js';") has no from.
const IMPORT=/^import\s+(?:(?:\{[^}]*\}|[^"\n;{])+?\s+from\s+)?"([^"]+)";$/gm;
// The page loads static/js/main.js as an ES module. For this DOM-free harness the module graph is inlined into one
// script, dependencies first, with import lines and export keywords removed, so each test gets a fresh copy and can
// reach module-level functions and variables by name. A separate test imports the real modules.
function moduleSources(entry){
  const order=[],seen=new Set();
  const visit=file=>{
    if(seen.has(file))return;
    seen.add(file);
    const src=fs.readFileSync(file,'utf8');
    for(const m of src.matchAll(IMPORT))visit(path.resolve(path.dirname(file),m[1]));
    order.push(src);
  };
  visit(entry);
  return order;
}
const sources=moduleSources(path.join(JS_DIR,'main.js'));
// Inlined, two modules' top-level names would collide (a later function silently replaces an earlier one).
{
 const names=sources.flatMap(src=>[...src.matchAll(/^(?:export )?(?:async )?(?:function|const|let|class) ([A-Za-z0-9_$]+)/gm)].map(m=>m[1]));
 const dup=names.filter((n,i)=>names.indexOf(n)!==i);
 if(dup.length)throw new Error('top-level names used by two modules: '+[...new Set(dup)].join(', '));
}
const app='"use strict";\n'+sources
  .map(src=>src.replace(IMPORT,'').replace(/^export (?=(?:async )?function|const |let )/gm,''))
  .join('\n')
  .replace(/^start\(\);$/m,'');
function fakeDocument(){
  const nodes=new Map(),selections=new Map();
  function node(selector){
    if(!nodes.has(selector))nodes.set(selector,{
      innerHTML:'',textContent:'',hidden:false,disabled:false,checked:false,open:false,
      elements:new Proxy({}, {get:(target,key)=>target[key]??(target[key]={value:'',checked:false})}),
      classList:{toggle(){}},listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},
      querySelector(){return null;},append(){},reset(){},showModal(){this.open=true;},close(){this.open=false;},
      scrollIntoView(){},focus(){this.focused=true;},setAttribute(name,value){this[name]=value;},toggleAttribute(name,value){this[name]=value;}
    });
    return nodes.get(selector);
  }
  const document={listeners:{},querySelector:s=>s==='dialog[open]'?null:node(s),querySelectorAll:s=>selections.get(s)||[],addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);},hidden:false,activeElement:null,dispatchEvent(){},
    created:[],createElement(tag){const el={tag,dataset:{},classList:{toggle(){}},setAttribute(name,value){this[name]=value;},append(){}};this.created.push(el);return el;}};
  return {node,selections,document};
}
function harness(){
  const {node,selections,document}=fakeDocument();
  const context=vm.createContext({document,location:{hash:''},CustomEvent:class{constructor(type){this.type=type;}},CSS:{escape:s=>s},console,URL,URLSearchParams,crypto:require('node:crypto').webcrypto,structuredClone,setTimeout:()=>1,clearTimeout(){},matchMedia:()=>({matches:false}),fetch(){throw new Error('Unexpected network request');}});
  vm.runInContext(app,context);
  return {node,selections,document,run:code=>vm.runInContext(code,context),state:value=>vm.runInContext('state='+JSON.stringify(value),context)};
}
test('partial/truncated source output is explicit and uses actual discovery fields',()=>{
  const h=harness();
  const html=h.run(`renderSourceRows({sources:[{kind:'boss',source_id:'boss',status:'ok',truncated:true,fetched:12,returned:2,pages:1,checked_at:'2026-10-22T00:00:00Z'}]})`);
  assert.match(html,/BOSS 直聘/);assert.match(html,/部分完成/);assert.match(html,/badge warn/);
  assert.match(html,/仍可能有未检查的岗位/);assert.match(html,/读取 12 条/);assert.match(html,/保留 2 条/);
});
test('blocked source cannot become a successful zero-result claim or unsafe link',()=>{
  const h=harness();const html=h.run(`renderSourceRows({sources:[{kind:'liepin',status:'blocked',fetched:0,pages:0,error:'<script>injected</script>',search_url:'javascript:alert(1)'}]})`);
  assert.match(html,/猎聘/);assert.match(html,/需要处理/);assert.doesNotMatch(html,/读取 0 条|未找到结果|href="javascript:/);
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
});
test('unsupported channels cannot expose the execute action even with stale approval',()=>{
  const h=harness();assert.doesNotMatch(h.run(`actionButton({channel:'boss',status:'approved',approval:{},application_url:'https://www.zhipin.com/'})`),/data-execute/);
  assert.match(h.run(`actionButton({channel:'anker',status:'approved',approval:{},application_url:'https://anker-in.jobs.feishu.cn/index/resume/123/apply'})`),/data-execute/);
});
test('batch approval remains disabled for unsupported channel while material review remains available',()=>{
  const h=harness();h.state({candidate:{facts:[]},jobs:[{id:'boss1',title:'Synthetic',company:'Test',channel:'boss',url:'https://www.zhipin.com/job_detail/test.html',application_url:'https://www.zhipin.com/',package:{id:'p',snapshot:'x',claims:[],blockers:[],gaps:[]}}]});
  h.run(`openReview(['boss1'])`);
  assert.equal(h.node('#review-confirm').disabled,true);assert.equal(h.node('#approve-batch').disabled,true);
  assert.equal(h.node('#external-review').hidden,true);assert.equal(h.node('#external-review-controls').disabled,true);assert.equal(h.node('#material-review-confirm').checked,false);assert.equal(h.node('#save-material-review').disabled,true);
});
test('needs_ocr draft cannot be confirmed even if partial facts are present and selected',()=>{
  const h=harness();h.state({candidate_draft:{id:'d',status:'needs_ocr',candidate:{facts:[{id:'f',text:'Python',source:{reference:'page 1'}}]},profile:{}}});
  h.selections.set('#resume-confirm-form input[name=confirmed_fact_ids]:checked',[{value:'f'}]);
  h.run('renderResumeDraft();updateResumeConfirm()');
  assert.equal(h.node('#resume-confirm-button').disabled,true);assert.match(h.node('#resume-draft').innerHTML,/暂不能确认/);
  h.run('setBusy(false)');assert.equal(h.node('#resume-confirm-button').disabled,true);
});
test('new resumé facts require explicit selection and safe text rendering',()=>{
  const h=harness();h.state({candidate_draft:{id:'d',status:'needs_review',candidate:{facts:[{id:'f',text:'<img src=x onerror=alert(1)>',source:{reference:'local'}}]},profile:{}}});
  h.run('renderResumeDraft();updateResumeConfirm()');const html=h.node('#resume-draft').innerHTML;
  assert.equal(h.node('#resume-confirm-button').disabled,true);assert.doesNotMatch(html,/<img|value="f" checked/);assert.match(html,/&lt;img/);
});
test('recommendation shows evidence gaps without treating them as missing ability or scoring',()=>{
  const h=harness();const html=h.run(`recommendationSummary({recommendation:{skill_matches:[{name:'Python',fact_ids:['f']}],missing_skills:['RAG'],priority:9,note:'Local evidence'}})`);
  assert.match(html,/相关经历/);assert.match(html,/Python/);assert.match(html,/缺少原文提及不代表你不具备/);assert.doesNotMatch(html,/priority|9\/10/);
});
test('company boards recognize supported ATS and reject non-public URLs',()=>{
  const h=harness();h.state({config:{company_boards:[]}});
  assert.equal(h.run(`parseBoards('https://jobs.lever.co/example')[0].type`),'lever');
  for(const url of ['http://jobs.lever.co/example','https://user:secret@example.com/jobs','https://127.0.0.1/private'])assert.throws(()=>h.run(`parseBoards(${JSON.stringify(url)})`));
});
test('truncated sources cannot leave the run heading claiming completion',()=>{
  const h=harness();h.state({search_running:false,runs:[{status:'completed',sources:[{kind:'anker',status:'ok',truncated:true,fetched:5,pages:1}]}]});h.run('renderSearchProgress()');
  assert.match(h.node('#search-progress').innerHTML,/最近一轮：部分完成/);assert.doesNotMatch(h.node('#search-progress').innerHTML,/最近一轮：已完成/);
});
test('Anker execution requires the supported HTTPS application receiver',()=>{
  const h=harness();for(const url of ['https://example.com/apply','http://anker-in.jobs.feishu.cn/index/resume/123/apply','https://anker-in.jobs.feishu.cn.evil.example/index/resume/123/apply'])assert.equal(h.run(`executionSupported({channel:'anker',application_url:${JSON.stringify(url)}})`),false);
});
test('generic company HTTPS pages round-trip and enable the website source',()=>{
  const h=harness();h.state({config:{company_boards:[]}});
  const board=h.run(`parseBoards('https://careers.example.com/jobs#open')[0]`);
  assert.equal(board.type,'website');assert.equal(board.url,'https://careers.example.com/jobs');
  assert.equal(h.run(`boardUrl(${JSON.stringify(board)})`),board.url);
  assert.deepEqual(Array.from(h.run(`includeBoardSources(['boss'],[${JSON.stringify(board)}])`)),['boss','website']);
  assert.equal(h.run(`parseBoards('https://jobs.lever.co.evil.example/example')[0].type`),'website');
});
test('optional SearXNG remains absent until explicitly configured and rejects local endpoint',()=>{
  const h=harness();assert.equal(h.run(`searchProviderInput('')`),null);
  const provider=h.run(`searchProviderInput('https://search.example.com/search')`);
  assert.equal(provider.provider,'searxng');assert.equal(provider.url,'https://search.example.com/search');
  for(const url of ['http://search.example.com/search','https://localhost/search','https://host.local/search','https://[::1]/search','https://secret@example.com/search'])assert.throws(()=>h.run(`searchProviderInput(${JSON.stringify(url)})`));
});

test('application entry is a manual link and cannot imply verified form or automatic execution',()=>{
  const h=harness();const html=h.run(`applicationRoute({channel:'lever',application_url:'https://jobs.lever.co/acme/id/apply',raw:{application_route:{status:'careers_linked',career_url:'https://acme.example/careers',evidence_type:'link'}}})`);
  assert.match(html,/人工操作/);assert.match(html,/表单尚需核验/);assert.match(html,/acme.example/);assert.doesNotMatch(html,/data-execute|已核验提交/);
  assert.equal(h.run(`applicationRoute({application_url:'javascript:alert(1)'})`),'');
});
test('a job with neither an application URL nor an entry check renders without an entry section instead of throwing',()=>{
 const h=harness();assert.equal(h.run(`applicationRoute({id:'j',title:'x'})`),'');
});
test('blank page is reported as a source failure instead of an empty result',()=>{
  const h=harness();const html=h.run(`renderSourceRows({sources:[{kind:'boss',status:'blank_page',error:'about:blank',fetched:0,pages:0}]})`);
  assert.match(html,/页面退回空白/);assert.match(html,/badge warn/);assert.doesNotMatch(html,/未找到结果/);
});

test('recent failed entry hides its application link without claiming the job is closed',()=>{
  const h=harness();const html=h.run(`applicationRoute({application_url:'https://jobs.ashbyhq.com/acme/id/application',raw:{application_route:{entry_check:{status:'not_found',url:'https://jobs.ashbyhq.com/acme/id/application',checked_at:new Date().toISOString()}}}})`);
  assert.match(html,/暂不可用/);assert.doesNotMatch(html,/打开申请入口/);assert.match(html,/不据此判定岗位已关闭/);
});

test('email application is plain contact text and never a send link',()=>{
 const h=harness();const html=h.run(`applicationRoute({application_url:'https://join.dify.ai/roles',raw:{application_route:{entry_type:'email',email:'joinus@dify.ai',career_url:'https://join.dify.ai/roles'}}})`);
 assert.match(html,/joinus@dify.ai/);assert.match(html,/不自动发送/);assert.doesNotMatch(html,/mailto:|打开申请入口/);
});
test('a repaired receiver shows its observed form with the old check retained in data',()=>{
 const h=harness();const html=h.run(`applicationRoute({application_url:'https://acme.example/careers/role',raw:{application_route:{repair:{reason:'official_same_role_form'},entry_check:{url:'https://acme.example/careers/role',status:'form_seen',checked_at:new Date().toISOString()}}}})`);
 assert.match(html,/同职位表单/);assert.match(html,/原入口核验记录已保留/);assert.match(html,/href="https:\/\/acme.example\/careers\/role"/);
});

test('Moka verification is limited to official HTTPS job application routes',()=>{
 const h=harness();
 for(const url of ['https://app.mokahr.com/apply/moonshot/148506#/job/abc/apply','https://hire-r1.mokahr.com/social-recruitment/cobo/100000912#/job/abc/apply'])assert.equal(h.run(`supportsEntryVerification({application_url:${JSON.stringify(url)}})`),true);
 for(const url of ['https://user:secret@app.mokahr.com/apply/moonshot/148506#/job/abc/apply','https://app.mokahr.com:8443/apply/moonshot/148506#/job/abc/apply','http://app.mokahr.com/apply/moonshot/148506#/job/abc/apply','https://app.mokahr.com.evil.example/apply/moonshot/148506#/job/abc/apply','https://app.mokahr.com/apply/moonshot/148506#/job/abc','https://app.mokahr.com/apply/moonshot/148506#/jobs'])assert.equal(h.run(`supportsEntryVerification({application_url:${JSON.stringify(url)}})`),false);
});
test('entry login confirmation is explicit and cannot appear before the login window is ready',()=>{
 const h=harness();const job={id:'moka',application_url:'https://app.mokahr.com/apply/moonshot/148506#/job/abc/apply'};
 h.state({entry_verifications:{moka:{status:'opening',message:'Opening'}}});
 assert.doesNotMatch(h.run(`entryVerificationControls(${JSON.stringify(job)})`),/entry_finish/);
 h.state({entry_verifications:{moka:{status:'awaiting_login',message:'<script>login</script>'}}});
 const html=h.run(`entryVerificationControls(${JSON.stringify(job)})`);
 assert.match(html,/entry_finish/);assert.match(html,/entry_cancel/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>|data-execute/);
});
test('incomplete and unconfirmed entry checks remain explicit',()=>{
 const h=harness();
 for(const [status,label] of [['form_incomplete','表单未完整加载'],['session_unconfirmed','登录状态未确认']]){
 const html=h.run(`applicationRoute({application_url:'https://example.com/apply',raw:{application_route:{entry_check:{status:${JSON.stringify(status)},url:'https://example.com/apply',checked_at:new Date().toISOString()}}}})`);
 assert.match(html,new RegExp(label));assert.doesNotMatch(html,/entry-status verified/);
 }
});
test('queue text search composes with the review filter',()=>{
 const h=harness();h.state({jobs:[{id:'a',title:'AI Agent',company:'Kimi',package:{},status:'prepared'},{id:'b',title:'Backend',company:'KIMI',status:'new'},{id:'c',title:'AI Agent',company:'Other',package:{},status:'prepared'}]});
 h.run(`query='kimi';filter='review'`);assert.deepEqual(Array.from(h.run('filteredJobs().map(j=>j.id)')),['a']);
});
test('unverified availability stays visible independently of an email application route',()=>{
 const h=harness();const job={id:'imtoken',availability:'unverified',application_url:'https://careers.token.im/en/job',raw:{availability_note:'官网职位列表暂不可用；是否仍在招需确认。',application_route:{entry_type:'email',email:'hr@token.im'}}};
 assert.equal(h.run(`queueEntryLabel(${JSON.stringify(job)})`),'在招待确认');
 const html=h.run(`availabilityNotice(${JSON.stringify(job)})+applicationRoute(${JSON.stringify(job)})`);
 assert.match(html,/在招待确认/);assert.match(html,/官网职位列表暂不可用/);assert.match(html,/不自动发送/);
});
test('seeing a form cannot by itself claim an authenticated session',()=>{
 const h=harness();const job={application_url:'https://example.com/apply',raw:{application_route:{entry_check:{status:'form_seen',url:'https://example.com/apply',checked_at:new Date().toISOString()}}}};
 assert.doesNotMatch(h.run(`applicationRoute(${JSON.stringify(job)})`),/独立会话已确认登录/);
 job.raw.application_route.entry_check.authenticated=true;
 assert.match(h.run(`applicationRoute(${JSON.stringify(job)})`),/独立会话已确认登录/);
});
test('local material review requires an explicit check and never includes outbound permissions',async()=>{
 const h=harness();h.state({candidate:{synthetic:true},jobs:[{id:'j',title:'AI',channel:'website',package:{id:'p',snapshot:'snap',blockers:['姓名待补充'],gaps:[],claims:[]}}]});
 h.run(`openReview(['j']);globalThis.calls=[];action=async(name,payload)=>{calls.push({name,payload});return null;}`);
 await h.run('saveMaterialReview()');assert.equal(h.run('calls.length'),0);
 h.node('#material-review-confirm').checked=true;await h.run('saveMaterialReview()');
 const call=JSON.parse(h.run('JSON.stringify(calls[0])'));
 assert.deepEqual(call,{name:'review_materials',payload:{job_ids:['j'],snapshots:{j:'snap'},acknowledge_review:true}});
 assert.match(h.node('#review-content').innerHTML,/姓名待补充/);assert.equal(h.node('#external-review').hidden,true);
});
test('current local review leaves the pending filter but preserves material gaps and unknown status',()=>{
 const h=harness();h.state({jobs:[{id:'j',title:'AI',status:'prepared',material_review_current:true,package:{blockers:['姓名待补充']}},{id:'new',status:'prepared',package:{}}]});
 h.run("filter='review'");assert.deepEqual(Array.from(h.run('filteredJobs().map(j=>j.id)')),['new']);
 assert.match(h.run('jobBadge(state.jobs[0])'),/已复核 · 待补充/);
 assert.match(h.run("jobBadge({...state.jobs[0],status:'submission_unknown'})"),/结果待查证/);
});
test('synthetic Anker candidates cannot open outbound authorization even when receiver is supported',()=>{
 const h=harness();h.state({candidate:{synthetic:true},jobs:[{id:'j',title:'AI',channel:'anker',application_url:'https://anker-in.jobs.feishu.cn/index/resume/123/apply',package:{id:'p',snapshot:'s',claims:[],blockers:[],gaps:[]}}]});h.run("openReview(['j'])");
 assert.equal(h.node('#external-review').hidden,true);assert.equal(h.node('#review-confirm').disabled,true);
 assert.doesNotMatch(h.run("actionButton({...state.jobs[0],approval:{}})"),/data-execute/);
});
test('real supported authorization stays separate, collapsed and guarded by gap acknowledgement',()=>{
 const h=harness();h.state({candidate:{synthetic:false},jobs:[{id:'j',title:'AI',channel:'anker',application_url:'https://anker-in.jobs.feishu.cn/index/resume/123/apply',package:{id:'p',snapshot:'s',claims:[],blockers:[],gaps:['经验待确认']}}]});h.run("openReview(['j'])");
 assert.equal(h.node('#external-review').hidden,false);assert.equal(h.node('#external-review').open,false);
 h.node('#review-confirm').checked=true;h.selections.set('#review-form input[name=permission]:checked',[{value:'upload'}]);
 h.run('updateApprove()');assert.equal(h.node('#approve-batch').disabled,true);
 h.node('#external-review').open=true;h.run('updateApprove()');assert.equal(h.node('#approve-batch').disabled,true);
 h.node('#acknowledge-gaps').checked=true;h.run('updateApprove()');assert.equal(h.node('#approve-batch').disabled,false);
 h.run('setBusy(true)');assert.equal(h.node('#approve-batch').disabled,true);
});
function configureSearch(h){
 h.state({dataset:'app',candidate:{facts:[]},config:{keywords:['old'],sources:['website'],company_boards:[]}});
 const f=h.node('#config-form');for(const [key,value] of Object.entries({keywords:'Agent',company_board_urls:'https://careers.example.com/',search_provider_url:'',cities:'',salary_min:'',max_jobs:'5',max_pages:'2',interval_minutes:'60',submission_limit:'0',browser_channel:''}))f.elements[key].value=value;
 h.selections.set('#config-form input[name=sources]:checked',[{value:'website'}]);h.run('markConfigDirty()');return f;
}
test('save and search validates and persists the current form before running',async()=>{
 const h=harness();configureSearch(h);assert.equal(h.node('#run-button').textContent,'保存并搜索');
 h.run(`globalThis.calls=[];action=async(name,payload)=>{calls.push({name,payload});if(name==='config')state.config=payload.config;return {};}`);
 await h.run('startSearch()');const calls=JSON.parse(h.run('JSON.stringify(calls)'));
 assert.deepEqual(calls.map(c=>c.name),['config','run']);assert.deepEqual(calls[0].payload.config.keywords,['Agent']);assert.equal(h.run('configDirty'),false);
});
test('the 猎聘 card switch is shown from the saved config and saved from the form',async()=>{
 const h=harness();configureSearch(h);const f=h.node('#config-form');
 h.state({dataset:'app',candidate:{facts:[]},config:{keywords:['AI'],sources:['liepin'],company_boards:[],liepin_cards:true}});h.run('renderSettings()');
 assert.equal(f.elements.liepin_cards.checked,true);
 f.elements.liepin_cards.checked=false;
 assert.equal(JSON.parse(h.run("JSON.stringify(configFromForm($('#config-form')))")).liepin_cards,false);
});
test('invalid or failed configuration never starts search',async()=>{
 const h=harness();const f=configureSearch(h);h.run(`globalThis.calls=[];action=async(name)=>{calls.push(name);return null;}`);
 f.elements.keywords.value='';await h.run('startSearch()');assert.equal(h.run('calls.length'),0);
 f.elements.keywords.value='Agent';await h.run('startSearch()');assert.deepEqual(Array.from(h.run('calls')),['config']);assert.equal(h.run('configDirty'),true);
});
test('demo saves dirty settings before its synthetic action and never runs real discovery',async()=>{
 const h=harness();configureSearch(h);h.run(`state.dataset='demo';refreshRunButton();globalThis.calls=[];action=async(name)=>{calls.push(name);return {};}`);
 assert.equal(h.node('#run-button').textContent,'保存并运行演示');await h.run('startSearch()');assert.deepEqual(Array.from(h.run('calls')),['config','demo']);assert.equal(h.node('#run-button').textContent,'运行演示');
});
test('resume feedback is cleared on retry and busy feedback is inside the dialog',async()=>{
 const h=harness();let removed=false;h.node('#resume-dialog').querySelector=selector=>selector==='.dialog-error'?{remove(){removed=true;}}:null;
 await h.run('uploadResume({preventDefault(){},target:{}})');assert.equal(removed,true);assert.equal(h.node('#notice').hidden,true);
 h.node('#resume-dialog').open=true;h.run("setBusy(true,'正在本地解析…')");
 assert.equal(h.node('#resume-operation-status').hidden,false);assert.equal(h.node('#resume-operation-status').textContent,'正在本地解析…');assert.equal(h.node('#resume-upload-button').textContent,'正在本地解析…');
 h.run('setBusy(false)');assert.equal(h.node('#resume-operation-status').hidden,true);
});
test('resume source locators are concise and full provenance remains in closed details',()=>{
 const h=harness();const html=h.run(`factSourceDetail({source:{reference:'upload://abc123#page=2&paragraph=5',label:'synthetic.pdf'}})`);
 assert.match(html,/<small>第 2 页 · 第 5 段<\/small>/);assert.match(html,/<details><summary>来源记录<\/summary><small>upload:\/\/abc123/);assert.doesNotMatch(html,/<details open/);
});
test('successful resume upload focuses the newly rendered facts heading',async()=>{
 const h=harness();h.state({csrf_token:'local'});h.node('#resume-file').files=[{name:'synthetic.md',size:20}];h.node('#resume-upload-form').elements.synthetic.checked=true;
 h.run(`globalThis.FileReader=class{readAsDataURL(){this.result='data:text/plain;base64,c3ludGhldGlj';this.onload();}};fetch=async()=>({ok:true,json:async()=>({state:{candidate_draft:{id:'draft',status:'needs_review',candidate:{facts:[]},profile:{}}}})});render=()=>{};`);
 await h.run("uploadResume({preventDefault(){},target:document.querySelector('#resume-upload-form')})");assert.equal(h.node('#resume-draft-title').focused,true);assert.equal(h.run('busy'),false);
});

test('demo validation failures do not run fixtures, and running status has priority',async()=>{
 const h=harness();const f=configureSearch(h);h.run(`state.dataset='demo';globalThis.calls=[];action=async(name)=>{calls.push(name);return null;}`);f.elements.keywords.value='';await h.run('startSearch()');assert.equal(h.run('calls.length'),0);
 h.run("state.search_running=true;refreshRunButton()");assert.equal(h.node('#run-button').textContent,'演示进行中');assert.equal(h.node('#run-button').disabled,true);
});

test('asynchronous demo start does not claim completion or public-source search',async()=>{
 const h=harness();h.state({dataset:'demo',search_running:false,runs:[]});h.run(`action=async()=>{state.search_running=true;return {};}`);await h.run('startSearch()');h.run('renderSearchProgress()');
 assert.match(h.node('#toast').textContent,/已启动/);assert.doesNotMatch(h.node('#toast').textContent,/已完成|已结束/);
 assert.match(h.node('#search-progress').innerHTML,/正在准备合成岗位/);assert.match(h.node('#search-progress').innerHTML,/仅使用合成资料/);assert.doesNotMatch(h.node('#search-progress').innerHTML,/正在搜索已选渠道|读取公开岗位/);
});

test('saving local material review returns keyboard focus to the current job title',async()=>{
 const h=harness();h.state({candidate:{synthetic:true},jobs:[{id:'j',title:'AI',channel:'website',package:{id:'p',snapshot:'snap',blockers:[],gaps:[],claims:[]}}]});
 h.run(`openReview(['j']);action=async()=>({});`);h.node('#material-review-confirm').checked=true;await h.run('saveMaterialReview()');
 assert.equal(h.node('#review-dialog').open,false);assert.equal(h.node('#detail-title').focused,true);
});

const ORIENT_XSS='<img src=x onerror=alert(1)>';
function orientState(h,orientation,extra={}){
 h.state({dataset:'app',config:{keywords:[],keyword:''},candidate:{facts:[{id:'f1',text:ORIENT_XSS+'事实'}]},
  direction_table:[{id:'backend',name:'后端开发',family:'技术研发'},{id:'x"><script>',name:ORIENT_XSS,family:'<b>家族</b>'},
   {id:'pm',name:'产品经理',family:'产品'},{id:'da',name:'数据分析师',family:'数据'},{id:'ops',name:'运营',family:'运营'}],
  orientation,...extra});
}
const ORIENT_PROPOSAL={by:'ai',questions_by:'ai',notes:[ORIENT_XSS],answers:{},
 questions:[{id:'q1',text:ORIENT_XSS,kind:'choice',options:['<script>alert(1)</script>','B']},{id:'q2',text:'城市',kind:'text',options:[]}],
 directions:[{id:'backend',name:ORIENT_XSS,why:'<script>why</script>',fact_ids:['f1','gone<i>'],source:'ai'}],
 terms:['<b>term</b>'],conditions:{cities:[ORIENT_XSS],years:null,remote:true,exclude_industries:[]}};

test('orient page escapes every server and model string, including table ids in attributes',()=>{
 const h=harness();orientState(h,ORIENT_PROPOSAL);
 const steps=h.run('orientBody()');
 h.run("orientMode='pick'");const pick=h.run('orientBody()');
 for(const html of [steps,pick]){
  assert.doesNotMatch(html,/<img|<script|<b>|<i>|onerror=alert\(1\)>/);
 }
 assert.match(steps,/&lt;img src=x onerror=alert\(1\)&gt;/);assert.match(steps,/&lt;script&gt;why&lt;\/script&gt;/);
 assert.match(steps,/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);assert.match(steps,/data-tip="gone&lt;i&gt;：这条事实已不在资料里">gone&lt;i&gt;<\/span>/);
 assert.match(pick,/value="x&quot;&gt;&lt;script&gt;"/);assert.match(pick,/&lt;b&gt;家族&lt;\/b&gt;/);
});
test('each direction shows its own search terms and names the ones the merged list leaves out',()=>{
 const h=harness();orientState(h,{by:'ai',directions:[{id:'backend',name:'后端开发',terms:['后端','<b>Go</b>']},{id:'da',name:'数据分析师',terms:[]}],terms:['后端','数据分析']});
 const html=h.run('directionsSection()');
 assert.match(html,/<td data-dir="后端开发"><span class="term" [^>]*>后端<\/span><span class="term off" [^>]*data-tip="本轮不搜：合并后只保留 8 个词">&lt;b&gt;Go&lt;\/b&gt;（本轮不搜）<\/span><\/td>/);
 assert.match(html,/<td data-dir="数据分析师"><span class="st st-muted">这个方向没有单独的搜索词<\/span><\/td>/);
 assert.match(html,/合并后的搜索词：后端 · 数据分析/);
});
test('orient page says whether AI was used, from the by and questions_by fields',()=>{
 const h=harness();orientState(h,ORIENT_PROPOSAL);
 assert.match(h.run('directionsSection()'),/建议方向.*使用了 AI/);assert.match(h.run('directionsSection()'),/<span class="src">AI 建议<\/span>/);
 assert.match(h.run('questionsSection()'),/使用了 AI/);assert.match(h.run('questionsSection()'),/<span class="ai">AI 追问<\/span>/);
 orientState(h,{...ORIENT_PROPOSAL,by:'rules',questions_by:'rules',directions:[{...ORIENT_PROPOSAL.directions[0],source:'rules'}]});
 assert.match(h.run('directionsSection()'),/未使用 AI · 本地规则/);assert.match(h.run('questionsSection()'),/未使用 AI · 本地规则/);
 assert.doesNotMatch(h.run('orientBody()'),/使用了 AI|AI 追问|AI 建议/);
 orientState(h,{...ORIENT_PROPOSAL,by:'user',directions:[{...ORIENT_PROPOSAL.directions[0],source:'user'}]});
 assert.match(h.run('directionsSection()'),/未使用 AI · 你手动选择/);assert.match(h.run('directionsSection()'),/<span class="src">你选的<\/span>/);
});
test('without directions or keywords, 开始搜索 opens 定方向 instead of searching',async()=>{
 const h=harness();orientState(h,null);h.run(`globalThis.calls=[];action=async(name)=>{calls.push(name);return {};}`);
 await h.run('startSearch()');
 assert.equal(h.run('calls.length'),0);assert.equal(h.run('location.hash'),'#/orient');
 h.run('renderOrient()');assert.match(h.node('#view').innerHTML,/还没有搜索方向。先定方向/);assert.match(h.node('#view').innerHTML,/跳过问题，直接选方向/);
 orientState(h,{directions:[{id:'backend',name:'后端开发'}],terms:['后端'],by:'rules'});h.run('renderOrient()');
 assert.doesNotMatch(h.node('#view').innerHTML,/还没有搜索方向/);
 h.run("location.hash='#/search'");orientState(h,{directions:[{id:'backend',name:'后端开发'}],terms:['后端'],by:'user'});
 await h.run('startSearch()');assert.deepEqual(Array.from(h.run('calls')),['run']);assert.equal(h.run('location.hash'),'#/search');
});
test('answers keep multi-choice as lists, single choice as one string, leave blanks out and resend the untouched ones',async()=>{
 const h=harness();
 orientState(h,{questions:[{id:'family',text:'你想找哪些行业的工作？（可多选）',kind:'choice',options:['技术研发','产品']},
  {id:'years',text:'经验？',kind:'choice',options:['1-3 年','3-5 年']},{id:'city',text:'城市',kind:'text',options:[]},{id:'exclude',text:'排除',kind:'text',options:[]},
  {id:'switch',text:'转方向？',kind:'choice',options:['是','否']}],answers:{switch:'否'}});
 const html=h.run('questionsSection()');
 assert.match(html,/type="checkbox" name="orient-q-0" value="技术研发"/);assert.match(html,/type="radio" name="orient-q-1" value="1-3 年"/);
 assert.match(html,/type="radio" name="orient-q-1" value="" checked> 暂不回答/);assert.doesNotMatch(html,/orient-q-4/);
 assert.match(h.run('answersSection()'),/<dt>转方向<\/dt><dd>否<\/dd><dd><button type="button" class="linkish" data-orient-edit="switch"/);
 const fields={'orient-q-0':[{checked:true,value:'技术研发'},{checked:true,value:'产品'}],'orient-q-1':[{checked:false,value:'1-3 年'},{checked:true,value:'3-5 年'},{checked:false,value:''}],
  'orient-q-2':[{value:'  上海、杭州 '}],'orient-q-3':[{value:'  '}]};
 h.run(`globalThis.calls=[];action=async(name,payload)=>{calls.push({name,payload});return {};}`);
 await h.run(`submitAnswers({querySelectorAll:s=>(${JSON.stringify(fields)})[s.match(/"(.+)"/)[1]]||[]})`);
 assert.deepEqual(JSON.parse(h.run('JSON.stringify(calls)')),[{name:'orient_answer',payload:{answers:{switch:'否',family:['技术研发','产品'],years:'3-5 年',city:'上海、杭州'}}}]);
});
test('saving picked directions keeps known reasons, sends terms only when given, and refuses more than four',async()=>{
 const h=harness();orientState(h,{directions:[{id:'backend',name:'后端开发',why:'有后端经历'}],terms:['后端'],by:'ai'});
 h.run(`globalThis.calls=[];action=async(name,payload)=>{calls.push({name,payload});return {};}`);
 const form={elements:{terms:{value:''}}};
 h.selections.set('#orient-pick-form input[name=direction]:checked',[{value:'backend'},{value:'pm'}]);
 await h.run(`savePick(${JSON.stringify(form)})`);
 assert.deepEqual(JSON.parse(h.run('JSON.stringify(calls)')),[{name:'directions_set',payload:{directions:[{id:'backend',why:'有后端经历'},{id:'pm'}]}}]);
 h.run('calls.length=0');form.elements.terms.value='后端\nPython 后端，后端';
 await h.run(`savePick(${JSON.stringify(form)})`);
 assert.deepEqual(JSON.parse(h.run('JSON.stringify(calls[0].payload.terms)')),['后端','Python 后端']);
 h.run('calls.length=0');h.selections.set('#orient-pick-form input[name=direction]:checked',['backend','pm','da','ops','x'].map(value=>({value})));
 await h.run(`savePick(${JSON.stringify(form)})`);assert.equal(h.run('calls.length'),0);assert.match(h.node('#orient-pick-count').textContent,/请选 1 到 4 个方向/);
});
test('orient is keyboard operable: native controls, labelled fields, and focus moved to each new step',async()=>{
 const h=harness();orientState(h,null);
 h.run("location.hash='#/orient';openOrient()");assert.equal(h.node('#view h1').focused,true);
 orientState(h,{questions:[{id:'city',text:'城市',kind:'text',options:[]},{id:'years',text:'经验',kind:'choice',options:['1-3 年']}],answers:{}});
 h.run("orientMode='steps'");const steps=h.run('orientBody()');
 assert.doesNotMatch(steps,/<(div|span|a|li|td)[^>]*data-(orient|next)/);
 assert.match(steps,/<label class="orient-question">城市<input type="text"/);assert.match(steps,/<fieldset><legend>经验<\/legend>/);
 assert.match(steps,/<button type="submit"[^>]*>提交回答，重新给方向<\/button>/);assert.match(steps,/<button type="button" class="btn" data-orient-pick>/);
 h.run('showPick()');assert.equal(h.node('#orient-pick-title').focused,true);
 const pick=h.node('#view').innerHTML;
 assert.match(pick,/<details class="orient-family"[^>]*><summary>/);assert.match(pick,/<label><input type="checkbox" name="direction"/);
 assert.match(pick,/<button type="button" class="btn" data-orient-back>返回<\/button>/);
 h.run(`action=async()=>{state.orientation={directions:[{id:'backend',name:'后端开发'}],terms:['后端'],by:'rules'};return {};}`);
 await h.run(`submitAnswers({querySelectorAll:()=>[]})`);assert.equal(h.node('#orient-directions-title').focused,true);
 h.run('adopt()');assert.equal(h.node('#run-button').focused,true);
 assert.match(h.node('#toast').textContent,/已采用 1 个方向。点「开始搜索」/);
});
test('next actions and 暂不建议 are buttons with their reasons, escaped',()=>{
 const h=harness();orientState(h,{directions:[],terms:[],not_recommended:[{id:'sales',name:'<b>销售</b>',why:'你排除了<i>',fact_ids:['f1'],jd:[{job_id:'j',evidence:'<x>'}]}],
  next_actions:[{id:'a1',kind:'search',target:{direction_id:'backend'},text:'搜<b>后端</b>'},{id:'a2',kind:'confirm_fact',target:{fact_id:'f1'},text:'确认 f1'}]});
 const html=h.run('notRecommendedSection()+nextActionsSection()');
 assert.match(html,/<b>&lt;b&gt;销售&lt;\/b&gt;<\/b><span>你排除了&lt;i&gt;/);assert.match(html,/JD 1 处/);assert.doesNotMatch(html,/<i>|<x>/);
 assert.match(html,/<span>搜&lt;b&gt;后端&lt;\/b&gt;<\/span><button class="btn" type="button" data-next="a1">开始找岗位<\/button><span class="kind">搜索<\/span>/);
 assert.match(html,/data-next="a2">去确认<\/button>/);
 h.run(`state.orientation.next_actions=[]`);assert.match(h.run('nextActionsSection()'),/回答问题或选定方向后/);
});
test('page styles fit a 390px screen: no fixed width beyond it, and the two columns and the comparison stack',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../static/style.css'),'utf8');
 const own=css.slice(0,css.indexOf('/* 冻结的工作台'));
 for(const m of own.matchAll(/([^{}]+)\{([^}]*)\}/g)){
  if(/@media \(min-width/.test(m[1]))continue;
  for(const w of m[2].matchAll(/(?:^|[\s;])(width|min-width|flex-basis)\s*:\s*(\d+)px/g))assert.ok(Number(w[2])<=358||/\.(search|set|peek|d-head|with-margin|form|filter \.menu|tip)\b/.test(m[1]),m[1].trim()+' '+w[0]);
 }
 const phone=own.slice(own.indexOf('@media (max-width: 760px)'));
 assert.match(phone,/\.cols2,\s*\.set \{[^}]*grid-template-columns: 1fr/);
 assert.match(phone,/\.compare thead \{[^}]*display: none/);assert.match(phone,/\.compare td::before \{[^}]*content: attr\(data-dir\)/);
 assert.match(phone,/\.d-head,\s*\.with-margin \{[^}]*display: block/);
 assert.match(own,/dialog|\.palette \{[^}]*width: min\(560px, calc\(100vw - 32px\)\)/);
});
test('the real ES modules link and render one state through main.js',async()=>{
 const {node,document}=fakeDocument();
 const state={dataset:'app',control:'running',jobs:[{id:'j',title:'Synthetic role',company:'Co'}],config:{keywords:[]},candidate:{facts:[]},
  orientation:{directions:[{id:'backend',name:'后端开发'}],terms:['后端'],by:'rules'},direction_table:[]};
 const saved={};
 for(const key of ['document','location','matchMedia','setInterval','fetch','CSS'])saved[key]=Object.getOwnPropertyDescriptor(globalThis,key);
 Object.assign(globalThis,{document,location:{hash:'#/workbench'},matchMedia:()=>({matches:false}),setInterval:()=>1,CSS:{escape:s=>s},
  fetch:async url=>{assert.equal(url,'/api/state');return {ok:true,json:async()=>state};}});
 try{
  await import(require('node:url').pathToFileURL(path.join(JS_DIR,'main.js')).href);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('#queue-count').textContent,1);assert.match(node('#job-list').innerHTML,/Synthetic role/);
  assert.equal(node('#workbench-page').hidden,false);assert.equal(node('#view').hidden,true);assert.equal(document.title,'工作台 · auto-hunt-job');
  assert.equal(node('#notice').textContent,'');assert.equal(node('#run').textContent,'还没有运行过搜索。');assert.equal(node('#synth').hidden,true);
 }finally{
  for(const [key,desc] of Object.entries(saved))desc?Object.defineProperty(globalThis,key,desc):delete globalThis[key];
 }
});

test('card choice buttons send the triage action with job_id and value, and undo sends null',async()=>{
 const h=harness();h.state({jobs:[{id:'j"1',title:'AI',status:'new',bucket:'pending',triage:null}]});
 h.run(`globalThis.calls=[];action=async(name,payload)=>{calls.push({name,payload});return {};};CSS={escape:s=>s}`);
 const html=h.run('triageControls(state.jobs[0])');
 for(const [value,label] of [['interested','感兴趣'],['later','稍后'],['skipped','跳过']])
  assert.match(html,new RegExp(`<button type="button" class="secondary" data-triage="${value}" data-triage-job="j&quot;1" aria-pressed="false">${label}</button>`));
 assert.doesNotMatch(html,/撤销选择/);
 const click=(value)=>({target:{closest:s=>s==='[data-triage-job]'?{dataset:{triageJob:'j"1',triage:value}}:null}});
 for(const fn of h.document.listeners.click)fn(click('later'));
 await h.run('Promise.resolve()');
 await h.run(`chooseTriage('j"1',null)`);
 assert.deepEqual(JSON.parse(h.run('JSON.stringify(calls)')),[{name:'triage',payload:{job_id:'j"1',value:'later'}},{name:'triage',payload:{job_id:'j"1',value:null}}]);
 h.run("state.jobs[0].triage='interested'");
 assert.match(h.run('triageControls(state.jobs[0])'),/class="primary" data-triage="interested"[^>]*aria-pressed="true"/);
 assert.match(h.run('triageControls(state.jobs[0])'),/data-triage="" data-triage-job="j&quot;1">撤销选择/);
 assert.match(h.run('triageControls(state.jobs[0])'),/正在后台准备材料/);
});
test('locked or approved jobs cannot change or undo their card choice',()=>{
 const h=harness();
 for(const status of ['sending','unknown','submitted','rejected']){
  const html=h.run(`triageControls({id:'j',status:${JSON.stringify(status)},triage:'interested'})`);
  assert.doesNotMatch(html,/data-triage=/);assert.match(html,/已锁定，不能改选择/);
 }
 const approved=h.run(`triageControls({id:'j',status:'approved',triage:'interested',package:{}})`);
 assert.doesNotMatch(approved,/data-triage="">|删除这份材料/);assert.match(approved,/材料已批准，不能撤销选择/);
});
test('the queue groups jobs by the server bucket in a fixed order and shows the server counts',()=>{
 const h=harness();
 h.state({counts:{pending:2,chosen:1,materials:1,sent:0,skipped:1,new_today:3},jobs:[
  {id:'s',title:'Skipped',bucket:'skipped',triage:'skipped',status:'new'},{id:'m',title:'Materials',bucket:'materials',status:'review',package:{}},
  {id:'p1',title:'Pending',bucket:'pending',status:'new'},{id:'c',title:'Chosen',bucket:'chosen',triage:'interested',status:'new'},
  {id:'x',title:'Unknown bucket',bucket:'<b>',status:'new'}]});
 h.run('renderQueue()');const html=h.node('#job-list').innerHTML;
 assert.match(html,/待选 2 · 已选 1 · 材料 1 · 已投 0 · 已跳过 1 · 今天新增 3/);
 const order=[...html.matchAll(/class="queue-group-title">([^ <]+) <span class="count">(\d+)<\/span>/g)].map(m=>m[1]+m[2]);
 assert.deepEqual(order,['待选2','已选1','材料1','已跳过1']);
 assert.ok(html.indexOf('Pending')<html.indexOf('Chosen')&&html.indexOf('Chosen')<html.indexOf('Materials')&&html.indexOf('Materials')<html.indexOf('Skipped'));
 assert.match(html,/<details class="queue-group" data-disclosure="bucket-skipped"><summary class="queue-group-title">已跳过/);
 assert.match(html,/待选 <span class="count">2<\/span><\/h2>.*Pending.*Unknown bucket.*<\/section><section class="queue-group" aria-label="已选">/);
 assert.doesNotMatch(html,/<b>/);
});
test('prepare_error is escaped in the detail and flagged in the queue row',()=>{
 const h=harness();h.state({candidate:{facts:[]},jobs:[{id:'j',title:'AI',status:'new',bucket:'chosen',triage:'interested',application_url:'https://example.com/apply',prepare_error:'<img src=x onerror=alert(1)>'}]});
 h.run("activeId='j';renderQueue();renderDetail()");
 const detail=h.node('#detail-pane').innerHTML;
 assert.match(detail,/材料准备失败：&lt;img src=x onerror=alert\(1\)&gt;/);assert.doesNotMatch(detail,/<img|正在后台准备材料/);
 assert.match(h.node('#job-list').innerHTML,/<span class="badge warn">准备失败<\/span>/);
});

const NOW=Date.parse('2026-11-03T04:00:00Z');
test('search params leave out empty filters, repeat city, and drop fresh for the held-back count',()=>{
 const h=harness();
 assert.equal(h.run(`searchParams({q:'  Go 支付 ',city:'上海',direction:'backend',source:'feishu',fresh:7})`),'q=Go+%E6%94%AF%E4%BB%98&city=%E4%B8%8A%E6%B5%B7&direction=backend&source=feishu&fresh=7&limit=100');
 assert.equal(h.run(`searchParams({q:'',city:null,direction:null,source:null,fresh:7},{withFresh:false})`),'limit=100');
});
test('freshness only says first seen, last seen and still in the list, never 发布 or 在招',()=>{
 const h=harness();const f=g=>JSON.parse(h.run(`JSON.stringify(freshness(${JSON.stringify(g)},${NOW}))`));
 assert.deepEqual(f({status:'open',first_seen:'2026-11-02T01:00:00Z',last_seen:'2026-11-03T01:00:00Z'}),{tone:'fresh',label:'新搜到',detail:'昨天首次搜到，今天还搜得到'});
 assert.deepEqual(f({status:'open',first_seen:'2026-09-18T01:00:00Z',last_seen:'2026-11-02T01:00:00Z'}),{tone:'ok',label:'仍在列表',detail:'9 月 18 日首次搜到，昨天最近一次搜到'});
 assert.deepEqual(f({status:'open',first_seen:'2026-10-28T01:00:00Z',last_seen:'2026-10-31T01:00:00Z'}),{tone:'warn',label:'近几天没搜到',detail:'6 天前首次搜到，3 天前最近一次搜到'});
 assert.deepEqual(f({status:'closed',first_seen:'2026-10-01T01:00:00Z',last_seen:'2026-10-17T01:00:00Z'}),{tone:'off',label:'已不在列表',detail:'最近一次搜到是 10 月 17 日，之后连续两轮没再出现'});
 assert.equal(f({status:'open',first_seen:null,last_seen:null}).label,'搜到时间不明');
 const src=fs.readFileSync(path.join(JS_DIR,'shared/time.js'),'utf8')+fs.readFileSync(path.join(JS_DIR,'search/page.js'),'utf8');
 // The two allowed uses: the library note (不等于招聘方仍在招) and a date a source itself gave (X 写的发布日期).
 const said=src.replace(/\/\/.*$/gm,'').replace(/不等于招聘方仍在招/g,'').replace(/写的发布日期/g,'');
 assert.doesNotMatch(said,/发布|在招/);
});
const GROUP={group:'g1',title:'<img src=x onerror=1>工程师',company:'A&B',city:'上海',status:'closed',direction:'backend',first_seen:'2026-10-01T01:00:00Z',last_seen:'2026-10-17T01:00:00Z',
 sources:[{job_id:'j"1',source:'<b>',status:'closed',first_seen:'2026-10-01T01:00:00Z',last_seen:'2026-10-17T01:00:00Z',matched:true,salary:'<i>30k</i>',location:'上海'},
  {job_id:'j2',source:'feishu',status:'open',first_seen:'2026-10-01T01:00:00Z',last_seen:'2026-10-17T01:00:00Z',matched:false,salary:null,posted_at:'2026-10-27'}]};
test('a result group escapes every library string and greys out a closed group',()=>{
 const h=harness();h.state({jobs:[{id:'j"1',title:'x',triage:'interested'}]});
 const html=h.run(`groupHtml(${JSON.stringify(GROUP)})`);
 assert.doesNotMatch(html,/<img|<b>|<i>/);
 assert.match(html,/&lt;img src=x onerror=1&gt;工程师/);assert.match(html,/A&amp;B/);assert.match(html,/&lt;i&gt;30k&lt;\/i&gt;/);
 assert.match(html,/class="group closed"/);assert.match(html,/href="#\/job\/j%22%221"|href="#\/job\/j%221"/);
 assert.match(html,/<span class="st st-off">已不在列表<\/span>/);assert.match(html,/这条记录没命中检索词/);
 assert.match(html,/飞书招聘写的发布日期：10 月 27 日/);assert.match(html,/<span class="tri-tag" data-v="interested">感兴趣<\/span>/);
});
test('the sentence spells out the filters, counts records and groups, and offers the held-back groups',()=>{
 const h=harness();h.state({orientation:{directions:[{id:'backend',name:'后端开发'}]}});
 h.run(`searchQuery.q='<script>';searchQuery.city='上海';searchQuery.direction='backend';searchQuery.fresh=7;searchData={total_groups:1,groups:[${JSON.stringify(GROUP)}]};heldBack=2`);
 const s=h.run('sentenceHtml()');
 assert.match(s,/^在 <b>上海<\/b> 找 <b>后端开发<\/b>，标题或 JD 含 <b>&lt;script&gt;<\/b>，看 <b>全部来源<\/b>，只看最近 7 天搜到过、仍在列表的：1 条记录合并成 1 组。/);
 assert.match(s,/另有 2 组已不在列表或超出时间范围，<button type="button" data-act="show-all">一起显示<\/button>/);
 h.run(`searchError='参数<错误>'`);assert.equal(h.run('sentenceHtml()'),'搜索没有完成：参数&lt;错误&gt;');
});
test('the preview quotes the JD in the serif excerpt and admits when there is no match explanation yet',()=>{
 const h=harness();h.state({jobs:[{id:'j"1',title:'x',jd:'短行\n负责 <b>支付</b> 核心链路的服务开发与稳定性建设。\n第二段也足够长，会出现在摘录里。'}]});
 const html=h.run(`peekHtml(${JSON.stringify(GROUP)})`);
 assert.match(html,/<p class="excerpt"><span class="from">JD 摘录（&lt;b&gt;）<\/span>负责 &lt;b&gt;支付&lt;\/b&gt;/);assert.doesNotMatch(html,/短行/);
 assert.match(html,/还没做匹配解释/);assert.match(html,/打开详情 <span class="kbd" aria-hidden="true">↵<\/span>/);
 h.run(`rememberMatch('j"1',{hard:[{status:'met'},{status:'unknown'}],keywords:[{coverage:'explicit'},{coverage:'absent'}],evidence:[{fact_ids:['f1']},{fact_ids:[]}]})`);
 assert.match(h.run(`peekHtml(${JSON.stringify(GROUP)})`),/1 符合，0 不符合，1 不知道.*<span class="hl">1<\/span> \/ 2 有原词，0 相近.*1 \/ 2 有事实/);
});

const MATCH={hard:[{kind:'language',requirement:'英语六级',jd_evidence:'英语六级优先',status:'unknown',fact_ids:['f7'],why:'f7 还没确认'},
  {kind:'years',requirement:'3年以上',jd_evidence:'3 年以上 <Go> 开发经验',status:'not_met',fact_ids:['f1'],why:'事实里只有 2 年'}],
 keywords:[{keyword:'<Go>',jd_evidence:'3 年以上 <Go> 开发经验',coverage:'explicit',fact_ids:['f1'],related_fact_ids:[],why:'有原词'},
  {keyword:'Kubernetes',jd_evidence:'了解 Kubernetes',coverage:'related',fact_ids:[],related_fact_ids:['f2'],why:'只有 k8s'},
  {keyword:'Kafka',jd_evidence:'熟悉 Kafka',coverage:'absent',fact_ids:[],related_fact_ids:[],why:'事实里没有'}],
 evidence:[{kind:'hard_skill',requirement:'Kafka',jd_evidence:'熟悉 Kafka',fact_ids:[],related_fact_ids:[]}],
 structure:{years:{value:{min:3,max:null},evidence:'3 年以上 <Go> 开发经验'},hard_skills:[{value:'<Go>',evidence:'<Go>'}],soft_skills:[],languages:[],certificates:[],bonus:[],location:[]},
 structure_by:'rules',notice:'不打分<b>',extract_note:'按规则抽取'};
test('the three ATS steps keep 不知道 apart from 不符合, count rows and escape every model string',()=>{
 const h=harness();h.state({candidate:{facts:[{id:'f1',text:'Go 两年',status:'confirmed',source:{reference:'简历'}},{id:'f7',text:'六级',status:'unconfirmed',source:{reference:'简历'}}]}});
 const html=h.run(`verdictHtml(${JSON.stringify(MATCH)})`);
 assert.match(html,/语言：英语六级.*<span class="mark unknown">不知道<\/span>/);assert.match(html,/年限：3年以上.*<span class="mark bad">不符合<\/span>/);
 assert.match(html,/<p class="score">0 \/ 2<\/p>/);assert.match(html,/<p class="score">1 \/ 3<\/p>/);assert.match(html,/<p class="score">0 \/ 1<\/p>/);
 assert.match(html,/<li data-c="explicit"[^>]*><span>&lt;Go&gt;<\/span>/);assert.match(html,/<li data-c="related"[^>]*>.*相近说法/);
 assert.match(html,/class="fact pending"[^>]*>f7</);assert.match(html,/定位原文/);
 assert.doesNotMatch(html,/<Go>|<b>/);assert.match(html,/不打分&lt;b&gt;/);
});
test('JD marks never nest, escape the text and put each note beside its paragraph',()=>{
 const h=harness();h.state({candidate:{facts:[]}});
 const html=h.run(`jdHtml({jd:'任职要求\\n3 年以上 <Go> 开发经验，熟悉 Kafka。\\n英语六级优先'},${JSON.stringify(MATCH)})`);
 assert.match(html,/<h3 class="jd-h">任职要求<\/h3>/);
 assert.match(html,/<mark class="ev ev-kw-explicit" data-m="3 年以上 &lt;Go&gt; 开发经验">3 年以上 &lt;Go&gt; 开发经验<\/mark>/);
 assert.match(html,/<mark class="ev ev-kw-absent" data-m="熟悉 Kafka">熟悉 Kafka<\/mark>/);
 assert.doesNotMatch(html,/<mark[^>]*>[^<]*<mark/);assert.doesNotMatch(html,/<Go>/);
 const paras=html.split('<div class="para');
 assert.match(paras[1],/年限：不符合。事实里只有 2 年/);assert.match(paras[1],/Kafka：没有事实/);assert.doesNotMatch(paras[1],/英语六级/);
 assert.match(paras[2],/语言：不知道。f7 还没确认/);
});
test('the job header names unconfirmed facts it left out, and the structure quotes its evidence escaped',()=>{
 const h=harness();h.state({candidate:{facts:[{id:'f1',status:'confirmed',text:'x',source:{}},{id:'f7',status:'unconfirmed',text:'y',source:{}}]},jobs:[{id:'j',title:'T<x>',company:'C',jd:''}]});
 const html=h.run(`jobPageHtml(state.jobs[0],null,${JSON.stringify(MATCH)})`);
 assert.match(html,/只用了 1 条已确认的事实。f7 还没确认，没有拿来对照。/);assert.match(html,/data-open-candidate>去确认/);
 assert.match(html,/<h1 id="page-title" tabindex="-1">T&lt;x&gt;<\/h1>/);assert.match(html,/返回搜索结果（Esc）/);assert.match(html,/这一组还没有抓到 JD 原文/);
 assert.match(html,/<dt>年限<\/dt><dd>3–不限 年<span class="src">「3 年以上 &lt;Go&gt; 开发经验」<\/span>/);assert.match(html,/<dt>学历<\/dt><dd><span class="none">原文没提<\/span>/);
 assert.match(html,/在工作台打开这个岗位/);assert.doesNotMatch(html,/发布/);
 const none=h.run(`jobPageHtml(state.jobs[0],null,null)`);assert.match(none,/还没做匹配解释/);assert.match(none,/data-act="job-match"/);
});

test('triage tabs count by each job own choice, keep applied jobs out and escape the rows',()=>{
 const h=harness();h.state({jobs:[{id:'a',title:'<b>A</b>',triage:null,bucket:'pending',status:'new',collected_at:'2026-10-30T01:00:00Z'},
  {id:'b',title:'B',triage:'interested',bucket:'chosen',status:'new'},{id:'c',title:'C',triage:'later',bucket:'pending',status:'new'},
  {id:'d',title:'D',triage:null,bucket:'skipped',status:'rejected'},{id:'e',title:'E',triage:'interested',bucket:'sent',status:'submitted'},{id:'f',title:'F',triage:null,bucket:'sent',status:'submitted'}]});
 assert.deepEqual(JSON.parse(h.run('JSON.stringify(tabCounts(state.jobs))')),{pending:1,interested:2,later:1,skipped:1});
 const html=h.run('triageHtml()');
 assert.match(html,/data-bucket="pending" aria-selected="true" tabindex="0">待选<span class="c">1<\/span>/);
 assert.match(html,/<p class="t">&lt;b&gt;A&lt;\/b&gt;<\/p>/);assert.doesNotMatch(html,/<b>A/);
 assert.match(html,/本机收集于 10 月 30 日/);assert.doesNotMatch(html,/发布|在招/);
 assert.match(html,/data-tri="interested">感兴趣 <span class="kbd" aria-hidden="true">1<\/span>/);
 h.run("switchTab('interested')");const locked=h.node('#view').innerHTML;
 const rowE=locked.split('<div class="titem"').find(r=>r.includes('data-tid="e"'));
 assert.match(rowE,/已锁定，不能改选择/);assert.doesNotMatch(rowE,/data-tri=/);assert.match(locked.split('<div class="titem"').find(r=>r.includes('data-tid="b"')),/data-tri="later"/);
 h.run("switchTab('later')");assert.match(h.node('#view').innerHTML,/这一组是空的|<p class="t">C<\/p>/);
});
test('1/2/3 toggle the choice through the triage action, again clears it, and U restores the previous one',async()=>{
 const h=harness();h.state({jobs:[{id:'j',title:'T',triage:null,status:'new'},{id:'z',title:'Z',triage:null,status:'submitted'}]});
 h.run(`globalThis.calls=[];action=async(name,payload)=>{calls.push({name,payload});state.jobs.find(j=>j.id===payload.job_id).triage=payload.value;return {};}`);
 await h.run(`toggleTriage(jobById('j'),'later')`);await h.run(`toggleTriage(jobById('j'),'later')`);
 await h.run('undoTriage()');await h.run('undoTriage()');await h.run('undoTriage()');
 assert.deepEqual(JSON.parse(h.run('JSON.stringify(calls)')).map(c=>c.payload),[{job_id:'j',value:'later'},{job_id:'j',value:null},{job_id:'j',value:'later'},{job_id:'j',value:null}]);
 assert.equal(h.node('#toast').textContent,'没有可以撤销的分拣');
 assert.equal(await h.run(`toggleTriage(jobById('z'),'skipped')`),false);assert.equal(h.run('calls.length'),4);assert.match(h.node('#toast').textContent,/已锁定/);
});
test('the bottom bar marks the current choice with aria-pressed and disables a locked job',()=>{
 const h=harness();
 const html=h.run(`barHtml({id:'j',title:'<i>T</i>',company:'C',triage:'later',status:'new'},'search')`);
 assert.match(html,/data-bar-triage="later" aria-pressed="true"/);assert.match(html,/data-bar-triage="interested" aria-pressed="false"/);
 assert.match(html,/title="&lt;i&gt;T&lt;\/i&gt;，C"/);assert.match(html,/全部操作 <span class="kbd" aria-hidden="true">⌘K<\/span>/);
 assert.match(h.run(`barHtml({id:'j',title:'T',status:'submitted'},'job')`),/已锁定，不能改选择.*disabled/);
});

test('settings show only the key tail, send no empty key, and leave every consent kind unticked by default',()=>{
 const h=harness();h.state({ai:{settings:{base_url:'https://api.example.com/v1',model:'m-1',budget_cny:5},key_hint:'3f9c',consent:null,consent_current:false},config:{sources:['anker']},runs:[]});
 const html=h.run('settingsHtml()');
 assert.match(html,/placeholder="已保存，尾号 3f9c。留空表示不改…"/);assert.doesNotMatch(html,/value="[^"]*3f9c/);
 assert.equal((html.match(/name="kind" value="[a-z_]+" checked/g)||[]).length,0);
 assert.match(html,/<span>完整简历<\/span><span class="n warn">不脱敏/);
 assert.match(html,/还没有同意。勾选后，同意只对 api\.example\.com 的 m-1 有效/);
 const form={elements:{base_url:{value:' https://api.example.com/v1 '},model:{value:'m-1'},budget_cny:{value:''},api_key:{value:'  '}}};
 assert.deepEqual(JSON.parse(h.run(`JSON.stringify(aiPayload(${JSON.stringify(form)}))`)),{base_url:'https://api.example.com/v1',model:'m-1'});
 const checked={querySelectorAll:()=>[{value:'job_text'},{value:'resume_redacted'}]};
 h.run(`globalThis.checked={querySelectorAll:()=>[{value:'job_text'},{value:'resume_redacted'}]}`);
 assert.deepEqual(JSON.parse(h.run('JSON.stringify(consentPayload(checked))')),{kinds:['job_text','resume_redacted'],host:'api.example.com',model:'m-1'});
});
test('a consent for another service is shown as no longer valid, not as granted',()=>{
 const h=harness();h.state({ai:{settings:{base_url:'https://api.example.com',model:'m-2'},consent:{host:'old.example.com',model:'m-1',kinds:['job_text'],granted_at:'2026-10-30T13:14:00Z'},consent_current:false}});
 const html=h.run('settingsHtml()');
 assert.match(html,/原来的同意给的是 old\.example\.com 的 m-1，和现在的服务不一样，已不生效/);assert.doesNotMatch(html,/value="job_text" checked/);
});
test('each source says how its last run went in words and shapes, with the reason escaped',()=>{
 const h=harness();h.state({config:{sources:['boss','liepin']},runs:[{finished_at:'2026-11-03T02:00:00Z',sources:[
  {kind:'boss',status:'failed',error:'<script>x</script>'},{kind:'liepin',status:'needs_login'},{kind:'anker',status:'ok',truncated:true,returned:5},{kind:'lever',status:'ok',returned:2}]}]});
 const html=h.run('settingsHtml()');
 assert.match(html,/BOSS 直聘<\/td><td><span class="st st-bad">失败<\/span><span class="note">&lt;script&gt;x&lt;\/script&gt;<\/span>/);
 assert.match(html,/猎聘<\/td><td><span class="st st-warn">需要登录<\/span>/);
 assert.match(html,/安克官网<\/td><td><span class="st st-warn">结果被截断<\/span>.*<td class="num">5<\/td>/);
 assert.match(html,/Lever<\/td><td><span class="st st-ok">成功<\/span><\/td><td class="num">2<\/td>/);
 assert.match(html,/Ashby<\/td><td><span class="st st-muted">还没运行<\/span><\/td><td class="num">—<\/td>/);
 assert.match(html,/data-source="boss" aria-label="启用 BOSS 直聘" checked/);assert.match(html,/data-source="anker" aria-label="启用 安克官网" >/);
 assert.match(html,/那一轮不会把没取到的岗位标成"已不在列表"/);assert.doesNotMatch(html,/<script>/);
});
test('the frozen workbench stays reachable from settings, the job page and the palette',()=>{
 const h=harness();h.state({});
 const html=h.run('settingsHtml()');
 for(const hook of ['data-open-resume','data-open-candidate','data-act="edit-targets"','data-open-import','href="#/workbench"','href="/bookmarklets"'])assert.ok(html.includes(hook),hook);
 assert.match(h.run(`jobPageHtml({id:'j',title:'T',jd:''},null,null)`),/data-act="open-workbench" data-job="j">在工作台打开这个岗位/);
 const index=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
 assert.match(index,/<div class="wb" id="workbench-page" hidden>/);
 for(const id of ['review-dialog','candidate-dialog','resume-dialog','import-dialog','config-form','control-button','stop-button'])assert.ok(index.includes(`id="${id}"`),id);
});

test('every text colour pair in the tokens reaches 4.5:1 in light and dark (DESIGN.md §2)',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../static/style.css'),'utf8');
 const vars=block=>Object.fromEntries([...block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)].map(m=>[m[1],m[2]]));
 const light=vars(css.slice(css.indexOf(':root {'),css.indexOf('}',css.indexOf(':root {'))));
 const darkAt=css.indexOf('@media (prefers-color-scheme: dark)');
 const dark={...light,...vars(css.slice(darkAt,css.indexOf('}',css.indexOf(':root {',darkAt))))};
 const lum=h=>{const c=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255).map(v=>v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4);return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2];};
 const ratio=(a,b)=>{const [x,y]=[lum(a),lum(b)].sort((p,q)=>q-p);return (x+0.05)/(y+0.05);};
 // Foreground on background as the pages and the reskinned workbench use them.
 const pairs=[['ink','paper'],['ink-2','paper'],['ink-3','paper'],['ink-2','wash'],['ink-3','wash-2'],['ok','paper'],['warn','paper'],['bad','paper'],
  ['pen','paper'],['pen','wash'],['on-marker','marker'],['paper','ink'],['ok','wash'],['warn','wash'],['bad','wash'],['ink','wash'],['ink-2','wash-2']];
 for(const [name,t] of [['light',light],['dark',dark]])for(const [fg,bg] of pairs){
  assert.ok(t[fg]&&t[bg],`${name}: --${fg} / --${bg} missing`);
  assert.ok(ratio(t[fg],t[bg])>=4.5,`${name}: --${fg} on --${bg} is ${ratio(t[fg],t[bg]).toFixed(2)}:1`);
 }
 assert.equal(light['on-marker'],dark['on-marker']);
});

const BOOKMARKLETS=['boss-zhipin','liepin','liepin-list','lagou','mokahr','universal'];
const BM_DIR=path.join(__dirname,'../static/bookmarklets');
// Mirrors hunt/bookmarklets.py assemble(): the shared delivery prelude replaces each script's "// @deliver" line.
const bookmarkletSource=name=>fs.readFileSync(path.join(BM_DIR,name+'.js'),'utf8').replace(/^ *\/\/ @deliver$/m,()=>fs.readFileSync(path.join(BM_DIR,'_deliver.js'),'utf8'));

test('bookmarklet sources and the built scripts are valid JavaScript',()=>{
 const {spawnSync}=require('node:child_process');
 for(const name of [...BOOKMARKLETS,'_deliver']){
  const r=spawnSync(process.execPath,['--check',path.join(BM_DIR,name+'.js')],{encoding:'utf8'});
  assert.equal(r.status,0,name+': '+r.stderr);
 }
 for(const name of BOOKMARKLETS)assert.doesNotThrow(()=>new vm.Script(bookmarkletSource(name)),name);
});

// A minimal page: dom maps a selector to its elements; querySelector answers with the first one.
// runTimers: timer callbacks fire on the next microtask, so a script that sleeps between steps can be driven to the end.
function runBookmarklet(name,{text='',title='页面',dom={},fetchImpl,runTimers=false}={}){
 const toasts=[],timers=[],calls=[];
 const el=()=>({style:{},remove(){this.removed=true;},appendChild(){}});
 const document={title,body:{innerText:text,appendChild(node){toasts.push(node);}},documentElement:{},
  querySelectorAll:s=>dom[s]||[],querySelector:s=>(dom[s]||[])[0]||null,getElementById:()=>null,createElement:el,addEventListener(){}};
 const context=vm.createContext({document,location:{href:'https://careers.example.com/jobs/1?utm_source=x',pathname:'/jobs/1'},TextEncoder,JSON,Object,String,Math,Date,Array,URL,Set,
  setTimeout:(fn,ms)=>{timers.push({fn,ms});if(runTimers)Promise.resolve().then(fn);return 1;},
  fetch:async(url,init)=>{calls.push({url,init});return fetchImpl?fetchImpl(url,init):{ok:true,status:200,json:async()=>({ok:true,duplicate:false})};}});
 const code=bookmarkletSource(name).replaceAll('__INBOX_URL__','http://127.0.0.1:8771/api/inbox').replaceAll('__INBOX_TOKEN__','tok-123');
 return {toasts,timers,calls,payload:()=>JSON.parse(calls[0].init.body),run:()=>vm.runInContext(code,context)};
}
const visible=text=>({innerText:text,getClientRects:()=>[1],closest:()=>null});
const inDialog=text=>({innerText:text,getClientRects:()=>[1],closest:()=>({})});
const hidden=text=>({innerText:text,getClientRects:()=>[],closest:()=>null});

for(const name of ['universal','liepin','lagou']){
 test(name+' bookmarklet posts with the inbox token, stays under the size limit, and uses a self-removing toast',async()=>{
  const h=runBookmarklet(name,{text:'负责后端服务开发。'.repeat(20000)});
  await h.run();
  const [{url,init}]=h.calls;
  assert.equal(url,'http://127.0.0.1:8771/api/inbox');
  assert.equal(init.method,'POST');assert.equal(init.headers['X-Inbox-Token'],'tok-123');assert.equal(init.credentials,'omit');
  const bytes=Buffer.byteLength(init.body);
  assert.ok(bytes<=180000,'body bytes '+bytes);
  const payload=JSON.parse(init.body);
  assert.equal(payload.url,'https://careers.example.com/jobs/1?utm_source=x');
  assert.ok(payload.extracted.raw_text.length>1000&&payload.extracted.raw_text.length<100000);
  assert.equal(h.toasts.length,1);assert.match(h.toasts[0].textContent,/已发送到工作台/);assert.equal(h.toasts[0].style.background,'#38634d');
  assert.equal(h.timers.at(-1).ms,3000);h.timers.at(-1).fn();assert.equal(h.toasts[0].removed,true);
 });

 test(name+' bookmarklet reports a rejected token and an unreachable inbox without blocking dialogs',async()=>{
  const rejected=runBookmarklet(name,{text:'正文'.repeat(300),fetchImpl:async()=>({ok:false,status:403,json:async()=>({error:'收件令牌无效'})})});
  await rejected.run();
  assert.match(rejected.toasts[0].textContent,/令牌无效或已重置/);assert.equal(rejected.toasts[0].style.background,'#a04841');
  const down=runBookmarklet(name,{text:'正文'.repeat(300),fetchImpl:async()=>{throw new TypeError('Failed to fetch');}});
  await down.run();
  assert.match(down.toasts[0].textContent,/连不上本地工作台/);assert.equal(down.timers.at(-1).ms,3000);
 });
}

// A 猎聘 search card as the page renders it: hashed class names next to stable ones (jobCardPcContainer, jobTitleBox, companyName).
function liepinCard(id,title,{href='https://www.liepin.com/job/'+id+'.shtml?pgRef=x&skId=ab&index=0',place='上海-闵行区',head}={}){
 const link={href,innerText:head||title+'\n【上海-闵行区】\n急聘 50-80k·14薪\n8年以上 本科'};
 const nodes={'.jobTitleBox':{innerText:title+'【 '+place+' 】',querySelector:s=>s==='.ellipsis-1'?{innerText:title}:null},
  '.companyName':{innerText:'示例银行'},'[data-nick="job-detail-company-info"]':{innerText:'示例银行\n银行 1000-9999人'},
  '.recruiterName':{innerText:'华先生·CEO'}};
 return {querySelectorAll:s=>s==='a[href]'?[link]:[],querySelector:s=>nodes[s]||null};
}

test('liepin-list sends one canonical item per search card and one summary toast',async()=>{
 const cards=[liepinCard(1986324371,'衍生品定价与风控负责人'),liepinCard(1986324371,'重复卡片'),liepinCard(1990000001,'信贷风控经理',{href:'https://www.liepin.com/a/1990000001.shtml?d_sfrom=x'}),
  liepinCard(1,'外链卡片',{href:'https://evil.example/job/1.shtml'})];
 const h=runBookmarklet('liepin-list',{title:'风控招聘',dom:{'.jobCardPcContainer':cards},
  fetchImpl:async(url,init)=>({ok:true,status:200,json:async()=>({ok:true,duplicate:JSON.parse(init.body).url.includes('/a/')})})});
 await h.run();
 const sent=h.calls.map(c=>JSON.parse(c.init.body));
 assert.deepEqual(sent.map(p=>p.url),['https://www.liepin.com/job/1986324371.shtml','https://www.liepin.com/a/1990000001.shtml']);
 for(const c of h.calls){assert.equal(c.init.headers['X-Inbox-Token'],'tok-123');assert.equal(c.init.credentials,'omit');}
 const first=sent[0];
 assert.equal(first.platform,'liepin');assert.equal(first.summary_only,true);
 assert.deepEqual([first.extracted.job_title,first.extracted.company,first.extracted.location,first.extracted.salary],['衍生品定价与风控负责人','示例银行','上海-闵行区','50-80k·14薪']);
 assert.match(first.extracted.raw_text,/^猎聘搜索结果卡片，不含完整职位描述。/);assert.match(first.extracted.raw_text,/银行 1000-9999人/);
 assert.doesNotMatch(first.extracted.raw_text,/华先生/);
 assert.equal(h.toasts.length,2);assert.match(h.toasts[0].textContent,/第 1 页：正在发送 2 个岗位/);
 assert.equal(h.toasts[1].textContent,'本次共 1 页 2 个岗位：新增 1，工作台已有 1。已是最后一页。');assert.equal(h.toasts[1].style.background,'#38634d');
 assert.equal(h.timers.at(-1).ms,8000);
});

test('liepin-list stops on a rejected token or a dead inbox, and says when the page has no cards',async()=>{
 const cards=[liepinCard(1,'甲'),liepinCard(2,'乙')];
 const rejected=runBookmarklet('liepin-list',{dom:{'.jobCardPcContainer':cards},fetchImpl:async()=>({ok:false,status:403,json:async()=>({error:'收件令牌无效'})})});
 await rejected.run();
 assert.equal(rejected.calls.length,1);assert.match(rejected.toasts.at(-1).textContent,/令牌无效或已重置/);
 let n=0;
 const down=runBookmarklet('liepin-list',{dom:{'.jobCardPcContainer':cards},fetchImpl:async()=>{if(n++)throw new TypeError('Failed to fetch');return {ok:true,status:200,json:async()=>({ok:true,duplicate:false})};}});
 await down.run();
 assert.match(down.toasts.at(-1).textContent,/^已发送 1 个后中断。连不上本地工作台/);assert.equal(down.toasts.at(-1).style.background,'#a04841');
 const bad=runBookmarklet('liepin-list',{dom:{'.jobCardPcContainer':cards},fetchImpl:async()=>({ok:false,status:400,json:async()=>({error:'缺少页面正文'})})});
 await bad.run();
 assert.equal(bad.toasts.at(-1).textContent,'本次共 1 页 2 个岗位：新增 0，工作台已有 0，没收下 2。已是最后一页。');assert.equal(bad.toasts.at(-1).style.background,'#a04841');
 const empty=runBookmarklet('liepin-list',{});
 await empty.run();
 assert.equal(empty.calls.length,0);assert.match(empty.toasts[0].textContent,/没有找到猎聘岗位卡片/);
});

// A results listing with an Ant Design pager: clicking 下一页 swaps in the next page's cards, as 猎聘 does without navigating.
function liepinPager(pages,{stuck=false}={}){
 let at=0;
 const dom={'.jobCardPcContainer':pages[0],'.ant-pagination-item-active':[{innerText:'1'}]};
 const li={className:'ant-pagination-next',getAttribute:n=>n==='aria-disabled'?String(at>=pages.length-1):null,
  querySelector:s=>s==='button'?button:null};
 const button={clicks:0,click(){this.clicks++;if(stuck||at>=pages.length-1)return;at++;
  dom['.jobCardPcContainer']=pages[at];dom['.ant-pagination-item-active']=[{innerText:String(at+1)}];}};
 dom['li.ant-pagination-next']=[li];
 return {dom,button};
}
const liepinPage=(n,size=2)=>Array.from({length:size},(_,i)=>liepinCard(1990000000+n*100+i,'第'+n+'页岗位'+i));

test('liepin-list pages with 下一页 at a reader pace until the last page, sending each job once',async()=>{
 // 20 pages, like the 运营 search that the old 10-page cap cut in half; page 2 repeats a card from page 1.
 const pages=[liepinPage(1),[...liepinPage(2),liepinPage(1)[0]],...Array.from({length:18},(_,i)=>liepinPage(i+3))];
 const {dom,button}=liepinPager(pages);
 const h=runBookmarklet('liepin-list',{dom,runTimers:true});
 await h.run();
 assert.equal(button.clicks,19);
 assert.equal(h.calls.length,40);
 assert.equal(new Set(h.calls.map(c=>JSON.parse(c.init.body).url)).size,40);
 assert.equal(h.toasts.at(-1).textContent,'本次共 20 页 40 个岗位：新增 40，工作台已有 0。已是最后一页。');
 const pauses=h.timers.map(t=>t.ms).filter(ms=>ms>=3000&&ms<=6000&&ms!==3000);
 assert.equal(pauses.length,19,'one pause before each click');
});

test('liepin-list stops when 下一页 changes nothing, at the safety cap, and when the bookmark is clicked again',async()=>{
 const stuck=liepinPager([liepinPage(1),liepinPage(2)],{stuck:true});
 const s=runBookmarklet('liepin-list',{dom:stuck.dom,runTimers:true});
 await s.run();
 assert.equal(s.calls.length,2);assert.match(s.toasts.at(-1).textContent,/列表没有变化，已停下/);assert.equal(s.toasts.at(-1).style.background,'#a04841');
 const many=liepinPager(Array.from({length:53},(_,i)=>liepinPage(i+1,1)));
 const m=runBookmarklet('liepin-list',{dom:many.dom,runTimers:true});
 await m.run();
 assert.equal(m.calls.length,50);assert.equal(many.button.clicks,49);assert.match(m.toasts.at(-1).textContent,/^本次共 50 页 50 个岗位.*已到安全上限 50 页。$/);
 const two=liepinPager([liepinPage(1),liepinPage(2),liepinPage(3)]);
 const t=runBookmarklet('liepin-list',{dom:two.dom,runTimers:true});
 const first=t.run();
 await t.run();
 assert.match(t.toasts.at(-1).textContent,/翻完当前这一页就停/);
 await first;
 assert.equal(two.button.clicks,0);assert.equal(t.calls.length,2);assert.match(t.toasts.at(-1).textContent,/按你的要求停在第 1 页。$/);
});

test('universal title skips a decoy h1 and prefers the h1 that appears in the page title',async()=>{
 const h=runBookmarklet('universal',{text:'正文'.repeat(30),title:'云mall-java后端开发工程师 | 腾讯招聘',
  dom:{h1:[visible('分享岗位'),visible('云mall-java后端开发工程师')]}});
 await h.run();assert.equal(h.payload().extracted.job_title,'云mall-java后端开发工程师');
});

test('universal title ignores a hidden h1 and falls back to the document title',async()=>{
 const h=runBookmarklet('universal',{text:'正文'.repeat(30),title:'数据工程师 - 示例公司',dom:{h1:[hidden('数据工程师')]}});
 await h.run();assert.equal(h.payload().extracted.job_title,'数据工程师 - 示例公司');
});

test('universal title prefers JSON-LD JobPosting over h1 and og:title, through @graph, arrays and bad blocks',async()=>{
 const ld=json=>({textContent:json});
 const dom={'script[type="application/ld+json"]':[ld('{not json'),ld(JSON.stringify([{'@type':'Organization'},{'@graph':[{'@type':['Thing','JobPosting'],title:'数据工程师'}]}]))],
  'meta[property="og:title"]':[{content:'OG 标题'}],h1:[visible('分享岗位')]};
 const h=runBookmarklet('universal',{text:'正文'.repeat(30),title:'分享岗位',dom});
 await h.run();assert.equal(h.payload().extracted.job_title,'数据工程师');
});

test('universal title uses og:title before any h1',async()=>{
 const h=runBookmarklet('universal',{text:'正文'.repeat(30),dom:{'meta[property="og:title"]':[{content:'后端工程师'}],h1:[visible('分享岗位')]}});
 await h.run();assert.equal(h.payload().extracted.job_title,'后端工程师');
});

test('universal title takes the first usable h1 inside the chosen main container, skipping share dialogs',async()=>{
 const main={innerText:'岗位职责'.repeat(80),querySelectorAll:s=>s==='h1'?[inDialog('分享岗位'),visible('算法工程师')]:[]};
 const h=runBookmarklet('universal',{text:'x',title:'招聘',dom:{main:[main],h1:[visible('分享岗位')]}});
 await h.run();assert.equal(h.payload().extracted.job_title,'算法工程师');
});

test('universal title falls back to the page title when every h1 sits in a share dialog (Tencent case)',async()=>{
 const main={innerText:'岗位职责'.repeat(80),querySelectorAll:s=>s==='h1'?[inDialog('分享岗位')]:[]};
 const h=runBookmarklet('universal',{text:'x',title:'岗位详情 | 腾讯招聘',dom:{main:[main],h1:[inDialog('分享岗位')]}});
 await h.run();assert.equal(h.payload().extracted.job_title,'岗位详情 | 腾讯招聘');
});

test('mokahr warns and sends nothing when the iframe is cross-origin (contentDocument is null, no throw)',async()=>{
 const h=runBookmarklet('mokahr',{text:'壳页面',dom:{'iframe[src*="mokahr.com"]':[{contentDocument:null}]}});
 await h.run();
 assert.equal(h.calls.length,0);assert.match(h.toasts[0].textContent,/跨域/);assert.equal(h.toasts[0].style.background,'#a04841');assert.equal(h.timers.at(-1).ms,3000);
});

test('mokahr reads a same-origin iframe document',async()=>{
 const inner={body:{innerText:'分享\n职位信息\n职位名称\n职位名称\n数据策略工程师\n工作地点\n工作地点\n杭州'},querySelector:()=>null};
 const h=runBookmarklet('mokahr',{text:'壳页面',dom:{'iframe[src*="mokahr.com"]':[{contentDocument:inner}]}});
 await h.run();assert.equal(h.payload().extracted.job_title,'数据策略工程师');assert.equal(h.payload().extracted.location,'杭州');
});

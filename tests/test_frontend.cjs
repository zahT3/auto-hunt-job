'use strict';
// DOM-free safety contract tests: no browser, recruitment site, or network access.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const JS_DIR=path.join(__dirname,'../static/js');
const IMPORT=/^import\s+(?:[\s\S]*?\s+from\s+)?"([^"]+)";$/gm;
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
const app='"use strict";\n'+moduleSources(path.join(JS_DIR,'main.js'))
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
      querySelector(){return null;},reset(){},showModal(){this.open=true;},close(){this.open=false;},
      scrollIntoView(){},focus(){this.focused=true;},setAttribute(name,value){this[name]=value;},toggleAttribute(name,value){this[name]=value;}
    });
    return nodes.get(selector);
  }
  const document={listeners:{},querySelector:s=>s==='dialog[open]'?null:node(s),querySelectorAll:s=>selections.get(s)||[],addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);},hidden:false,activeElement:null};
  return {node,selections,document};
}
function harness(){
  const {node,selections,document}=fakeDocument();
  const context=vm.createContext({document,console,URL,crypto:require('node:crypto').webcrypto,structuredClone,setTimeout:()=>1,clearTimeout(){},matchMedia:()=>({matches:false}),fetch(){throw new Error('Unexpected network request');}});
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

test('orient view escapes every server and model string, including table ids in attributes',()=>{
 const h=harness();orientState(h,ORIENT_PROPOSAL);
 const steps=h.run('orientBody()');
 h.run("orientMode='pick'");const pick=h.run('orientBody()');
 for(const html of [steps,pick]){
  assert.doesNotMatch(html,/<img|<script|<b>|<i>|onerror=alert\(1\)>/);
 }
 assert.match(steps,/&lt;img src=x onerror=alert\(1\)&gt;/);assert.match(steps,/&lt;script&gt;why&lt;\/script&gt;/);
 assert.match(steps,/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);assert.match(steps,/事实 gone&lt;i&gt;（已不在资料中）/);
 assert.match(pick,/value="x&quot;&gt;&lt;script&gt;"/);assert.match(pick,/&lt;b&gt;家族&lt;\/b&gt;/);
});
test('each direction shows its own search terms above the merged list',()=>{
 const h=harness();orientState(h,{by:'ai',directions:[{id:'backend',name:'后端开发',terms:['后端','<b>Go</b>']},{id:'da',name:'数据分析师',terms:[]}],terms:['后端','Go','数据分析']});
 const html=h.run('directionsSection()');
 assert.match(html,/后端开发<\/strong><p>未写理由<\/p><p class="orient-direction-terms">搜索词：后端 · &lt;b&gt;Go&lt;\/b&gt;<\/p>/);
 assert.equal((html.match(/orient-direction-terms/g)||[]).length,1);
 assert.match(html,/<strong>合并后的搜索词<\/strong><span>后端 · Go · 数据分析<\/span>/);
 orientState(h,{by:'ai',directions:[{id:'backend',name:'后端开发'}],terms:['后端']});
 assert.match(h.run('directionsSection()'),/<strong>搜索词<\/strong>/);
});
test('orient view says whether AI was used, from the by and questions_by fields',()=>{
 const h=harness();orientState(h,ORIENT_PROPOSAL);
 assert.match(h.run('directionsSection()'),/建议方向.*使用了 AI/);
 orientState(h,{...ORIENT_PROPOSAL,by:'rules',questions_by:'rules'});
 assert.match(h.run('directionsSection()'),/建议方向.*未使用 AI · 本地规则/);assert.match(h.run('questionsSection()'),/未使用 AI · 本地规则/);
 assert.doesNotMatch(h.run('orientBody()'),/使用了 AI/);
 orientState(h,{...ORIENT_PROPOSAL,by:'user'});
 assert.match(h.run('directionsSection()'),/已选方向.*未使用 AI · 你手动选择/);
});
test('without directions or keywords, 开始找岗位 opens 定方向 instead of searching',async()=>{
 const h=harness();orientState(h,null);h.run(`globalThis.calls=[];action=async(name)=>{calls.push(name);return {};}`);
 await h.run('startSearch()');
 assert.equal(h.run('calls.length'),0);assert.equal(h.node('#orient-dialog').open,true);
 assert.match(h.node('#orient-body').innerHTML,/还没有搜索方向。先定方向/);assert.match(h.node('#orient-body').innerHTML,/跳过问题，直接选方向/);
 orientState(h,{directions:[{id:'backend',name:'后端开发'}],terms:['后端'],by:'user'});h.node('#orient-dialog').open=false;
 await h.run('startSearch()');assert.deepEqual(Array.from(h.run('calls')),['run']);assert.equal(h.node('#orient-dialog').open,false);
});
test('answers keep multi-choice as lists, single choice as one string, and leave blanks out',async()=>{
 const h=harness();
 orientState(h,{questions:[{id:'family',text:'你想找哪些行业的工作？（可多选）',kind:'choice',options:['技术研发','产品']},
  {id:'years',text:'经验？',kind:'choice',options:['1-3 年','3-5 年']},{id:'city',text:'城市',kind:'text',options:[]},{id:'exclude',text:'排除',kind:'text',options:[]}],answers:{}});
 const html=h.run('questionsSection()');
 assert.match(html,/type="checkbox" name="orient-q-0" value="技术研发"/);assert.match(html,/type="radio" name="orient-q-1" value="1-3 年"/);
 assert.match(html,/type="radio" name="orient-q-1" value="" checked>暂不回答/);
 const fields={'orient-q-0':[{checked:true,value:'技术研发'},{checked:true,value:'产品'}],'orient-q-1':[{checked:false,value:'1-3 年'},{checked:true,value:'3-5 年'},{checked:false,value:''}],
  'orient-q-2':[{value:'  上海、杭州 '}],'orient-q-3':[{value:'  '}]};
 h.run(`globalThis.calls=[];action=async(name,payload)=>{calls.push({name,payload});return {};}`);
 await h.run(`submitAnswers({querySelectorAll:s=>(${JSON.stringify(fields)})[s.match(/"(.+)"/)[1]]})`);
 assert.deepEqual(JSON.parse(h.run('JSON.stringify(calls)')),[{name:'orient_answer',payload:{answers:{family:['技术研发','产品'],years:'3-5 年',city:'上海、杭州'}}}]);
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
 h.run('openOrient()');assert.equal(h.node('#orient-dialog').open,true);assert.equal(h.node('#orient-questions-title').focused,true);
 orientState(h,{questions:[{id:'city',text:'城市',kind:'text',options:[]},{id:'years',text:'经验',kind:'choice',options:['1-3 年']}],answers:{}});
 h.run("orientMode='steps'");const steps=h.run('orientBody()');
 assert.doesNotMatch(steps,/<(div|span|a)[^>]*data-orient/);
 assert.match(steps,/<label class="orient-question">1\. 城市<input type="text"/);assert.match(steps,/<fieldset class="orient-question"><legend>2\. 经验<\/legend>/);
 assert.match(steps,/<button type="submit"[^>]*>提交回答，给出方向<\/button>/);assert.match(steps,/<button type="button" class="text-button" data-orient-pick>/);
 h.run('showPick()');assert.equal(h.node('#orient-pick-title').focused,true);
 const pick=h.node('#orient-body').innerHTML;
 assert.match(pick,/<details class="orient-family"[^>]*><summary>/);assert.match(pick,/<label class="check-label"><input type="checkbox" name="direction"/);
 assert.match(pick,/<button type="button" class="text-button" data-orient-back>返回<\/button>/);
 h.run(`action=async()=>{state.orientation={directions:[{id:'backend',name:'后端开发'}],terms:['后端'],by:'rules'};return {};}`);
 await h.run(`submitAnswers({querySelectorAll:()=>[]})`);assert.equal(h.node('#orient-directions-title').focused,true);
 h.run('adopt()');assert.equal(h.node('#orient-dialog').open,false);assert.equal(h.node('#run-button').focused,true);
 assert.match(h.node('#toast').textContent,/已采用 1 个方向。点「开始找岗位」/);
});
test('orient styles fit a 390px screen: no fixed width beyond it, wrapping rows, long words broken',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../static/style.css'),'utf8');
 const orient=css.slice(css.indexOf('/* 定方向 dialog */'));
 assert.ok(orient.length>100);
 for(const m of orient.matchAll(/(?:^|[\s;{])(width|min-width|flex-basis)\s*:\s*(\d+)px/g))assert.ok(Number(m[2])<=358,m[0]);
 assert.match(orient,/\.orient-body\s*\{[^}]*overflow-wrap:\s*anywhere/);
 for(const rule of ['.orient-actions','.orient-options','.orient-line','.orient-section-head'])assert.match(orient,new RegExp(rule.replace('.','\\.')+'\\s*\\{[^}]*flex-wrap:\\s*wrap'),rule);
 // The dialog itself is bounded by the viewport (existing rule the orient dialog relies on).
 assert.match(css,/dialog\{[^}]*max-width:calc\(100vw - 32px\)/);
});
test('the real ES modules link and render one state through main.js',async()=>{
 const {node,document}=fakeDocument();
 const state={dataset:'app',control:'running',jobs:[{id:'j',title:'Synthetic role',company:'Co'}],config:{keywords:[]},candidate:{facts:[]},
  orientation:{directions:[{id:'backend',name:'后端开发'}],terms:['后端'],by:'rules'},direction_table:[]};
 const saved={};
 for(const key of ['document','matchMedia','setInterval','fetch','CSS'])saved[key]=Object.getOwnPropertyDescriptor(globalThis,key);
 Object.assign(globalThis,{document,matchMedia:()=>({matches:false}),setInterval:()=>1,CSS:{escape:s=>s},
  fetch:async url=>{assert.equal(url,'/api/state');return {ok:true,json:async()=>state};}});
 try{
  await import(require('node:url').pathToFileURL(path.join(JS_DIR,'main.js')).href);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('#queue-count').textContent,1);assert.match(node('#job-list').innerHTML,/Synthetic role/);
  assert.equal(node('#orient-open').textContent,'方向：后端开发');assert.match(node('#orient-body').innerHTML,/建议方向/);
 }finally{
  for(const [key,desc] of Object.entries(saved))desc?Object.defineProperty(globalThis,key,desc):delete globalThis[key];
 }
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

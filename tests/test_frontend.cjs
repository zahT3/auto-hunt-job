'use strict';
// DOM-free safety contract tests: no browser, recruitment site, or network access.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const app=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8')
  .replace(/^loadState\(\);$/m,'')
  .replace(/^setInterval\(.*$/m,'');
function harness(){
  const nodes=new Map(),selections=new Map();
  function node(selector){
    if(!nodes.has(selector))nodes.set(selector,{
      innerHTML:'',textContent:'',hidden:false,disabled:false,checked:false,open:false,
      elements:new Proxy({}, {get:(target,key)=>target[key]??(target[key]={value:'',checked:false})}),
      classList:{toggle(){}},listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},
      querySelector(){return null;},reset(){},showModal(){this.open=true;},close(){this.open=false;},
      scrollIntoView(){},focus(){},toggleAttribute(name,value){this[name]=value;}
    });
    return nodes.get(selector);
  }
  const document={listeners:{},querySelector:s=>s==='dialog[open]'?null:node(s),querySelectorAll:s=>selections.get(s)||[],addEventListener(name,fn){this.listeners[name]=fn;},hidden:false,activeElement:null};
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
  assert.match(h.node('#review-content').innerHTML,/不能批准对外执行/);
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

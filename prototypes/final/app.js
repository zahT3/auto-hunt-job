// auto-hunt-job 合并原型。搜索、分拣、定方向、设置照方向 A（键盘优先）；岗位详情照方向 B（ATS 三步并排 + 原文页边批注）。
// 数据结构见 data.js，和后端接口一致。键盘：/ 搜索，J/K 或方向键移动，Enter 打开，1/2/3 分拣，U 撤销，⌘K 全部操作，Esc 返回。
(function () {
  const D = window.DATA;

  // ---- 小工具 ----
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ESC[c]);
  class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
  const raw = (s) => new Raw(s);
  const html = (strings, ...vals) => raw(strings.reduce((out, s, i) => {
    let v = i < vals.length ? vals[i] : '';
    if (Array.isArray(v)) v = v.map((x) => (x instanceof Raw ? x.s : esc(x))).join('');
    else v = v instanceof Raw ? v.s : esc(v);
    return out + s + v;
  }, ''));

  // 时间：接口给 UTC，界面按北京时间算"今天""N 天前"。
  const TZ = 'Asia/Shanghai';
  const ymd = (iso) => new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(iso));
  const hm = (iso) => new Intl.DateTimeFormat('zh-CN', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(iso));
  const daysAgo = (iso) => Math.round((new Date(ymd(D.NOW)) - new Date(ymd(iso))) / 864e5);
  const md = (iso) => { const s = ymd(iso); return s.slice(5, 7).replace(/^0/, '') + ' 月 ' + s.slice(8).replace(/^0/, '') + ' 日'; };
  const rel = (iso) => { const d = daysAgo(iso); return d <= 0 ? '今天' : d === 1 ? '昨天' : d <= 7 ? d + ' 天前' : md(iso); };
  const srcName = (k) => D.SOURCE_NAMES[k] || k;
  const dirName = (id) => (D.directionTable.find((d) => d.id === id) || { name: id || '未归类' }).name;
  const fact = (id) => D.facts.find((f) => f.id === id);
  const groupOf = (gid) => D.groups.find((g) => g.group === gid);
  const lead = (g) => D.jobs[g.sources[0].job_id];
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  // 新旧只说本机知道的事：第一次搜到、最近一次搜到、还在不在来源列表里。不说"发布""在招"。
  const fresh = (g) => {
    if (g.status === 'closed') return { tone: 'off', label: '已不在列表', detail: `最近一次搜到是 ${md(g.last_seen)}，之后连续两轮没再出现` };
    const first = daysAgo(g.first_seen), last = daysAgo(g.last_seen);
    const lastText = last <= 0 ? '今天还搜得到' : `${rel(g.last_seen)}最近一次搜到`;
    if (last >= 3) return { tone: 'warn', label: '近几天没搜到', detail: `${rel(g.first_seen)}首次搜到，${lastText}` };
    return { tone: first <= 2 ? 'fresh' : 'ok', label: first <= 2 ? '新搜到' : '仍在列表', detail: `${rel(g.first_seen)}首次搜到，${lastText}` };
  };
  const sourceState = (s) => (s.status === 'closed' ? { tone: 'off', label: '已不在列表' } : { tone: 'ok', label: '在列表' });
  // 只有来源自己写了发布日期才显示，并写明是哪个来源说的。
  const postedLine = (g) => g.sources.filter((s) => s.posted_at).map((s) => `${srcName(s.source)}写的发布日期：${md(s.posted_at + 'T04:00:00+00:00')}`).join('；');
  const salaryOf = (g) => (g.sources.find((s) => s.salary) || {}).salary || '薪资没写';

  const st = (tone, label) => html`<span class="st st-${tone}">${label}</span>`;
  const mk = (tone, label) => html`<span class="mark ${tone}">${label}</span>`;
  const kbd = (k) => html`<span class="kbd" aria-hidden="true">${k}</span>`;
  const factChip = (id) => { const f = fact(id); return f ? html`<span class="fact ${f.status === 'confirmed' ? '' : 'pending'}" tabindex="0" data-tip="${id}：${f.text}（${f.source.reference}${f.status === 'confirmed' ? '' : '，还没确认'}）">${id}</span>` : ''; };
  const jdRef = (refs) => (refs && refs.length ? html`<span class="jdref" tabindex="0" data-tip="${refs.map((r) => `${(D.jobs[r.job_id] || {}).company || r.job_id}：「${r.evidence}」`).join('；')}">JD ${refs.length} 处</span>` : '');

  // ---- 状态 ----
  const view = document.getElementById('view');
  const bar = document.getElementById('bar');
  const toastEl = document.getElementById('toast');
  const q = Object.assign({}, D.query);
  let showAll = false;
  let selected = null;
  let triageTab = 'pending';
  let triageSel = null;
  let returnFocus = null;
  const history = [];

  const parse = () => { const p = (location.hash || '#/search').slice(2).split('/'); return { page: p[0] || 'search', id: p[1] || null }; };
  const go = (path) => { location.hash = '#/' + path; };

  // ---- 搜索：照 /api/search 的规则在本地过滤 ----
  const words = () => (q.q || '').trim().split(/\s+/).filter(Boolean).map((w) => w.toLowerCase());
  const recordHits = (s, title) => { const ws = words(); const text = (title + ' ' + ((D.jobs[s.job_id] || {}).jd || '')).toLowerCase(); return ws.every((w) => text.includes(w)); };
  const search = () => {
    const all = [], hidden = [];
    D.groups.forEach((g) => {
      const sources = g.sources.map((s) => Object.assign({}, s, { matched: recordHits(s, g.title) && (!q.source || s.source === q.source) }));
      if (!sources.some((s) => s.matched)) return;
      if (q.city && g.city !== q.city) return;
      if (q.direction && g.direction !== q.direction) return;
      const row = Object.assign({}, g, { sources, title_match: words().every((w) => g.title.toLowerCase().includes(w)) });
      if (q.fresh !== 'all' && !(g.status === 'open' && daysAgo(g.last_seen) <= q.fresh)) hidden.push(row); else all.push(row);
    });
    const sort = (a, b) => (a.status === b.status ? 0 : a.status === 'open' ? -1 : 1) || (b.title_match - a.title_match) || (new Date(b.last_seen) - new Date(a.last_seen));
    return { groups: all.sort(sort), hidden: hidden.sort(sort) };
  };
  const FRESH = [{ v: 3, t: '最近 3 天' }, { v: 7, t: '最近 7 天' }, { v: 30, t: '最近 30 天' }, { v: 'all', t: '不限' }];
  const FILTERS = [
    { key: 'city', label: '城市', opts: [{ v: null, t: '不限' }].concat(['上海', '杭州', '远程'].map((c) => ({ v: c, t: c }))) },
    { key: 'direction', label: '方向', opts: [{ v: null, t: '不限' }].concat(D.directionTable.map((d) => ({ v: d.id, t: d.name }))) },
    { key: 'source', label: '来源', opts: [{ v: null, t: '全部来源' }].concat(Object.keys(D.SOURCE_NAMES).map((k) => ({ v: k, t: D.SOURCE_NAMES[k] }))) },
    { key: 'fresh', label: '搜到', opts: FRESH },
  ];
  const fText = (f) => (f.opts.find((o) => o.v === q[f.key]) || f.opts[0]).t;
  const filterHTML = (f) => html`<details class="filter" data-key="${f.key}"><summary><span class="k">${f.label}</span> ${fText(f)}</summary>
    <div class="menu" role="group" aria-label="${f.label}">${f.opts.map((o) => html`<label><input type="radio" name="f-${f.key}" value="${String(o.v)}" ${raw(q[f.key] === o.v ? 'checked' : '')}> ${o.t}</label>`)}</div></details>`;
  const sentence = (res) => {
    const records = res.groups.reduce((n, g) => n + g.sources.filter((s) => s.matched).length, 0);
    const when = q.fresh === 'all' ? '不限时间' : `只看${FRESH.find((o) => o.v === q.fresh).t}搜到过、仍在列表的`;
    let s = html`在 <b>${q.city || '所有城市'}</b> 找 <b>${q.direction ? dirName(q.direction) : '所有方向'}</b>${q.q ? html`，标题或 JD 含 <b>${q.q}</b>` : ''}，看 <b>${q.source ? srcName(q.source) : '全部来源'}</b>，${when}：${records} 条记录合并成 ${res.groups.length} 组。`;
    if (res.hidden.length && !showAll) s = html`${s} 另有 ${res.hidden.length} 组已不在列表或超出时间范围，<button type="button" data-act="show-all">一起显示</button>`;
    return s;
  };
  const groupHTML = (g) => {
    const f = fresh(g);
    const j = lead(g);
    const posted = postedLine(g);
    return html`<article class="group ${g.status}" id="g-${g.group}" data-id="${g.group}" tabindex="-1" aria-selected="${String(selected === g.group)}">
      <div class="g-head"><a class="g-title" href="#/job/${j.id}">${g.title}</a><span class="g-pay">${salaryOf(g)}</span></div>
      <p class="g-meta">${g.company}，${g.city}，${dirName(g.direction)}</p>
      <p class="g-fresh">${st(f.tone, f.label)}<span class="d">${f.detail}</span>${j.triage ? html`<span class="tri-tag" data-v="${j.triage}">${triName(j.triage)}</span>` : ''}</p>
      ${posted ? html`<p class="posted">${posted}</p>` : ''}
      <details class="sources"><summary>${g.sources.length} 个来源${g.sources.map((s) => { const x = sourceState(s); return st(x.tone, srcName(s.source)); })}</summary>
        <div class="kv" role="table" aria-label="来源记录">
          <span class="h">来源</span><span class="h">状态</span><span class="h">首次搜到</span><span class="h">最近搜到</span><span class="h">说明</span>
          ${g.sources.map((s) => { const x = sourceState(s); return html`<span>${srcName(s.source)}</span>${st(x.tone, x.label)}<span>${rel(s.first_seen)}</span><span>${rel(s.last_seen)}</span><span class="note">${s.matched ? (s.salary || s.location || '') : '这条记录没命中检索词'}</span>`; })}
        </div></details>
    </article>`;
  };
  const matchSummary = (jid) => {
    const m = D.match[jid];
    if (!m) return html`<p class="sec-note">还没做匹配解释。打开详情后可以运行；对照只用规则，不发送内容。</p>`;
    const n = (rows, k, v) => rows.filter((r) => r[k] === v).length;
    return html`<div class="summary3">
      <div><h3>第 1 步 硬条件</h3><p>${n(m.hard, 'status', 'met')} 符合，${n(m.hard, 'status', 'not_met')} 不符合，${n(m.hard, 'status', 'unknown')} 不知道</p></div>
      <div><h3>第 2 步 关键词覆盖</h3><p><span class="hl">${n(m.keywords, 'coverage', 'explicit')}</span> / ${m.keywords.length} 有原词，${n(m.keywords, 'coverage', 'related')} 相近</p></div>
      <div><h3>第 3 步 事实证据</h3><p>${m.evidence.filter((r) => r.fact_ids.length).length} / ${m.evidence.length} 有事实</p></div></div>`;
  };
  const peekHTML = (g) => {
    if (!g) return html`<div class="empty"><h2>选一组岗位</h2><p>用 J、K 或方向键在左边移动，按 Enter 打开详情。</p></div>`;
    const f = fresh(g), j = lead(g);
    const jd = j.jd ? j.jd.split('\n').filter((l) => l.length > 12).slice(0, 2).join('') : null;
    return html`<h2>${g.title}</h2><p class="sub">${g.company}，${g.city}，${salaryOf(g)}</p>
      <p class="g-fresh peek-fresh">${st(f.tone, f.label)}<span class="d">${f.detail}</span></p>
      ${jd ? html`<p class="excerpt"><span class="from">JD 摘录（${srcName(g.sources[0].source)}）</span>${jd}</p>` : html`<p class="sub">这一组还没有抓到 JD 原文。</p>`}
      ${matchSummary(j.id)}
      <div class="actions"><a class="btn btn-primary" href="#/job/${j.id}">打开详情 ${kbd('↵')}</a></div>`;
  };
  const emptyHTML = () => html`<div class="empty"><h2>没有符合这些条件的岗位</h2><p>${q.fresh === 'all' ? '' : FRESH.find((o) => o.v === q.fresh).t + '、'}${q.city || '所有城市'}里，本机岗位库没有找到。可以放宽时间，或者换个词再搜一次。</p><button class="btn" type="button" data-act="widen">放宽到 30 天</button></div>`;
  const renderSearch = () => {
    const res = search();
    const list = showAll ? res.groups.concat(res.hidden) : res.groups;
    if (!list.find((g) => g.group === selected)) selected = list[0] ? list[0].group : null;
    view.innerHTML = html`<h1 class="vh">搜索岗位</h1><div class="search">
      <div class="search-left">
        <form class="qbox" role="search" data-form="q">
          <div class="qfield"><input id="q" type="search" value="${q.q}" placeholder="岗位、公司或技能，例如 Go 支付…" aria-label="搜索岗位" autocomplete="off">${kbd('/')}</div>
          <div class="filters">${FILTERS.map(filterHTML)}</div>
          <p class="sentence" aria-live="polite">${sentence(res)}</p>
          <p class="apinote">只查本机岗位库；"在列表"是本机库的判断，不等于招聘方仍在招。</p>
        </form>
        <div class="results" id="results" aria-label="搜索结果">${list.length ? list.map(groupHTML) : emptyHTML()}</div>
      </div>
      <section class="peek" id="peek" aria-label="岗位预览">${peekHTML(list.find((g) => g.group === selected))}</section></div>`;
    renderBar();
  };
  const refreshResults = () => {
    const res = search();
    const list = showAll ? res.groups.concat(res.hidden) : res.groups;
    if (!list.find((g) => g.group === selected)) selected = list[0] ? list[0].group : null;
    document.querySelector('.sentence').innerHTML = sentence(res);
    document.getElementById('results').innerHTML = list.length ? list.map(groupHTML).join('') : emptyHTML();
    document.getElementById('peek').innerHTML = peekHTML(list.find((g) => g.group === selected));
    FILTERS.forEach((f) => { const s = document.querySelector(`details[data-key="${f.key}"] summary`); if (s) s.innerHTML = html`<span class="k">${f.label}</span> ${fText(f)}`; });
    renderBar();
  };

  // ---- 底部操作条 ----
  const TRIAGE = [{ v: 'interested', t: '感兴趣', key: '1' }, { v: 'later', t: '稍后', key: '2' }, { v: 'skipped', t: '跳过', key: '3' }];
  const triName = (v) => (v ? TRIAGE.find((t) => t.v === v).t : '待选');
  const currentJob = () => {
    const r = parse();
    if (r.page === 'job') return D.jobs[r.id];
    if (r.page === 'triage' && triageSel) return lead(groupOf(triageSel));
    if (r.page === 'search' && selected) return lead(groupOf(selected));
    return null;
  };
  const renderBar = () => {
    const j = currentJob();
    const page = parse().page;
    if (!j || !['search', 'job', 'triage'].includes(page)) { bar.hidden = true; return; }
    bar.hidden = false;
    bar.dataset.page = page;
    bar.innerHTML = html`<p class="cur" title="${j.title}，${j.company}"><b>${j.title}</b>，${j.company}</p>
      ${TRIAGE.map((t) => html`<button class="btn" type="button" data-tri="${t.v}" aria-pressed="${String(j.triage === t.v)}">${t.t} ${kbd(t.key)}</button>`)}
      <button class="btn opt" type="button" data-act="palette">全部操作 ${kbd('⌘K')}</button>`;
  };

  // ---- 岗位详情：B 的读法 ----
  const HARD_KIND = { education: '学历', years: '年限', language: '语言', certificate: '证书', location: '地点', remote: '远程' };
  const hardTone = (s) => ({ met: 'ok', not_met: 'bad', unknown: 'unknown' }[s]);
  const hardLabel = (s) => ({ met: '符合', not_met: '不符合', unknown: '不知道' }[s]);
  const covTone = (c) => ({ explicit: 'ok', related: 'near', absent: 'bad' }[c]);
  const covLabel = (c) => ({ explicit: '有原词', related: '相近说法', absent: '没有' }[c]);
  const evTone = (r) => (r.fact_ids.length ? 'ok' : r.related_fact_ids.length ? 'near' : 'bad');
  const evLabel = (r) => (r.fact_ids.length ? '有事实' : r.related_fact_ids.length ? '只有相近事实' : '没有事实');
  const hardReq = (r) => (r.kind === 'remote' ? (r.requirement ? '可以全远程' : '不能全远程') : r.requirement);

  // JD 原文里的标记：关键词按覆盖程度用荧光笔，硬条件和证据用下划线。长片段先标，不嵌套。
  const marksFor = (m) => {
    const out = [], seen = new Set();
    const add = (text, cls, id) => { if (text && !seen.has(text)) { seen.add(text); out.push({ text, cls, id }); } };
    m.keywords.forEach((k, i) => add(k.jd_evidence, 'kw-' + k.coverage, 'k' + i));
    m.hard.forEach((r, i) => add(r.jd_evidence, hardTone(r.status) === 'unknown' ? 'unknown' : hardTone(r.status), 'h' + i));
    m.evidence.forEach((r, i) => add(r.jd_evidence, evTone(r) === 'near' ? 'unknown' : evTone(r), 'e' + i));
    return out;
  };
  const markText = (text, marks) => {
    const segs = [{ s: esc(text), m: false }];
    marks.slice().sort((a, b) => b.text.length - a.text.length).forEach((mm) => {
      const t = esc(mm.text);
      for (let i = 0; i < segs.length; i++) {
        const k = segs[i].m ? -1 : segs[i].s.indexOf(t);
        if (k < 0) continue;
        segs.splice(i, 1, { s: segs[i].s.slice(0, k), m: false }, { s: `<mark class="ev ev-${mm.cls}" data-m="${esc(mm.text)}">${t}</mark>`, m: true }, { s: segs[i].s.slice(k + t.length), m: false });
        break;
      }
    });
    return raw(segs.map((x) => x.s).join(''));
  };
  // 每段原文旁的批注：哪些硬条件、证据、非原词关键词的依据落在这一段。
  const notesFor = (m, para) => {
    const out = [];
    m.hard.forEach((r) => { if (r.jd_evidence && para.includes(r.jd_evidence)) out.push({ tone: hardTone(r.status), text: `${HARD_KIND[r.kind]}：${hardLabel(r.status)}${r.why ? '。' + r.why : ''}`, facts: r.fact_ids }); });
    m.evidence.forEach((r) => { if (r.jd_evidence && para.includes(r.jd_evidence)) out.push({ tone: evTone(r), text: `${r.requirement}：${evLabel(r)}`, facts: r.fact_ids.length ? r.fact_ids : r.related_fact_ids }); });
    m.keywords.forEach((k) => { if (k.coverage !== 'explicit' && k.jd_evidence && para.includes(k.jd_evidence) && k.why) out.push({ tone: covTone(k.coverage), text: `「${k.keyword}」${covLabel(k.coverage)}。${k.why}`, facts: k.related_fact_ids }); });
    return out;
  };
  const GLYPH = { ok: '✓', bad: '✗', unknown: '？', near: '～' };

  const renderJob = (id) => {
    const j = D.jobs[id];
    if (!j) { view.innerHTML = html`<div class="page empty"><h2>找不到这个岗位</h2><a href="#/search">返回搜索</a></div>`; return; }
    const g = groupOf(j.group), f = fresh(g), m = D.match[id], posted = postedLine(g);
    const paras = (j.jd || '').split('\n');
    const HEADS = new Set(['岗位职责', '任职要求', '工作地点']);
    const marks = m ? marksFor(m) : [];
    let n = 0;
    const cnt = (rows, test) => `${rows.filter(test).length} / ${rows.length}`;
    view.innerHTML = html`<article class="detail">
      <a class="back" href="#/search" data-act="back">返回搜索结果（Esc）</a>
      <header class="d-head"><div>
          <h1>${j.title}</h1>
          <p class="sub">${j.company}，${j.location || g.city}，${salaryOf(g)}</p>
          <p class="fresh">${st(f.tone, f.label)}<span class="d">${f.detail}</span></p>
          ${posted ? html`<p class="posted">${posted}</p>` : ''}
        </div>
        ${m ? (() => { const pend = D.facts.filter((x) => x.status !== 'confirmed'); return html`<p class="note-m">只用了 ${D.facts.length - pend.length} 条已确认的事实。${pend.length ? html`${pend.map((x) => x.id).join('、')} 还没确认，没有拿来对照。` : ''}<span class="sub">${m.extract_note}${pend.length ? html`；<a href="#/orient">去确认</a>` : ''}</span></p>`; })() : ''}
      </header>
      ${m ? html`<div class="verdict" aria-label="匹配解释">
        <section aria-labelledby="v1"><p class="step"><span id="v1">第 1 步 硬条件</span><span>招聘系统先按这些筛人</span></p><p class="score">${cnt(m.hard, (r) => r.status === 'met')}</p>
          <ul>${m.hard.map((r) => html`<li><span>${HARD_KIND[r.kind]}：${hardReq(r)}${r.fact_ids.map(factChip)}</span>${mk(hardTone(r.status), hardLabel(r.status))}${r.why ? html`<span class="why">${r.why}</span>` : ''}</li>`)}</ul></section>
        <section aria-labelledby="v2"><p class="step"><span id="v2">第 2 步 关键词覆盖</span><span>再看简历里有没有原词</span></p><p class="score">${cnt(m.keywords, (k) => k.coverage === 'explicit')}</p>
          <ul class="kwchips">${m.keywords.map((k) => html`<li data-c="${k.coverage}" tabindex="0" data-tip="${k.why || ('依据 ' + k.fact_ids.join('、'))}"><span>${k.keyword}</span><span class="t">${k.coverage === 'explicit' ? k.fact_ids.join(' ') : covLabel(k.coverage)}</span></li>`)}</ul>
          <p class="legend"><span><span class="hl">黄底</span> 有原词</span><span><mark class="ev ev-kw-related">虚线</mark> 只有相近说法</span><span><mark class="ev ev-kw-absent">波浪线</mark> 没有</span></p></section>
        <section aria-labelledby="v3"><p class="step"><span id="v3">第 3 步 事实证据</span><span>最后才有人读</span></p><p class="score">${cnt(m.evidence, (r) => r.fact_ids.length)}</p>
          <ul>${m.evidence.map((r) => html`<li><span>${r.requirement}${(r.fact_ids.length ? r.fact_ids : r.related_fact_ids).map(factChip)}<button class="locate" type="button" data-loc="${r.jd_evidence}">定位原文</button></span>${mk(evTone(r), evLabel(r))}</li>`)}</ul>
          <p class="note">${m.notice}。</p></section>
      </div>` : html`<div class="empty flush"><h2>这个岗位还没做匹配解释</h2><p>对照只用规则，不发送内容；如果还没有 JD 结构，会先按"岗位原文"的同意决定是否调用 ${D.ai.consent.host}。</p><button class="btn btn-primary" type="button" data-act="fake">做匹配解释</button></div>`}
      <div class="sec-h"><h2>原文与批注</h2><span class="tally">${m ? (m.structure_by === 'ai' ? 'JD 结构由 AI 抽取；批注只引用已确认事实' : 'JD 结构由本地规则抽取') : '还没有批注'}</span></div>
      <div class="jd">${j.jd ? paras.map((p) => {
        if (HEADS.has(p)) return html`<h3 class="jd-h">${p}</h3>`;
        n += 1;
        const notes = m ? notesFor(m, p) : [];
        return html`<div class="para with-margin"><p><span class="num" aria-hidden="true">${n}</span>${markText(p, marks)}</p>
          <div class="notes">${notes.map((x) => html`<p class="note-m"><span class="mk ${x.tone}" aria-hidden="true">${GLYPH[x.tone]}</span>${x.text}${x.facts && x.facts.length ? html`<span class="sub">依据 ${x.facts.map(factChip)}</span>` : ''}</p>`)}</div></div>`;
      }) : html`<p class="sub">这一组还没有抓到 JD 原文。</p>`}</div>
      ${m ? html`<div class="sec-h"><h2>结构化结果</h2><span class="tally">每项后面是原文依据</span></div>
      <dl class="struct">
        <dt>年限</dt><dd>${m.structure.years ? html`${m.structure.years.value.min}–${m.structure.years.value.max == null ? '不限' : m.structure.years.value.max} 年<span class="src">「${m.structure.years.evidence}」</span>` : html`<span class="none">原文没提</span>`}</dd>
        <dt>学历</dt><dd>${m.structure.education ? html`${m.structure.education.value}<span class="src">「${m.structure.education.evidence}」</span>` : html`<span class="none">原文没提</span>`}</dd>
        <dt>远程</dt><dd>${m.structure.remote ? html`${m.structure.remote.value ? '可以全远程' : '不能全远程'}<span class="src">「${m.structure.remote.evidence}」</span>` : html`<span class="none">原文没提</span>`}</dd>
        ${[['硬技能', 'hard_skills'], ['软技能', 'soft_skills'], ['加分项', 'bonus'], ['地点', 'location']].map(([t, k]) => html`<dt>${t}</dt><dd>${m.structure[k].length ? m.structure[k].map((x) => x.value).join('、') : html`<span class="none">原文没提</span>`}</dd>`)}
      </dl>` : ''}
      <div class="sec-h"><h2>来源记录</h2><span class="tally">同一公司、同一标题、同一城市的记录合成一组</span></div>
      <table class="srcs"><thead><tr><th>来源</th><th>状态</th><th>首次搜到</th><th>最近搜到</th><th>说明</th></tr></thead>
        <tbody>${g.sources.map((s) => { const x = sourceState(s); return html`<tr><td>${srcName(s.source)}</td><td>${st(x.tone, x.label)}</td><td>${md(s.first_seen)}</td><td>${md(s.last_seen)} ${hm(s.last_seen)}</td><td>${s.posted_at ? '来源写的发布日期 ' + md(s.posted_at + 'T04:00:00+00:00') + '；' : ''}${s.salary || ''} ${s.location || ''}</td></tr>`; })}</tbody></table>
    </article>`;
    renderBar();
  };

  // ---- 定方向：state.orientation ----
  const SHORT_Q = { family: '行业', city: '城市', years: '经验年限', remote: '远程', exclude: '排除的行业', switch: '转方向', english: '英语', start: '到岗时间' };
  const KIND_ACTION = { search: '开始找岗位', answer_question: '去回答', add_fact: '补充事实', confirm_fact: '去确认', job_match: '看匹配解释' };
  const KIND_NAME = { search: '搜索', answer_question: '追问', add_fact: '补充事实', confirm_fact: '确认事实', job_match: '单岗匹配' };
  const pointList = (items) => (items.length ? html`<ul>${items.map((x) => html`<li>${x.text}<span class="refs">${x.fact_ids.map(factChip)}${jdRef(x.jd)}</span></li>`)}</ul>` : html`<span class="st st-muted">没有依据可写</span>`);
  const renderOrient = () => {
    const o = D.orientation;
    const answered = o.questions.filter((x) => o.answers[x.id] != null);
    const open = o.questions.filter((x) => o.answers[x.id] == null);
    const ansText = (v) => (Array.isArray(v) ? v.join('、') : v) || '没填';
    const c = o.conditions;
    view.innerHTML = html`<div class="page">
      <header class="page-h"><h1>定方向</h1>
        <p>按 ${D.facts.filter((f) => f.status === 'confirmed').length} 条已确认事实和你的回答给出${o.by === 'ai' ? '，AI 起草（deepseek-chat，合成）' : '，本地规则'}，${hm(o.updated_at)} 更新。采用后，搜索会用下面的合并搜索词。</p></header>
      <div class="cols2">
        <section aria-labelledby="o1">
          <div class="sec-h"><h2 id="o1">你的回答</h2><span class="tally"><a href="#/orient" data-act="fake">全部重答</a></span></div>
          <dl class="answers">${answered.map((x) => html`<dt>${SHORT_Q[x.id] || x.text}</dt><dd>${ansText(o.answers[x.id])}</dd><dd><a href="#/orient" data-act="fake">改</a></dd>`)}</dl>
          <p class="conds">搜索条件：城市 ${c.cities.join('、') || '不限'}；年限 ${c.years || '不限'}；远程 ${c.remote || '没说'}；排除 ${c.exclude_industries.join('、') || '无'}。</p>
          <div class="sec-h gap"><h2>追问</h2><span class="tally">${open.length} 个，回答后会重新给方向</span></div>
          ${open.map((x) => html`<div class="fq" id="q-${x.id}"><fieldset><legend>${x.text}${o.questions_by === 'ai' ? html`<span class="ai">AI 追问</span>` : ''}</legend>
            <div class="opts">${x.options.map((op) => html`<label><input type="radio" name="${x.id}" value="${op}"> ${op}</label>`)}</div></fieldset></div>`)}
        </section>
        <section aria-labelledby="o2">
          <div class="sec-h"><h2 id="o2">建议方向</h2><span class="tally">${o.directions.length} 个；优势、短板、风险每条都有事实或 JD 依据</span></div>
          <table class="compare"><thead><tr><th></th>${o.directions.map((d) => html`<th scope="col"><span class="nm">${d.name}</span><span class="src">${d.source === 'ai' ? 'AI 建议' : d.source === 'rules' ? '本地规则' : '你选的'}</span></th>`)}</tr></thead>
            <tbody>
              <tr><th scope="row">理由</th>${o.directions.map((d) => html`<td data-dir="${d.name}"><span class="why">${d.why}</span><span class="refs">${d.fact_ids.map(factChip)}</span></td>`)}</tr>
              <tr><th scope="row">优势</th>${o.directions.map((d) => html`<td data-dir="${d.name}">${pointList(d.strengths)}</td>`)}</tr>
              <tr><th scope="row">短板</th>${o.directions.map((d) => html`<td data-dir="${d.name}">${pointList(d.gaps)}</td>`)}</tr>
              <tr><th scope="row">风险</th>${o.directions.map((d) => html`<td data-dir="${d.name}">${pointList(d.risks)}</td>`)}</tr>
              <tr><th scope="row">搜索词</th>${o.directions.map((d) => html`<td data-dir="${d.name}">${d.terms.map((t) => { const on = o.terms.includes(t); return html`<span class="term ${on ? '' : 'off'}" tabindex="0" data-tip="${on ? '在合并后的 8 个词里，本轮会搜' : '本轮不搜：合并后只保留 8 个词'}">${t}${on ? '' : '（本轮不搜）'}</span>`; })}</td>`)}</tr>
            </tbody></table>
          <div class="adopt"><button class="btn btn-primary" type="button" data-act="fake">采用这 ${o.directions.length} 个方向</button><button class="btn" type="button" data-act="fake">修改方向</button></div>
        </section>
        <section aria-labelledby="o3">
          <div class="sec-h"><h2 id="o3">暂不建议优先投</h2></div>
          <ul class="notnow">${o.not_recommended.length ? o.not_recommended.map((x) => html`<li><b>${x.name}</b><span>${x.why}${x.fact_ids.map(factChip)}${jdRef(x.jd)}</span></li>`) : html`<li><span>没有。</span></li>`}</ul>
        </section>
        <section aria-labelledby="o4">
          <div class="sec-h"><h2 id="o4">今天就能做</h2><span class="tally">按先后排</span></div>
          <ul class="tasks">${o.next_actions.map((a) => html`<li><span>${a.text}</span><button class="btn" type="button" data-next="${a.id}">${KIND_ACTION[a.kind]}</button><span class="kind">${KIND_NAME[a.kind]}</span></li>`)}</ul>
        </section>
      </div></div>`;
    bar.hidden = true;
  };

  // ---- 分拣 ----
  const BUCKETS = [['pending', '待选'], ['interested', '感兴趣'], ['later', '稍后'], ['skipped', '跳过']];
  const inBucket = (b) => D.groups.filter((g) => (lead(g).triage || 'pending') === b);
  const counts = () => { const c = { pending: 0, interested: 0, later: 0, skipped: 0 }; D.groups.forEach((g) => { c[lead(g).triage || 'pending'] += 1; }); return c; };
  const renderTriage = () => {
    const c = counts();
    const list = inBucket(triageTab);
    if (!list.find((g) => g.group === triageSel)) triageSel = list[0] ? list[0].group : null;
    view.innerHTML = html`<div class="page">
      <header class="page-h"><h1>分拣</h1><p>每组岗位分到 感兴趣、稍后、跳过。计数是总数，不是未读数。选"感兴趣"后会开始准备材料，材料要你审核后才会用。</p></header>
      <div class="split" role="tablist" aria-label="分组">${BUCKETS.map(([b, t]) => html`<button role="tab" type="button" data-bucket="${b}" aria-selected="${String(triageTab === b)}">${t}<span class="c">${c[b]}</span></button>`)}
        <span class="split-help">Tab 切换分组，1 感兴趣，2 稍后，3 跳过，U 撤销</span></div>
      <div class="tlist" role="listbox" aria-label="${BUCKETS.find((x) => x[0] === triageTab)[1]}">
        ${list.length ? list.map((g) => { const f = fresh(g), j = lead(g); return html`<div class="titem" role="option" id="t-${g.group}" data-tid="${g.group}" tabindex="-1" aria-selected="${String(triageSel === g.group)}">
          <div><p class="t">${g.title}</p><p class="m">${g.company}，${g.city}，${salaryOf(g)}</p></div>
          <div class="right">${st(f.tone, f.label)}</div>
          <div class="more"><p class="g-fresh"><span class="d">${f.detail}；${g.sources.length} 个来源</span></p>
            <div class="acts">${TRIAGE.filter((t) => t.v !== triageTab).map((t) => html`<button class="btn" type="button" data-tri="${t.v}">${t.t} ${kbd(t.key)}</button>`)}<a class="btn" href="#/job/${j.id}">打开详情 ${kbd('↵')}</a></div></div></div>`; })
        : html`<div class="empty"><h2>${triageTab === 'pending' ? '待选清空了' : '这一组是空的'}</h2><p>${triageTab === 'pending' ? '下一轮搜索后，新搜到的岗位会出现在这里。' : '在待选里按对应的数字键，岗位会移到这里。'}</p>${triageTab === 'pending' ? html`<a class="btn" href="#/search">去搜索</a>` : ''}</div>`}
      </div></div>`;
    renderBar();
  };

  // ---- 设置 ----
  const RUN = { ok: ['ok', '成功'], failed: ['bad', '失败'], login: ['warn', '需要登录'], truncated: ['warn', '结果被截断'], never: ['muted', '还没运行'] };
  const renderSettings = () => {
    const a = D.ai;
    view.innerHTML = html`<div class="page">
      <header class="page-h"><h1>设置</h1><p>都保存在本机。</p></header>
      <div class="set"><nav aria-label="设置分区"><a href="#s-ai" data-jump="s-ai">AI 服务</a><a href="#s-consent" data-jump="s-consent">发送同意</a><a href="#s-src" data-jump="s-src">来源</a></nav>
        <div>
          <section id="s-ai" aria-labelledby="h-ai"><h2 id="h-ai">AI 服务</h2>
            <p class="lead">定方向、JD 结构化会调用这个服务。没有设置、没有同意或预算用完时用本地规则，结果会标"本地规则"。</p>
            <div class="form">
              <label for="ai-url">服务地址</label><input id="ai-url" type="text" value="${a.settings.base_url}" spellcheck="false">
              <label for="ai-model">模型</label><input id="ai-model" type="text" value="${a.settings.model}" spellcheck="false">
              <label for="ai-key">密钥</label><input id="ai-key" type="password" placeholder="已保存，尾号 ${a.key_hint}。留空表示不改…" autocomplete="off">
              <p class="help">密钥只存本机，界面只显示尾号。</p>
              <span class="label">本月花费</span><div><span>¥${a.spent_cny.toFixed(2)} / ¥${a.settings.budget_cny.toFixed(2)}</span><div class="meter" role="meter" aria-label="本月花费" aria-valuemin="0" aria-valuemax="${a.settings.budget_cny}" aria-valuenow="${a.spent_cny}"><i data-pct="${(a.spent_cny / a.settings.budget_cny * 100).toFixed(1)}"></i></div></div>
            </div></section>
          <section id="s-consent" aria-labelledby="h-consent"><h2 id="h-consent">发送同意</h2>
            <p class="lead">勾选的内容才会发给上面的服务。默认都不勾。</p>
            <div class="consent">${a.kinds.map((k) => html`<label><input type="checkbox" ${raw(a.consent.kinds.includes(k.id) ? 'checked' : '')}><span>${k.name}</span><span class="n ${k.id === 'resume_full' ? 'warn' : ''}">${k.note}</span></label>`)}</div>
            <p class="bound">这份同意只对 ${a.consent.host} 的 ${a.consent.model} 有效，${md(a.consent.granted_at)}授予。换服务地址或模型后要重新同意。</p></section>
          <section id="s-src" aria-labelledby="h-src"><h2 id="h-src">来源</h2>
            <p class="lead">只读搜索，不会投递。失败或被截断的来源写出原因；那一轮不会把没取到的岗位标成"已不在列表"。</p>
            <table class="srcs"><thead><tr><th>启用</th><th>来源</th><th>上次运行（${hm(D.run.finished_at)}）</th><th class="num">岗位</th></tr></thead>
              <tbody>${D.run.sources.map((s) => { const r = RUN[s.state]; return html`<tr><td><input type="checkbox" aria-label="启用 ${s.name}" ${raw(s.enabled ? 'checked' : '')}></td><td>${s.name}</td><td>${st(r[0], r[1])}${s.note ? html`<span class="note">${s.note}</span>` : ''}</td><td class="num">${s.state === 'never' ? '—' : s.found}</td></tr>`; })}</tbody></table></section>
        </div></div></div>`;
    view.querySelectorAll('[data-pct]').forEach((i) => { i.style.width = i.dataset.pct + '%'; });
    bar.hidden = true;
  };

  // ---- 路由 ----
  const runLine = () => {
    const r = D.run;
    const bad = r.sources.filter((s) => s.state === 'failed').map((s) => s.name).join('、');
    const login = r.sources.filter((s) => s.state === 'login').map((s) => s.name).join('、');
    const cut = r.sources.filter((s) => s.state === 'truncated').map((s) => s.name).join('、');
    const line = `${hm(r.finished_at)} 搜完：库里 ${D.groups.length} 组岗位。${bad}失败，${login} 需要登录，${cut}结果被截断。`;
    const el = document.getElementById('run');
    el.textContent = line;
    el.title = line;
  };
  const render = () => {
    const r = parse();
    document.querySelectorAll('.nav a').forEach((a) => { if (a.dataset.page === r.page || (r.page === 'job' && a.dataset.page === 'search')) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    document.querySelectorAll('[data-count]').forEach((el) => { el.textContent = counts()[el.dataset.count]; });
    if (r.page === 'job') renderJob(r.id);
    else if (r.page === 'orient') renderOrient();
    else if (r.page === 'triage') renderTriage();
    else if (r.page === 'settings') renderSettings();
    else renderSearch();
    document.title = ({ job: '岗位详情', orient: '定方向', triage: '分拣', settings: '设置' }[r.page] || '搜索') + ' · auto-hunt-job';
  };
  const routeChange = () => {
    const r = parse();
    render();
    if (r.page === 'search' && returnFocus) {
      const el = document.getElementById('g-' + returnFocus);
      if (el) { el.focus(); el.scrollIntoView({ block: 'nearest' }); }
      returnFocus = null;
      return;
    }
    const h = view.querySelector('h1');
    if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
    window.scrollTo(0, 0);
  };

  // ---- 交互 ----
  const toast = (msg, undo) => {
    toastEl.innerHTML = html`<span>${msg}</span>${undo ? html`<button type="button" data-act="undo">撤销（U）</button>` : ''}`;
    toastEl.classList.add('on');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => toastEl.classList.remove('on'), 5000);
  };
  const refocus = () => {
    const el = document.getElementById('g-' + selected) || document.getElementById('t-' + triageSel);
    if (el && ['search', 'triage'].includes(parse().page)) el.focus();
  };
  const triage = (v) => {
    const j = currentJob();
    if (!j) return;
    const next = j.triage === v ? null : v;
    history.push({ id: j.id, prev: j.triage });
    j.triage = next;
    toast(next ? `已移到「${triName(next)}」：${j.title}` : `已放回待选：${j.title}`, true);
    if (parse().page === 'triage') { const list = inBucket(triageTab); triageSel = list[0] ? list[0].group : null; }
    render();
    refocus();
  };
  const undo = () => {
    const last = history.pop();
    if (!last) { toast('没有可以撤销的分拣'); return; }
    D.jobs[last.id].triage = last.prev;
    toast(`已撤销：${D.jobs[last.id].title} 回到「${triName(last.prev)}」`);
    render();
    refocus();
  };
  const select = (gid) => {
    selected = gid;
    document.querySelectorAll('.group').forEach((x) => x.setAttribute('aria-selected', String(x.dataset.id === gid)));
    document.getElementById('peek').innerHTML = peekHTML(search().groups.concat(search().hidden).find((g) => g.group === gid));
    renderBar();
  };
  const move = (d) => {
    const page = parse().page;
    const sel = page === 'search' ? '.group' : '.titem';
    const rows = [...document.querySelectorAll(sel)];
    const cur = page === 'search' ? selected : triageSel;
    const i = rows.findIndex((x) => (x.dataset.id || x.dataset.tid) === cur);
    const n = rows[Math.max(0, Math.min(rows.length - 1, i + d))];
    if (!n) return;
    if (page === 'search') select(n.dataset.id);
    else { triageSel = n.dataset.tid; rows.forEach((x) => x.setAttribute('aria-selected', String(x === n))); renderBar(); }
    n.focus(); n.scrollIntoView({ block: 'nearest' });
  };

  // 命令面板：每个动作右边写它的键。
  const palette = document.getElementById('palette');
  const pq = document.getElementById('palette-q');
  const plist = document.getElementById('palette-list');
  const ACTIONS = [
    { t: '搜索岗位', k: '/', run: () => { go('search'); setTimeout(() => document.getElementById('q').focus(), 0); } },
    { t: '标为感兴趣', k: '1', run: () => triage('interested') },
    { t: '稍后再看', k: '2', run: () => triage('later') },
    { t: '跳过', k: '3', run: () => triage('skipped') },
    { t: '撤销上一次分拣', k: 'U', run: () => undo() },
    { t: '去分拣', k: 'G 然后 T', run: () => go('triage') },
    { t: '去定方向', k: 'G 然后 O', run: () => go('orient') },
    { t: '去设置', k: 'G 然后 S', run: () => go('settings') },
  ];
  let paletteReturn = null;
  const paletteList = () => { const s = pq.value.trim(); plist.innerHTML = html`${ACTIONS.filter((a) => !s || a.t.includes(s)).map((a) => html`<li><button type="button" data-pa="${a.t}"><span>${a.t}</span>${kbd(a.k)}</button></li>`)}`; };
  const openPalette = () => { paletteReturn = document.activeElement; pq.value = ''; paletteList(); palette.showModal(); pq.focus(); };
  palette.addEventListener('close', () => { if (paletteReturn && paletteReturn.isConnected) paletteReturn.focus(); });
  pq.addEventListener('input', paletteList);
  plist.addEventListener('click', (e) => { const b = e.target.closest('[data-pa]'); if (!b) return; palette.close(); ACTIONS.find((a) => a.t === b.dataset.pa).run(); });

  // 加载态：超过 150ms 才显示骨架，显示后至少 400ms；骨架和真实行同高。
  const loading = (box, skeleton, done) => {
    let shownAt = 0;
    box.setAttribute('aria-busy', 'true');
    const t = setTimeout(() => { shownAt = Date.now(); box.innerHTML = skeleton; }, 150);
    setTimeout(() => { clearTimeout(t); const wait = shownAt ? Math.max(0, 400 - (Date.now() - shownAt)) : 0; setTimeout(() => { box.removeAttribute('aria-busy'); done(); }, wait); }, 700);
  };

  document.addEventListener('click', (e) => {
    const t = e.target;
    const tri = t.closest('[data-tri]'); if (tri) { triage(tri.dataset.tri); return; }
    const nx = t.closest('[data-next]');
    if (nx) {
      const a = D.orientation.next_actions.find((x) => x.id === nx.dataset.next);
      if (a.kind === 'search') { q.direction = a.target.direction_id; q.q = ''; go('search'); }
      else if (a.kind === 'job_match') go('job/' + a.target.job_id);
      else if (a.kind === 'answer_question') { const el = document.getElementById('q-' + a.target.question_id); if (el) { el.scrollIntoView({ block: 'center', behavior: reduced() ? 'auto' : 'smooth' }); el.querySelector('input').focus({ preventScroll: true }); } }
      else toast('原型里不执行这个操作');
      return;
    }
    const act = t.closest('[data-act]');
    if (act) {
      const a = act.dataset.act;
      if (a === 'show-all') { showAll = true; refreshResults(); }
      else if (a === 'widen') { q.fresh = 30; refreshResults(); }
      else if (a === 'palette') openPalette();
      else if (a === 'undo') undo();
      else if (a === 'back') { e.preventDefault(); returnFocus = (D.jobs[parse().id] || {}).group; go('search'); }
      else if (a === 'fake') { e.preventDefault(); toast('原型里不执行这个操作'); }
      return;
    }
    const g = t.closest('.group');
    if (g && !t.closest('a, summary, button, .kv')) { select(g.dataset.id); g.focus(); return; }
    const ti = t.closest('.titem');
    if (ti && !t.closest('a, button')) { triageSel = ti.dataset.tid; renderTriage(); document.getElementById('t-' + triageSel).focus(); return; }
    const bk = t.closest('[data-bucket]');
    if (bk) { triageTab = bk.dataset.bucket; triageSel = null; renderTriage(); document.querySelector(`[data-bucket="${triageTab}"]`).focus(); return; }
    const loc = t.closest('[data-loc]');
    if (loc) {
      const m = [...document.querySelectorAll('mark.ev')].find((x) => x.dataset.m === loc.dataset.loc || x.textContent === loc.dataset.loc);
      document.querySelectorAll('mark.ev.on').forEach((x) => x.classList.remove('on'));
      if (m) { m.classList.add('on'); m.scrollIntoView({ block: 'center', behavior: reduced() ? 'auto' : 'smooth' }); }
      return;
    }
    const jump = t.closest('[data-jump]');
    if (jump) { e.preventDefault(); const s = document.getElementById(jump.dataset.jump); s.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth' }); const h = s.querySelector('h2'); h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
    document.querySelectorAll('details.filter[open]').forEach((d) => { if (!d.contains(t)) d.open = false; });
  });
  document.addEventListener('change', (e) => {
    const inp = e.target;
    if (!inp.name || !inp.name.startsWith('f-')) return;
    const key = inp.name.slice(2);
    const raw0 = inp.value;
    q[key] = raw0 === 'null' ? null : key === 'fresh' ? (raw0 === 'all' ? 'all' : Number(raw0)) : raw0;
    refreshResults();
  });
  document.addEventListener('input', (e) => { if (e.target.id === 'q') { q.q = e.target.value; refreshResults(); } });
  document.addEventListener('submit', (e) => { if (e.target.dataset.form === 'q') e.preventDefault(); });

  let gPending = false;
  document.addEventListener('keydown', (e) => {
    const typing = e.target.matches('input, textarea, select') && !['checkbox', 'radio'].includes(e.target.type);
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); return; }
    if (e.key === 'Escape') {
      const open = document.querySelector('details.filter[open]');
      if (open) { open.open = false; open.querySelector('summary').focus(); return; }
      if (typing && e.target.id === 'q') { e.target.blur(); const g = document.getElementById('g-' + selected); if (g) g.focus(); return; }
      if (parse().page === 'job') { returnFocus = (D.jobs[parse().id] || {}).group; go('search'); }
      return;
    }
    if (typing || e.metaKey || e.ctrlKey || e.altKey || palette.open) return;
    const page = parse().page;
    if (gPending) { gPending = false; const to = { t: 'triage', o: 'orient', s: 'settings', f: 'search' }[e.key.toLowerCase()]; if (to) { go(to); return; } }
    if (e.key === 'g') { gPending = true; setTimeout(() => { gPending = false; }, 800); return; }
    if (e.key === '/') { e.preventDefault(); if (page !== 'search') go('search'); setTimeout(() => document.getElementById('q').focus(), 0); return; }
    if ((e.key === 'j' || e.key === 'ArrowDown') && ['search', 'triage'].includes(page)) { e.preventDefault(); move(1); return; }
    if ((e.key === 'k' || e.key === 'ArrowUp') && ['search', 'triage'].includes(page)) { e.preventDefault(); move(-1); return; }
    if (e.key === 'Enter' && !e.target.closest('a, button, summary')) {
      const gid = page === 'search' ? selected : page === 'triage' ? triageSel : null;
      if (gid) { returnFocus = gid; go('job/' + lead(groupOf(gid)).id); }
      return;
    }
    if (['1', '2', '3'].includes(e.key) && ['search', 'triage', 'job'].includes(page)) { triage(TRIAGE[Number(e.key) - 1].v); return; }
    if (e.key === 'u') { undo(); return; }
    if (e.key === 'Tab' && page === 'triage' && e.target.closest('.titem, [data-bucket]')) {
      e.preventDefault();
      const i = BUCKETS.findIndex((b) => b[0] === triageTab);
      triageTab = BUCKETS[(i + (e.shiftKey ? BUCKETS.length - 1 : 1)) % BUCKETS.length][0];
      triageSel = null;
      renderTriage();
      (document.querySelector('.titem') || document.querySelector(`[data-bucket="${triageTab}"]`)).focus();
    }
  });

  const skeleton = html`${[1, 2, 3, 4].map(() => html`<div class="group sk" aria-hidden="true"><span class="sk-line"></span><span class="sk-line w40"></span><span class="sk-line w60"></span><span class="sk-line w80"></span></div>`)}<p class="vh">正在搜索…</p>`.toString();
  document.getElementById('run-btn').addEventListener('click', (e) => {
    const btn = e.currentTarget;
    if (parse().page !== 'search') go('search');
    setTimeout(() => {
      btn.disabled = true; btn.textContent = '正在搜索…';
      loading(document.getElementById('results'), skeleton, () => { btn.disabled = false; btn.textContent = '开始搜索'; refreshResults(); toast('搜完了（原型：合成数据，没有真的联网）'); });
    }, 0);
  });
  window.addEventListener('hashchange', routeChange);
  runLine();
  render();
})();

// 三个原型共用的小工具：转义、日期、新旧标签、筛选、分拣状态、路由。只读 window.PROTO，不联网。
window.U = (function () {
  const P = window.PROTO;
  const NOW = new Date(P.NOW);

  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ESC[c]);
  // html`...${x}` 转义插值；raw() 包起来的片段原样放入。
  class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
  const raw = (s) => new Raw(s);
  const html = (strings, ...vals) => raw(strings.reduce((out, s, i) => {
    let v = i < vals.length ? vals[i] : '';
    if (Array.isArray(v)) v = v.map((x) => (x instanceof Raw ? x.s : esc(x))).join('');
    else v = v instanceof Raw ? v.s : esc(v);
    return out + s + v;
  }, ''));

  const day = (s) => new Date(s.length <= 10 ? s + 'T00:00:00+08:00' : s);
  const daysAgo = (s) => Math.round((day(P.NOW.slice(0, 10)) - day(s.slice(0, 10))) / 864e5);
  const md = (s) => s.slice(5, 10);
  // Geist 的做法：一周内写相对时间，更早写日期。
  const rel = (s) => {
    if (!s) return '未知';
    const d = daysAgo(s);
    if (d <= 0) return '今天';
    if (d === 1) return '昨天';
    if (d <= 7) return d + ' 天前';
    return md(s);
  };
  const clock = (s) => (s ? s.slice(11, 16) : '');

  const sourceName = (id) => (P.sources.find((s) => s.id === id) || { name: id }).name;
  const dirName = (id) => (P.directions.find((d) => d.id === id) || { name: id }).name;
  const job = (id) => P.jobs.find((j) => j.id === id);
  const fact = (id) => P.facts.find((f) => f.id === id);

  // 新旧：label 是列表里的短词，detail 是一句完整说明。未知、待确认、可能下线分开，不合并。
  const FRESH = {
    new: { label: '新发布', tone: 'fresh' },
    week: { label: '本周发布', tone: 'fresh' },
    open: { label: '仍在招', tone: 'ok' },
    stale: { label: '可能已下线', tone: 'warn' },
    unconfirmed: { label: '在招待确认', tone: 'warn' },
    unknown: { label: '发布时间未知', tone: 'unknown' },
  };
  const verifiedAt = (j) => {
    const v = j.sightings.filter((s) => s.state === 'verified').map((s) => s.checked).sort().pop();
    return v || null;
  };
  const fresh = (j) => {
    const f = FRESH[j.fresh];
    const v = verifiedAt(j);
    let detail;
    if (j.fresh === 'new' || j.fresh === 'week') detail = rel(j.posted) + '发布' + (v ? '，' + rel(v) + '核验在招' : '，还没有逐条核验');
    else if (j.fresh === 'open') detail = daysAgo(j.posted) + ' 天前发布，' + rel(v) + '核验仍在招';
    else if (j.fresh === 'stale') detail = (j.sightings.find((s) => s.state === 'gone') || {}).note || '来源里已经找不到';
    else if (j.fresh === 'unconfirmed') detail = j.sightings[0].note;
    else detail = '来源没有给发布日期，' + rel(j.sightings[0].first) + '第一次发现';
    return { key: j.fresh, label: f.label, tone: f.tone, detail, age: j.posted ? daysAgo(j.posted) : null, verified: v };
  };

  const SIGHT = {
    verified: { label: '已核验在招', tone: 'ok' },
    listed: { label: '列表中出现', tone: 'muted' },
    failed: { label: '抓取失败', tone: 'bad' },
    gone: { label: '已找不到', tone: 'warn' },
    unknown: { label: '状态未知', tone: 'unknown' },
  };
  const sight = (s) => Object.assign({}, SIGHT[s.state], { source: sourceName(s.source) });

  const STATUS = {
    matched: { label: '符合', tone: 'ok' },
    missing: { label: '缺少', tone: 'bad' },
    unknown: { label: '不知道', tone: 'unknown' },
  };

  const RUN = {
    ok: { label: '成功', tone: 'ok' },
    failed: { label: '失败', tone: 'bad' },
    login: { label: '需要登录', tone: 'warn' },
    never: { label: '还没运行', tone: 'unknown' },
  };

  // 筛选。发布时间未知的岗位不会被"7 天内"悄悄丢掉，单独返回，界面要告诉用户。
  const filter = (q) => {
    const text = (q.q || '').trim().toLowerCase();
    const base = P.jobs.filter((j) => {
      if (text && !(j.title + j.company + j.digest).toLowerCase().includes(text)) return false;
      if (q.city.length && !q.city.includes(j.city)) return false;
      if (q.direction.length && !q.direction.includes(j.direction)) return false;
      if (q.source !== 'all' && !j.sightings.some((s) => s.source === q.source)) return false;
      return true;
    });
    if (q.fresh === 'all') return { shown: base, undated: [] };
    const shown = [], undated = [];
    base.forEach((j) => {
      if (!j.posted) undated.push(j);
      else if (daysAgo(j.posted) <= q.fresh || j.fresh === 'open') shown.push(j);
    });
    return { shown, undated };
  };
  const FRESH_OPTIONS = [{ v: 3, t: '3 天内' }, { v: 7, t: '7 天内' }, { v: 30, t: '30 天内' }, { v: 'all', t: '不限时间' }];
  const freshText = (v) => FRESH_OPTIONS.find((o) => o.v === v).t;

  // 分拣：内存里的状态和撤销栈。已有材料的岗位撤销会被后端拒绝，这里用 j.package 模拟。
  const TRIAGE = [
    { v: 'interested', t: '感兴趣', key: '1' },
    { v: 'later', t: '稍后', key: '2' },
    { v: 'skipped', t: '跳过', key: '3' },
  ];
  const history = [];
  const listeners = [];
  const setTriage = (id, v) => {
    const j = job(id);
    history.push({ id, prev: j.triage });
    j.triage = v;
    listeners.forEach((f) => f(id));
  };
  const undo = () => {
    const last = history.pop();
    if (!last) return null;
    job(last.id).triage = last.prev;
    listeners.forEach((f) => f(last.id));
    return last.id;
  };
  const onTriage = (f) => listeners.push(f);
  const counts = () => {
    const c = { pending: 0, interested: 0, later: 0, skipped: 0 };
    P.jobs.forEach((j) => { c[j.triage || 'pending'] += 1; });
    return c;
  };
  const triageName = (v) => (v ? TRIAGE.find((t) => t.v === v).t : '待选');

  // 路由：#/search、#/job/j1、#/orient、#/triage、#/settings
  const parse = () => {
    const parts = (location.hash || '#/search').slice(2).split('/');
    return { page: parts[0] || 'search', id: parts[1] || null };
  };
  const go = (path) => { location.hash = '#/' + path; };

  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // JD 原文里把证据片段包成 <mark>。长片段先标；已经标过的范围不再嵌套。
  const markJD = (text, marks) => {
    const segs = [{ s: esc(text), m: false }];
    marks.slice().sort((a, b) => b.text.length - a.text.length).forEach((m) => {
      const t = esc(m.text);
      if (!t) return;
      for (let i = 0; i < segs.length; i++) {
        const sg = segs[i];
        const k = sg.m ? -1 : sg.s.indexOf(t);
        if (k < 0) continue;
        segs.splice(i, 1, { s: sg.s.slice(0, k), m: false },
          { s: '<mark class="ev ev-' + m.tone + '" data-m="' + esc(m.id) + '">' + t + '</mark>', m: true },
          { s: sg.s.slice(k + t.length), m: false });
        break;
      }
    });
    return raw(segs.map((x) => x.s).join(''));
  };
  // 一个岗位的所有证据片段，供 markJD 使用。tone 取匹配状态。
  const jdMarks = (id) => {
    const m = P.match[id];
    if (!m) return [];
    const seen = new Set();
    const out = [];
    [].concat(m.hard, m.evidence).forEach((r, i) => {
      if (!r.evidence || seen.has(r.evidence)) return;
      seen.add(r.evidence);
      out.push({ id: 'r' + i, text: r.evidence, tone: r.status });
    });
    (P.structure[id] ? P.structure[id].hard_skills : []).forEach((s) => {
      if (seen.has(s.evidence)) return;
      seen.add(s.evidence);
      const kw = m.keywords.find((k) => k.k === s.value);
      out.push({ id: 'k-' + s.value, text: s.evidence, tone: kw ? kw.status : 'unknown' });
    });
    return out;
  };

  // 加载态（Vercel 的做法）：工作超过 150ms 才显示骨架，显示了就至少停 400ms，避免一闪而过。
  // 原型里"工作"是假的 700ms。骨架的行高和真实结果一致，换回结果时布局不跳。
  const loading = (box, skeleton, done, work = 700) => {
    const start = Date.now();
    let shownAt = 0;
    box.setAttribute('aria-busy', 'true');
    const t = setTimeout(() => { shownAt = Date.now(); box.innerHTML = skeleton; }, 150);
    setTimeout(() => {
      clearTimeout(t);
      const wait = shownAt ? Math.max(0, 400 - (Date.now() - shownAt)) : 0;
      setTimeout(() => { box.removeAttribute('aria-busy'); done(Date.now() - start); }, wait);
    }, work);
  };

  return { loading, P, NOW, esc, html, raw, rel, md, clock, daysAgo, sourceName, dirName, job, fact, fresh, sight, STATUS, RUN,
    filter, FRESH_OPTIONS, freshText, TRIAGE, setTriage, undo, onTriage, counts, triageName, parse, go, reduced, markJD, jdMarks };
})();

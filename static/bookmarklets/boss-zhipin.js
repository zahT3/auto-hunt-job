// Ported from shuheng-mo/career-ops-china tools/bookmarklets/boss-zhipin.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// Changes for auto-hunt-job: posts to this app's local inbox with X-Inbox-Token, shows a 3 s toast instead of
// a blocking dialog, and trims raw_text so the request stays under the inbox size limit.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// Boss直聘（zhipin.com）专用 JD 捕获：处理反复制，并避免把侧栏推荐岗位的公司名当成当前岗位的公司。

(async function () {
  const INBOX_URL = '__INBOX_URL__';
  const INBOX_TOKEN = '__INBOX_TOKEN__';
  const BODY_LIMIT = 180000;

  const toast = (message, bad) => {
    const old = document.getElementById('__hunt_toast');
    if (old) old.remove();
    const el = document.createElement('div');
    el.id = '__hunt_toast';
    el.textContent = message;
    Object.assign(el.style, {
      position: 'fixed', right: '16px', bottom: '16px', zIndex: '2147483647', maxWidth: '320px',
      padding: '10px 14px', borderRadius: '6px', color: '#fff', background: bad ? '#a04841' : '#38634d',
      font: '14px/1.5 sans-serif', whiteSpace: 'pre-wrap', boxShadow: '0 2px 8px rgba(0,0,0,.3)',
    });
    (document.body || document.documentElement).appendChild(el);
    setTimeout(() => el.remove(), 3000);
  };

  const bytes = (text) => new TextEncoder().encode(text).length;

  const deliver = async (payload) => {
    const ex = payload.extracted;
    for (const key of Object.keys(ex)) {
      if (key !== 'raw_text' && typeof ex[key] === 'string') ex[key] = ex[key].slice(0, 2000);
    }
    ex.raw_text = String(ex.raw_text || '').slice(0, 100000);
    let body = JSON.stringify(payload);
    let size = bytes(body);
    while (size > BODY_LIMIT && ex.raw_text.length > 1000) {
      ex.raw_text = ex.raw_text.slice(0, Math.floor(ex.raw_text.length * BODY_LIMIT / size * 0.95));
      if (/[\uD800-\uDBFF]$/.test(ex.raw_text)) ex.raw_text = ex.raw_text.slice(0, -1);
      body = JSON.stringify(payload);
      size = bytes(body);
    }
    const title = ex.job_title || payload.page_title || '';
    try {
      const res = await fetch(INBOX_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Inbox-Token': INBOX_TOKEN },
        body,
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
      });
      let data = {};
      try { data = await res.json(); } catch {}
      if (res.ok && data.ok) toast((data.duplicate ? '工作台里已有这个岗位：' : '已发送到工作台：') + title);
      else if (res.status === 403) toast('令牌无效或已重置，请回到安装页重新拖一次书签。', true);
      else toast('工作台没有收下：' + (data.error || res.status), true);
    } catch (e) {
      toast('连不上本地工作台。请确认它在运行；若本站禁止向外发请求，或浏览器拦截了对本机的访问，这个书签在此页无法使用。', true);
    }
  };

  // === 1. 强力剥离 anti-copy（沿用旧版，稳定） ===
  const allEls = document.querySelectorAll('*');
  allEls.forEach((el) => {
    try {
      el.style.userSelect = 'auto';
      el.style.webkitUserSelect = 'auto';
      el.style.mozUserSelect = 'auto';
      if (el.oncopy) el.oncopy = null;
      if (el.oncontextmenu) el.oncontextmenu = null;
      if (el.onselectstart) el.onselectstart = null;
    } catch {}
  });
  ['copy', 'cut', 'contextmenu', 'selectstart', 'mousedown'].forEach((evt) => {
    document.addEventListener(evt, (e) => e.stopPropagation(), true);
  });

  // === 2. DOM 范围约束（针对 2026-04 company 错抽 bug） ===
  const PRIMARY_CONTAINERS = [
    '.job-banner',
    '.job-primary',
    '.info-primary',
    '.job-detail-box',
    '.job-container',
    '[class*="detail-primary"]',
    '[class*="job-detail"]:not([class*="recommend"]):not([class*="related"])',
  ];
  const EXCLUDE_SELECTORS = [
    '.sider', '.side-bar', '.recommend-list', '.recommend-jobs',
    '[class*="recommend"]', '[class*="related"]', '[class*="similar"]',
    '[class*="other-job"]', '.job-history', '.job-list',
    '.job-card',
  ];
  const EXCLUDE_SELECTOR_STR = EXCLUDE_SELECTORS.join(', ');

  const isInExcluded = (el) => {
    try { return !!el.closest(EXCLUDE_SELECTOR_STR); } catch { return false; }
  };

  const readText = (el) => {
    if (!el) return '';
    const txt = (el.innerText || el.textContent || '').trim();
    return txt;
  };

  // 先在主岗位容器内找；找不到再全局找但排除推荐位
  const pickScoped = (subSelectors) => {
    for (const container of PRIMARY_CONTAINERS) {
      const c = document.querySelector(container);
      if (!c || isInExcluded(c)) continue;
      for (const sel of subSelectors) {
        const el = c.querySelector(sel);
        const t = readText(el);
        if (t) return t;
      }
    }
    for (const sel of subSelectors) {
      const els = Array.from(document.querySelectorAll(sel));
      for (const el of els) {
        if (isInExcluded(el)) continue;
        const t = readText(el);
        if (t) return t;
      }
    }
    return '';
  };

  // === 3. 从 HR 签名段反推真实 company（最稳的兜底） ===
  const HR_TITLE_PATTERN = /(?:HR|人力|招聘|猎头|顾问|HRBP|经理|专员|研发HR|总监|BP|Manager|Recruiter|高级人力|助理)/i;
  const ACTIVITY_PATTERN = /(?:在线|刚刚活跃|本月活跃|近期活跃|[0-9]+\s*(?:分钟|小时|天)前活跃)/;

  const extractCompanyFromHR = () => {
    // 3a. 先找 class 含 boss/hr/author/publisher 的 DOM
    const hrDomSelectors = [
      '.boss-info', '.hr-info', '.job-author', '.job-publisher',
      '[class*="boss-name"]', '[class*="hr-card"]', '[class*="publisher"]', '[class*="recruiter"]',
      '[class*="op-info"]',
    ];
    for (const sel of hrDomSelectors) {
      const el = document.querySelector(sel);
      if (!el || isInExcluded(el)) continue;
      const txt = readText(el);
      // 格式 "HR名 [活跃] 公司名 · HR职位"
      // 拿 · 前的最后一段作为公司名
      const parts = txt.split('·').map((s) => s.trim());
      if (parts.length >= 2 && HR_TITLE_PATTERN.test(parts[parts.length - 1])) {
        // 前半段 = "HR名 [活跃] 公司名"，取末尾一个词组
        const pre = parts.slice(0, -1).join('·').trim();
        // 去掉活跃状态关键字
        let co = pre.replace(ACTIVITY_PATTERN, '').trim();
        // 去掉 HR 名字（通常是 2-4 字 + 女士/先生，或英文姓名）
        co = co.replace(/^[^\s]{2,10}(女士|先生|小姐)\s+/, '').trim();
        co = co.replace(/^[A-Z][a-z]+\s+[A-Z][a-z]+\s+/, '').trim();
        // 空格 split 后取最长的一段作为公司名（最稳的启发式）
        const tokens = co.split(/\s+/).filter(Boolean);
        if (tokens.length >= 1) {
          const longest = tokens.reduce((a, b) => (b.length > a.length ? b : a), '');
          if (longest.length >= 2) return longest;
        }
        if (co) return co;
      }
    }

    // 3b. 全 body innerText 正则兜底
    const bodyTxt = document.body.innerText;
    const pattern = new RegExp(
      String.raw`(?:^|\n)\s*[^\s\n·]{2,10}(?:\s+` + ACTIVITY_PATTERN.source + String.raw`)?\s+([^\s\n·]{2,40})\s*·\s*` + HR_TITLE_PATTERN.source,
      'm'
    );
    const m = bodyTxt.match(pattern);
    if (m && m[1]) return m[1].trim();
    return '';
  };

  // === 4. 字段抽取（company 走新逻辑，其他沿用旧版） ===
  const jobTitleRaw = pickScoped(['.job-name', '.name h1', '[class*="job-title"]', 'h1']);
  const salaryRaw = pickScoped(['.job-salary', '.salary', '[class*="salary"]']);
  const locationRaw = pickScoped(['.job-location', '.location-address', '[class*="location"]', '[class*="city"]']);
  const seniorityRaw = pickScoped(['.job-experience', '[class*="experience"]', '[class*="text-experience"]']);
  const descriptionRaw = pickScoped([
    '.job-detail-section',
    '.job-detail-content',
    '.job-sec-text',
    '.job-detail',
    '[class*="job-detail"]',
  ]);
  const requirementsRaw = pickScoped(['.job-tags', '[class*="job-keyword"]', '[class*="job-tag"]']);

  // company：主卡片优先 → HR 反推兜底
  let companyRaw = pickScoped([
    '.company-name', '.info-company .name', '.info-company a',
    '[class*="company-info"] .name', '[class*="company-info"] a',
    '.company-info-box .name',
  ]);
  const companyFromHR = extractCompanyFromHR();
  // 启发式校验：如果主卡片抽到的 company 看起来像推荐位（极短/含数字/明显异常）
  // 或者和 HR 反推结果差异很大，以 HR 为准
  const looksDubious = (c) => {
    if (!c) return true;
    if (c.length < 2 || c.length > 40) return true;
    // 如果主卡片和 HR 反推都有值且不一致，优先信 HR（因为 HR 更稳）
    return false;
  };
  let company = companyRaw;
  if (companyFromHR) {
    // 如果 HR 反推和主卡片不同，优先用 HR（HR 签名是权威）
    if (!companyRaw || companyFromHR !== companyRaw) {
      company = companyFromHR;
    }
  }
  if (!company || looksDubious(company)) company = companyRaw || companyFromHR || '';

  const extracted = {
    job_title: jobTitleRaw,
    company,
    company_from_card: companyRaw,
    company_from_hr: companyFromHR,
    salary: salaryRaw,
    location: locationRaw,
    seniority_experience: seniorityRaw,
    description: descriptionRaw,
    requirements: requirementsRaw,
  };

  const payload = {
    url: location.href,
    page_title: document.title,
    captured_at: new Date().toISOString(),
    platform: 'boss-zhipin',
    extracted: { ...extracted, raw_text: document.body.innerText.trim() },
  };

  await deliver(payload);
})();

// Ported from shuheng-mo/career-ops-china tools/bookmarklets/mokahr.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// Changes for auto-hunt-job: posts to this app's local inbox with X-Inbox-Token, shows a 3 s toast instead of
// a blocking dialog, and trims raw_text so the request stays under the inbox size limit.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// Mokahr 专用 JD 捕获（上游 v2）：解析 innerText 里的「职位信息」label-value 块，CSS 选择器只做兜底。

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

  document.querySelectorAll('*').forEach((el) => {
    try {
      el.style.userSelect = 'auto';
      el.style.webkitUserSelect = 'auto';
    } catch {}
  });

  let frameDoc = document;
  const mokahrFrame =
    document.querySelector('iframe[src*="mokahr.com"]') ||
    document.querySelector('iframe[src*="moka"]');
  if (mokahrFrame) {
    try {
      if (mokahrFrame.contentDocument) {
        frameDoc = mokahrFrame.contentDocument;
      }
    } catch {
      toast('Mokahr iframe 是跨域的，无法直接读取。请在新标签页打开 iframe 链接，再点书签。', true);
      return;
    }
  }

  const rawFull = (frameDoc.body || document.body).innerText.trim();

  // ---- 主策略：解析 "职位信息" label-value 块 ----
  // Mokahr 表格典型形状（label 重复 2 次 + 值一行）：
  //   职位信息
  //   职位名称
  //   职位名称
  //   Agent 数据策略工程师
  //   薪资范围 / 薪资范围 / -
  //   职位性质 / 职位性质 / 全职
  //   职能类型 / 职能类型 / 其他
  //   所属部门 / 所属部门 / DeepSeek
  //   工作地点 / 工作地点 / 浙江·杭州市 北京市
  //   发布日期 / 发布日期 / 2026-04-17
  const FIELDS = ['职位名称', '薪资范围', '职位性质', '职能类型', '所属部门', '工作地点', '发布日期'];
  const parseInfoBlock = (text) => {
    const idx = text.indexOf('职位信息');
    if (idx < 0) return {};
    const tail = text.slice(idx).split('\n').map((s) => s.trim()).filter(Boolean);
    const out = {};
    for (let i = 0; i < tail.length; i++) {
      const line = tail[i];
      if (!FIELDS.includes(line)) continue;
      let j = i + 1;
      while (j < tail.length && tail[j] === line) j++;
      const value = tail[j] && !FIELDS.includes(tail[j]) ? tail[j] : '';
      if (value && value !== '-') out[line] = value;
    }
    return out;
  };

  // ---- 备用：顶部 pipe 头（"全职|其他|DeepSeek|浙江·杭州市 北京市"） ----
  const parsePipeHeader = (text) => {
    const lines = text.split('\n').map((s) => s.trim()).filter(Boolean);
    const shareIdx = lines.indexOf('分享');
    if (shareIdx < 0) return {};
    for (let i = shareIdx + 1; i < Math.min(shareIdx + 5, lines.length); i++) {
      if (lines[i].includes('|')) {
        const [nature, func, dept, loc] = lines[i].split('|').map((s) => s.trim());
        return {
          职位性质: nature || '',
          职能类型: func || '',
          所属部门: dept || '',
          工作地点: loc || '',
        };
      }
    }
    return {};
  };

  // ---- 标题：取 "分享" 前一行，若是 "急"/"热招" tag 再往前一行 ----
  const TITLE_TAGS = ['急', '热招', '紧急', 'HOT', 'NEW'];
  const TITLE_BLACKLIST = ['职位列表', '社招职位', '校招&实习职位', '登录', '首页', '关于我们'];
  const parseTitle = (text) => {
    const lines = text.split('\n').map((s) => s.trim()).filter(Boolean);
    const shareIdx = lines.indexOf('分享');
    if (shareIdx < 1) return '';
    let t = lines[shareIdx - 1];
    if (TITLE_TAGS.includes(t) && shareIdx >= 2) t = lines[shareIdx - 2];
    if (TITLE_BLACKLIST.includes(t)) return '';
    return t;
  };

  // ---- 描述：取 "职位描述" 到 "职位信息" 之间 ----
  const parseDescription = (text) => {
    const start = text.indexOf('职位描述');
    const end = text.indexOf('职位信息');
    if (start < 0) return '';
    const slice = end > start ? text.slice(start, end) : text.slice(start);
    return slice.trim();
  };

  // ---- CSS fallback（旧 DOM 或未知租户仍可能命中）----
  const pickCss = (selectors) => {
    for (const sel of selectors) {
      const el = frameDoc.querySelector(sel);
      if (el) {
        const txt = (el.innerText || el.textContent || '').trim();
        if (txt) return txt;
      }
    }
    return '';
  };

  // ---- 租户→公司名 fallback（路径识别，不是 hostname）----
  const tenantCompany = (() => {
    const p = location.pathname;
    if (p.includes('high-flyer')) return 'DeepSeek';
    if (p.includes('moonshot')) return '月之暗面 Moonshot';
    if (p.includes('megviihr')) return '旷视';
    return '';
  })();

  const info = parseInfoBlock(rawFull);
  const header = parsePipeHeader(rawFull);
  const title = parseTitle(rawFull);
  const desc = parseDescription(rawFull);

  const extracted = {
    job_title:
      info['职位名称'] ||
      title ||
      pickCss(['.job-detail-title', '.position-name', '[class*="job-title"]', '[class*="position-title"]', 'h1', 'h2']),
    company:
      info['所属部门'] ||
      header['所属部门'] ||
      pickCss(['.company-name', '[class*="company"]', '.brand-name']) ||
      tenantCompany,
    location:
      info['工作地点'] ||
      header['工作地点'] ||
      pickCss(['.job-location', '[class*="location"]', '[class*="city"]']),
    salary: info['薪资范围'] || pickCss(['.salary', '[class*="salary"]']),
    job_type: info['职位性质'] || header['职位性质'] || '',
    function_category: info['职能类型'] || header['职能类型'] || '',
    published_at: info['发布日期'] || '',
    description:
      desc ||
      pickCss([
        '.job-detail-content',
        '.job-description',
        '.position-detail',
        '[class*="job-detail"]',
        '[class*="position-content"]',
        '[class*="content"]',
        '.job-content',
      ]),
  };

  const payload = {
    url: location.href,
    page_title: document.title,
    captured_at: new Date().toISOString(),
    platform: 'mokahr',
    extracted: { ...extracted, raw_text: rawFull },
  };

  await deliver(payload);
})();

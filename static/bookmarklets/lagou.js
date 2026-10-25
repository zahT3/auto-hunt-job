// Ported from shuheng-mo/career-ops-china tools/bookmarklets/lagou.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// Changes for auto-hunt-job: posts to this app's local inbox with X-Inbox-Token, shows a 3 s toast instead of
// a blocking dialog, and trims raw_text so the request stays under the inbox size limit.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// 拉勾（lagou.com）专用 JD 捕获：用户登录后 DOM 可读。

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
      if (el.oncopy) el.oncopy = null;
    } catch {}
  });
  ['copy', 'cut', 'contextmenu', 'selectstart'].forEach((evt) => {
    document.addEventListener(evt, (e) => e.stopPropagation(), true);
  });

  const bodyText = document.body.innerText || '';
  if (/请\s*登录|登录后|立即登录/.test(bodyText) && bodyText.length < 1200) {
    toast('拉勾要求登录。请先登录，刷新页面后再点书签。', true);
    return;
  }

  const pickText = (selectors) => {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) {
        const txt = (el.innerText || el.textContent || '').trim();
        if (txt.length > 0) return txt;
      }
    }
    return '';
  };

  const extracted = {
    job_title: pickText(['.job-name .name', '.position-head h1', '[class*="position-content"] h1', 'h1']),
    company: pickText(['.company .name', '.company_name', '[class*="company-info"] .name']),
    salary: pickText(['.salary', '[class*="salary"]', '.job_request .salary']),
    location: pickText(['.work_addr', '[class*="work-addr"]', '[class*="location"]']),
    description: pickText([
      '.job-detail',
      '#job_detail',
      '.job_bt',
      '[class*="job-detail"]',
      '[class*="job-description"]',
    ]),
    requirements: pickText(['.position-label', '[class*="position-tag"]', '[class*="job-keyword"]']),
  };

  const payload = {
    url: location.href,
    page_title: document.title,
    captured_at: new Date().toISOString(),
    platform: 'lagou',
    extracted: { ...extracted, raw_text: document.body.innerText.trim() },
  };

  await deliver(payload);
})();

// Ported from shuheng-mo/career-ops-china tools/bookmarklets/universal.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// Changes for auto-hunt-job: posts to this app's local inbox with X-Inbox-Token, shows a 3 s toast instead of
// a blocking dialog, and trims raw_text so the request stays under the inbox size limit.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// 通用 JD 捕获，适用于多数站点；不适用于 iframe 内嵌的 ATS（用 mokahr.js）和微信公众号。

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

  const stripAntiCopy = () => {
    document.querySelectorAll('*').forEach((el) => {
      try {
        el.style.userSelect = 'auto';
        el.style.webkitUserSelect = 'auto';
        if (el.oncopy) el.oncopy = null;
        if (el.oncontextmenu) el.oncontextmenu = null;
      } catch {}
    });
    ['copy', 'cut', 'contextmenu', 'selectstart'].forEach((evt) => {
      document.addEventListener(evt, (e) => e.stopPropagation(), true);
    });
  };
  stripAntiCopy();

  // Try common JD container selectors first; fallback to body.
  const SELECTORS = [
    '[class*="job-detail"]', '[class*="position-detail"]', '[class*="jd-content"]',
    '[class*="job-content"]', '[class*="job-description"]', '[class*="job-info"]',
    '[class*="position-content"]', '[class*="detail-content"]', '[class*="job-desc"]',
    '[class*="recruitDetail"]', '[class*="positionDetail"]',
    'main', 'article', '#main', '#content', '.content',
  ];

  let main = null;
  let bestLen = 0;
  for (const sel of SELECTORS) {
    const els = document.querySelectorAll(sel);
    for (const el of els) {
      const len = (el.innerText || '').trim().length;
      if (len > bestLen && len > 200) {
        main = el;
        bestLen = len;
      }
    }
  }
  if (!main) main = document.body;

  // Best-effort structured extraction
  const text = main.innerText.trim();
  const titleGuess =
    document.querySelector('h1')?.innerText ||
    document.querySelector('[class*="title"]')?.innerText ||
    document.title;

  const payload = {
    url: location.href,
    page_title: document.title,
    captured_at: new Date().toISOString(),
    platform: 'universal',
    extracted: {
      job_title: (titleGuess || '').trim().slice(0, 200),
      raw_text: text,
    },
  };

  await deliver(payload);
})();

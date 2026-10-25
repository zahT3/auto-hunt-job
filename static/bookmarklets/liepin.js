// Ported from shuheng-mo/career-ops-china tools/bookmarklets/liepin.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// Changes for auto-hunt-job: posts to this app's local inbox with X-Inbox-Token, shows a 3 s toast instead of
// a blocking dialog, and trims raw_text so the request stays under the inbox size limit.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// 猎聘（liepin.com）专用 JD 捕获：部分详情页有反复制和登录墙。

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

  // 强剥 anti-copy
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

  // 检测登录墙
  const bodyText = document.body.innerText || '';
  if (/请\s*登录|登录后查看|立即登录|登录\s*并\s*查看/.test(bodyText) && bodyText.length < 1500) {
    toast('猎聘要求登录后才能看完整 JD。请先登录，刷新页面后再点书签。', true);
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
    job_title: pickText([
      '.title-info h1', '.job-title-wrap h1',
      '[class*="job-title-name"]', '[class*="title-info"] h1', 'h1',
    ]),
    company: pickText([
      '.company-info-container .name', '[class*="company-name"]',
      '.company-name a', '[class*="company-info"] .name',
    ]),
    salary: pickText(['.job-item-title .salary', '[class*="salary"]', '.salary']),
    location: pickText(['.basic-infor span:first-child', '[class*="job-place"]', '[class*="location"]']),
    description: pickText([
      '.job-intro-content', '.job-describe-content', '.content.content-word',
      '[class*="job-describe"]', '[class*="job-intro"]', '[class*="job-detail"]',
    ]),
    requirements: pickText(['.job-item-list', '[class*="tag-list"]', '[class*="labels"]']),
  };

  // 2026-10 改版后 h1 / 地点选择器都失效了，但页面标题仍是
  // 「【城市 岗位名招聘】-公司城市招聘信息-猎聘」
  const titleMatch = document.title.match(/^【(\S+)\s+(.+?)招聘】/);
  if (titleMatch) {
    if (!extracted.location) extracted.location = titleMatch[1];
    if (!extracted.job_title) extracted.job_title = titleMatch[2];
  }

  const payload = {
    url: location.href,
    page_title: document.title,
    captured_at: new Date().toISOString(),
    platform: 'liepin',
    extracted: { ...extracted, raw_text: document.body.innerText.trim() },
  };

  await deliver(payload);
})();

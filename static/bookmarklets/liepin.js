// Ported from shuheng-mo/career-ops-china tools/bookmarklets/liepin.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// Changes for auto-hunt-job: posts to this app's local inbox with X-Inbox-Token, shows a 3 s toast instead of
// a blocking dialog, and trims raw_text so the request stays under the inbox size limit.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// 猎聘（liepin.com）专用 JD 捕获：部分详情页有反复制和登录墙。

(async function () {
  // @deliver

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

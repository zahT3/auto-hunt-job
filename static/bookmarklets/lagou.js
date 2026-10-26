// Ported from shuheng-mo/career-ops-china tools/bookmarklets/lagou.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// Changes for auto-hunt-job: posts to this app's local inbox with X-Inbox-Token, shows a 3 s toast instead of
// a blocking dialog, and trims raw_text so the request stays under the inbox size limit.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// 拉勾（lagou.com）专用 JD 捕获：用户登录后 DOM 可读。

(async function () {
  // @deliver

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

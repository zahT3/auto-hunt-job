// Ported from shuheng-mo/career-ops-china tools/bookmarklets/universal.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// Changes for auto-hunt-job: posts to this app's local inbox with X-Inbox-Token, shows a 3 s toast instead of
// a blocking dialog, and trims raw_text so the request stays under the inbox size limit.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// 通用 JD 捕获，适用于多数站点；不适用于 iframe 内嵌的 ATS（用 mokahr.js）和微信公众号。

(async function () {
  // @deliver

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
  // The first h1 is often a share dialog or banner, so structured data and the page title decide first.
  const jobPostingTitle = () => {
    const find = (node) => {
      if (!node || typeof node !== 'object') return '';
      if (Array.isArray(node)) {
        for (const item of node) {
          const found = find(item);
          if (found) return found;
        }
        return '';
      }
      if ([].concat(node['@type'] || []).includes('JobPosting') && typeof node.title === 'string' && node.title.trim()) {
        return node.title.trim();
      }
      return find(node['@graph']);
    };
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const found = find(JSON.parse(script.textContent));
        if (found) return found;
      } catch {}
    }
    return '';
  };
  const DIALOGS = '[class*="share"], [class*="popover"], [class*="modal"], [class*="dialog"], [role="dialog"]';
  const usableHeadings = (root) =>
    Array.from(root.querySelectorAll('h1'))
      .filter((h) => (h.innerText || '').trim() && h.getClientRects().length > 0 && !h.closest(DIALOGS))
      .map((h) => h.innerText.trim());
  const headingInTitle = () => usableHeadings(document).find((t) => (document.title || '').includes(t)) || '';
  const titleGuess =
    jobPostingTitle() ||
    (document.querySelector('meta[property="og:title"]')?.content || '').trim() ||
    (main !== document.body ? usableHeadings(main)[0] : '') ||
    headingInTitle() ||
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

// Delivery half of every bookmarklet: toast, size fitting, POST to the local inbox. hunt/bookmarklets.py splices this
// file into each script at its "// @deliver" line, so a built bookmarklet is self-contained.
// The fetch/payload shape is adapted from shuheng-mo/career-ops-china tools/bookmarklets/*.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.

const INBOX_URL = '__INBOX_URL__';
const INBOX_TOKEN = '__INBOX_TOKEN__';
const BODY_LIMIT = 180000;

const toast = (message, bad, ms = 3000) => {
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
  setTimeout(() => el.remove(), ms);
};

const bytes = (text) => new TextEncoder().encode(text).length;

const UNREACHABLE = '连不上本地工作台。请确认它在运行；若本站禁止向外发请求，或浏览器拦截了对本机的访问，这个书签在此页无法使用。';
const TOKEN_BAD = '令牌无效或已重置，请回到安装页重新拖一次书签。';

// Fits one payload under the inbox limit and POSTs it; throws when the inbox cannot be reached.
const post = async (payload) => {
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
  const res = await fetch(INBOX_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Inbox-Token': INBOX_TOKEN },
    body,
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
  });
  let data = {};
  try { data = await res.json(); } catch {}
  return { res, data };
};

const deliver = async (payload) => {
  let reply;
  try { reply = await post(payload); } catch (e) { toast(UNREACHABLE, true); return; }
  const { res, data } = reply;
  const title = payload.extracted.job_title || payload.page_title || '';
  if (res.ok && data.ok) toast((data.duplicate ? '工作台里已有这个岗位：' : '已发送到工作台：') + title);
  else if (res.status === 403) toast(TOKEN_BAD, true);
  else toast('工作台没有收下：' + (data.error || res.status), true);
};

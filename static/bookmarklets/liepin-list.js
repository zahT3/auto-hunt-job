// Written for auto-hunt-job; only the spliced-in delivery code (_deliver.js) derives from career-ops-china.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// 猎聘（liepin.com）搜索结果页：把本页每张岗位卡片作为一条摘要发进收件箱。之后你自己翻页（点「下一页」或页码），
// 新出现的卡片会自动送过去；书签不点击、不翻页、不轮询，只在页面自己换了内容时读一次。再点一次书签就停，关掉页面也停。
// 卡片里没有职位描述；之后在岗位详情页点「猎聘」书签，会落到同一个岗位链接上，用完整 JD 替换这段摘要。

(async function () {
  // @deliver

  // How long the listing must stay still after a change before it is read: a page's cards arrive over a few frames.
  const SETTLE = 600;

  const running = globalThis.__huntLiepinRun;
  if (running) {
    running.stop();
    return;
  }

  const text = (el) => (el ? (el.innerText || el.textContent || '').trim() : '');
  // The query carries per-visit search state (skId, ckId, index...); the inbox keys the job on origin + path.
  const jobUrl = (card) => {
    for (const a of card.querySelectorAll('a[href]')) {
      try {
        const u = new URL(a.href, location.href);
        if (/(^|\.)liepin\.com$/.test(u.hostname) && /^\/(?:job|a)\/\d+\.shtml$/.test(u.pathname)) return { link: a, url: u.origin + u.pathname };
      } catch {}
    }
    return null;
  };
  const cards = () => Array.from(document.querySelectorAll('.jobCardPcContainer'));
  // What identifies the listing on screen: the active page number plus the job links, so a re-render is noticed.
  const marker = () => text(document.querySelector('.ant-pagination-item-active')) + '|' +
    cards().map((card) => (jobUrl(card) || {}).url || '').join(',');

  const seen = new Set();
  const collect = () => {
    const items = [];
    for (const card of cards()) {
      const found = jobUrl(card);
      const box = card.querySelector('.jobTitleBox');
      const title = text(box && box.querySelector('.ellipsis-1'));
      if (!found || !title || seen.has(found.url)) continue;
      seen.add(found.url);
      // The recruiter box (name, online status) is left out on purpose: only the job and company parts are sent.
      const head = text(found.link);
      items.push({
        url: found.url,
        page_title: document.title,
        captured_at: new Date().toISOString(),
        platform: 'liepin',
        summary_only: true,
        extracted: {
          job_title: title,
          company: text(card.querySelector('.companyName')),
          salary: (head.match(/\d+(?:\.\d+)?-\d+(?:\.\d+)?[kK万](?:·\d+薪)?|薪资面议|面议/) || [''])[0],
          location: (text(box).match(/【\s*([^】]+?)\s*】/) || ['', ''])[1],
          raw_text: ['猎聘搜索结果卡片，不含完整职位描述。', head, text(card.querySelector('[data-nick="job-detail-company-info"]'))]
            .filter(Boolean).join('\n'),
        },
      });
    }
    return items;
  };
  const total = { added: 0, known: 0, failed: 0, pages: 0 };
  const summary = () => total.pages + ' 页 ' + (total.added + total.known + total.failed) + ' 个岗位：新增 ' + total.added +
    '，工作台已有 ' + total.known + (total.failed ? '，没收下 ' + total.failed : '');
  let observer = null, timer = null, last = '', sending = false, again = false, ended = false;

  const finish = (message, bad) => {
    if (ended) return;
    ended = true;
    if (observer) observer.disconnect();
    if (timer) clearTimeout(timer);
    globalThis.__huntLiepinRun = null;
    toast(message, bad, 8000);
  };

  // Send the cards not sent yet. Returns false when the run has to end (token rejected, inbox gone).
  const send = async () => {
    const items = collect();
    if (!items.length) return true;
    total.pages += 1;
    toast('第 ' + total.pages + ' 页：正在发送 ' + items.length + ' 个岗位…');
    for (const item of items) {
      let reply;
      try { reply = await post(item); } catch (e) {
        finish((total.added + total.known ? '已发送 ' + (total.added + total.known) + ' 个后中断。' : '') + UNREACHABLE, true);
        return false;
      }
      if (reply.res.status === 403) { finish(TOKEN_BAD, true); return false; }
      if (reply.res.ok && reply.data.ok) reply.data.duplicate ? total.known++ : total.added++;
      else total.failed++;
    }
    return true;
  };

  // The page replaced its listing (the user turned the page): read it once it has settled.
  const changed = async () => {
    timer = null;
    if (ended) return;
    if (sending) { again = true; return; }
    const now = marker();
    if (!cards().length || now === last) return;
    last = now;
    sending = true;
    try {
      if (!(await send())) return;
      if (!ended) toast('已收下 ' + summary() + '。\n继续翻页会自动收下；再点一次书签停止。', total.failed > 0, 5000);
    } catch (e) {
      finish('出错停下（已发送 ' + (total.added + total.known) + ' 个）：' + (e && e.message ? e.message : e), true);
    } finally {
      sending = false;
      if (again && !ended) { again = false; changed(); }
    }
  };

  if (!cards().length) {
    toast('这页没有找到猎聘岗位卡片。请在猎聘搜索结果页使用；岗位详情页请用「猎聘」书签。', true);
    return;
  }
  globalThis.__huntLiepinRun = { stop: () => finish('已停止。本次共 ' + summary() + '。', total.failed > 0) };
  await changed();
  if (ended) return;
  observer = new MutationObserver(() => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(changed, SETTLE);
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();

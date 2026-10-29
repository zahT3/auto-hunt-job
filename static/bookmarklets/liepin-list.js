// Written for auto-hunt-job; only the spliced-in delivery code (_deliver.js) derives from career-ops-china.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// 猎聘（liepin.com）搜索结果页：把本页每张岗位卡片作为一条摘要发进收件箱，然后点「下一页」继续，一直到最后一页。
// 卡片里没有职位描述；之后在岗位详情页点「猎聘」书签，会落到同一个岗位链接上，用完整 JD 替换这段摘要。
// 翻页中再点一次书签就停下。

(async function () {
  // @deliver

  // Only a safety net against a pager that never ends; a normal run stops at the last page well before this.
  const MAX_PAGES = 50;
  // Seconds of pause between pages, so the run moves at a reader's pace rather than as fast as the site answers.
  const PAUSE_MIN = 3, PAUSE_MAX = 6;
  const WAIT_TRIES = 50, WAIT_STEP = 300;

  if (globalThis.__huntLiepinRun) {
    globalThis.__huntLiepinRun.stop = true;
    toast('收到，翻完当前这一页就停。');
    return;
  }
  const run = (globalThis.__huntLiepinRun = { stop: false });

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
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
  const nextButton = () => {
    const li = document.querySelector('li.ant-pagination-next');
    if (!li || li.getAttribute('aria-disabled') === 'true' || /\bant-pagination-disabled\b/.test(li.className || '')) return null;
    return li.querySelector('button') || li;
  };

  const total = { added: 0, known: 0, failed: 0, pages: 0 };
  const summary = () => total.pages + ' 页 ' + (total.added + total.known + total.failed) + ' 个岗位：新增 ' + total.added +
    '，工作台已有 ' + total.known + (total.failed ? '，没收下 ' + total.failed : '');
  let ending = '';
  try {
    if (!cards().length) {
      toast('这页没有找到猎聘岗位卡片。请在猎聘搜索结果页使用；岗位详情页请用「猎聘」书签。', true);
      return;
    }
    while (true) {
      const items = collect();
      total.pages += 1;
      toast('第 ' + total.pages + ' 页：正在发送 ' + items.length + ' 个岗位…');
      for (const item of items) {
        let reply;
        try { reply = await post(item); } catch (e) {
          toast((total.added + total.known ? '已发送 ' + (total.added + total.known) + ' 个后中断。' : '') + UNREACHABLE, true, 8000);
          return;
        }
        if (reply.res.status === 403) { toast(TOKEN_BAD, true, 8000); return; }
        if (reply.res.ok && reply.data.ok) reply.data.duplicate ? total.known++ : total.added++;
        else total.failed++;
      }
      if (run.stop) { ending = '按你的要求停在第 ' + total.pages + ' 页。'; break; }
      if (total.pages >= MAX_PAGES) { ending = '已到安全上限 ' + MAX_PAGES + ' 页。'; break; }
      const next = nextButton();
      if (!next) { ending = '已是最后一页。'; break; }
      toast(summary() + '。\n稍等几秒翻到第 ' + (total.pages + 1) + ' 页；再点一次书签可停下。');
      await sleep((PAUSE_MIN + Math.random() * (PAUSE_MAX - PAUSE_MIN)) * 1000);
      if (run.stop) { ending = '按你的要求停在第 ' + total.pages + ' 页。'; break; }
      const before = marker();
      next.click();
      let changed = false;
      for (let i = 0; i < WAIT_TRIES && !changed; i++) {
        await sleep(WAIT_STEP);
        changed = cards().length > 0 && marker() !== before;
      }
      if (!changed) { ending = '点了「下一页」但列表没有变化，已停下。可能要验证或页面改版，请看一眼页面。'; break; }
      // Cards of one page can arrive over a few frames.
      await sleep(500);
    }
    toast('本次共 ' + summary() + '。' + ending, total.failed > 0 || ending.startsWith('点了'), 8000);
  } catch (e) {
    toast('出错停下（已发送 ' + (total.added + total.known) + ' 个）：' + (e && e.message ? e.message : e), true, 8000);
  } finally {
    globalThis.__huntLiepinRun = null;
  }
})();

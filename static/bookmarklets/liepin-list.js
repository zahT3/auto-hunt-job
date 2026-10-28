// Written for auto-hunt-job; only the spliced-in delivery code (_deliver.js) derives from career-ops-china.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// 猎聘（liepin.com）搜索结果页：一次把本页每张岗位卡片作为一条摘要发进收件箱。卡片里没有职位描述；
// 之后在岗位详情页点「猎聘」书签，会落到同一个岗位链接上，用完整 JD 替换这段摘要。

(async function () {
  // @deliver

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

  const seen = new Set();
  const items = [];
  for (const card of document.querySelectorAll('.jobCardPcContainer')) {
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
  if (!items.length) {
    toast('这页没有找到猎聘岗位卡片。请在猎聘搜索结果页使用；岗位详情页请用「猎聘」书签。', true);
    return;
  }

  toast('正在发送本页 ' + items.length + ' 个岗位…');
  let added = 0, known = 0, failed = 0;
  for (const item of items) {
    let reply;
    try { reply = await post(item); } catch (e) {
      toast((added + known ? '已发送 ' + (added + known) + ' 个后中断。' : '') + UNREACHABLE, true);
      return;
    }
    if (reply.res.status === 403) { toast(TOKEN_BAD, true); return; }
    if (reply.res.ok && reply.data.ok) reply.data.duplicate ? known++ : added++;
    else failed++;
  }
  toast('本页 ' + items.length + ' 个岗位：新增 ' + added + '，工作台已有 ' + known + (failed ? '，没收下 ' + failed : '') + '。', failed > 0);
})();

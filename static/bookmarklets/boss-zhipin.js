// Ported from shuheng-mo/career-ops-china tools/bookmarklets/boss-zhipin.js
// (https://github.com/shuheng-mo/career-ops-china, commit bef1e7122d2d84a0bf7137a9d5ffb88808d05c5c, MIT License).
// Changes for auto-hunt-job: posts to this app's local inbox with X-Inbox-Token, shows a 3 s toast instead of
// a blocking dialog, and trims raw_text so the request stays under the inbox size limit.
// __INBOX_URL__ and __INBOX_TOKEN__ are filled in when the install page is rendered; they are never committed.
// The page-data path below (reading jobs from BOSS's own Vue 2 components) is written for auto-hunt-job. Its idea,
// the list selector and the jobList / jobDetail property names come from Ocyss/boss-helper
// (https://github.com/Ocyss/boss-helper, MIT License); no code is copied from it.
// Boss直聘（zhipin.com）专用 JD 捕获：
// 1. 列表页：读页面组件自己的 jobList，把整页岗位作为"仅列表信息"发进收件箱（没有职位描述）。
// 2. 同一次点击给 jobDetail 和 jobList 挂上 setter：之后你自己点开哪个岗位、自己翻到哪一页，就把那份数据发过去。
//    书签不点击、不翻页、不轮询，不请求 BOSS 的接口，不读 cookie；关掉页面后钩子随页面消失。
// 3. 读不到页面数据、字段对不上或出错时，退回页面文字抽取：处理反复制，并避免把侧栏推荐岗位的公司名当成当前岗位的公司。

(async function () {
  // @deliver

  const LIST_SELECTOR = '#wrap .page-job-wrapper,.job-recommend-main,.page-jobs-main';
  const PLATFORM = 'boss-zhipin';
  const str = (v) => (typeof v === 'string' ? v.trim() : '');
  const strings = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []);
  const flag = (v) => (v === 1 || v === true ? 1 : 0);
  const stamp = (v) => (typeof v === 'number' || typeof v === 'string' ? v : null);
  const origin = /(^|\.)zhipin\.com$/.test(location.hostname) ? location.origin : 'https://www.zhipin.com';
  // A list card and the detail of the same job must land on one inbox record, so both use the canonical job URL.
  const jobUrl = (id) => origin + '/job_detail/' + encodeURIComponent(id) + '.html';
  const validItem = (it) => !!it && typeof it === 'object' && str(it.encryptJobId) !== '' && str(it.jobName) !== '';

  const listComponent = () => {
    for (const el of document.querySelectorAll(LIST_SELECTOR)) if (el.__vue__) return el.__vue__;
    return null;
  };

  // Only the job and its company. The recruiter's name, title and online status are never put in a payload.
  const fromItem = (it) => ({
    url: jobUrl(it.encryptJobId),
    page_title: document.title,
    captured_at: new Date().toISOString(),
    platform: PLATFORM,
    summary_only: true,
    structured: {
      brandName: str(it.brandName), salaryDesc: str(it.salaryDesc), skills: strings(it.skills),
      jobExperience: str(it.jobExperience), jobDegree: str(it.jobDegree), cityName: str(it.cityName),
      goldHunter: flag(it.goldHunter), lastModifyTime: stamp(it.lastModifyTime),
    },
    extracted: {
      job_title: str(it.jobName),
      company: str(it.brandName),
      salary: str(it.salaryDesc),
      location: [str(it.cityName), str(it.areaDistrict), str(it.businessDistrict)].filter(Boolean).join('·'),
      seniority_experience: [str(it.jobExperience), str(it.jobDegree)].filter(Boolean).join(' · '),
      raw_text: ['BOSS 直聘列表信息，不含职位描述。', str(it.jobName), str(it.brandName), str(it.salaryDesc),
        [str(it.cityName), str(it.areaDistrict)].filter(Boolean).join(' '), str(it.jobExperience), str(it.jobDegree),
        strings(it.skills).join('、')].filter(Boolean).join('\n'),
    },
  });

  // List items seen on this page, keyed by lid and securityId, so a detail can be matched to its card.
  const seen = new Map();
  const remember = (list) => {
    for (const it of list) for (const key of [str(it.lid), str(it.securityId)]) if (key) seen.set(key, it);
  };

  // A detail is used only when it carries its own description and a job id (its own, or its card's).
  const fromDetail = (d) => {
    const info = d && d.jobInfo;
    if (!info || str(info.postDescription) === '' || str(info.jobName) === '') return null;
    const item = seen.get(str(d.lid)) || seen.get(str(d.securityId)) || null;
    const id = str(info.encryptId) || str(info.encryptJobId) || (item ? str(item.encryptJobId) : '');
    if (!id) return null;
    const brand = (d.brandComInfo && str(d.brandComInfo.brandName)) || (item ? str(item.brandName) : '');
    return {
      url: jobUrl(id),
      page_title: document.title,
      captured_at: new Date().toISOString(),
      platform: PLATFORM,
      structured: {
        brandName: brand, salaryDesc: str(info.salaryDesc),
        skills: strings(info.showSkills).length ? strings(info.showSkills) : strings(item && item.skills),
        jobExperience: str(info.experienceName), jobDegree: str(info.degreeName), cityName: str(info.locationName),
        goldHunter: flag(item && item.goldHunter), bossActiveTimeDesc: d.bossInfo ? str(d.bossInfo.activeTimeDesc) : '',
        lastModifyTime: stamp(item && item.lastModifyTime),
      },
      extracted: {
        job_title: str(info.jobName),
        company: brand,
        salary: str(info.salaryDesc),
        location: str(info.locationName),
        seniority_experience: [str(info.experienceName), str(info.degreeName)].filter(Boolean).join(' · '),
        raw_text: str(info.postDescription),
      },
    };
  };

  const sendAll = async (payloads) => {
    const tally = { added: 0, known: 0, failed: 0 };
    for (const p of payloads) {
      const { res, data } = await post(p);
      if (res.status === 403) throw Object.assign(new Error('token'), { token: true });
      if (res.ok && data.ok) data.duplicate ? tally.known++ : tally.added++;
      else tally.failed++;
    }
    return tally;
  };
  const report = async (payloads, describe) => {
    let tally;
    try { tally = await sendAll(payloads); } catch (e) { toast(e && e.token ? TOKEN_BAD : UNREACHABLE, true); return; }
    toast(describe(tally), tally.failed > 0, 6000);
  };
  const listMessage = (n) => (t) => '本页 ' + n + ' 个岗位（仅列表信息，不含职位描述）：新增 ' + t.added + '，工作台已有 ' + t.known +
    (t.failed ? '，没收下 ' + t.failed : '') + '。之后你自己点开的岗位会补上详情。';
  const detailMessage = (title) => (t) => (t.failed ? '工作台没有收下：' : '已发送岗位详情：') + title;

  // Wraps a reactive property's setter on the component: the page's own assignment runs first, then the new value is read.
  const hook = (vm, key, onSet) => {
    let owner = vm;
    let desc = null;
    while (owner && !(desc = Object.getOwnPropertyDescriptor(owner, key))) owner = Object.getPrototypeOf(owner);
    if (!desc || typeof desc.get !== 'function' || typeof desc.set !== 'function' || !desc.configurable) throw new Error('no setter for ' + key);
    Object.defineProperty(vm, key, {
      configurable: true,
      enumerable: desc.enumerable,
      get() { return desc.get.call(this); },
      set(value) {
        desc.set.call(this, value);
        try { onSet(value); } catch (e) { toast('读这份岗位数据时出错，已跳过。', true); }
      },
    });
  };

  // Returns false when the page data cannot be used, so the caller falls back to the page text.
  const fromPage = async () => {
    const vm = listComponent();
    if (!vm) return false;
    const list = vm.jobList;
    if (!Array.isArray(list) || !list.length || !list.every(validItem)) return false;
    remember(list);
    if (!vm.__huntHooked) {
      const sent = new Set();
      const onDetail = (d) => {
        const p = fromDetail(d);
        if (!p || sent.has(p.url + '#' + p.extracted.raw_text.length)) return;
        sent.add(p.url + '#' + p.extracted.raw_text.length);
        report([p], detailMessage(p.extracted.job_title));
      };
      hook(vm, 'jobDetail', onDetail);
      hook(vm, 'jobList', (next) => {
        if (!Array.isArray(next) || !next.length || !next.every(validItem)) return;
        remember(next);
        report(next.map(fromItem), listMessage(next.length));
      });
      Object.defineProperty(vm, '__huntHooked', { value: onDetail });
    }
    await report(list.map(fromItem), listMessage(list.length));
    // A job the user had already opened before clicking the bookmarklet is sent too.
    vm.__huntHooked(vm.jobDetail);
    return true;
  };

  const fromText = async () => {
    // === 1. 强力剥离 anti-copy（沿用旧版，稳定） ===
    const allEls = document.querySelectorAll('*');
    allEls.forEach((el) => {
      try {
        el.style.userSelect = 'auto';
        el.style.webkitUserSelect = 'auto';
        el.style.mozUserSelect = 'auto';
        if (el.oncopy) el.oncopy = null;
        if (el.oncontextmenu) el.oncontextmenu = null;
        if (el.onselectstart) el.onselectstart = null;
      } catch {}
    });
    ['copy', 'cut', 'contextmenu', 'selectstart'].forEach((evt) => {
      document.addEventListener(evt, (e) => e.stopPropagation(), true);
    });

    // === 2. DOM 范围约束（针对 2026-04 company 错抽 bug） ===
    const PRIMARY_CONTAINERS = [
      '.job-banner',
      '.job-primary',
      '.info-primary',
      '.job-detail-box',
      '.job-container',
      '[class*="detail-primary"]',
      '[class*="job-detail"]:not([class*="recommend"]):not([class*="related"])',
    ];
    const EXCLUDE_SELECTORS = [
      '.sider', '.side-bar', '.recommend-list', '.recommend-jobs',
      '[class*="recommend"]', '[class*="related"]', '[class*="similar"]',
      '[class*="other-job"]', '.job-history', '.job-list',
      '.job-card',
    ];
    const EXCLUDE_SELECTOR_STR = EXCLUDE_SELECTORS.join(', ');

    const isInExcluded = (el) => {
      try { return !!el.closest(EXCLUDE_SELECTOR_STR); } catch { return false; }
    };

    const readText = (el) => {
      if (!el) return '';
      const txt = (el.innerText || el.textContent || '').trim();
      return txt;
    };

    // 先在主岗位容器内找；找不到再全局找但排除推荐位
    const pickScoped = (subSelectors) => {
      for (const container of PRIMARY_CONTAINERS) {
        const c = document.querySelector(container);
        if (!c || isInExcluded(c)) continue;
        for (const sel of subSelectors) {
          const el = c.querySelector(sel);
          const t = readText(el);
          if (t) return t;
        }
      }
      for (const sel of subSelectors) {
        const els = Array.from(document.querySelectorAll(sel));
        for (const el of els) {
          if (isInExcluded(el)) continue;
          const t = readText(el);
          if (t) return t;
        }
      }
      return '';
    };

    // === 3. 从 HR 签名段反推真实 company（最稳的兜底） ===
    const HR_TITLE_PATTERN = /(?:HR|人力|招聘|猎头|顾问|HRBP|经理|专员|研发HR|总监|BP|Manager|Recruiter|高级人力|助理)/i;
    const ACTIVITY_PATTERN = /(?:在线|刚刚活跃|本月活跃|近期活跃|[0-9]+\s*(?:分钟|小时|天)前活跃)/;

    const extractCompanyFromHR = () => {
      // 3a. 先找 class 含 boss/hr/author/publisher 的 DOM
      const hrDomSelectors = [
        '.boss-info', '.hr-info', '.job-author', '.job-publisher',
        '[class*="boss-name"]', '[class*="hr-card"]', '[class*="publisher"]', '[class*="recruiter"]',
        '[class*="op-info"]',
      ];
      for (const sel of hrDomSelectors) {
        const el = document.querySelector(sel);
        if (!el || isInExcluded(el)) continue;
        const txt = readText(el);
        // 格式 "HR名 [活跃] 公司名 · HR职位"
        // 拿 · 前的最后一段作为公司名
        const parts = txt.split('·').map((s) => s.trim());
        if (parts.length >= 2 && HR_TITLE_PATTERN.test(parts[parts.length - 1])) {
          // 前半段 = "HR名 [活跃] 公司名"，取末尾一个词组
          const pre = parts.slice(0, -1).join('·').trim();
          // 去掉活跃状态关键字
          let co = pre.replace(ACTIVITY_PATTERN, '').trim();
          // 去掉 HR 名字（通常是 2-4 字 + 女士/先生，或英文姓名）
          co = co.replace(/^[^\s]{2,10}(女士|先生|小姐)\s+/, '').trim();
          co = co.replace(/^[A-Z][a-z]+\s+[A-Z][a-z]+\s+/, '').trim();
          // 空格 split 后取最长的一段作为公司名（最稳的启发式）
          const tokens = co.split(/\s+/).filter(Boolean);
          if (tokens.length >= 1) {
            const longest = tokens.reduce((a, b) => (b.length > a.length ? b : a), '');
            if (longest.length >= 2) return longest;
          }
          if (co) return co;
        }
      }

      // 3b. 全 body innerText 正则兜底
      const bodyTxt = document.body.innerText;
      const pattern = new RegExp(
        String.raw`(?:^|\n)\s*[^\s\n·]{2,10}(?:\s+` + ACTIVITY_PATTERN.source + String.raw`)?\s+([^\s\n·]{2,40})\s*·\s*` + HR_TITLE_PATTERN.source,
        'm'
      );
      const m = bodyTxt.match(pattern);
      if (m && m[1]) return m[1].trim();
      return '';
    };

    // === 4. 字段抽取（company 走新逻辑，其他沿用旧版） ===
    const jobTitleRaw = pickScoped(['.job-name', '.name h1', '[class*="job-title"]', 'h1']);
    const salaryRaw = pickScoped(['.job-salary', '.salary', '[class*="salary"]']);
    const locationRaw = pickScoped(['.job-location', '.location-address', '[class*="location"]', '[class*="city"]']);
    const seniorityRaw = pickScoped(['.job-experience', '[class*="experience"]', '[class*="text-experience"]']);
    const descriptionRaw = pickScoped([
      '.job-detail-section',
      '.job-detail-content',
      '.job-sec-text',
      '.job-detail',
      '[class*="job-detail"]',
    ]);
    const requirementsRaw = pickScoped(['.job-tags', '[class*="job-keyword"]', '[class*="job-tag"]']);

    // company：主卡片优先 → HR 反推兜底
    let companyRaw = pickScoped([
      '.company-name', '.info-company .name', '.info-company a',
      '[class*="company-info"] .name', '[class*="company-info"] a',
      '.company-info-box .name',
    ]);
    const companyFromHR = extractCompanyFromHR();
    // 启发式校验：如果主卡片抽到的 company 看起来像推荐位（极短/含数字/明显异常）
    // 或者和 HR 反推结果差异很大，以 HR 为准
    const looksDubious = (c) => {
      if (!c) return true;
      if (c.length < 2 || c.length > 40) return true;
      // 如果主卡片和 HR 反推都有值且不一致，优先信 HR（因为 HR 更稳）
      return false;
    };
    let company = companyRaw;
    if (companyFromHR) {
      // 如果 HR 反推和主卡片不同，优先用 HR（HR 签名是权威）
      if (!companyRaw || companyFromHR !== companyRaw) {
        company = companyFromHR;
      }
    }
    if (!company || looksDubious(company)) company = companyRaw || companyFromHR || '';

    const extracted = {
      job_title: jobTitleRaw,
      company,
      company_from_card: companyRaw,
      company_from_hr: companyFromHR,
      salary: salaryRaw,
      location: locationRaw,
      seniority_experience: seniorityRaw,
      description: descriptionRaw,
      requirements: requirementsRaw,
    };

    const payload = {
      url: location.href,
      page_title: document.title,
      captured_at: new Date().toISOString(),
      platform: 'boss-zhipin',
      extracted: { ...extracted, raw_text: document.body.innerText.trim() },
    };

    const reply = await post(payload).catch(() => null);
    if (!reply) { toast(UNREACHABLE, true); return; }
    const { res, data } = reply;
    if (res.status === 403) { toast(TOKEN_BAD, true); return; }
    const title = payload.extracted.job_title || payload.page_title || '';
    if (res.ok && data.ok) toast('已改用页面文字读取。' + (data.duplicate ? '工作台里已有这个岗位：' : '已发送到工作台：') + title, false, 6000);
    else toast('已改用页面文字读取。工作台没有收下：' + (data.error || res.status), true, 6000);
  };

  let used = false;
  try { used = await fromPage(); } catch (e) { used = false; }
  if (!used) await fromText();
})();

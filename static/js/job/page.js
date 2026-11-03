// 岗位详情 (#/job/<id>): the ATS three steps side by side, then the JD paragraph by paragraph with margin notes.
import { $, $$, esc, items, motionBehavior, replaceContent } from "../shared/dom.js";
import { sourceName } from "../shared/names.js";
import { state } from "../shared/state.js";
import { clock, freshness, monthDay, sourceState } from "../shared/time.js";
import { factChip, mark, stateWord } from "../shared/ui.js";
import { groupOfJob } from "../search/page.js";
import { postedLine, salaryOf } from "../search/model.js";
import { go, registerPage, route, setReturnTarget } from "../shell/router.js";
import { jobById } from "../triage/actions.js";
import { showJob } from "../workbench/queue.js";
import { cachedMatch, loadMatch, matchMayUseModel } from "./match.js";

const HARD_KIND = {
  education: "学历",
  years: "年限",
  language: "语言",
  certificate: "证书",
  location: "地点",
  remote: "远程",
};
const HARD = { met: ["ok", "符合"], not_met: ["bad", "不符合"], unknown: ["unknown", "不知道"] };
const COVERAGE = {
  explicit: ["ok", "有原词"],
  related: ["near", "相近说法"],
  absent: ["bad", "没有"],
};
const GLYPH = { ok: "✓", bad: "✗", unknown: "？", near: "～" };
const HEADING =
  /^(岗位职责|工作职责|职位描述|岗位描述|任职要求|岗位要求|任职资格|加分项|工作地点|我们提供|福利待遇)[:：]?$/;

const groups = new Map();
const loading = new Set();

const hardOf = (r) => HARD[r.status] || HARD.unknown;
const evidenceTone = (r) =>
  items(r.fact_ids).length ? "ok" : items(r.related_fact_ids).length ? "near" : "bad";
const evidenceLabel = (r) =>
  items(r.fact_ids).length
    ? "有事实"
    : items(r.related_fact_ids).length
      ? "只有相近事实"
      : "没有事实";
const hardRequirement = (r) =>
  r.kind === "remote" ? (r.requirement ? "可以全远程" : "不能全远程") : r.requirement;

// Marks in the JD text: keyword coverage as highlighter, hard conditions and evidence as underlines.
// Longer quotes are marked first and marks never nest.
export function marksFor(m) {
  const out = [];
  const seen = new Set();
  const add = (text, cls) => {
    if (text && !seen.has(text)) {
      seen.add(text);
      out.push({ text, cls });
    }
  };
  items(m.keywords).forEach((k) => add(k.jd_evidence, "kw-" + k.coverage));
  items(m.hard).forEach((r) => add(r.jd_evidence, hardOf(r)[0]));
  items(m.evidence).forEach((r) => {
    const tone = evidenceTone(r);
    add(r.jd_evidence, tone === "near" ? "unknown" : tone);
  });
  return out;
}

export function markText(text, marks) {
  const segs = [{ s: esc(text), marked: false }];
  for (const mk of [...marks].sort((a, b) => b.text.length - a.text.length)) {
    const t = esc(mk.text);
    for (let i = 0; i < segs.length; i++) {
      const at = segs[i].marked ? -1 : segs[i].s.indexOf(t);
      if (at < 0) continue;
      segs.splice(
        i,
        1,
        { s: segs[i].s.slice(0, at), marked: false },
        { s: `<mark class="ev ev-${esc(mk.cls)}" data-m="${t}">${t}</mark>`, marked: true },
        { s: segs[i].s.slice(at + t.length), marked: false },
      );
      break;
    }
  }
  return segs.map((x) => x.s).join("");
}

// The notes beside a paragraph: hard conditions, evidence and non-explicit keywords whose quote is in it.
export function notesFor(m, para) {
  const out = [];
  for (const r of items(m.hard))
    if (r.jd_evidence && para.includes(r.jd_evidence))
      out.push({
        tone: hardOf(r)[0],
        text: `${HARD_KIND[r.kind] || r.kind}：${hardOf(r)[1]}${r.why ? "。" + r.why : ""}`,
        facts: items(r.fact_ids),
      });
  for (const r of items(m.evidence))
    if (r.jd_evidence && para.includes(r.jd_evidence))
      out.push({
        tone: evidenceTone(r),
        text: `${r.requirement}：${evidenceLabel(r)}`,
        facts: items(r.fact_ids).length ? items(r.fact_ids) : items(r.related_fact_ids),
      });
  for (const k of items(m.keywords))
    if (k.coverage !== "explicit" && k.jd_evidence && para.includes(k.jd_evidence) && k.why)
      out.push({
        tone: (COVERAGE[k.coverage] || COVERAGE.absent)[0],
        text: `「${k.keyword}」${(COVERAGE[k.coverage] || COVERAGE.absent)[1]}。${k.why}`,
        facts: items(k.related_fact_ids),
      });
  return out;
}

const noteHtml = (x) =>
  `<p class="note-m"><span class="mk ${esc(x.tone)}" aria-hidden="true">${GLYPH[x.tone] || ""}</span>${esc(x.text)}` +
  `${x.facts.length ? `<span class="sub">依据 ${x.facts.map(factChip).join("")}</span>` : ""}</p>`;

const count = (rows, test) => `${items(rows).filter(test).length} / ${items(rows).length}`;

export function verdictHtml(m) {
  const hard = items(m.hard)
    .map(
      (r) =>
        `<li><span>${esc(HARD_KIND[r.kind] || r.kind)}：${esc(hardRequirement(r))}${items(r.fact_ids).map(factChip).join("")}</span>` +
        `${mark(...hardOf(r))}${r.why ? `<span class="why">${esc(r.why)}</span>` : ""}</li>`,
    )
    .join("");
  const keywords = items(m.keywords)
    .map((k) => {
      const [, label] = COVERAGE[k.coverage] || COVERAGE.absent;
      const tip = k.why || "依据 " + items(k.fact_ids).join("、");
      return (
        `<li data-c="${esc(k.coverage)}" tabindex="0" data-tip="${esc(tip)}"><span>${esc(k.keyword)}</span>` +
        `<span class="t">${esc(k.coverage === "explicit" ? items(k.fact_ids).join(" ") : label)}</span></li>`
      );
    })
    .join("");
  const evidence = items(m.evidence)
    .map((r) => {
      const facts = items(r.fact_ids).length ? items(r.fact_ids) : items(r.related_fact_ids);
      return (
        `<li><span>${esc(r.requirement)}${facts.map(factChip).join("")}` +
        `${r.jd_evidence ? `<button class="locate" type="button" data-loc="${esc(r.jd_evidence)}">定位原文</button>` : ""}</span>` +
        `${mark(evidenceTone(r), evidenceLabel(r))}</li>`
      );
    })
    .join("");
  const empty = (rows, text) => (items(rows).length ? "" : `<p class="note">${text}</p>`);
  return (
    `<div class="verdict" aria-label="匹配解释">` +
    `<section aria-labelledby="v1"><p class="step"><span id="v1">第 1 步 硬条件</span><span>招聘系统先按这些筛人</span></p>` +
    `<p class="score">${count(m.hard, (r) => r.status === "met")}</p><ul>${hard}</ul>${empty(m.hard, "原文里没有硬条件。")}</section>` +
    `<section aria-labelledby="v2"><p class="step"><span id="v2">第 2 步 关键词覆盖</span><span>再看简历里有没有原词</span></p>` +
    `<p class="score">${count(m.keywords, (k) => k.coverage === "explicit")}</p><ul class="kwchips">${keywords}</ul>${empty(m.keywords, "原文里没认出技能关键词。")}` +
    `<p class="legend"><span><span class="hl">黄底</span> 有原词</span><span><mark class="ev ev-kw-related">虚线</mark> 只有相近说法</span>` +
    `<span><mark class="ev ev-kw-absent">波浪线</mark> 没有</span></p></section>` +
    `<section aria-labelledby="v3"><p class="step"><span id="v3">第 3 步 事实证据</span><span>最后才有人读</span></p>` +
    `<p class="score">${count(m.evidence, (r) => items(r.fact_ids).length)}</p><ul>${evidence}</ul>` +
    `<p class="note">${esc(m.notice || "")}${m.notice ? "。" : ""}</p></section></div>`
  );
}

function headNote(m) {
  const facts = items(state?.candidate?.facts);
  const pending = facts.filter((f) => f.status !== "confirmed");
  return (
    `<p class="note-m">只用了 ${facts.length - pending.length} 条已确认的事实。` +
    `${pending.length ? `${esc(pending.map((f) => f.id).join("、"))} 还没确认，没有拿来对照。` : ""}` +
    `<span class="sub">${esc(m.extract_note || "")}${pending.length ? '；<button type="button" class="linkish" data-open-candidate>去确认</button>' : ""}</span></p>`
  );
}

export function jdHtml(job, m) {
  if (!job.jd) return '<p class="sub">这一组还没有抓到 JD 原文。</p>';
  const marks = m ? marksFor(m) : [];
  let n = 0;
  return String(job.jd)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((p) => {
      if (HEADING.test(p)) return `<h3 class="jd-h">${esc(p)}</h3>`;
      n += 1;
      const notes = m ? notesFor(m, p) : [];
      return (
        `<div class="para with-margin"><p><span class="num" aria-hidden="true">${n}</span>${markText(p, marks)}</p>` +
        `<div class="notes">${notes.map(noteHtml).join("")}</div></div>`
      );
    })
    .join("");
}

export function structureHtml(s) {
  const one = (x, show) =>
    x
      ? `${esc(show(x.value))}<span class="src">「${esc(x.evidence)}」</span>`
      : '<span class="none">原文没提</span>';
  const many = (list) =>
    items(list).length
      ? items(list)
          .map((x) => `${esc(x.value)}<span class="src">「${esc(x.evidence)}」</span>`)
          .join("")
      : '<span class="none">原文没提</span>';
  const years = (v) => `${v.min ?? 0}–${v.max == null ? "不限" : v.max} 年`;
  return (
    `<dl class="struct">` +
    `<dt>年限</dt><dd>${one(s.years, years)}</dd>` +
    `<dt>学历</dt><dd>${one(s.education, (v) => v)}</dd>` +
    `<dt>远程</dt><dd>${one(s.remote, (v) => (v ? "可以全远程" : "不能全远程"))}</dd>` +
    [
      ["硬技能", "hard_skills"],
      ["软技能", "soft_skills"],
      ["语言", "languages"],
      ["证书", "certificates"],
      ["加分项", "bonus"],
      ["地点", "location"],
    ]
      .map(([t, k]) => `<dt>${t}</dt><dd>${many(s[k])}</dd>`)
      .join("") +
    `</dl>`
  );
}

function sourcesHtml(g, job) {
  const rows = g
    ? items(g.sources).map((s) => {
        const x = sourceState(s);
        return (
          `<tr><td>${esc(sourceName(s.source))}</td><td>${stateWord(x.tone, x.label)}</td>` +
          `<td>${esc(monthDay(s.first_seen))}</td><td>${esc(monthDay(s.last_seen))} ${esc(clock(s.last_seen))}</td>` +
          `<td>${s.posted_at ? `来源写的发布日期 ${esc(monthDay(s.posted_at))}；` : ""}${esc(s.salary || "")} ${esc(s.location || "")}` +
          `${s.url ? ` <a href="${esc(safeLink(s.url))}" target="_blank" rel="noopener noreferrer">原文</a>` : ""}</td></tr>`
        );
      })
    : [
        `<tr><td>${esc(sourceName(job.channel))}</td><td>${stateWord("muted", "本机库状态未读到")}</td><td colspan="3">这条岗位不在当前搜索结果里；回到搜索页能看到它的来源记录。</td></tr>`,
      ];
  return (
    `<table class="srcs"><thead><tr><th>来源</th><th>状态</th><th>首次搜到</th><th>最近搜到</th><th>说明</th></tr></thead>` +
    `<tbody>${rows.join("")}</tbody></table>`
  );
}

const safeLink = (v) => {
  try {
    const u = new URL(v);
    return ["http:", "https:"].includes(u.protocol) ? u.href : "#";
  } catch {
    return "#";
  }
};

export function jobPageHtml(job, g, m) {
  const f = g ? freshness(g) : null;
  const posted = g ? postedLine(g) : "";
  const salary = g ? salaryOf(g) : job.salary || "薪资没写";
  const matchPart = m
    ? verdictHtml(m)
    : loading.has(job.id)
      ? '<div class="empty flush" aria-busy="true"><h2>正在对照…</h2><p>按招聘系统的顺序对照已确认的简历事实。</p></div>'
      : `<div class="empty flush"><h2>这个岗位还没做匹配解释</h2><p>对照只用规则，不发送内容；还没有 JD 结构时会先抽取，` +
        `${matchMayUseModel() ? `按「岗位原文」的同意会调用 ${esc(state.ai.consent?.host || "模型服务")}。` : "现在没有同意或密钥，只用本地规则。"}</p>` +
        `<button class="btn btn-primary" type="button" data-act="job-match">做匹配解释</button></div>`;
  return (
    `<article class="detail">` +
    `<a class="back" href="#/search" data-act="back">返回搜索结果（Esc）</a>` +
    `<header class="d-head"><div><h1>${esc(job.title || "岗位名称待确认")}</h1>` +
    `<p class="sub">${esc(job.company || "公司待确认")}，${esc(job.location || g?.city || "地点未知")}，${esc(salary)}</p>` +
    (f
      ? `<p class="fresh">${stateWord(f.tone, f.label)}<span class="d">${esc(f.detail)}</span></p>`
      : "") +
    (posted ? `<p class="posted">${esc(posted)}</p>` : "") +
    `</div>${m ? headNote(m) : ""}</header>` +
    matchPart +
    `<div class="sec-h"><h2>原文与批注</h2><span class="tally">${m ? (m.structure_by === "ai" ? "JD 结构由 AI 抽取；批注只引用已确认事实" : "JD 结构由本地规则抽取") : "还没有批注"}</span></div>` +
    `<div class="jd">${jdHtml(job, m)}</div>` +
    (m?.structure
      ? `<div class="sec-h"><h2>结构化结果</h2><span class="tally">每项后面是原文依据</span></div>${structureHtml(m.structure)}`
      : "") +
    `<div class="sec-h"><h2>来源记录</h2><span class="tally">同一公司、同一标题、同一城市的记录合成一组</span></div>` +
    sourcesHtml(g, job) +
    `<div class="sec-h"><h2>材料与投递</h2><span class="tally">冻结的工作台功能，做法不变</span></div>` +
    `<p class="small-note">审核、材料包、执行和入口核验仍在工作台里做；对外操作要逐项授权。</p>` +
    `<div class="actions"><button class="btn" type="button" data-act="open-workbench" data-job="${esc(job.id)}">在工作台打开这个岗位</button></div>` +
    `</article>`
  );
}

async function findGroup(job) {
  if (groups.has(job.id) || !job.title) return;
  const known = groupOfJob(job.id);
  if (known) {
    groups.set(job.id, known);
    return;
  }
  try {
    const r = await fetch("/api/search?" + new URLSearchParams({ q: job.title, limit: "50" }), {
      cache: "no-store",
    });
    const data = await r.json();
    const g = items(data.groups).find((x) => items(x.sources).some((s) => s.job_id === job.id));
    groups.set(job.id, g || null);
  } catch {
    groups.set(job.id, null);
  }
  if (route().page === "job" && route().id === job.id) renderJob(job.id);
}

async function runMatch(id) {
  if (loading.has(id)) return;
  loading.add(id);
  renderJob(id);
  await loadMatch(id);
  loading.delete(id);
  if (route().page === "job" && route().id === id) renderJob(id);
}

export function renderJob(id) {
  const job = jobById(id);
  if (!job) {
    replaceContent(
      "#view",
      `<div class="page empty"><h1>找不到这个岗位</h1><p>本机岗位库里没有 ${esc(id || "")}。</p><a href="#/search">返回搜索</a></div>`,
    );
    return;
  }
  replaceContent("#view", jobPageHtml(job, groups.get(id) || groupOfJob(id), cachedMatch(id)));
}

function back() {
  const g = groups.get(route().id) || groupOfJob(route().id);
  if (g) setReturnTarget(`#g-${CSS.escape(g.group)}`);
  go("search");
}

registerPage("job", {
  title: "岗位详情",
  enter(id) {
    const job = jobById(id);
    if (!job) return;
    findGroup(job);
    if (!cachedMatch(id) && !matchMayUseModel()) runMatch(id);
  },
  render: renderJob,
  currentJob() {
    return jobById(route().id);
  },
  escape() {
    back();
    return true;
  },
});

document.addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]");
  if (act?.dataset.act === "back") {
    e.preventDefault();
    back();
    return;
  }
  if (act?.dataset.act === "open-workbench") {
    setReturnTarget("#detail-title");
    showJob(act.dataset.job);
    go("workbench");
    return;
  }
  if (act?.dataset.act === "job-match") {
    runMatch(route().id);
    return;
  }
  const loc = e.target.closest("[data-loc]");
  if (loc) {
    const marks = $$("mark.ev");
    // A quote may sit inside a longer marked quote, since marks never nest.
    const target =
      marks.find((x) => x.dataset.m === loc.dataset.loc) ||
      marks.find((x) => x.dataset.m.includes(loc.dataset.loc));
    for (const x of $$("mark.ev.on")) x.classList.remove("on");
    if (target) {
      target.classList.add("on");
      target.scrollIntoView({ block: "center", behavior: motionBehavior() });
    }
  }
});

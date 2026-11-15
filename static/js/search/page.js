// 搜索（首页）: searchQuery box, filters, the sentence that says what is shown, the searchData groups and a preview.
import { $, $$, esc, items, replaceContent } from "../shared/dom.js";
import { directionName, sourceName } from "../shared/names.js";
import { state } from "../shared/state.js";
import { freshness, relative, sourceState } from "../shared/time.js";
import { toast } from "../shared/feedback.js";
import { addHideRule, hideRules, loadHideRules } from "../shared/hide.js";
import { kbd, stateWord } from "../shared/ui.js";
import { cachedMatch, matchCounts } from "../job/match.js";
import { go, registerPage, route, setReturnTarget } from "../shell/router.js";
import { choiceLabel, jobById } from "../triage/actions.js";
import {
  defaultQuery,
  filterOptions,
  hiddenByRules,
  hiddenText,
  hideRuleText,
  hideValue,
  leadJobId,
  optionText,
  postedLine,
  salaryActive,
  salaryBounds,
  salaryNotes,
  salaryOf,
  salaryPhrase,
  searchParams,
  sentenceParts,
} from "./model.js";

export const searchQuery = defaultQuery();
let searchData = null;
let heldBack = 0;
let searchError = null;
let selectedGroup = null;
let searchSeq = 0;
let seenRun = null;

export function searchResult() {
  return searchData;
}

export function groupById(id) {
  return items(searchData?.groups).find((g) => g.group === id) || null;
}

// The group a job belongs to, from the current results; null when the job is not among them.
export function groupOfJob(jobId) {
  return (
    items(searchData?.groups).find((g) => items(g.sources).some((s) => s.job_id === jobId)) || null
  );
}

async function getJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  const data = await r.json();
  if (!r.ok || data.error)
    throw new Error(typeof data.error === "string" ? data.error : "搜索未完成。");
  return data;
}

// Shows the skeleton only if the work takes over 150ms, then keeps it at least 400ms (DESIGN.md §5).
export async function runSearch() {
  const id = ++searchSeq;
  let shownAt = 0;
  const box = $("#results");
  box?.setAttribute("aria-busy", "true");
  const timer = setTimeout(() => {
    shownAt = Date.now();
    if (id === searchSeq && $("#results")) $("#results").innerHTML = skeleton();
  }, 150);
  try {
    const main = await getJson("/api/search?" + searchParams(searchQuery));
    // Groups the time filter holds back are counted, so the sentence can say how many and offer to show them.
    const wide = searchQuery.fresh
      ? await getJson("/api/search?" + searchParams(searchQuery, { withFresh: false }))
      : main;
    if (id !== searchSeq) return;
    searchData = main;
    heldBack = Math.max(0, (wide.total_groups || 0) - (main.total_groups || 0));
    searchError = null;
  } catch (e) {
    if (id !== searchSeq) return;
    searchData = null;
    searchError = e.message || "搜索未完成。";
  } finally {
    clearTimeout(timer);
  }
  const wait = shownAt ? Math.max(0, 400 - (Date.now() - shownAt)) : 0;
  if (wait) await new Promise((resolve) => setTimeout(resolve, wait));
  if (id !== searchSeq) return;
  $("#results")?.removeAttribute("aria-busy");
  if (route().page === "search") renderParts();
}

function skeleton() {
  const row =
    '<div class="group sk" aria-hidden="true"><span class="sk-line"></span><span class="sk-line w40"></span>' +
    '<span class="sk-line w60"></span><span class="sk-line w80"></span></div>';
  return row.repeat(4) + '<p class="vh">正在搜索…</p>';
}

function filterHtml(f) {
  const value = searchQuery[f.key];
  const radios = f.opts
    .map(
      ([v, t]) =>
        `<label><input type="radio" name="f-${f.key}" value="${esc(v ?? "")}" ${v === value ? "checked" : ""}> ${esc(t)}</label>`,
    )
    .join("");
  return (
    `<details class="filter" data-key="${f.key}"><summary><span class="k">${esc(f.label)}</span> ${esc(optionText(f, value))}</summary>` +
    `<div class="menu" role="group" aria-label="${esc(f.label)}">${radios}</div></details>`
  );
}

function salaryFilterHtml() {
  return (
    `<details class="filter" data-key="salary"><summary><span class="k">薪资</span> ${esc(salaryPhrase(searchQuery) || "不限")}</summary>` +
    `<div class="menu menu-pay" role="group" aria-label="薪资（月薪，元）">` +
    `<label for="sal-min">最低</label><input id="sal-min" type="text" inputmode="decimal" autocomplete="off" spellcheck="false" placeholder="15k" value="${esc(searchQuery.salaryMin)}">` +
    `<label for="sal-max">最高</label><input id="sal-max" type="text" inputmode="decimal" autocomplete="off" spellcheck="false" placeholder="1.5万" value="${esc(searchQuery.salaryMax)}">` +
    `<p class="pay-err" id="sal-err" role="alert" hidden></p>` +
    `<div class="pay-act"><button class="btn btn-primary" type="button" data-act="salary-apply">应用</button>` +
    `<button class="btn" type="button" data-act="salary-clear">清除</button></div></div></details>`
  );
}

// Under the sentence: what the salary filter left out or could not judge, and what the hide list holds back.
export function metaNotesHtml() {
  if (!searchData) return "";
  const parts = salaryNotes(searchQuery, searchData).map((n) => `<span>${esc(n)}</span>`);
  const n = searchData.hidden || 0;
  if (n && !searchQuery.includeHidden)
    parts.push(
      `<span>${esc(hiddenText(n))} · <button type="button" class="linkish" data-act="show-hidden">查看</button></span>`,
    );
  if (n && searchQuery.includeHidden)
    parts.push(
      `<span>下面包含被隐藏的 ${n} 条 · <button type="button" class="linkish" data-act="hide-hidden">重新隐藏</button></span>`,
    );
  return parts.join("");
}

function hideButtons(g, cls) {
  const id = esc(g.group);
  const one = (kind, text, value) =>
    value
      ? `<button type="button" class="${cls}" data-act="hide" data-kind="${kind}" data-id="${id}" aria-label="${esc(text)}：${esc(value)}">${text}</button>`
      : "";
  return one("company", "不想看这家公司", hideValue(g, "company")) + one("title", "不想看这个岗位名", hideValue(g, "title"));
}

function hiddenByHtml(g) {
  const ids = items(g.sources).flatMap((s) => items(s.hidden_by));
  if (!ids.length) return "";
  const named = hiddenByRules(g, hideRules).map(hideRuleText);
  return `<p class="hidden-by">已被不想看清单隐藏：${esc(named.join("；") || "规则已不在清单里")}</p>`;
}

export function sentenceHtml() {
  if (searchError) return `搜索没有完成：${esc(searchError)}`;
  if (!searchData) return "正在读取本机岗位库…";
  const p = sentenceParts(searchQuery, searchData, heldBack);
  const b = (v) => `<b>${esc(v)}</b>`;
  let s =
    `在 ${b(p.city)} 找 ${b(p.direction)}${p.words ? `，标题或 JD 含 ${b(p.words)}` : ""}，看 ${b(p.source)}，` +
    `${p.salary ? `${b(p.salary)}，` : ""}${esc(p.when)}：${p.records} 条记录合并成 ${p.groups} 组。`;
  if (p.total > p.groups) s += ` 只列出前 ${p.groups} 组，共 ${p.total} 组。`;
  if (p.hidden)
    s += ` 另有 ${p.hidden} 组已不在列表或超出时间范围，<button type="button" data-act="show-all">一起显示</button>`;
  return s;
}

export function groupHtml(g) {
  const f = freshness(g);
  const job = jobById(leadJobId(g));
  const posted = postedLine(g);
  const rows = items(g.sources)
    .map((s) => {
      const x = sourceState(s);
      return (
        `<span>${esc(sourceName(s.source))}</span>${stateWord(x.tone, x.label)}` +
        `<span>${esc(relative(s.first_seen))}</span><span>${esc(relative(s.last_seen))}</span>` +
        `<span class="note">${esc(s.matched ? s.salary || s.location || "" : "这条记录没命中检索词")}</span>`
      );
    })
    .join("");
  return (
    `<article class="group ${g.status === "closed" ? "closed" : "open"}${items(g.sources).some((s) => items(s.hidden_by).length) ? " is-hidden" : ""}" id="g-${esc(g.group)}" data-id="${esc(g.group)}" tabindex="-1" aria-selected="${selectedGroup === g.group}">` +
    `<div class="g-head"><a class="g-title" href="#/job/${esc(encodeURIComponent(leadJobId(g) || ""))}">${esc(g.title)}</a><span class="g-pay">${esc(salaryOf(g))}</span></div>` +
    `<p class="g-meta">${esc(g.company || "公司待确认")}，${esc(g.city || "地点未知")}，${esc(directionName(g.direction))}</p>` +
    `<p class="g-fresh">${stateWord(f.tone, f.label)}<span class="d">${esc(f.detail)}</span>` +
    `${job?.triage ? `<span class="tri-tag" data-v="${esc(job.triage)}">${esc(choiceLabel(job.triage))}</span>` : ""}</p>` +
    `${posted ? `<p class="posted">${esc(posted)}</p>` : ""}` +
    hiddenByHtml(g) +
    `<p class="g-tools">${hideButtons(g, "linkish")}</p>` +
    `<details class="sources" data-disclosure="src-${esc(g.group)}"><summary>${items(g.sources).length} 个来源` +
    items(g.sources)
      .map((s) => stateWord(sourceState(s).tone, sourceName(s.source)))
      .join("") +
    `</summary><div class="kv" role="table" aria-label="来源记录">` +
    `<span class="h">来源</span><span class="h">状态</span><span class="h">首次搜到</span><span class="h">最近搜到</span><span class="h">说明</span>` +
    `${rows}</div></details></article>`
  );
}

function matchSummaryHtml(jobId) {
  const m = cachedMatch(jobId);
  if (!m)
    return '<p class="sec-note">还没做匹配解释。打开详情后可以运行；对照只用规则，不发送内容。</p>';
  const c = matchCounts(m);
  return (
    `<div class="summary3">` +
    `<div><h3>第 1 步 硬条件</h3><p>${c.hard.met} 符合，${c.hard.notMet} 不符合，${c.hard.unknown} 不知道</p></div>` +
    `<div><h3>第 2 步 关键词覆盖</h3><p><span class="hl">${c.keywords.explicit}</span> / ${c.keywords.total} 有原词，${c.keywords.related} 相近</p></div>` +
    `<div><h3>第 3 步 事实证据</h3><p>${c.evidence.facts} / ${c.evidence.total} 有事实</p></div></div>`
  );
}

export function peekHtml(g) {
  if (!g)
    return '<div class="empty"><h2>选一组岗位</h2><p>用 J、K 或方向键在左边移动，按 Enter 打开详情。</p></div>';
  const f = freshness(g);
  const jobId = leadJobId(g);
  const job = jobById(jobId);
  const lines = String(job?.jd || "")
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 12)
    .slice(0, 2)
    .join("");
  return (
    `<h2>${esc(g.title)}</h2><p class="sub">${esc(g.company || "公司待确认")}，${esc(g.city || "地点未知")}，${esc(salaryOf(g))}</p>` +
    `<p class="g-fresh peek-fresh">${stateWord(f.tone, f.label)}<span class="d">${esc(f.detail)}</span></p>` +
    (lines
      ? `<p class="excerpt"><span class="from">JD 摘录（${esc(sourceName(items(g.sources)[0]?.source))}）</span>${esc(lines)}</p>`
      : '<p class="sub">这一组还没有抓到 JD 原文。</p>') +
    matchSummaryHtml(jobId) +
    hiddenByHtml(g) +
    `<div class="actions"><a class="btn btn-primary" href="#/job/${esc(encodeURIComponent(jobId || ""))}">打开详情 ${kbd("↵")}</a>` +
    `${hideButtons(g, "btn")}</div>`
  );
}

function emptyHtml() {
  if (searchError)
    return `<div class="empty"><h2>搜索没有完成</h2><p>${esc(searchError)}。本机服务返回了错误；检查条件后再搜一次。</p></div>`;
  const when = searchQuery.fresh
    ? optionText(filterOptions(searchQuery, [])[3], searchQuery.fresh) + "、"
    : "";
  const none = !state?.jobs?.length;
  return (
    `<div class="empty"><h2>没有符合这些条件的岗位</h2>` +
    `<p>${esc(when)}${esc(searchQuery.city || "所有城市")}里，本机岗位库没有找到${searchQuery.q.trim() ? `含「${esc(searchQuery.q.trim())}」的岗位` : ""}。` +
    `${none ? "岗位库还是空的：先定方向，再点「开始搜索」。" : "可以放宽时间，或者换个词再搜一次。"}</p>` +
    `${searchQuery.fresh && searchQuery.fresh < 30 ? '<button class="btn" type="button" data-act="widen">放宽到 30 天</button>' : ""}` +
    `${salaryActive(searchQuery) || searchQuery.knownOnly ? '<button class="btn" type="button" data-act="salary-clear">去掉薪资条件</button>' : ""}` +
    `${searchData?.hidden && !searchQuery.includeHidden ? `<button class="btn" type="button" data-act="show-hidden">${esc(hiddenText(searchData.hidden))} · 查看</button>` : ""}` +
    `${none ? '<a class="btn" href="#/orient">去定方向</a>' : ""}</div>`
  );
}

function shownGroups() {
  return items(searchData?.groups);
}

function renderParts() {
  const groups = shownGroups();
  if (!groups.some((g) => g.group === selectedGroup)) selectedGroup = groups[0]?.group || null;
  replaceContent(".sentence", sentenceHtml());
  replaceContent("#meta-notes", metaNotesHtml());
  const known = $("#known-only");
  if (known) known.checked = searchQuery.knownOnly;
  const pay = $('details.filter[data-key="salary"] summary');
  if (pay) pay.innerHTML = `<span class="k">薪资</span> ${esc(salaryPhrase(searchQuery) || "不限")}`;
  replaceContent(
    "#results",
    groups.length
      ? groups.map(groupHtml).join("")
      : searchData || searchError
        ? emptyHtml()
        : skeleton(),
  );
  replaceContent("#peek", peekHtml(groupById(selectedGroup)));
  for (const f of filterOptions(searchQuery, groups)) {
    const box = $(`details.filter[data-key="${f.key}"]`);
    if (box && !box.open && !box.contains(document.activeElement)) box.outerHTML = filterHtml(f);
  }
}

function mount() {
  $("#view").innerHTML =
    `<h1 class="vh" id="page-title" tabindex="-1">搜索岗位</h1><div class="search"><div class="search-left">` +
    `<form class="qbox" role="search" data-form="q">` +
    `<div class="qfield"><input id="q" type="search" value="${esc(searchQuery.q)}" placeholder="岗位、公司或技能，例如 Go 支付…" aria-label="搜索岗位" autocomplete="off">${kbd("/")}</div>` +
    `<div class="filters">${filterOptions(searchQuery, shownGroups()).map(filterHtml).join("")}${salaryFilterHtml()}</div>` +
    `<p class="sentence" aria-live="polite"></p>` +
    `<div class="resultmeta"><label class="chk"><input type="checkbox" id="known-only"${searchQuery.knownOnly ? " checked" : ""}> 只看写明薪资的</label><span id="meta-notes" aria-live="polite"></span></div>` +
    `<p class="apinote">只查本机岗位库；"在列表"是本机库的判断，不等于招聘方仍在招。</p></form>` +
    `<div class="results" id="results" aria-label="搜索结果"></div></div>` +
    `<section class="peek" id="peek" aria-label="岗位预览"></section></div>`;
  renderParts();
}

export function selectGroup(id, { focus = false } = {}) {
  selectedGroup = id;
  for (const row of $$(".group")) row.setAttribute("aria-selected", String(row.dataset.id === id));
  replaceContent("#peek", peekHtml(groupById(id)));
  const row = $(`#g-${CSS.escape(id)}`);
  if (focus && row) {
    row.focus();
    row.scrollIntoView?.({ block: "nearest" });
  }
  document.dispatchEvent(new CustomEvent("job-selection"));
}

let typingTimer = null;

function openSelected() {
  const jobId = leadJobId(groupById(selectedGroup) || {});
  if (!jobId) return;
  setReturnTarget(`#g-${CSS.escape(selectedGroup)}`);
  go("job/" + encodeURIComponent(jobId));
}

registerPage("search", {
  title: "搜索",
  enter() {
    if (!searchData && !searchError) runSearch();
    loadHideRules()
      .then(() => route().page === "search" && renderParts())
      .catch(() => {});
  },
  render() {
    if (!$("#view .search")) mount();
    // A finished run adds jobs to the library: search again once, quietly.
    const run = items(state?.runs)[0];
    const marker = run && !state.search_running ? run.id + (run.finished_at || "") : null;
    if (marker && marker !== seenRun) {
      if (seenRun !== null) runSearch();
      seenRun = marker;
    } else renderParts();
  },
  currentJob() {
    return jobById(leadJobId(groupById(selectedGroup) || {}));
  },
  move(step) {
    const rows = $$(".group[data-id]");
    const i = rows.findIndex((r) => r.dataset.id === selectedGroup);
    const next = rows[Math.max(0, Math.min(rows.length - 1, i + step))];
    if (next) selectGroup(next.dataset.id, { focus: true });
  },
  open: openSelected,
  escape(target) {
    if (target?.id !== "q") return false;
    target.blur();
    $(`#g-${CSS.escape(selectedGroup || "")}`)?.focus();
    return true;
  },
});

document.addEventListener("input", (e) => {
  if (e.target.id !== "q") return;
  searchQuery.q = e.target.value;
  clearTimeout(typingTimer);
  typingTimer = setTimeout(runSearch, 200);
});
document.addEventListener("submit", (e) => {
  if (e.target.dataset?.form !== "q") return;
  e.preventDefault();
  clearTimeout(typingTimer);
  runSearch();
});
document.addEventListener("change", (e) => {
  const name = e.target.name || "";
  if (!name.startsWith("f-")) return;
  const key = name.slice(2);
  const v = e.target.value;
  searchQuery[key] = v === "" ? null : key === "fresh" ? Number(v) : v;
  e.target.closest("details").open = false;
  e.target.closest("details").querySelector("summary").focus();
  runSearch();
});
function applySalary() {
  const next = { ...searchQuery, salaryMin: $("#sal-min").value, salaryMax: $("#sal-max").value };
  const err = $("#sal-err");
  const bad = salaryBounds(next).error;
  err.hidden = !bad;
  err.textContent = bad || "";
  for (const input of [$("#sal-min"), $("#sal-max")]) input.toggleAttribute("aria-invalid", !!bad);
  if (bad) return;
  searchQuery.salaryMin = next.salaryMin.trim();
  searchQuery.salaryMax = next.salaryMax.trim();
  const box = $('details.filter[data-key="salary"]');
  box.open = false;
  box.querySelector("summary").focus();
  runSearch();
}

async function hideGroup(button) {
  const g = groupById(button.dataset.id);
  const value = g && hideValue(g, button.dataset.kind);
  if (!value) return;
  try {
    const result = await addHideRule(button.dataset.kind, value);
    toast(`已加入不想看清单：${hideRuleText(result.rule)}。可以在设置里删除。`);
  } catch (e) {
    toast(e.message || "没有加入不想看清单。");
    return;
  }
  await runSearch();
  refocus();
}

// A button that vanished with the re-render takes focus with it: put it on the selected row instead.
function refocus() {
  if (!document.activeElement || document.activeElement === document.body)
    ($(`#g-${CSS.escape(selectedGroup || "")}`) || $("#page-title"))?.focus();
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !["sal-min", "sal-max"].includes(e.target.id)) return;
  e.preventDefault();
  applySalary();
});
document.addEventListener("change", (e) => {
  if (e.target.id !== "known-only") return;
  searchQuery.knownOnly = e.target.checked;
  runSearch();
});
document.addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "hide") {
    hideGroup(e.target.closest("[data-act]"));
    return;
  }
  if (act === "show-hidden" || act === "hide-hidden") {
    searchQuery.includeHidden = act === "show-hidden";
    runSearch().then(refocus);
    return;
  }
  if (act === "salary-apply") {
    applySalary();
    return;
  }
  if (act === "salary-clear") {
    searchQuery.salaryMin = searchQuery.salaryMax = "";
    searchQuery.knownOnly = false;
    for (const id of ["sal-min", "sal-max"]) if ($("#" + id)) $("#" + id).value = "";
    runSearch();
    return;
  }
  if (act === "show-all") {
    searchQuery.fresh = null;
    runSearch();
    return;
  }
  if (act === "widen") {
    searchQuery.fresh = 30;
    runSearch();
    return;
  }
  const title = e.target.closest(".g-title");
  if (title) {
    setReturnTarget(`#g-${CSS.escape(title.closest(".group").dataset.id)}`);
    return;
  }
  const row = e.target.closest(".group[data-id]");
  if (row && !e.target.closest("a, summary, button, .kv")) {
    selectGroup(row.dataset.id, { focus: true });
    // Phones have no preview pane: tapping a group opens its detail.
    if (matchMedia("(max-width: 760px)").matches) openSelected();
  }
  for (const d of $$("details.filter[open]")) if (!d.contains(e.target)) d.open = false;
});

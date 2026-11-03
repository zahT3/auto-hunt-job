// 分拣 (#/triage): tabs 待选 / 感兴趣 / 稍后 / 跳过 with totals, the list of the current tab, the selected row
// open with its explanation and actions. 1/2/3 choose (again to clear), U undoes, Tab / Shift+Tab switch tabs.
import { $, esc, items, replaceContent } from "../shared/dom.js";
import { state } from "../shared/state.js";
import { freshness, monthDay } from "../shared/time.js";
import { kbd, stateWord } from "../shared/ui.js";
import { groupOfJob } from "../search/page.js";
import { go, registerPage, route, setReturnTarget } from "../shell/router.js";
import { jobById, toggleTriage } from "./actions.js";
import { CHOICES, TABS, preparing, tabCounts, tabOf, triageLocked } from "./model.js";
import { prepareErrorNote } from "./view.js";

export let triageTab = "pending";
let triageSel = null;
let selIndex = 0;
// Groups of the whole library (no filters), so each row can say when it was first and last seen.
const library = new Map();

async function loadLibrary() {
  try {
    const r = await fetch("/api/search?limit=500", { cache: "no-store" });
    const data = await r.json();
    if (!r.ok || data.error) return;
    library.clear();
    for (const g of items(data.groups)) for (const s of items(g.sources)) library.set(s.job_id, g);
  } catch {
    return;
  }
  if (route().page === "triage") renderTriage();
}

export function tabJobs(tab = triageTab) {
  return items(state?.jobs).filter((j) => tabOf(j) === tab);
}

// The explanation line: the library's freshness when the job is in the current search results,
// otherwise only the collection date the job record carries.
export function explain(job) {
  const g = library.get(job.id) || groupOfJob(job.id);
  if (g) {
    const f = freshness(g);
    return {
      tone: f.tone,
      label: f.label,
      detail: `${f.detail}；${items(g.sources).length} 个来源`,
    };
  }
  return {
    tone: "muted",
    label: "搜到时间不明",
    detail: job.collected_at ? `本机收集于 ${monthDay(job.collected_at)}` : "本机没有记下收集时间",
  };
}

export function itemHtml(job) {
  const x = explain(job);
  const on = triageSel === job.id;
  const status = preparing(job)
    ? '<p class="small-note" role="status">正在后台准备材料，准备好后到工作台审核。</p>'
    : "";
  const actions = triageLocked(job)
    ? '<p class="small-note">已锁定，不能改选择。</p>'
    : CHOICES.filter(([v]) => v !== triageTab)
        .map(
          ([v, t]) =>
            `<button class="btn" type="button" data-tri="${v}">${t} ${kbd(String(CHOICES.findIndex(([c]) => c === v) + 1))}</button>`,
        )
        .join("");
  return (
    `<div class="titem" role="option" id="t-${esc(job.id)}" data-tid="${esc(job.id)}" tabindex="-1" aria-selected="${on}">` +
    `<div><p class="t">${esc(job.title || "岗位名称待确认")}</p><p class="m">${esc(job.company || "公司待确认")}，${esc(job.location || "地点未知")}，${esc(job.salary || "薪资没写")}</p></div>` +
    `<div class="right">${stateWord(x.tone, x.label)}</div>` +
    `<div class="more"><p class="g-fresh"><span class="d">${esc(x.detail)}</span></p>${status}${prepareErrorNote(job)}` +
    `<div class="acts">${actions}<a class="btn" href="#/job/${esc(encodeURIComponent(job.id))}" data-open-job-page>打开详情 ${kbd("↵")}</a></div></div></div>`
  );
}

function triageEmptyHtml() {
  const pending = triageTab === "pending";
  return (
    `<div class="empty"><h2>${pending ? "待选清空了" : "这一组是空的"}</h2>` +
    `<p>${pending ? "下一轮搜索后，新搜到的岗位会出现在这里。" : "在待选里按对应的数字键（1 感兴趣，2 稍后，3 跳过），岗位会移到这里。"}</p>` +
    `${pending ? '<a class="btn" href="#/search">去搜索</a>' : ""}</div>`
  );
}

export function triageHtml() {
  const counts = tabCounts(state?.jobs);
  const list = tabJobs();
  if (!list.some((j) => j.id === triageSel))
    triageSel = list[Math.min(selIndex, list.length - 1)]?.id || null;
  const label = TABS.find(([k]) => k === triageTab)[1];
  return (
    `<div class="page"><header class="page-h"><h1 id="page-title" tabindex="-1">分拣</h1>` +
    `<p>每个岗位分到 感兴趣、稍后、跳过。计数是总数，不是未读数。选"感兴趣"后会开始准备材料，材料要你审核后才会用。</p></header>` +
    `<div class="split" role="tablist" aria-label="分组">` +
    TABS.map(
      ([k, t]) =>
        `<button role="tab" type="button" data-bucket="${k}" aria-selected="${triageTab === k}" tabindex="${triageTab === k ? 0 : -1}">${t}<span class="c">${counts[k]}</span></button>`,
    ).join("") +
    `<span class="split-help">Tab 切换分组，1 感兴趣，2 稍后，3 跳过，U 撤销</span></div>` +
    `<div class="tlist" role="listbox" aria-label="${esc(label)}">${list.length ? list.map(itemHtml).join("") : triageEmptyHtml()}</div></div>`
  );
}

export function renderTriage() {
  replaceContent("#view", triageHtml());
}

function select(id, { focus = true } = {}) {
  triageSel = id;
  selIndex = Math.max(
    0,
    tabJobs().findIndex((j) => j.id === id),
  );
  renderTriage();
  if (focus) $(`#t-${CSS.escape(id)}`)?.focus();
  document.dispatchEvent(new CustomEvent("job-selection"));
}

// After a choice the job leaves this tab; the row now at the same place becomes the selection.
export function afterTriage() {
  triageSel = null;
  renderTriage();
  if (triageSel) $(`#t-${CSS.escape(triageSel)}`)?.focus();
  else $(`[data-bucket="${triageTab}"]`)?.focus();
  document.dispatchEvent(new CustomEvent("job-selection"));
}

export function switchTab(tab) {
  triageTab = tab;
  triageSel = null;
  selIndex = 0;
  renderTriage();
  ($(".titem") || $(`[data-bucket="${tab}"]`))?.focus();
  document.dispatchEvent(new CustomEvent("job-selection"));
}

registerPage("triage", {
  title: "分拣",
  enter: loadLibrary,
  render: renderTriage,
  currentJob() {
    return jobById(triageSel);
  },
  move(step) {
    const list = tabJobs();
    const i = list.findIndex((j) => j.id === triageSel);
    const next = list[Math.max(0, Math.min(list.length - 1, i + step))];
    if (next) select(next.id);
  },
  open() {
    if (!triageSel) return;
    setReturnTarget(`#t-${CSS.escape(triageSel)}`);
    go("job/" + encodeURIComponent(triageSel));
  },
  afterTriage,
  tab(e) {
    if (!e.target.closest?.(".titem, [data-bucket]")) return false;
    const i = TABS.findIndex(([k]) => k === triageTab);
    switchTab(TABS[(i + (e.shiftKey ? TABS.length - 1 : 1)) % TABS.length][0]);
    return true;
  },
});

document.addEventListener("click", (e) => {
  if (!e.target.closest?.("#view")) return;
  const tab = e.target.closest("[data-bucket]");
  if (tab) {
    switchTab(tab.dataset.bucket);
    return;
  }
  const tri = e.target.closest(".titem [data-tri]");
  if (tri) {
    const job = jobById(tri.closest(".titem").dataset.tid);
    toggleTriage(job, tri.dataset.tri).then((ok) => ok && afterTriage());
    return;
  }
  const row = e.target.closest(".titem");
  if (row && !e.target.closest("a, button")) select(row.dataset.tid);
  if (e.target.closest("[data-open-job-page]") && triageSel)
    setReturnTarget(`#t-${CSS.escape(triageSel)}`);
});

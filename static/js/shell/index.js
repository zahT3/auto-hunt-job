// The frame around every page: top bar, bottom triage bar, command palette, toast undo and the keyboard map.
import { $, $$, esc, items } from "../shared/dom.js";
import { isDemo, registerView, state } from "../shared/state.js";
import { clock } from "../shared/time.js";
import { kbd } from "../shared/ui.js";
import { tabCounts } from "../triage/model.js";
import { toggleTriage, undoTriage } from "../triage/actions.js";
import { syntheticCandidate } from "../workbench/routes.js";
import { changeRoute, currentPage, go, renderCurrent, route } from "./router.js";
import { hideTip, tipOpen } from "./tip.js";

const FAILED = ["failed", "fetch_error", "parse_error", "blank_page", "blocked", "needs_browser"];
const LOGIN = ["needs_login", "login_required", "captcha"];

// One sentence about the last run; the full text goes into title because the line is cut.
export function runLine() {
  if (state?.search_running) return isDemo() ? "正在准备合成岗位…" : "正在搜索已选来源…";
  const run = items(state?.runs)[0];
  if (!run) return "还没有运行过搜索。";
  const sources = items(run.sources || run.channel_results);
  const name = (s) => s.kind || s.source || s.channel || s.name || "来源";
  const list = (test) => sources.filter(test).map(name).join("、");
  const failed = list((s) => FAILED.includes(s.status));
  const login = list((s) => LOGIN.includes(s.status));
  const cut = list((s) => s.truncated);
  const when = run.finished_at || run.started_at;
  return (
    `${when ? clock(when) + " " : ""}${run.status === "running" ? "开始搜索" : "搜完"}：发现 ${run.discovered ?? 0} 个岗位。` +
    (failed ? `${failed} 失败。` : "") +
    (login ? `${login} 需要登录。` : "") +
    (cut ? `${cut} 结果被截断。` : "")
  );
}

const TRIAGE_KEYS = [
  ["interested", "感兴趣", "1"],
  ["later", "稍后", "2"],
  ["skipped", "跳过", "3"],
];

export function barHtml(job, page) {
  const locked = ["sending", "unknown", "submitted", "rejected"].includes(job.status);
  return (
    `<p class="cur" title="${esc(job.title)}，${esc(job.company || "")}"><b>${esc(job.title)}</b>，${esc(job.company || "公司待确认")}</p>` +
    (locked ? '<span class="small-note">已锁定，不能改选择</span>' : "") +
    TRIAGE_KEYS.map(
      ([v, t, k]) =>
        `<button class="btn" type="button" data-bar-triage="${v}" aria-pressed="${job.triage === v}" ${locked ? "disabled" : ""}>${t} ${kbd(k)}</button>`,
    ).join("") +
    `<button class="btn opt" type="button" data-act="palette">全部操作 ${kbd("⌘K")}</button>`
  );
}

export function renderBar() {
  const page = route().page;
  const job = ["search", "job", "triage"].includes(page) ? currentPage()?.currentJob?.() : null;
  const bar = $("#bar");
  bar.hidden = !job;
  if (!job) return;
  bar.dataset.page = page;
  const html = barHtml(job, page);
  if (bar._renderedHtml !== html) {
    bar.innerHTML = html;
    bar._renderedHtml = html;
  }
}

function renderTop() {
  $("#synth").hidden = !syntheticCandidate();
  const pending = tabCounts(state?.jobs).pending;
  for (const el of $$("[data-count]")) el.textContent = String(pending);
  const line = runLine();
  $("#run").textContent = line;
  $("#run").title = line;
}

registerView({
  render() {
    renderTop();
    renderCurrent();
    renderBar();
  },
});

// ---- command palette ----
const ACTIONS = [
  ["搜索岗位", "/", () => focusQuery()],
  ["标为感兴趣", "1", () => triageKey("interested")],
  ["稍后再看", "2", () => triageKey("later")],
  ["跳过", "3", () => triageKey("skipped")],
  ["撤销上一次分拣", "U", () => undoTriage()],
  ["去分拣", "G 然后 T", () => go("triage")],
  ["去定方向", "G 然后 O", () => go("orient")],
  ["去设置", "G 然后 S", () => go("settings")],
  ["去搜索", "G 然后 F", () => go("search")],
  ["打开工作台（审核、材料包、执行、入口核验）", "", () => go("workbench")],
];
let paletteReturn = null;

function paletteList() {
  const s = $("#palette-q").value.trim();
  $("#palette-list").innerHTML = ACTIONS.filter(([t]) => !s || t.includes(s))
    .map(
      ([t, k]) =>
        `<li><button type="button" data-pa="${esc(t)}"><span>${esc(t)}</span>${k ? kbd(k) : ""}</button></li>`,
    )
    .join("");
}

export function openPalette() {
  paletteReturn = document.activeElement;
  $("#palette-q").value = "";
  paletteList();
  $("#palette").showModal();
  $("#palette-q").focus();
}

$("#palette").addEventListener("close", () => {
  if (paletteReturn?.isConnected) paletteReturn.focus();
});
$("#palette-q").addEventListener("input", paletteList);
$("#palette-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-pa]");
  if (!b) return;
  $("#palette").close();
  ACTIONS.find(([t]) => t === b.dataset.pa)?.[2]();
});

// ---- keyboard (DESIGN.md §7) ----
function focusQuery() {
  if (route().page !== "search") go("search");
  setTimeout(() => $("#q")?.focus(), 0);
}

async function triageKey(value) {
  const page = currentPage();
  const job = page?.currentJob?.();
  if (!job) return;
  if (await toggleTriage(job, value)) page.afterTriage?.();
}

let gPending = false;
document.addEventListener("keydown", (e) => {
  const t = e.target;
  const typing = t.matches?.("input, textarea, select") && !["checkbox", "radio"].includes(t.type);
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    openPalette();
    return;
  }
  if (e.key === "Escape") {
    if (tipOpen()) {
      hideTip();
      return;
    }
    const open = document.querySelector("details.filter[open]");
    if (open) {
      open.open = false;
      open.querySelector("summary").focus();
      return;
    }
    if (document.querySelector("dialog[open]")) return;
    if (currentPage()?.escape?.(t)) e.preventDefault();
    return;
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("dialog[open]"))
    return;
  const page = route().page;
  if (page === "workbench") return;
  if (gPending) {
    gPending = false;
    const to = { t: "triage", o: "orient", s: "settings", f: "search" }[e.key.toLowerCase()];
    if (to) {
      go(to);
      return;
    }
  }
  if (e.key === "g") {
    gPending = true;
    setTimeout(() => (gPending = false), 800);
    return;
  }
  if (e.key === "/") {
    e.preventDefault();
    focusQuery();
    return;
  }
  const p = currentPage();
  if ((e.key === "j" || e.key === "ArrowDown") && p?.move) {
    e.preventDefault();
    p.move(1);
    return;
  }
  if ((e.key === "k" || e.key === "ArrowUp") && p?.move) {
    e.preventDefault();
    p.move(-1);
    return;
  }
  if (e.key === "Enter" && p?.open && !t.closest("a, button, summary, input, label")) {
    p.open();
    return;
  }
  const index = ["1", "2", "3"].indexOf(e.key);
  if (index >= 0 && ["search", "triage", "job"].includes(page)) {
    triageKey(TRIAGE_KEYS[index][0]);
    return;
  }
  if (e.key === "u") {
    undoTriage().then((ok) => ok && currentPage()?.afterTriage?.());
    return;
  }
  if (e.key === "Tab" && p?.tab?.(e)) e.preventDefault();
});

document.addEventListener("click", (e) => {
  const tri = e.target.closest("[data-bar-triage]");
  if (tri) {
    triageKey(tri.dataset.barTriage);
    return;
  }
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "palette") openPalette();
  if (act === "undo") undoTriage().then((ok) => ok && currentPage()?.afterTriage?.());
});
document.addEventListener("job-selection", renderBar);
globalThis.addEventListener?.("hashchange", () => {
  changeRoute();
  renderBar();
});

export function startShell() {
  changeRoute();
  renderBar();
}

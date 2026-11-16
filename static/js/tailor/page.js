// 为这个岗位改简历 (#/tailor/<job id>): every edit with before and after, the facts behind it, one key per decision;
// gaps are listed, never written into the résumé. Export writes local files and shows the read-back check.
import { action } from "../shared/api.js";
import { $, $$, dateOf, esc, items, replaceContent } from "../shared/dom.js";
import { busy, render } from "../shared/state.js";
import { kbd, mark } from "../shared/ui.js";
import { go, registerPage, route } from "../shell/router.js";
import { jobById } from "../triage/actions.js";
import {
  TAILOR_GAP,
  TAILOR_OPS,
  TAILOR_STATUS,
  tailorChangeHtml,
  tailorHardText,
  tailorMove,
  tailorWarnings,
} from "./model.js";

const tailorViews = new Map(); // job id -> the last tailor_get / tailor / tailor_review result
const tailorExports = new Map(); // job id -> the last tailor_export result
const tailorNotes = new Map(); // job id -> why the AI path did not run, after a generate
const tailorErrors = new Map(); // job id -> {text, resume} of the last action that failed, shown at the export bar
const tailorLoading = new Set();
let tailorFocus = null;
let tailorFormats = ["md", "pdf", "docx"];

const FORMAT_NAMES = { md: "Markdown", pdf: "PDF", docx: "DOCX" };
const STRUCTURE_STEP = {
  no_facts: ["还没有已确认的事实", "先确认简历里的事实，再核对简历结构。", "去确认事实"],
  no_structure: ["还没有简历结构", "先在确认页核对简历结构，之后每个岗位都复用它。", "去核对简历结构"],
  unconfirmed: ["简历结构还没有确认", "预填的结构要先在确认页核对并确认，才能为岗位改简历。", "去核对简历结构"],
  stale: ["简历结构需要重新核对", "有条目过期或字段待确认，先在确认页处理。", "去核对简历结构"],
};

const tailorEdits = (view) => items(view?.document?.edits);
const tailorEditIds = (view) => tailorEdits(view).map((e) => e.id);
const tailorFactChip = (view, ref) => {
  const f = view.facts?.[ref.id];
  return `<span class="fact" tabindex="0" data-tip="${esc(f ? f.text : ref.id)}">${esc(ref.id)}</span>`;
};

function tailorEditHtml(view, edit, latest) {
  const [tone, label] = TAILOR_STATUS[edit.status] || TAILOR_STATUS.pending;
  const warnings = tailorWarnings(edit);
  const req = edit.requirement;
  const cited = items(edit.fact_ids).map((r) => view.facts?.[r.id]);
  const note = edit.checks?.reviewer_note;
  const on = edit.id === tailorFocus;
  return (
    `<li class="tl-edit${on ? " on" : ""}" id="tl-e-${esc(edit.id)}" data-edit="${esc(edit.id)}" data-status="${esc(edit.status)}" tabindex="0">` +
    `<p class="tl-head"><span class="tl-op">${esc(TAILOR_OPS[edit.op] || edit.op)}</span>` +
    `<span class="tl-by">${edit.by === "ai" ? "AI" : "规则"}</span>${mark(tone, label)}</p>` +
    (req
      ? `<p class="sub">对应岗位要求：${esc(req.value)}${req.jd_evidence ? `，原文「${esc(req.jd_evidence)}」` : ""}</p>`
      : "") +
    tailorChangeHtml(edit) +
    (warnings.length
      ? `<p class="tl-warn" role="note">${warnings.map((w) => `<span class="tl-flag">${esc(w)}</span>`).join("")}${note ? esc(note) : ""}</p>`
      : "") +
    (edit.why ? `<p class="sub">${esc(edit.why)}</p>` : "") +
    `<p class="sub">来源：${items(edit.fact_ids)
      .map((r) => tailorFactChip(view, r))
      .join("")}</p>` +
    `<details><summary>来源事实原文</summary>${cited
      .filter(Boolean)
      .map(
        (f) =>
          `<p class="tl-src"><span class="sub">${esc(f.id)}${f.reference ? `（${esc(f.reference)}）` : ""}</span><br>${esc(f.text)}</p>`,
      )
      .join("")}</details>` +
    (latest && edit.status !== "stale"
      ? `<div class="tl-actions"><button class="btn" type="button" data-tl="accept" data-id="${esc(edit.id)}" ${edit.status === "accepted" ? "disabled" : ""}>接受 ${kbd("a")}</button>` +
        `<button class="btn" type="button" data-tl="reject" data-id="${esc(edit.id)}" ${edit.status === "rejected" ? "disabled" : ""}>撤销 ${kbd("u")}</button></div>`
      : "") +
    `</li>`
  );
}

function tailorPreviewHtml(rendered, hidden) {
  if (!items(rendered?.sections).some((s) => items(s.lines).length))
    return (
      `<p class="warning-box" role="status">简历结构里还没有条目，所以没有可排版的内容。到确认页把事实分到条目里。` +
      `<button class="linkish" type="button" data-open-resume>去核对简历结构</button></p>`
    );
  const hiddenCount = Object.keys(hidden || {}).length;
  const sections = items(rendered?.sections)
    .map((s) =>
      items(s.lines).length
        ? `<div class="tl-sec">${s.lines
            .map(
              (l) =>
                `<p class="tl-line tl-${esc(l.kind)}${items(l.edit_ids).length ? " changed" : ""}">${esc(l.text)}</p>`,
            )
            .join("")}</div>`
        : "",
    )
    .join("");
  return sections + (hiddenCount ? `<p class="sub">已隐藏 ${hiddenCount} 条；事实本身没有改动。</p>` : "");
}

function tailorGapsHtml(doc) {
  const gaps = items(doc.gaps);
  if (!gaps.length) return '<p class="sub">岗位要求都有对应的事实。</p>';
  return `<ul class="tl-gaps">${gaps
    .map(
      (g) =>
        `<li><b>${esc(g.requirement)}</b><span class="st st-muted">${esc(TAILOR_GAP[g.type] || g.type)}</span>` +
        `${g.jd_evidence ? `<span class="sub">原文「${esc(g.jd_evidence)}」</span>` : ""}` +
        `${items(g.related_terms).length ? `<span class="sub">事实里有：${esc(g.related_terms.join("、"))}</span>` : ""}` +
        `<button class="linkish" type="button" data-open-candidate>我有这项，去补充事实</button></li>`,
    )
    .join("")}</ul>`;
}

function tailorRejectedHtml(view) {
  const rows = items(view.document.rejected_by_gate);
  const viewRows = items(view.rejected_in_view);
  if (!rows.length && !viewRows.length) return "";
  return (
    `<details class="tl-rejected"><summary>被本地检查拒绝的提议（${rows.length + viewRows.length}）</summary>` +
    `<p class="sub">这些改不进简历，也没有接受按钮。要用这些内容，先把它补充为已确认事实。</p><ul>` +
    rows
      .map(
        (r) =>
          `<li>${esc(tailorHardText(r))}<span class="sub">${esc(r.edit?.after || r.edit?.before || "")}</span></li>`,
      )
      .join("") +
    viewRows.map((r) => `<li>${esc(r.edit_id)}：${esc(r.text)}</li>`).join("") +
    `</ul><button class="linkish" type="button" data-open-candidate>去补充事实</button></details>`
  );
}

function tailorExportHtml(result) {
  if (!result) return "";
  const rows = Object.entries(result.files || {}).map(([fmt, f]) => {
    const c = f.check || {};
    const problems = [
      ...(items(c.missing_lines).length ? [`${c.missing_lines.length} 行读回时找不到`] : []),
      ...(c.section_order_ok === false ? ["章节顺序被打乱"] : []),
      ...(c.pages_ok === false ? [`${c.page_count} 页，超过页数上限`] : []),
    ];
    return (
      `<li><b>${esc(FORMAT_NAMES[fmt] || fmt)}</b> ${mark(c.ok ? "ok" : "bad", c.ok ? "自检通过" : "自检没通过")}` +
      `<span class="sub"><code>${esc(f.path)}</code>${c.page_count ? `，${c.page_count} 页` : ""}</span>` +
      `${problems.length ? `<span class="tl-warn">${esc(problems.join("；"))}</span>` : ""}` +
      `${items(c.warnings).map((w) => `<span class="tl-warn">${esc(w)}</span>`).join("")}</li>`
    );
  });
  const errors = Object.entries(result.errors || {}).map(
    ([fmt, text]) => `<li><b>${esc(FORMAT_NAMES[fmt] || fmt)}</b> ${mark("bad", "没有导出")}<span class="tl-warn">${esc(text)}</span></li>`,
  );
  const first = Object.values(result.files || {}).find((f) => items(f.check?.keyword_coverage).length);
  const coverage = first
    ? `<table class="srcs"><thead><tr><th>岗位关键词</th><th>导出前</th><th>读回后</th></tr></thead><tbody>${first.check.keyword_coverage
        .map(
          (k) =>
            `<tr><td>${esc(k.keyword)}</td><td>${esc(k.before)}</td><td>${esc(k.after)}${k.changed ? " ← 有变化" : ""}</td></tr>`,
        )
        .join("")}</tbody></table>`
    : "";
  return (
    `<section class="tl-export" aria-label="导出结果"><div class="sec-h"><h2>导出结果</h2><span class="tally">第 ${esc(result.version)} 版${result.excluded_pending ? `，不含 ${result.excluded_pending} 条待审核` : ""}</span></div>` +
    `<ul class="tl-files">${rows.join("")}${errors.join("")}</ul>${coverage}` +
    `<p class="note">${esc(result.notice)}</p></section>`
  );
}

function tailorToolbarHtml(view, id) {
  const doc = view.document;
  const ai = view.ai || {};
  const versions = items(view.versions);
  const how = doc.by === "ai" ? `规则 + AI 改写（${esc(doc.model?.host || "")} / ${esc(doc.model?.model || "")}）` : "规则路径，没有使用 AI";
  return (
    `<div class="tl-tools"><label>版本 <select id="tl-version">${versions
      .map(
        (v) =>
          `<option value="${v.version}"${v.version === doc.version ? " selected" : ""}>v${v.version}（${v.by === "ai" ? "含 AI" : "规则"} · ${esc(dateOf(v.created_at))}）</option>`,
      )
      .join("")}</select></label>` +
    `<span class="sub">本版：${how}${view.latest ? "" : "。旧版只读"}</span>` +
    `<button class="btn" type="button" data-act="tailor-generate">重新生成（规则）</button>` +
    `<button class="btn" type="button" data-act="tailor-ai" ${ai.available ? "" : "disabled"}>用 AI 改写措辞</button></div>` +
    `<p class="small-note">${esc(ai.available ? ai.estimate?.text || "" : ai.reason || "")}</p>` +
    (tailorNotes.get(id) ? `<p class="warning-box" role="status">${esc(tailorNotes.get(id))}</p>` : "")
  );
}

function tailorErrorHtml(id) {
  const e = tailorErrors.get(id);
  return e
    ? `<p class="warning-box" role="alert">${esc(e.text)}${e.resume ? ' <button class="linkish" type="button" data-open-resume>去核对简历结构</button>' : ""}</p>`
    : "";
}

function tailorFooterHtml(view, id) {
  const ok = view.trace?.status === "pass";
  const result = view.result?.ok;
  const formats = Object.entries(FORMAT_NAMES)
    .map(
      ([k, n]) =>
        `<label class="tl-fmt"><input type="checkbox" data-fmt="${k}" ${tailorFormats.includes(k) ? "checked" : ""}> ${n}</label>`,
    )
    .join("");
  const pending = view.pending;
  return (
    `<div class="tl-foot"><p>${pending ? `${pending} 条待审核` : "没有待审核"}，` +
    `预检${ok ? "通过" : "没通过"}${result ? "" : "，改写后的行有疑点"}${view.stale ? `，${view.stale} 条事实已变` : ""}</p>` +
    `<fieldset class="tl-fmts"><legend>格式</legend>${formats}</fieldset>` +
    `<button class="btn btn-primary" type="button" data-act="tailor-export" ${ok && tailorFormats.length && view.latest !== false && !view.empty ? "" : "disabled"}>${pending ? `导出（不含 ${pending} 条待审核）` : "导出"}</button></div>`
  );
}

export function tailorPageHtml(job, view, loading, exported, id) {
  const head =
    `<a class="back" href="#/job/${esc(id)}" data-act="tailor-back">返回岗位（Esc）</a>` +
    `<header class="d-head"><div><h1 id="page-title" tabindex="-1">为这个岗位改简历</h1>` +
    `<p class="sub">${esc(job?.title || "岗位名称待确认")}，${esc(job?.company || "公司待确认")}</p></div></header>`;
  if (loading && !view)
    return `<article class="detail tailor">${head}<div class="empty flush" aria-busy="true"><h2>正在读取…</h2></div></article>`;
  if (view?.needs_structure) {
    const [title, text, button] = STRUCTURE_STEP[view.code] || STRUCTURE_STEP.unconfirmed;
    return (
      `<article class="detail tailor">${head}<div class="empty flush"><h2>${esc(title)}</h2><p>${esc(text)}</p>` +
      `<button class="btn btn-primary" type="button" data-open-resume>${button}</button> ` +
      `<button class="btn" type="button" data-act="tailor-reload">已处理，重新检查</button></div></article>`
    );
  }
  if (!view?.document)
    return (
      `<article class="detail tailor">${head}<div class="empty flush"><h2>还没有为这个岗位生成定制版</h2>` +
      `<p>规则路径只调序、换成岗位原词、列出缺口，不新增任何文字，也不发送内容。生成的每一条修改都能逐条接受或撤销。</p>` +
      `<button class="btn btn-primary" type="button" data-act="tailor-generate">生成（规则）</button></div></article>`
    );
  const doc = view.document;
  const latest = view.latest !== false;
  const edits = tailorEdits(view);
  return (
    `<article class="detail tailor">${head}${tailorToolbarHtml(view, id)}` +
    (view.structure_changed ? `<p class="warning-box" role="status">简历结构在生成之后变过。<button class="linkish" type="button" data-open-resume>去核对</button>，再重新生成。</p>` : "") +
    `<div class="tl-cols"><section aria-label="修改"><div class="sec-h"><h2>修改</h2><span class="tally">${edits.length} 条 · j/k 切换，a 接受，u 撤销</span></div>` +
    (edits.length
      ? `<ol class="tl-edits">${edits.map((e) => tailorEditHtml(view, e, latest)).join("")}</ol>`
      : '<p class="sub">这个岗位和这份简历没有可调的地方：规则路径没提议任何修改。</p>') +
    `</section><section aria-label="定制版"><div class="sec-h"><h2>定制版</h2><span class="tally">只含已接受的修改</span></div>` +
    `<div class="tl-preview">${tailorPreviewHtml(view.rendered, view.hidden)}</div>` +
    `<details><summary>原始事实（没有改动）</summary><div class="tl-preview">${tailorPreviewHtml(view.original, {})}</div></details>` +
    `<div class="sec-h"><h2>缺口</h2><span class="tally">岗位有、事实里没有，不会写进简历</span></div>${tailorGapsHtml(doc)}</section></div>` +
    tailorRejectedHtml(view) +
    tailorFooterHtml(view, id) +
    tailorErrorHtml(id) +
    tailorExportHtml(exported)
  );
}

export function renderTailor(id) {
  const job = jobById(id);
  replaceContent("#view", tailorPageHtml(job, tailorViews.get(id), tailorLoading.has(id), tailorExports.get(id), id));
}

async function tailorLoad(id, version) {
  tailorLoading.add(id);
  const data = await action("tailor_get", { job_id: id, ...(version ? { version } : {}) }, "正在读取…");
  tailorLoading.delete(id);
  if (data?.result) tailorViews.set(id, data.result);
  render();
}

async function tailorRun(name, payload, label) {
  const id = route().id;
  const data = await action(name, { job_id: id, ...payload }, label);
  if (!data?.result) {
    // action() already put the message in #notice; keep it next to the export bar too, so it cannot be missed.
    if (data === null && !busy) tailorErrors.set(id, { text: $("#notice")?.textContent || "操作没有完成。", resume: false });
    render();
    return null;
  }
  if (data.result.needs_structure) {
    tailorErrors.set(id, { text: data.result.reason, resume: true });
    if (name === "tailor") tailorViews.set(id, data.result);
    render();
    return null;
  }
  tailorErrors.delete(id);
  if (name === "tailor") {
    const ai = data.result.ai || {};
    tailorNotes.set(id, ai.requested && !ai.used ? `没有用 AI：${ai.reason || "条件不满足"}，这一版只用了规则路径。` : "");
    tailorExports.delete(id);
  }
  if (name === "tailor_export") tailorExports.set(id, data.result);
  else tailorViews.set(id, data.result);
  render();
  return data.result;
}

async function tailorDecide(kind, id) {
  const job = route().id;
  const view = tailorViews.get(job);
  const edit = tailorEdits(view).find((e) => e.id === id);
  if (!edit || busy || view.latest === false) return;
  tailorFocus = id;
  const list = kind === "accept" ? { accept: [id] } : { reject: [id] };
  const result = await tailorRun("tailor_review", list, "正在检查…");
  if (result) tailorExports.delete(job);
  $(`#tl-e-${CSS.escape(id)}`)?.focus({ preventScroll: true });
}

function tailorMoveFocus(step) {
  const next = tailorMove(tailorEditIds(tailorViews.get(route().id)), tailorFocus, step);
  if (!next) return;
  tailorFocus = next;
  render();
  const card = $(`#tl-e-${CSS.escape(next)}`);
  card?.focus();
  card?.scrollIntoView?.({ block: "nearest" });
}

registerPage("tailor", {
  title: "改简历",
  enter(id) {
    tailorFocus = null;
    tailorLoad(id);
  },
  render: renderTailor,
  escape() {
    go("job/" + route().id);
    return true;
  },
});

document.addEventListener(
  "keydown",
  (e) => {
    if (route().page !== "tailor" || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("dialog[open]")) return;
    if (e.target.matches?.("input, textarea, select")) return;
    const key = e.key;
    const step = { j: 1, ArrowDown: 1, k: -1, ArrowUp: -1 }[key];
    if (step) tailorMoveFocus(step);
    else if (key === "a" || key === "u") tailorDecide(key === "a" ? "accept" : "reject", tailorFocus);
    else return;
    // Capture phase: the shell's own `u` (undo a triage choice) and j/k must not also run on this page.
    e.preventDefault();
    e.stopPropagation();
  },
  true,
);

document.addEventListener("click", (e) => {
  if (route().page !== "tailor") return;
  const decide = e.target.closest("[data-tl]");
  if (decide) {
    tailorDecide(decide.dataset.tl, decide.dataset.id);
    return;
  }
  const card = e.target.closest("[data-edit]");
  if (card && !e.target.closest("button, summary, a")) tailorFocus = card.dataset.edit;
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "tailor-generate") tailorRun("tailor", { ai: false }, "正在生成…");
  else if (act === "tailor-ai") tailorRun("tailor", { ai: true }, "正在请模型改写…");
  else if (act === "tailor-export")
    tailorRun("tailor_export", { formats: tailorFormats }, "正在导出并读回检查…");
  else if (act === "tailor-reload") tailorLoad(route().id);
  else if (act === "tailor-back") {
    e.preventDefault();
    go("job/" + route().id);
  }
});

document.addEventListener("change", (e) => {
  if (route().page !== "tailor") return;
  if (e.target.id === "tl-version") tailorLoad(route().id, Number(e.target.value));
  const fmt = e.target.dataset?.fmt;
  if (fmt) {
    tailorFormats = $$("[data-fmt]")
      .filter((x) => x.checked)
      .map((x) => x.dataset.fmt);
    render();
  }
});

// The résumé dialog is where the structure gets confirmed; when it closes, check again.
$("#resume-dialog")?.addEventListener("close", () => {
  if (route().page === "tailor") tailorLoad(route().id);
});

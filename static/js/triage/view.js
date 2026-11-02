// Card choice controls and bucket grouping as HTML strings; the workbench decides where they go.
import { action } from "../shared/api.js";
import { $, esc } from "../shared/dom.js";
import { toast } from "../shared/feedback.js";
import {
  CHOICES,
  bucketCounts,
  bucketLabel,
  bucketOf,
  groupByBucket,
  preparing,
  triageLocked,
  triagePayload,
  undoBlocked,
} from "./model.js";

export function countsLine() {
  const c = bucketCounts();
  const parts = ["pending", "chosen", "materials", "sent"].map(
    (key) => `${bucketLabel(key)} ${c[key]}`,
  );
  return `<p class="small-note triage-counts" aria-label="岗位分组数量">${parts.join(" · ")}${c.skipped ? ` · 已跳过 ${c.skipped}` : ""} · 今天新增 ${c.new_today}</p>`;
}

// One section per non-empty bucket in BUCKETS order; skipped jobs stay folded away.
export function groupedRows(jobs, row) {
  return groupByBucket(jobs)
    .map(({ key, label, jobs: rows }) => {
      const head = `${esc(label)} <span class="count">${rows.length}</span>`;
      const body = rows.map(row).join("");
      return key === "skipped"
        ? `<details class="queue-group" data-disclosure="bucket-skipped"><summary class="queue-group-title">${head}</summary>${body}</details>`
        : `<section class="queue-group" aria-label="${esc(label)}"><h2 class="queue-group-title">${head}</h2>${body}</section>`;
    })
    .join("");
}

export function prepareErrorNote(job) {
  return job.prepare_error
    ? `<div class="blocker-box" role="alert">材料准备失败：${esc(job.prepare_error)}。可以重新选择「感兴趣」再试，或在详情里手动准备。</div>`
    : "";
}

export function triageControls(job) {
  if (triageLocked(job))
    return `<section class="triage-controls" aria-label="你的选择"><p class="small-note">此岗位已锁定，不能改选择。</p></section>`;
  const buttons = CHOICES.map(
    ([value, label]) =>
      `<button type="button" class="${job.triage === value ? "primary" : "secondary"}" data-triage="${value}" data-triage-job="${esc(job.id)}" aria-pressed="${job.triage === value}">${label}</button>`,
  ).join("");
  const undo = job.triage
    ? undoBlocked(job)
      ? '<p class="small-note">材料已批准，不能撤销选择。</p>'
      : `<button type="button" class="text-button" data-triage="" data-triage-job="${esc(job.id)}">撤销选择</button>`
    : "";
  const status = preparing(job)
    ? '<p class="small-note" role="status">正在后台准备材料，完成后移到「材料」。</p>'
    : job.triage === "interested" && job.package && !undoBlocked(job)
      ? '<p class="small-note">材料已准备，撤销选择会删除这份材料。</p>'
      : "";
  return (
    `<section class="triage-controls" aria-label="你的选择">` +
    `<div class="triage-head"><strong>你的选择</strong><span class="small-note">当前分组：${esc(bucketLabel(bucketOf(job)))}</span></div>` +
    `<div class="triage-buttons">${buttons}${undo}</div>${status}${prepareErrorNote(job)}</section>`
  );
}

export async function chooseTriage(jobId, value) {
  if (!(await action("triage", triagePayload(jobId, value), "正在保存选择…"))) return;
  // The pressed button is re-rendered (undo removes itself), so focus returns to the same choice or the first one.
  const same = `[data-triage-job="${CSS.escape(jobId)}"]`;
  ($(`[data-triage="${value || ""}"]${same}`) || $(`[data-triage]${same}`))?.focus({
    preventScroll: true,
  });
  if (value === "interested") toast("已选为感兴趣，材料在后台准备。");
}

document.addEventListener("click", (e) => {
  const button = e.target.closest("[data-triage-job]");
  if (button) chooseTriage(button.dataset.triageJob, button.dataset.triage || null);
});

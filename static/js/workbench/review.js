// Batch review: local material review is always available; outbound authorization only for real, supported receivers.
import { action } from "../shared/api.js";
import {
  $,
  $$,
  esc,
  fieldValue,
  items,
  openDialog,
  safeUrl,
  sourceOf,
  textOf,
} from "../shared/dom.js";
import { notice, toast } from "../shared/feedback.js";
import { busy, state } from "../shared/state.js";
import { listBox } from "./detail.js";
import { renderQueue, selected } from "./queue.js";
import { canAuthorizeReview, syntheticCandidate } from "./routes.js";

export let reviewJobs = [];
export let outboundReviewEligible = false;

function reviewItem(j, c) {
  const p = j.package;
  const used = new Set(items(p.claims).flatMap((x) => items(x.fact_ids)));
  const fields =
    Object.entries(p.fields || {})
      .map(
        ([k, v]) =>
          `${{ name: "姓名", email: "邮箱", phone: "电话", city: "城市", years_experience: "相关经验年限" }[k] || k}：${textOf(fieldValue(v))}`,
      )
      .join("；") || "尚无已保存联系字段";
  const fileBase = `/api/file/${encodeURIComponent(p.id)}`;
  const factRows =
    items(c.facts)
      .filter((f) => used.has(f.id))
      .map(
        (f) =>
          `<div class="evidence-row"><p>${esc(f.text)}</p><small>${esc(f.id)} · ${esc(sourceOf(f))} · ${esc(f.status)} · ${esc(f.disclosure || "未设置")}</small></div>`,
      )
      .join("") || '<p class="small-note">没有可用于本次申请的个人主张。</p>';
  return (
    `<section class="review-item"><h3>${esc(j.title)}</h3>` +
    `<p class="muted">${esc(j.company)} · ${esc(j.channel || "来源待确认")}${j.material_review_current ? " · 已复核" : ""}</p>` +
    `<dl><dt>岗位来源</dt><dd><a href="${safeUrl(j.url)}" target="_blank" rel="noopener">${esc(j.url || "未提供来源地址")}</a></dd>` +
    `<dt>申请入口</dt><dd>${safeUrl(j.application_url) !== "#" ? `<a href="${safeUrl(j.application_url)}" target="_blank" rel="noopener">${esc(j.application_url)}</a>` : "入口尚待确认"}</dd>` +
    `<dt>候选人</dt><dd>${esc(c.name || "姓名未提供")} · 事实版本 ${esc(p.candidate_version || "未知")}${syntheticCandidate() ? " · 合成资料" : ""}</dd>` +
    `<dt>材料字段</dt><dd>${esc(fields)}</dd>` +
    `<dt>最终文件</dt><dd><a href="${fileBase}/resume.pdf" target="_blank" rel="noopener">查看 PDF</a> · <a href="${fileBase}/resume.txt" download>下载文本</a></dd></dl>` +
    `${listBox(p.blockers, "blocker")}${listBox(p.gaps)}` +
    `<details open><summary>最终简历原文</summary><pre class="document-preview">${esc(textOf(p.resume))}</pre></details>` +
    `${p.cover_letter ? `<details class="evidence-details"><summary>最终求职信</summary><pre class="document-preview">${esc(textOf(p.cover_letter))}</pre></details>` : ""}` +
    `${items(p.answers).length ? `<details class="evidence-details" open><summary>最终筛选答案</summary>${p.answers.map((a) => `<p class="small-note">${esc(a.question || a.field)}：${esc(a.answer || a.value || "未回答")}</p>`).join("")}</details>` : ""}` +
    `<details class="evidence-details"><summary>事实来源与披露范围 · ${used.size} 项</summary>${factRows}</details>` +
    `<details class="evidence-details"><summary>材料版本</summary><p class="snapshot">${esc(p.snapshot)}</p></details>` +
    `</section>`
  );
}

export function openReview(ids) {
  reviewJobs = (state.jobs || []).filter((j) => ids.includes(j.id));
  if (!reviewJobs.length) return;
  if (reviewJobs.length > 5) {
    notice("每批最多复核 5 个岗位，请减少所选岗位。", true);
    return;
  }
  if (reviewJobs.some((j) => !j.package)) {
    notice("所选岗位中还有未准备的材料，请先准备。", true);
    return;
  }
  const c = state.candidate || {};
  $("#review-form").reset();
  $("#material-review-confirm").checked = false;
  $("#save-material-review").disabled = true;
  outboundReviewEligible = canAuthorizeReview(reviewJobs);
  $("#external-review").hidden = !outboundReviewEligible;
  $("#external-review").open = false;
  $("#external-review-controls").disabled = !outboundReviewEligible;
  $("#review-form").elements.limit.value = reviewJobs.length;
  $("#review-form").elements.limit.max = reviewJobs.length;
  let blockers = false,
    gaps = false;
  for (const j of reviewJobs) {
    const p = j.package;
    blockers =
      blockers ||
      items(p.blockers).length > 0 ||
      items(j.match?.hard).some((h) => h.status === "not_met") ||
      [
        "unknown",
        "submission_unknown",
        "verification_required",
        "sending",
        "submitted",
        "verified",
        "rejected",
      ].includes(j.status);
    gaps = gaps || items(p.gaps).length > 0;
  }
  $("#review-content").innerHTML = reviewJobs.map((j) => reviewItem(j, c)).join("");
  $("#external-review-gaps").innerHTML =
    (gaps
      ? '<label class="check-label"><input id="acknowledge-gaps" type="checkbox">我已核对未知信息与材料缺口，同意保留其不确定性</label>'
      : "") +
    (blockers
      ? '<div class="blocker-box">本批次有未解决的缺口、硬条件或执行状态，不能批准对外操作。</div>'
      : "");
  $("#review-confirm").disabled = blockers || !outboundReviewEligible;
  $("#review-confirm").checked = false;
  $("#approve-batch").disabled = true;
  openDialog("#review-dialog");
}

export function updateLocalReview() {
  $("#save-material-review").disabled =
    busy || !reviewJobs.length || !$("#material-review-confirm").checked;
}

export function updateApprove() {
  const gap = $("#acknowledge-gaps");
  $("#approve-batch").disabled =
    busy ||
    !outboundReviewEligible ||
    !$("#external-review").open ||
    $("#review-confirm").disabled ||
    !$("#review-confirm").checked ||
    (gap && !gap.checked) ||
    !$$("#review-form input[name=permission]:checked").length;
}

export async function saveMaterialReview() {
  updateLocalReview();
  if ($("#save-material-review").disabled) return;
  const snapshots = Object.fromEntries(reviewJobs.map((j) => [j.id, j.package.snapshot]));
  if (
    await action(
      "review_materials",
      { job_ids: reviewJobs.map((j) => j.id), snapshots, acknowledge_review: true },
      "正在保存本地复核…",
    )
  ) {
    $("#review-dialog").close();
    selected.clear();
    renderQueue();
    $("#detail-title")?.focus({ preventScroll: true });
    toast("本地复核已保存；未授权任何对外操作。");
  }
}

$("#review-form").addEventListener("change", () => {
  updateApprove();
  updateLocalReview();
});
$("#external-review").addEventListener("toggle", updateApprove);
$("#save-material-review").addEventListener("click", saveMaterialReview);
$("#review-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  updateApprove();
  if ($("#approve-batch").disabled) return;
  const snapshots = Object.fromEntries(reviewJobs.map((j) => [j.id, j.package.snapshot]));
  const payload = {
    job_ids: reviewJobs.map((j) => j.id),
    decision: "approve",
    snapshots,
    snapshot: snapshots,
    permissions: $$("#review-form input[name=permission]:checked").map((x) => x.value),
    expires_hours: Number(form.elements.expires_hours.value),
    limit: Number(form.elements.limit.value),
    acknowledge_gaps: !!$("#acknowledge-gaps")?.checked,
    browser_plan_hash: form.elements.browser_plan_hash.value.trim().toLowerCase(),
  };
  if (await action("review", payload)) {
    $("#review-dialog").close();
    selected.clear();
    renderQueue();
    toast("已批准列出的材料快照。外部执行仍需通过渠道与授权检查。");
  }
});
$("#reject-batch").addEventListener("click", async () => {
  if (
    await action("review", {
      job_ids: reviewJobs.map((j) => j.id),
      decision: "reject",
      snapshots: Object.fromEntries(reviewJobs.map((j) => [j.id, j.package.snapshot])),
    })
  ) {
    $("#review-dialog").close();
    selected.clear();
    renderQueue();
    toast("所列岗位已标记为不申请。");
  }
});

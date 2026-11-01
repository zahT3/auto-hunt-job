// Résumé upload, the extracted-fact confirmation draft, and the profile line above the queue.
import { action } from "../shared/api.js";
import { $, $$, esc, items, openDialog, sourceOf, textOf } from "../shared/dom.js";
import { clearFeedback, notice, toast } from "../shared/feedback.js";
import { busy, render, setBusy, setState, state } from "../shared/state.js";
import { profileQueries } from "./settings.js";

export function renderProfile() {
  const c = state.candidate || {},
    draft = state.candidate_draft;
  const facts = items(c.facts).filter((f) => f.status === "confirmed");
  $("#profile-kind").textContent = c.synthetic || c.is_demo ? "合成候选人" : "候选资料";
  $("#profile-kind").className = "badge " + (c.synthetic || c.is_demo ? "warn" : "neutral");
  $("#profile-status").textContent = facts.length
    ? `${facts.length} 项已确认事实${draft ? " · 有简历待复核" : ""}`
    : "上传简历，确认事实后开始搜索";
  $("#target-summary").textContent = items(state.config?.keywords).join(" · ") || "设置搜索方向";
  $("#resume-review").hidden = !draft;
  $("#use-profile-queries").hidden = !profileQueries().length;
}

export function openResume() {
  renderResumeDraft();
  openDialog("#resume-dialog");
}

export function resumeConfirmationBlocked() {
  return (
    !state?.candidate_draft ||
    ["needs_ocr", "error", "failed"].includes(state.candidate_draft.status)
  );
}

export function updateResumeConfirm() {
  const button = $("#resume-confirm-button");
  if (button)
    button.disabled =
      busy ||
      resumeConfirmationBlocked() ||
      !$$("#resume-confirm-form input[name=confirmed_fact_ids]:checked").length;
}

export function factSourceDetail(fact) {
  const source = typeof fact.source === "object" ? fact.source : {},
    reference = sourceOf(fact);
  const number = (key) => {
    const raw = source[key] ?? reference.match(new RegExp("(?:[#&])" + key + "=(\\d+)"))?.[1];
    return /^\d+$/.test(String(raw)) && Number(raw) > 0 ? Number(raw) : null;
  };
  const page = number("page"),
    paragraph = number("paragraph");
  const locator = [page ? "第 " + page + " 页" : null, paragraph ? "第 " + paragraph + " 段" : null]
    .filter(Boolean)
    .join(" · ");
  return (
    `<div class="fact-source-note"><small>${esc(locator || source.label || "来源待定位")}</small>` +
    `<details><summary>来源记录</summary><small>${esc(reference)}</small>` +
    `${source.label && locator ? `<small>${esc(source.label)}</small>` : ""}</details></div>`
  );
}

export function renderResumeDraft() {
  const draft = state.candidate_draft,
    section = $("#resume-draft");
  section.hidden = !draft;
  if (!draft) {
    section.innerHTML = "";
    return;
  }
  const p = draft.profile || {},
    c = draft.candidate || {},
    facts = items(c.facts),
    blocked = resumeConfirmationBlocked();
  const warnings = items(draft.warnings).length
    ? `<div class="warning-box">${items(draft.warnings)
        .map((x) => `<p>${esc(textOf(x))}</p>`)
        .join("")}</div>`
    : "";
  const skills = items(p.skills).length
    ? `<div class="profile-readout"><h4>原文提到的技能</h4><p>${items(p.skills)
        .map((s) => esc(typeof s === "string" ? s : s.name))
        .join("、")}</p></div>`
    : "";
  const queries = items(p.suggested_queries).length
    ? `<div class="profile-readout"><h4>建议搜索词</h4><p>${p.suggested_queries.map(esc).join("、")}</p>` +
      `<p class="small-note">可在求职目标中采用或修改。搜索只发送关键词，不发送简历原文或联系方式。</p></div>`
    : "";
  const unknowns = items(p.unknowns).length
    ? `<div class="profile-readout"><h4>仍需补充</h4><p>${p.unknowns.map((x) => esc(textOf(x))).join("；")}</p></div>`
    : "";
  const factRows =
    facts
      .map(
        (fact, i) =>
          `<div class="extracted-fact">` +
          `<input id="resume-fact-${i}" type="checkbox" name="confirmed_fact_ids" value="${esc(fact.id)}" ${blocked ? "disabled" : ""}>` +
          `<div class="fact-copy"><label for="resume-fact-${i}"><strong>事实 ${i + 1}</strong><span class="fact-quote">${esc(fact.text)}</span></label>` +
          `${factSourceDetail(fact)}</div></div>`,
      )
      .join("") ||
    '<p class="small-note">未提取到可确认的文字。请检查扫描件提示，或换用文字版文件。</p>';
  section.innerHTML =
    `<div class="draft-heading"><h3 id="resume-draft-title" tabindex="-1">核对提取出的事实</h3>` +
    `<span class="badge neutral">${c.synthetic ? "合成候选人" : "本地私密资料"}</span></div>` +
    `<p class="small-note">${esc(draft.document?.filename || draft.document?.name || draft.filename || "已上传简历")} · ${facts.length} 项提取记录。只勾选准确、完整的事实；遗漏或错误可在确认后进入「查看 / 编辑事实」修正。</p>` +
    `${blocked ? '<div class="blocker-box">这份简历尚未成功提取文字，暂不能确认。请换用文字版 PDF 或 DOCX 后重新上传。</div>' : ""}` +
    warnings +
    skills +
    queries +
    `${p.notice ? `<p class="small-note">${esc(p.notice)}</p>` : ""}` +
    unknowns +
    `<form id="resume-confirm-form">` +
    `<label class="check-label draft-select-all"><input id="resume-select-all" type="checkbox" ${blocked ? "disabled" : ""}>我已逐项核对，选择以下全部事实</label>` +
    `<div class="extracted-facts">${factRows}</div>` +
    `<p class="small-note">本次确认只更新本地候选事实。申请披露范围仍为私密，具体岗位和最终材料需另行审核。</p>` +
    `<div class="dialog-actions"><button type="button" class="secondary" data-close>稍后复核</button>` +
    `<button type="submit" class="primary" id="resume-confirm-button" disabled>确认选中的事实</button></div></form>`;
}

export async function uploadResume(event) {
  event.preventDefault();
  if (busy) return;
  clearFeedback("#resume-dialog");
  const form = event.target,
    file = $("#resume-file").files?.[0];
  if (!file) return;
  try {
    if (file.size > 10 * 1024 * 1024)
      throw new Error("文件超过 10 MiB，请压缩或另存为较小文件后重试。");
    if (!/\.(pdf|docx|txt|md)$/i.test(file.name))
      throw new Error("请选择 PDF、DOCX、TXT 或 MD 文件。");
    setBusy(true, "正在本地解析…");
    const content = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = () => reject(new Error("无法读取文件，请重新选择。"));
      reader.readAsDataURL(file);
    });
    const response = await fetch("/api/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Local-Token": state.csrf_token },
      body: JSON.stringify({
        filename: file.name,
        content_base64: content,
        synthetic: form.elements.synthetic.checked,
      }),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(textOf(data.error) || "解析未完成。");
    setState(data.state || data);
    render();
    renderResumeDraft();
    $("#resume-draft-title")?.focus({ preventScroll: true });
    $("#resume-draft-title")?.scrollIntoView({ block: "nearest" });
    toast("已在本地提取，请核对候选事实。");
  } catch (error) {
    notice(error.message, true);
  } finally {
    setBusy(false);
    updateResumeConfirm();
  }
}

$("#resume-open").addEventListener("click", openResume);
$("#resume-review").addEventListener("click", openResume);
$("#resume-upload-form").addEventListener("submit", uploadResume);
$("#resume-draft").addEventListener("change", (event) => {
  if (event.target.id === "resume-select-all")
    $$("#resume-confirm-form input[name=confirmed_fact_ids]").forEach(
      (x) => (x.checked = event.target.checked),
    );
  const checks = $$("#resume-confirm-form input[name=confirmed_fact_ids]"),
    selectedChecks = checks.filter((x) => x.checked);
  updateResumeConfirm();
  $("#resume-select-all").checked = checks.length > 0 && checks.length === selectedChecks.length;
  $("#resume-select-all").indeterminate =
    selectedChecks.length > 0 && selectedChecks.length < checks.length;
});
$("#resume-draft").addEventListener("submit", async (event) => {
  if (event.target.id !== "resume-confirm-form") return;
  event.preventDefault();
  const ids = $$("#resume-confirm-form input[name=confirmed_fact_ids]:checked").map((x) => x.value);
  if (!ids.length || resumeConfirmationBlocked()) return;
  const result = await action(
    "resume_confirm",
    { draft_id: state.candidate_draft.id, confirmed_fact_ids: ids },
    "正在确认本地事实…",
  );
  if (result) {
    $("#resume-dialog").close();
    renderProfile();
    toast("事实已确认并用于本地画像。可采用建议关键词后运行搜索。");
  }
});

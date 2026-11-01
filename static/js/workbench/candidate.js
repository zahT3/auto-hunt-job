// The fact editor: every fact keeps an id, source, confirmation, version and disclosure scope.
import { action } from "../shared/api.js";
import { $, $$, esc, fieldValue, items, openDialog, sourceOf } from "../shared/dom.js";
import { notice, toast } from "../shared/feedback.js";
import { state } from "../shared/state.js";

export let editFacts = [];
let draftCandidate = {};

export function openCandidate() {
  const c = state.candidate || {};
  draftCandidate = structuredClone(c);
  const f = $("#candidate-form");
  f.elements.name.value = c.name || fieldValue(c.fields?.name) || "";
  f.elements.real_profile.checked = !c.synthetic && !c.is_demo;
  for (const k of ["email", "phone", "city"]) f.elements[k].value = fieldValue(c.fields?.[k]);
  editFacts = structuredClone(items(c.facts));
  renderFactEditor();
  openDialog("#candidate-dialog");
}

export function renderFactEditor() {
  const container = $("#fact-editor");
  container.innerHTML =
    editFacts
      .map(
        (f, i) =>
          `<div class="fact-edit" data-index="${i}">` +
          `<label>事实 ${i + 1}<textarea class="fact-text" rows="3" required>${esc(f.text)}</textarea></label>` +
          `<label>原始来源 / 页码 / 确认记录<input class="fact-source" value="${esc(sourceOf(f) === "来源待补充" ? "" : sourceOf(f))}" required placeholder="例如：用户确认记录 2026-10-16；简历第 1 页"></label>` +
          `<div class="fact-options">` +
          `<label class="check-label"><input type="checkbox" class="fact-confirm" ${f.status === "confirmed" ? "checked" : ""}>我确认其准确</label>` +
          `<label class="check-label"><input type="checkbox" class="fact-disclose" ${["application", "public"].includes(f.disclosure) ? "checked" : ""}>可用于申请</label>` +
          `<button type="button" class="text-button" data-remove-fact="${i}">移除</button>` +
          `</div></div>`,
      )
      .join("") || '<p class="small-note">暂未添加经历。可逐项填写，或导入你指定的资料文件。</p>';
}

export function collectFacts() {
  editFacts = $$(".fact-edit").map((el, i) => {
    const previous = editFacts[i] || {},
      text = el.querySelector(".fact-text").value.trim();
    const next = {
      ...previous,
      id: previous.id || "fact-" + crypto.randomUUID(),
      version: Number(previous.version || 0) + 1,
      text,
      source: {
        ...(typeof previous.source === "object" ? previous.source : {}),
        kind: previous.source?.kind || "user_confirmation",
        reference: el.querySelector(".fact-source").value.trim(),
      },
      status: el.querySelector(".fact-confirm").checked ? "confirmed" : "unconfirmed",
      disclosure: el.querySelector(".fact-disclose").checked ? "application" : "private",
    };
    if (previous.text !== text) delete next.value;
    return next;
  });
  return editFacts;
}

export function removeFact(index) {
  collectFacts();
  editFacts.splice(index, 1);
  renderFactEditor();
}

$("#edit-candidate").addEventListener("click", openCandidate);
$("#add-fact").addEventListener("click", () => {
  collectFacts();
  editFacts.push({
    text: "",
    source: { type: "user_confirmed", reference: "" },
    status: "unconfirmed",
    id: "fact-" + crypto.randomUUID(),
    version: 1,
    disclosure: "private",
  });
  renderFactEditor();
  $(".fact-edit:last-child textarea")?.focus();
});
$("#candidate-file").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error("文件超过 2 MB，请选择较小的候选资料文件。");
    const raw = JSON.parse(await file.text()),
      c = raw.candidate || raw;
    draftCandidate = structuredClone(c);
    if (!Array.isArray(c.facts)) throw new Error("资料格式需要包含 facts 数组。");
    if (c.name) $("#candidate-form").elements.name.value = c.name;
    for (const k of ["email", "phone", "city"])
      if (c.fields?.[k]) $("#candidate-form").elements[k].value = fieldValue(c.fields[k]);
    $("#candidate-form").elements.real_profile.checked = !c.synthetic && !c.is_demo;
    editFacts = c.facts.map((f) => ({
      ...f,
      status: f.status || "unconfirmed",
      disclosure: f.disclosure || "private",
      version: f.version || 1,
    }));
    renderFactEditor();
    toast("资料已读入表单。核对来源和披露范围后保存。");
  } catch (err) {
    notice("无法导入资料：" + err.message, true);
  }
});
$("#candidate-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const facts = collectFacts();
  const real = f.elements.real_profile.checked;
  if (
    real &&
    facts.some((x) => sourceOf(x).startsWith("synthetic:") || x.id?.startsWith("demo-"))
  ) {
    notice("真实资料中仍有合成事实。请先移除这些事实，再保存真实资料。", true);
    return;
  }
  const fields = { ...draftCandidate.fields };
  for (const key of ["name", "email", "phone", "city"]) {
    const value = f.elements[key].value.trim();
    if (!value) {
      delete fields[key];
      continue;
    }
    const old = draftCandidate.fields?.[key];
    if (
      old &&
      fieldValue(old) === value &&
      items(old.fact_ids).every((id) => facts.some((x) => x.id === id))
    )
      continue;
    const id = "contact-" + key;
    const row = {
      id,
      text:
        { name: "姓名", email: "联系邮箱", phone: "联系电话", city: "当前城市" }[key] +
        "：" +
        value +
        "。",
      value,
      source: {
        kind: "user_confirmation",
        reference: "工作台用户确认 " + new Date().toISOString(),
      },
      status: "confirmed",
      version: 1,
      disclosure: "application",
      tags: [key === "name" ? "identity" : "contact"],
    };
    const idx = facts.findIndex((x) => x.id === id);
    if (idx >= 0) {
      row.version = Number(facts[idx].version || 0) + 1;
      facts[idx] = row;
    } else facts.push(row);
    fields[key] = { value, fact_ids: [id] };
  }
  const candidate = {
    ...draftCandidate,
    name: f.elements.name.value.trim(),
    synthetic: !real,
    is_demo: !real,
    fields,
    facts,
  };
  if (await action("candidate", { candidate }, "正在保存资料…")) {
    $("#candidate-dialog").close();
    toast("事实资料已保存。已有材料的批准会按版本重新核验。");
  }
});

// 定方向: fetch follow-up questions, answer them for 1-4 proposed directions, or pick directions from the table.
import { action } from "../shared/api.js";
import { $, $$, esc, items, openDialog, replaceContent } from "../shared/dom.js";
import { toast } from "../shared/feedback.js";
import { registerView } from "../shared/state.js";
import {
  ANSWER_CHARS,
  MAX_DIRECTIONS,
  MAX_TERMS,
  answersFrom,
  chosenDirections,
  configKeywords,
  factText,
  isMultiple,
  orientation,
  provenance,
  searchTerms,
  tableFamilies,
  termsFrom,
} from "./model.js";

// "steps" shows directions and questions; "pick" shows the direction table.
let orientMode = "steps";
// Set when 开始找岗位 found no direction and no keyword, so the dialog says why it opened.
let orientForSearch = false;
let pickTermsEdited = false;

function provenanceBadge(by) {
  const { label, kind } = provenance(by);
  return `<span class="badge ${kind}">${esc(label)}</span>`;
}

function conditionsLine(c) {
  if (!c) return "";
  const parts = [
    items(c.cities).length ? "城市 " + items(c.cities).join("、") : null,
    c.years ? "经验 " + c.years : null,
    c.remote === true ? "接受远程" : c.remote === false ? "只看线下" : null,
    items(c.exclude_industries).length ? "排除 " + items(c.exclude_industries).join("、") : null,
  ].filter(Boolean);
  return parts.length
    ? `<p class="orient-line"><strong>条件</strong><span>${parts.map(esc).join(" · ")}</span></p>`
    : "";
}

function directionItem(d) {
  const facts = items(d.fact_ids);
  const evidence = facts.length
    ? `<details data-disclosure="orient-facts-${esc(d.id)}"><summary>依据的事实 · ${facts.length} 项</summary><ul>` +
      facts
        .map((id) => {
          const text = factText(id);
          return `<li>${text ? esc(text) : `事实 ${esc(id)}（已不在资料中）`}</li>`;
        })
        .join("") +
      `</ul></details>`
    : '<p class="small-note">没有引用已确认的事实。</p>';
  return (
    `<li><strong>${esc(d.name || d.id)}</strong>` +
    `<p>${esc(d.why || "未写理由")}</p>` +
    directionTermsLine(items(d.terms)) +
    `${evidence}</li>`
  );
}

// The search uses only the merged list (at most 8 terms), so a direction's other terms are named as unsearched.
function directionTermsLine(terms) {
  if (!terms.length) return "";
  const merged = new Set(searchTerms());
  const used = terms.filter((t) => merged.has(t));
  const left = terms.filter((t) => !merged.has(t));
  return (
    `<p class="orient-direction-terms">搜索词：${used.length ? used.map(esc).join(" · ") : "无"}` +
    (left.length
      ? `<span class="small-note">；未进合并词表，本轮不搜：${left.map(esc).join(" · ")}</span>`
      : "") +
    `</p>`
  );
}

export function directionsSection() {
  const o = orientation();
  const rows = chosenDirections();
  if (!rows.length) return "";
  const terms = searchTerms();
  const proposed = ["ai", "rules"].includes(o.by);
  const keywords = configKeywords();
  return (
    `<section class="orient-section" aria-labelledby="orient-directions-title">` +
    `<div class="orient-section-head"><h3 id="orient-directions-title" tabindex="-1">${proposed ? "建议方向" : "已选方向"}</h3>${provenanceBadge(o.by)}</div>` +
    `<ol class="orient-directions">${rows.map(directionItem).join("")}</ol>` +
    `<p class="orient-line"><strong>${rows.some((d) => items(d.terms).length) ? "合并后的搜索词" : "搜索词"}</strong><span>${terms.length ? terms.map(esc).join(" · ") : "尚无搜索词"}</span></p>` +
    conditionsLine(o.conditions) +
    (keywords.length
      ? `<div class="warning-box">「设置与待办」里已填写关键词（${keywords.map(esc).join("、")}），搜索会优先使用这些关键词，不使用上面的搜索词。</div>`
      : "") +
    `<div class="orient-actions">` +
    `<button type="button" class="primary" data-orient-adopt>采用这些方向</button>` +
    `<button type="button" class="secondary" data-orient-pick>修改方向</button>` +
    `</div></section>`
  );
}

function questionField(q, i, previous) {
  const name = `orient-q-${i}`;
  const label = `${i + 1}. ${esc(q.text)}`;
  if (q.kind === "text")
    return (
      `<label class="orient-question">${label}` +
      `<input type="text" name="${name}" maxlength="${ANSWER_CHARS}" value="${esc(typeof previous === "string" ? previous : "")}" autocomplete="off"></label>`
    );
  const chosen = items(Array.isArray(previous) ? previous : previous ? [previous] : []);
  const type = isMultiple(q) ? "checkbox" : "radio";
  const options = items(q.options)
    .map(
      (option) =>
        `<label class="check-label"><input type="${type}" name="${name}" value="${esc(option)}" ${chosen.includes(option) ? "checked" : ""}>${esc(option)}</label>`,
    )
    .join("");
  // A radio group cannot be cleared once chosen, so it carries its own "no answer".
  const skip =
    type === "radio"
      ? `<label class="check-label"><input type="radio" name="${name}" value="" ${chosen.length ? "" : "checked"}>暂不回答</label>`
      : "";
  return (
    `<fieldset class="orient-question"><legend>${label}</legend>` +
    `<div class="orient-options">${options}${skip}</div></fieldset>`
  );
}

export function questionsSection() {
  const o = orientation() || {};
  const questions = items(o.questions);
  const hasDirections = chosenDirections().length > 0;
  let body;
  if (!questions.length)
    body =
      `<p class="small-note">3–6 个问题，补充简历里看不出来的意向行业、城市和经验。没有配置或同意使用模型时，用固定问题和本地规则。</p>` +
      `<div class="orient-actions">` +
      `<button type="button" class="${hasDirections ? "secondary" : "primary"}" data-orient-questions>获取问题</button>` +
      `<button type="button" class="text-button" data-orient-pick>跳过问题，直接选方向</button>` +
      `</div>`;
  else
    body =
      `<form id="orient-answer-form" class="orient-answer-form">` +
      questions.map((q, i) => questionField(q, i, (o.answers || {})[q.id])).join("") +
      `<div class="orient-actions">` +
      `<button type="submit" class="${hasDirections ? "secondary" : "primary"}">提交回答，给出方向</button>` +
      `<button type="button" class="text-button" data-orient-pick>跳过问题，直接选方向</button>` +
      `</div></form>`;
  const head =
    `<div class="orient-section-head"><h3 id="orient-questions-title" tabindex="-1">回答几个问题</h3>` +
    `${questions.length ? provenanceBadge(o.questions_by) : ""}</div>`;
  if (hasDirections)
    return (
      `<details class="orient-section orient-more" data-disclosure="orient-questions">` +
      `<summary>重新回答问题</summary>${head}${body}</details>`
    );
  return `<section class="orient-section" aria-labelledby="orient-questions-title">${head}${body}</section>`;
}

export function pickSection() {
  const chosen = new Set(chosenDirections().map((d) => d.id));
  const families = tableFamilies();
  const table = families.length
    ? families
        .map(({ family, rows }, i) => {
          const picked = rows.filter((r) => chosen.has(r.id)).length;
          return (
            `<details class="orient-family" data-disclosure="orient-family-${i}" ${picked ? "open" : ""}>` +
            `<summary>${esc(family)} <span class="count">${rows.length}</span>${picked ? ` · 已选 ${picked}` : ""}</summary>` +
            `<div class="orient-options">` +
            rows
              .map(
                (r) =>
                  `<label class="check-label"><input type="checkbox" name="direction" value="${esc(r.id)}" ${chosen.has(r.id) ? "checked" : ""}>${esc(r.name)}</label>`,
              )
              .join("") +
            `</div></details>`
          );
        })
        .join("")
    : '<div class="blocker-box">本地服务没有提供方向表，暂时不能直接选方向。可以先回答问题，或在「设置与待办」里填写关键词。</div>';
  return (
    `<form id="orient-pick-form" class="orient-section" aria-labelledby="orient-pick-title">` +
    `<div class="orient-section-head"><h3 id="orient-pick-title" tabindex="-1">直接选方向</h3>` +
    `<span id="orient-pick-count" class="small-note" aria-live="polite">已选 ${chosen.size} / ${MAX_DIRECTIONS}</span></div>` +
    `<p class="small-note">从方向表里选 1–${MAX_DIRECTIONS} 个。保存后记为你手动选择，不调用 AI。</p>` +
    `<div class="orient-table">${table}</div>` +
    `<label class="orient-terms-field">搜索词（可选，每行一个，最多 ${MAX_TERMS} 个）` +
    `<textarea name="terms" rows="3" placeholder="留空则按所选方向从方向表生成">${esc(searchTerms().join("\n"))}</textarea></label>` +
    `<p class="small-note">只改方向、不改搜索词时，保存后按新方向重新生成搜索词。</p>` +
    `<div class="dialog-actions">` +
    `<button type="button" class="text-button" data-orient-back>返回</button>` +
    `<button type="submit" class="primary" ${families.length ? "" : "disabled"}>保存方向</button>` +
    `</div></form>`
  );
}

export function orientBody() {
  const o = orientation() || {};
  const notes = items(o.notes);
  return (
    `<p class="muted">按已确认的简历事实给出 1–${MAX_DIRECTIONS} 个求职方向和搜索词，保存在本机。开始找岗位时用这些搜索词。</p>` +
    (orientForSearch && !chosenDirections().length
      ? '<div class="warning-box" role="alert">还没有搜索方向。先定方向再开始找岗位；也可以在「设置与待办」里直接填写关键词。</div>'
      : "") +
    (notes.length && orientMode !== "pick"
      ? `<div class="orient-notes">${notes.map((n) => `<p class="small-note">${esc(n)}</p>`).join("")}</div>`
      : "") +
    (orientMode === "pick" ? pickSection() : directionsSection() + questionsSection())
  );
}

function renderOrientEntry() {
  const rows = chosenDirections();
  $("#orient-open").textContent = rows.length
    ? "方向：" + rows.map((d) => d.name || d.id).join("、")
    : "定方向";
}

export function renderOrient() {
  renderOrientEntry();
  replaceContent("#orient-body", orientBody());
}

function focusSoon(selector) {
  $(selector)?.focus({ preventScroll: false });
}

export function openOrient({ forSearch = false } = {}) {
  orientForSearch = forSearch;
  orientMode = "steps";
  renderOrient();
  openDialog("#orient-dialog");
  focusSoon(chosenDirections().length ? "#orient-directions-title" : "#orient-questions-title");
}

function showPick() {
  orientMode = "pick";
  pickTermsEdited = false;
  renderOrient();
  updatePickLimit();
  focusSoon("#orient-pick-title");
}

function showSteps() {
  orientMode = "steps";
  renderOrient();
  focusSoon(chosenDirections().length ? "#orient-directions-title" : "#orient-questions-title");
}

export function updatePickLimit() {
  const boxes = $$("#orient-pick-form input[name=direction]");
  const count = boxes.filter((b) => b.checked).length;
  for (const b of boxes) b.disabled = !b.checked && count >= MAX_DIRECTIONS;
  const counter = $("#orient-pick-count");
  if (counter)
    counter.textContent =
      count >= MAX_DIRECTIONS
        ? `已选 ${count} / ${MAX_DIRECTIONS}，取消一个才能再选`
        : `已选 ${count} / ${MAX_DIRECTIONS}`;
}

export async function fetchQuestions() {
  if (await action("orient_questions", {}, "正在准备问题…")) focusSoon("#orient-questions-title");
}

export async function submitAnswers(form) {
  const questions = items(orientation()?.questions);
  const answers = answersFrom(questions, (q) => {
    const fields = Array.from(form.querySelectorAll(`[name="orient-q-${questions.indexOf(q)}"]`));
    if (q.kind === "text") return fields.map((f) => f.value);
    return fields.filter((f) => f.checked && f.value).map((f) => f.value);
  });
  if (await action("orient_answer", { answers }, "正在整理方向…")) {
    orientMode = "steps";
    renderOrient();
    focusSoon("#orient-directions-title");
  }
}

export async function savePick(form) {
  const ids = $$("#orient-pick-form input[name=direction]:checked").map((b) => b.value);
  const counter = $("#orient-pick-count");
  if (!ids.length || ids.length > MAX_DIRECTIONS) {
    if (counter) counter.textContent = `请选 1 到 ${MAX_DIRECTIONS} 个方向`;
    return;
  }
  const previous = new Map(chosenDirections().map((d) => [d.id, d.why]));
  const directions = ids.map((id) => (previous.get(id) ? { id, why: previous.get(id) } : { id }));
  const payload = { directions };
  const terms = termsFrom(form.elements.terms.value);
  if (terms.length > MAX_TERMS) {
    if (counter) counter.textContent = `搜索词最多 ${MAX_TERMS} 个，现在有 ${terms.length} 个`;
    return;
  }
  if (terms.length) payload.terms = terms;
  if (await action("directions_set", payload, "正在保存方向…")) {
    orientMode = "steps";
    renderOrient();
    focusSoon("#orient-directions-title");
    toast("方向已保存。开始找岗位时使用这些搜索词。");
  }
}

function adopt() {
  const rows = chosenDirections();
  $("#orient-dialog").close();
  $("#run-button").focus();
  toast(
    configKeywords().length
      ? `已采用 ${rows.length} 个方向。设置里已有关键词，搜索会先用关键词。`
      : `已采用 ${rows.length} 个方向。点「开始找岗位」，按这些搜索词搜索。`,
  );
}

registerView({
  render: renderOrient,
  busy(value, label) {
    const status = $("#orient-status");
    status.hidden = !value || !$("#orient-dialog").open;
    status.textContent = value ? label || "正在处理…" : "";
    $("#orient-dialog").setAttribute("aria-busy", String(value));
  },
});

$("#orient-open").addEventListener("click", () => openOrient());
$("#orient-dialog").addEventListener("close", () => {
  orientForSearch = false;
  orientMode = "steps";
});
$("#orient-dialog").addEventListener("click", (e) => {
  if (e.target.closest("[data-orient-questions]")) fetchQuestions();
  else if (e.target.closest("[data-orient-pick]")) showPick();
  else if (e.target.closest("[data-orient-back]")) showSteps();
  else if (e.target.closest("[data-orient-adopt]")) adopt();
});
$("#orient-dialog").addEventListener("submit", (e) => {
  e.preventDefault();
  if (e.target.id === "orient-answer-form") submitAnswers(e.target);
  if (e.target.id === "orient-pick-form") savePick(e.target);
});
$("#orient-dialog").addEventListener("change", (e) => {
  if (e.target.name !== "direction") return;
  // Old terms belong to the old directions; unless the user wrote their own, let the server regenerate them.
  if (!pickTermsEdited) $("#orient-pick-form").elements.terms.value = "";
  updatePickLimit();
});
$("#orient-dialog").addEventListener("input", (e) => {
  if (e.target.name === "terms") pickTermsEdited = true;
});

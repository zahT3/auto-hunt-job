// 定方向 (#/orient): your answers and the open questions on the left, the proposed directions side by side on the
// right, then what not to apply for first and what to do today. Reads state.orientation; writes through
// orient_questions, orient_answer and directions_set.
import { action } from "../shared/api.js";
import { $, $$, esc, items, motionBehavior, replaceContent } from "../shared/dom.js";
import { toast } from "../shared/feedback.js";
import { state } from "../shared/state.js";
import { clock } from "../shared/time.js";
import { factChip, jdRefs, stateWord } from "../shared/ui.js";
import { runSearch, searchQuery } from "../search/page.js";
import { go, registerPage, route } from "../shell/router.js";
import { openCandidate } from "../workbench/candidate.js";
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

const SHORT_Q = {
  family: "行业",
  city: "城市",
  years: "经验年限",
  remote: "远程",
  exclude: "排除的行业",
  switch: "转方向",
  english: "英语",
  start: "到岗时间",
};
const NEXT = {
  search: ["开始找岗位", "搜索"],
  answer_question: ["去回答", "追问"],
  add_fact: ["补充事实", "补充事实"],
  confirm_fact: ["去确认", "确认事实"],
  job_match: ["看匹配解释", "单岗匹配"],
};

// "steps" shows answers, questions and the comparison; "pick" swaps the comparison for the direction table.
export let orientMode = "steps";
// Set when 开始搜索 found neither a direction nor a keyword, so the page says why it opened.
let orientForSearch = false;
let pickTermsEdited = false;
// Answered questions the user chose to change; they go back into the question form.
const editing = new Set();

const companyOf = (jobId) => items(state?.jobs).find((j) => j.id === jobId)?.company || "";
const answered = (o, q) => o.answers && o.answers[q.id] != null && o.answers[q.id] !== "";
const answerText = (v) => (Array.isArray(v) ? v.join("、") : v) || "没填";

function provenanceBadge(by) {
  const { label, kind } = provenance(by);
  return `<span class="badge ${kind}">${esc(label)}</span>`;
}

function conditionsLine(c) {
  if (!c) return "";
  const remote = c.remote === true ? "接受" : c.remote === false ? "只看线下" : "没说";
  return (
    `<p class="conds">搜索条件：城市 ${esc(items(c.cities).join("、") || "不限")}；年限 ${esc(c.years || "不限")}；` +
    `远程 ${remote}；排除 ${esc(items(c.exclude_industries).join("、") || "无")}。</p>`
  );
}

function questionField(q, i, previous, ai) {
  const name = `orient-q-${i}`;
  const label = `${esc(q.text)}${ai ? '<span class="ai">AI 追问</span>' : ""}`;
  if (q.kind === "text")
    return (
      `<div class="fq" id="q-${esc(q.id)}"><label class="orient-question">${label}` +
      `<input type="text" name="${name}" maxlength="${ANSWER_CHARS}" value="${esc(typeof previous === "string" ? previous : "")}" autocomplete="off"></label></div>`
    );
  const chosen = items(Array.isArray(previous) ? previous : previous ? [previous] : []);
  const type = isMultiple(q) ? "checkbox" : "radio";
  const options = items(q.options)
    .map(
      (option) =>
        `<label><input type="${type}" name="${name}" value="${esc(option)}" ${chosen.includes(option) ? "checked" : ""}> ${esc(option)}</label>`,
    )
    .join("");
  // A radio group cannot be cleared once chosen, so it carries its own "no answer".
  const skip =
    type === "radio"
      ? `<label><input type="radio" name="${name}" value="" ${chosen.length ? "" : "checked"}> 暂不回答</label>`
      : "";
  return (
    `<div class="fq" id="q-${esc(q.id)}"><fieldset><legend>${label}</legend>` +
    `<div class="opts">${options}${skip}</div></fieldset></div>`
  );
}

export function answersSection() {
  const o = orientation() || {};
  const questions = items(o.questions);
  const done = questions.filter((q) => answered(o, q));
  const rows = done.length
    ? `<dl class="answers">${done
        .map(
          (q) =>
            `<dt>${esc(SHORT_Q[q.id] || q.text)}</dt><dd>${esc(answerText(o.answers[q.id]))}</dd>` +
            `<dd><button type="button" class="linkish" data-orient-edit="${esc(q.id)}" aria-label="改：${esc(SHORT_Q[q.id] || q.text)}">改</button></dd>`,
        )
        .join("")}</dl>`
    : '<p class="sub">还没有回答。</p>';
  return (
    `<div class="sec-h"><h2 id="o1">你的回答</h2><span class="tally">${done.length} 个</span></div>` +
    rows +
    conditionsLine(o.conditions)
  );
}

export function questionsSection() {
  const o = orientation() || {};
  const questions = items(o.questions);
  const open = questions.filter((q) => !answered(o, q) || editing.has(q.id));
  const head = `<div class="sec-h gap"><h2 id="orient-questions-title" tabindex="-1">追问</h2>`;
  if (!questions.length)
    return (
      head +
      `<span class="tally">还没取</span></div>` +
      `<p class="sub">3–6 个问题，补充简历里看不出来的意向行业、城市和经验。没有配置或同意使用模型时，用固定问题和本地规则。</p>` +
      `<div class="adopt"><button type="button" class="btn btn-primary" data-orient-questions>获取问题</button>` +
      `<button type="button" class="btn" data-orient-pick>跳过问题，直接选方向</button></div>`
    );
  const ai = o.questions_by === "ai";
  const by = `<span class="tally">${open.length} 个，回答后会重新给方向 · ${esc(provenance(o.questions_by).label)}</span></div>`;
  if (!open.length)
    return (
      head +
      by +
      `<p class="sub">都回答了。要改哪一条，点左边的「改」。</p>` +
      `<div class="adopt"><button type="button" class="btn" data-orient-questions>换一组问题</button></div>`
    );
  return (
    head +
    by +
    `<form id="orient-answer-form">` +
    open.map((q) => questionField(q, questions.indexOf(q), (o.answers || {})[q.id], ai)).join("") +
    `<div class="adopt"><button type="submit" class="btn btn-primary">提交回答，重新给方向</button>` +
    `<button type="button" class="btn" data-orient-pick>跳过问题，直接选方向</button></div></form>`
  );
}

const pointList = (list) =>
  items(list).length
    ? `<ul>${items(list)
        .map(
          (x) =>
            `<li>${esc(x.text)}<span class="refs">${items(x.fact_ids).map(factChip).join("")}${jdRefs(x.jd, companyOf)}</span></li>`,
        )
        .join("")}</ul>`
    : stateWord("muted", "没有依据可写");

const sourceLabel = (s) =>
  s === "ai" ? "AI 建议" : s === "rules" ? "本地规则" : s === "agent" ? "本机助手" : "你选的";

export function directionsSection() {
  const o = orientation();
  const rows = chosenDirections();
  const head = `<div class="sec-h"><h2 id="orient-directions-title" tabindex="-1">建议方向</h2>`;
  if (!rows.length)
    return (
      head +
      `</div><div class="empty flush"><p>还没有方向。回答左边的问题，或者直接从方向表里选。</p>` +
      `<button type="button" class="btn" data-orient-pick>直接选方向</button></div>`
    );
  const merged = searchTerms();
  const keywords = configKeywords();
  const cell = (d, inner) => `<td data-dir="${esc(d.name || d.id)}">${inner}</td>`;
  const termCell = (d) =>
    items(d.terms).length
      ? items(d.terms)
          .map((t) => {
            const on = merged.includes(t);
            return `<span class="term${on ? "" : " off"}" tabindex="0" data-tip="${on ? "在合并后的 8 个词里，本轮会搜" : "本轮不搜：合并后只保留 8 个词"}">${esc(t)}${on ? "" : "（本轮不搜）"}</span>`;
          })
          .join("")
      : stateWord("muted", "这个方向没有单独的搜索词");
  return (
    head +
    `<span class="tally">${rows.length} 个 · ${esc(provenance(o.by).label)}；优势、短板、风险每条都有事实或 JD 依据</span></div>` +
    `<table class="compare"><thead><tr><th></th>${rows
      .map(
        (d) =>
          `<th scope="col"><span class="nm">${esc(d.name || d.id)}</span><span class="src">${esc(sourceLabel(d.source || o.by))}</span></th>`,
      )
      .join("")}</tr></thead><tbody>` +
    `<tr><th scope="row">理由</th>${rows
      .map((d) =>
        cell(
          d,
          `<span class="why">${esc(d.why || "未写理由")}</span><span class="refs">${items(d.fact_ids).map(factChip).join("")}</span>`,
        ),
      )
      .join("")}</tr>` +
    ["strengths", "gaps", "risks"]
      .map(
        (k, i) =>
          `<tr><th scope="row">${["优势", "短板", "风险"][i]}</th>${rows.map((d) => cell(d, pointList(d[k]))).join("")}</tr>`,
      )
      .join("") +
    `<tr><th scope="row">搜索词</th>${rows.map((d) => cell(d, termCell(d))).join("")}</tr>` +
    `</tbody></table>` +
    `<p class="conds">合并后的搜索词：${merged.length ? esc(merged.join(" · ")) : "尚无搜索词"}</p>` +
    (keywords.length
      ? `<p class="warnline">设置里已填写关键词（${esc(keywords.join("、"))}），搜索会优先使用这些关键词，不使用上面的搜索词。</p>`
      : "") +
    `<div class="adopt"><button class="btn btn-primary" type="button" data-orient-adopt>采用这 ${rows.length} 个方向</button>` +
    `<button class="btn" type="button" data-orient-pick>修改方向</button></div>`
  );
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
            `<div class="opts">` +
            rows
              .map(
                (r) =>
                  `<label><input type="checkbox" name="direction" value="${esc(r.id)}" ${chosen.has(r.id) ? "checked" : ""}> ${esc(r.name)}</label>`,
              )
              .join("") +
            `</div></details>`
          );
        })
        .join("")
    : '<p class="warnline">本地服务没有提供方向表，暂时不能直接选方向。可以先回答问题，或在设置里填写关键词。</p>';
  return (
    `<form id="orient-pick-form" aria-labelledby="orient-pick-title">` +
    `<div class="sec-h"><h2 id="orient-pick-title" tabindex="-1">直接选方向</h2>` +
    `<span id="orient-pick-count" class="tally" aria-live="polite">已选 ${chosen.size} / ${MAX_DIRECTIONS}</span></div>` +
    `<p class="sub">从方向表里选 1–${MAX_DIRECTIONS} 个。保存后记为你手动选择，不调用 AI。</p>` +
    `<div class="orient-table">${table}</div>` +
    `<label class="field">搜索词（可选，每行一个，最多 ${MAX_TERMS} 个）` +
    `<textarea name="terms" rows="3" placeholder="留空则按所选方向从方向表生成">${esc(searchTerms().join("\n"))}</textarea></label>` +
    `<p class="sub">只改方向、不改搜索词时，保存后按新方向重新生成搜索词。</p>` +
    `<div class="adopt"><button type="submit" class="btn btn-primary" ${families.length ? "" : "disabled"}>保存方向</button>` +
    `<button type="button" class="btn" data-orient-back>返回</button></div></form>`
  );
}

export function notRecommendedSection() {
  const list = items(orientation()?.not_recommended);
  return (
    `<div class="sec-h"><h2 id="o3">暂不建议优先投</h2></div><ul class="notnow">` +
    (list.length
      ? list
          .map(
            (x) =>
              `<li><b>${esc(x.name || x.id)}</b><span>${esc(x.why || "")}${items(x.fact_ids).map(factChip).join("")}${jdRefs(x.jd, companyOf)}</span></li>`,
          )
          .join("")
      : "<li><span>没有。</span></li>") +
    `</ul>`
  );
}

export function nextActionsSection() {
  const list = items(orientation()?.next_actions);
  return (
    `<div class="sec-h"><h2 id="o4">今天就能做</h2><span class="tally">按先后排</span></div><ul class="tasks">` +
    (list.length
      ? list
          .map((a) => {
            const [verb, kind] = NEXT[a.kind] || ["去看看", a.kind];
            return `<li><span>${esc(a.text)}</span><button class="btn" type="button" data-next="${esc(a.id)}">${esc(verb)}</button><span class="kind">${esc(kind)}</span></li>`;
          })
          .join("")
      : "<li><span>回答问题或选定方向后，这里会列出下一步。</span></li>") +
    `</ul>`
  );
}

export function orientBody() {
  const o = orientation() || {};
  const confirmed = items(state?.candidate?.facts).filter((f) => f.status === "confirmed").length;
  const by =
    o.by === "ai"
      ? `，AI 起草（${esc(state?.ai?.consent?.model || state?.ai?.settings?.model || "模型")}）`
      : o.by
        ? `，${esc(provenance(o.by).label)}`
        : "";
  const updated = o.updated_at ? `，${esc(clock(o.updated_at))} 更新` : "";
  const notes = items(o.notes);
  return (
    `<div class="page"><header class="page-h"><h1>定方向</h1>` +
    `<p>按 ${confirmed} 条已确认事实和你的回答给出${by}${updated}。采用后，搜索会用合并后的搜索词。</p>` +
    (orientForSearch && !chosenDirections().length
      ? '<p class="warnline" role="alert">还没有搜索方向。先定方向再开始搜索；也可以在设置里直接填写关键词。</p>'
      : "") +
    (notes.length && orientMode !== "pick"
      ? notes.map((n) => `<p class="sub">${esc(n)}</p>`).join("")
      : "") +
    `</header><div class="cols2">` +
    `<section aria-labelledby="o1">${answersSection()}${questionsSection()}</section>` +
    `<section aria-labelledby="${orientMode === "pick" ? "orient-pick-title" : "orient-directions-title"}">${orientMode === "pick" ? pickSection() : directionsSection()}</section>` +
    `<section class="wide" aria-labelledby="o3">${notRecommendedSection()}</section>` +
    `<section class="wide" aria-labelledby="o4">${nextActionsSection()}</section>` +
    `</div></div>`
  );
}

export function renderOrient() {
  replaceContent("#view", orientBody());
}

function focusSoon(selector) {
  $(selector)?.focus({ preventScroll: false });
}

// From 开始搜索 with nothing to search for.
export function openOrient({ forSearch = false } = {}) {
  orientForSearch = forSearch;
  orientMode = "steps";
  if (route().page === "orient") {
    renderOrient();
    focusSoon("#view h1");
  } else go("orient");
}

export function showPick() {
  orientMode = "pick";
  pickTermsEdited = false;
  renderOrient();
  updatePickLimit();
  focusSoon("#orient-pick-title");
}

export function showSteps() {
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
  if (await action("orient_questions", {}, "正在准备问题…")) {
    editing.clear();
    focusSoon("#orient-questions-title");
  }
}

// orient_answer replaces the saved answers, so the ones not in the form are sent again unchanged.
export async function submitAnswers(form) {
  const o = orientation() || {};
  const questions = items(o.questions);
  const asked = answersFrom(
    questions.filter(
      (q) => form.querySelectorAll(`[name="orient-q-${questions.indexOf(q)}"]`).length,
    ),
    (q) => {
      const fields = Array.from(form.querySelectorAll(`[name="orient-q-${questions.indexOf(q)}"]`));
      if (q.kind === "text") return fields.map((f) => f.value);
      return fields.filter((f) => f.checked && f.value).map((f) => f.value);
    },
  );
  const kept = Object.fromEntries(
    Object.entries(o.answers || {}).filter(
      ([id]) =>
        !form.querySelectorAll(`[name="orient-q-${questions.findIndex((q) => q.id === id)}"]`)
          .length,
    ),
  );
  if (await action("orient_answer", { answers: { ...kept, ...asked } }, "正在整理方向…")) {
    editing.clear();
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
    toast("方向已保存。开始搜索时使用这些搜索词。");
  }
}

export function adopt() {
  const rows = chosenDirections();
  $("#run-button").focus();
  toast(
    configKeywords().length
      ? `已采用 ${rows.length} 个方向。设置里已有关键词，搜索会先用关键词。`
      : `已采用 ${rows.length} 个方向。点「开始搜索」，按这些搜索词搜索。`,
  );
}

function editQuestion(id) {
  editing.add(id);
  renderOrient();
  const box = $(`#q-${CSS.escape(id)}`);
  box?.scrollIntoView({ block: "center", behavior: motionBehavior() });
  box?.querySelector("input")?.focus({ preventScroll: true });
}

function runNext(id) {
  const a = items(orientation()?.next_actions).find((x) => x.id === id);
  if (!a) return;
  const t = a.target || {};
  if (a.kind === "search") {
    Object.assign(searchQuery, { q: "", direction: t.direction_id || null });
    go("search");
    runSearch();
  } else if (a.kind === "job_match" && t.job_id) go("job/" + encodeURIComponent(t.job_id));
  else if (a.kind === "answer_question" && t.question_id) editQuestion(t.question_id);
  else if (a.kind === "add_fact") {
    openCandidate();
    toast(
      `在事实资料里补充${t.requirement ? `「${t.requirement}」` : "这项"}的依据，确认后再回来。`,
    );
  } else if (a.kind === "confirm_fact") {
    openCandidate();
    if (t.fact_id) toast(`确认 ${t.fact_id}：${factText(t.fact_id) || "这条事实"}`);
  }
}

registerPage("orient", {
  title: "定方向",
  render: renderOrient,
  leave() {
    orientForSearch = false;
    orientMode = "steps";
    editing.clear();
  },
});

document.addEventListener("click", (e) => {
  if (!e.target.closest?.("#view")) return;
  if (e.target.closest("[data-orient-questions]")) fetchQuestions();
  else if (e.target.closest("[data-orient-pick]")) showPick();
  else if (e.target.closest("[data-orient-back]")) showSteps();
  else if (e.target.closest("[data-orient-adopt]")) adopt();
  else if (e.target.closest("[data-orient-edit]"))
    editQuestion(e.target.closest("[data-orient-edit]").dataset.orientEdit);
  else if (e.target.closest("[data-next]")) runNext(e.target.closest("[data-next]").dataset.next);
});
document.addEventListener("submit", (e) => {
  if (e.target.id === "orient-answer-form") {
    e.preventDefault();
    submitAnswers(e.target);
  }
  if (e.target.id === "orient-pick-form") {
    e.preventDefault();
    savePick(e.target);
  }
});
document.addEventListener("change", (e) => {
  if (e.target.name !== "direction" || !e.target.closest?.("#orient-pick-form")) return;
  // Old terms belong to the old directions; unless the user wrote their own, let the server regenerate them.
  if (!pickTermsEdited) $("#orient-pick-form").elements.terms.value = "";
  updatePickLimit();
});
document.addEventListener("input", (e) => {
  if (e.target.name === "terms" && e.target.closest?.("#orient-pick-form")) pickTermsEdited = true;
});

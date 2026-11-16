// The résumé structure step of the résumé dialog: sections, entries and the company / title / dates cut from each
// entry head. Rules pre-fill it (structure_get); the user corrects and confirms it once (structure_save).
// A field can only point at a piece of the head line's own text, so the structure never holds words of its own.
import { action } from "../shared/api.js";
import { $, esc } from "../shared/dom.js";
import { toast } from "../shared/feedback.js";
import { busy, state } from "../shared/state.js";

const STRUCTURE_FIELDS = [
  ["company", "公司"],
  ["title", "职位"],
  ["start", "开始"],
  ["end", "结束"],
];
// The stored field names stay company / title; what they are called depends on the section.
const STRUCTURE_FIELD_NAMES = {
  education: { company: "学校", title: "学历或专业" },
  project: { company: "项目", title: "角色" },
};
export function structureFieldLabel(sectionKey, name, fallback) {
  return STRUCTURE_FIELD_NAMES[sectionKey]?.[name] || fallback;
}
const STRUCTURE_LABELS = {
  basic: "基本信息",
  education: "教育",
  work: "工作经历",
  internship: "实习经历",
  project: "项目经历",
  skills: "技能",
  certificates: "证书",
  awards: "奖项",
  summary: "自我评价",
  other: "其他",
};
const STRUCTURE_ENTRY_KEYS = ["education", "work", "internship", "project"];
let structureWork = null; // {structure, base, facts: Map, fragments}
let structureFocus = null;

// Spans count code points, like the Python side, not UTF-16 units.
const structureChars = (text) => Array.from(text || "");
export function structureSlice(text, span) {
  return span ? structureChars(text).slice(span[0], span[1]).join("") : "";
}

export function structureBlockers(structure) {
  let uncertain = 0,
    stale = 0;
  for (const section of structure.sections)
    for (const entry of section.entries) {
      if (entry.status === "stale") stale++;
      for (const field of Object.values(entry.fields)) if (field.confidence === "uncertain") uncertain++;
    }
  return { uncertain, stale, unassigned: structure.unassigned.length };
}

function structureFind(structure, entryId) {
  for (const section of structure.sections) {
    const index = section.entries.findIndex((e) => e.id === entryId);
    if (index >= 0) return { section, index, entry: section.entries[index] };
  }
  return null;
}

function structureRemoveFact(structure, factId) {
  structure.unassigned = structure.unassigned.filter((r) => r.id !== factId);
  for (const section of structure.sections)
    for (const entry of section.entries) entry.bullets = entry.bullets.filter((r) => r.id !== factId);
}

// Move a bullet line or an unassigned line to an entry, or to "unassigned". Head lines move only by merging.
export function structureMoveFact(structure, factId, target, version) {
  const found = structure.sections.flatMap((s) => s.entries).some((e) => e.head?.id === factId);
  if (found) return false;
  const ref = { id: factId, version };
  if (target === "unassigned") {
    structureRemoveFact(structure, factId);
    structure.unassigned.push(ref);
    return true;
  }
  const place = structureFind(structure, target);
  if (!place) return false;
  structureRemoveFact(structure, factId);
  place.entry.bullets.push(ref);
  return true;
}

// A bullet becomes the head of a new entry that takes the bullets after it; its fields start as `uncertain`.
export function structureSplit(structure, entryId, factId) {
  const place = structureFind(structure, entryId);
  if (!place || !STRUCTURE_ENTRY_KEYS.includes(place.section.key)) return false;
  const at = place.entry.bullets.findIndex((b) => b.id === factId);
  if (at < 0) return false;
  const next =
    1 +
    Math.max(
      0,
      ...structure.sections.flatMap((s) => s.entries.map((e) => Number(/^n(\d+)$/.exec(e.id)?.[1] || 0))),
    );
  const fields = Object.fromEntries(STRUCTURE_FIELDS.map(([name]) => [name, { span: null, confidence: "uncertain" }]));
  const rest = place.entry.bullets.splice(at);
  const head = rest.shift();
  place.section.entries.splice(place.index + 1, 0, { id: "n" + next, status: "ok", head, fields, bullets: rest });
  return true;
}

// An entry is folded into the one before it in the same section: its head line becomes a bullet.
export function structureMerge(structure, entryId) {
  const place = structureFind(structure, entryId);
  if (!place || place.index === 0) return false;
  const previous = place.section.entries[place.index - 1];
  if (place.entry.head) previous.bullets.push(place.entry.head);
  previous.bullets.push(...place.entry.bullets);
  place.section.entries.splice(place.index, 1);
  return true;
}

export function structureSetField(structure, entryId, name, span) {
  const place = structureFind(structure, entryId);
  if (!place || !place.entry.fields[name]) return false;
  place.entry.fields[name] = { span, confidence: "ok" };
  return true;
}

export function structureConfirmEntry(structure, entryId) {
  const place = structureFind(structure, entryId);
  if (!place) return false;
  for (const field of Object.values(place.entry.fields)) field.confidence = "ok";
  return true;
}

// Stale entry: point its references at the facts as they are now. The fields stay uncertain until the user settles them.
export function structureAdopt(structure, entryId, versions) {
  const place = structureFind(structure, entryId);
  if (!place) return false;
  const entry = place.entry;
  for (const item of [entry.head, ...entry.bullets]) if (item && versions.has(item.id)) item.version = versions.get(item.id);
  entry.status = "ok";
  return true;
}

function structureText(id) {
  return structureWork.facts.get(id)?.text || "";
}

function structureHeadHtml(entry, sectionKey) {
  const chars = structureChars(structureText(entry.head?.id));
  const marks = STRUCTURE_FIELDS.map(([name, label]) => ({ ...entry.fields[name], label: structureFieldLabel(sectionKey, name, label) }))
    .filter((f) => f.span)
    .sort((a, b) => a.span[0] - b.span[0]);
  let html = "",
    at = 0;
  for (const mark of marks) {
    if (mark.span[0] < at) continue;
    html +=
      esc(chars.slice(at, mark.span[0]).join("")) +
      `<mark class="ev ${mark.confidence === "ok" ? "ev-ok" : "ev-kw-related"}" title="${esc(mark.label)}">${esc(chars.slice(mark.span[0], mark.span[1]).join(""))}</mark>`;
    at = mark.span[1];
  }
  return html + esc(chars.slice(at).join(""));
}

function structureFieldHtml(entry, [name, label], sectionKey) {
  label = structureFieldLabel(sectionKey, name, label);
  const field = entry.fields[name],
    text = structureText(entry.head?.id),
    options = [...(structureWork.fragments[entry.head?.id] || [])];
  if (field.span && !options.some((o) => o.span[0] === field.span[0] && o.span[1] === field.span[1]))
    options.push({ span: field.span, text: structureSlice(text, field.span) });
  const chosen = field.span ? field.span.join(":") : "";
  const list =
    `<option value=""${chosen === "" ? " selected" : ""}>（留空）</option>` +
    options
      .map((o) => {
        const value = o.span.join(":");
        return `<option value="${value}"${value === chosen ? " selected" : ""}>${esc(o.text)}</option>`;
      })
      .join("");
  const flag = field.confidence === "uncertain" ? ' <span class="badge warn">待核对</span>' : "";
  return `<label>${esc(label)}${flag}<select data-entry="${esc(entry.id)}" data-field="${name}" ${entry.head && !busy ? "" : "disabled"}>${list}</select></label>`;
}

function structureTargets(structure, selected) {
  const entries = structure.sections.flatMap((section) =>
    section.entries.map((entry) => {
      const head = structureText(entry.head?.id) || structureText(section.title_fact?.id) || "（无条目头）";
      const label = STRUCTURE_LABELS[section.key] + " · " + structureChars(head).slice(0, 18).join("");
      return `<option value="${esc(entry.id)}"${entry.id === selected ? " selected" : ""}>${esc(label)}</option>`;
    }),
  );
  return entries.join("");
}

function structureBulletHtml(structure, entry, section, ref) {
  const split = STRUCTURE_ENTRY_KEYS.includes(section.key)
    ? ` <button type="button" class="secondary" data-act="split" data-entry="${esc(entry.id)}" data-fact="${esc(ref.id)}">作为新条目</button>`
    : "";
  return (
    `<li>${esc(structureText(ref.id))}<br><label>移到<select data-move="${esc(ref.id)}">` +
    `${structureTargets(structure, entry.id)}<option value="unassigned">未分配</option></select></label>${split}</li>`
  );
}

function structureEntryHtml(structure, section, entry, index) {
  const stale = entry.status === "stale";
  const open = Object.values(entry.fields).filter((f) => f.confidence === "uncertain").length;
  const badge = stale
    ? '<span class="badge warn">事实已变</span>'
    : open
      ? `<span class="badge warn">${open} 项待核对</span>`
      : '<span class="badge neutral">已核对</span>';
  const isEntry = STRUCTURE_ENTRY_KEYS.includes(section.key);
  const head = entry.head ? `<p><strong>${structureHeadHtml(entry, section.key)}</strong> ${badge}</p>` : `<p><em>没有条目头</em> ${badge}</p>`;
  const fields = isEntry
    ? `<div class="form-pair">${STRUCTURE_FIELDS.map((f) => structureFieldHtml(entry, f, section.key)).join("")}</div>`
    : "";
  const buttons = [
    stale
      ? `<button type="button" class="secondary" data-act="adopt" data-entry="${esc(entry.id)}">按当前事实重新核对</button>`
      : isEntry && open
        ? `<button type="button" class="secondary" data-act="confirm-entry" data-entry="${esc(entry.id)}">拆分无误，全部确认</button>`
        : "",
    index > 0
      ? `<button type="button" class="secondary" data-act="merge" data-entry="${esc(entry.id)}">并入上一条</button>`
      : "",
  ].join(" ");
  const bullets = entry.bullets.length
    ? `<ul>${entry.bullets.map((b) => structureBulletHtml(structure, entry, section, b)).join("")}</ul>`
    : "";
  return `<div class="profile-readout" data-entry-block="${esc(entry.id)}">${head}${fields}${bullets}<p>${buttons}</p></div>`;
}

export function structurePageHtml() {
  const { structure } = structureWork,
    blockers = structureBlockers(structure);
  const sections = structure.sections
    .map((section) => {
      const title = structureText(section.title_fact?.id) || STRUCTURE_LABELS[section.key];
      const same = section.entries.some((e) => e.head?.id === section.title_fact?.id);
      const heading = same ? STRUCTURE_LABELS[section.key] : title;
      const body = section.entries.map((e, i) => structureEntryHtml(structure, section, e, i)).join("");
      return `<h4>${esc(heading)}</h4>${body || '<p class="small-note">这个章节下没有内容。</p>'}`;
    })
    .join("");
  const unassigned = structure.unassigned.length
    ? `<h4>未分配的事实 <span class="badge warn">待放入</span></h4><p class="small-note">这些事实不属于任何条目，定制简历时不会使用；拿不准的行也在这里，请看一眼要不要放进某个条目。</p><ul>` +
      structure.unassigned
        .map(
          (r) =>
            `<li>${esc(structureText(r.id))}<br><label>放入<select data-move="${esc(r.id)}"><option value="unassigned" selected>未分配</option>${structureTargets(structure, "")}</select></label></li>`,
        )
        .join("") +
      "</ul>"
    : "";
  const waiting = blockers.uncertain + blockers.stale;
  const note = waiting
    ? `<div class="warning-box"><p>还有 ${blockers.uncertain} 个字段、${blockers.stale} 个条目待核对，核对完才能确认结构。</p></div>`
    : structure.status === "confirmed"
      ? `<p class="small-note">简历结构已确认（第 ${structure.version} 版）。</p>`
      : '<p class="small-note">全部字段已核对，可以确认结构。</p>';
  return (
    `<div class="draft-heading"><h3 id="resume-structure-title" tabindex="-1">确认简历结构</h3>` +
    `<span class="badge ${structure.status === "confirmed" && !waiting ? "neutral" : "warn"}">${structure.status === "confirmed" && !waiting ? "已确认" : "待确认"}</span></div>` +
    `<p class="small-note">程序按文字规则把事实分成章节和条目。公司、职位和时间只能从该行原文里选，也可以留空；定制简历时按这里的分组调整顺序。</p>` +
    note +
    sections +
    unassigned +
    `<div class="dialog-actions"><button type="button" class="secondary" data-act="save"${busy ? " disabled" : ""}>保存进度</button>` +
    `<button type="button" class="primary" data-act="confirm"${busy || waiting ? " disabled" : ""}>确认结构</button></div>`
  );
}

function structureRender() {
  const host = structureHost();
  if (!structureWork) return;
  host.innerHTML = structurePageHtml();
  if (structureFocus) {
    const [attr, value] = structureFocus;
    const target = $(`#resume-structure [${attr}="${value}"]`);
    target?.focus?.({ preventScroll: true });
  }
}

function structureSpan(value) {
  return value ? value.split(":").map(Number) : null;
}

export function structureChange(target) {
  if (!structureWork || busy) return;
  const structure = structureWork.structure;
  if (target.dataset.field) {
    structureSetField(structure, target.dataset.entry, target.dataset.field, structureSpan(target.value));
    structureFocus = ["data-field", target.dataset.field];
  } else if (target.dataset.move) {
    structureMoveFact(structure, target.dataset.move, target.value, structureWork.facts.get(target.dataset.move)?.version ?? 1);
    structureFocus = null;
  } else return;
  structureRender();
}

export async function structureClick(button) {
  if (!structureWork || busy) return;
  const structure = structureWork.structure,
    act = button.dataset.act,
    entry = button.dataset.entry;
  if (act === "confirm-entry") structureConfirmEntry(structure, entry);
  else if (act === "merge") structureMerge(structure, entry);
  else if (act === "split") structureSplit(structure, entry, button.dataset.fact);
  else if (act === "adopt") {
    const versions = new Map([...structureWork.facts].map(([id, f]) => [id, f.version]));
    structureAdopt(structure, entry, versions);
  } else if (act === "save" || act === "confirm") {
    const confirm = act === "confirm";
    const data = await action(
      "structure_save",
      { structure, base_version: structureWork.base, confirm },
      confirm ? "正在确认简历结构…" : "正在保存…",
    );
    if (data?.result?.structure) {
      structureWork.structure = data.result.structure;
      structureWork.base = data.result.structure.version;
      toast(confirm ? "简历结构已确认。" : "已保存进度。");
    }
  } else return;
  structureFocus = entry ? ["data-entry-block", entry] : null;
  structureRender();
  if (act === "confirm") $("#resume-structure-title")?.focus?.({ preventScroll: true });
}

function structureHost() {
  let host = $("#resume-structure");
  if (!host) {
    host = document.createElement("section");
    host.id = "resume-structure";
    host.className = "resume-draft";
    host.hidden = true;
    $("#resume-draft").after(host);
    host.addEventListener("click", (event) => {
      const button = event.target.closest?.("[data-act]");
      if (button) structureClick(button);
    });
    host.addEventListener("change", (event) => structureChange(event.target));
  }
  return host;
}

// Called whenever the résumé dialog redraws: shows the structure step once no new draft is waiting for fact review.
export async function mountStructure() {
  const host = structureHost();
  if (state?.candidate_draft) {
    host.hidden = true;
    return false;
  }
  const data = await action("structure_get", {}, "正在读取简历结构…");
  const result = data?.result;
  if (!result?.structure) {
    structureWork = null;
    host.hidden = true;
    return false;
  }
  structureWork = {
    structure: result.structure,
    base: result.structure.version,
    facts: new Map(result.facts.map((f) => [f.id, f])),
    fragments: result.fragments || {},
  };
  structureFocus = null;
  host.hidden = false;
  structureRender();
  return true;
}

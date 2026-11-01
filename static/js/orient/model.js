// Reads the orientation the server saved (questions, directions, search terms) without touching the DOM.
import { items } from "../shared/dom.js";
import { state } from "../shared/state.js";

export const MAX_DIRECTIONS = 4;
export const MAX_TERMS = 8;
export const ANSWER_CHARS = 300;

// Who produced the questions or directions: orient.py writes "ai" or "rules", directions_set writes "user" or "agent".
const PROVENANCE = {
  ai: ["使用了 AI", ""],
  rules: ["未使用 AI · 本地规则", "neutral"],
  user: ["未使用 AI · 你手动选择", "neutral"],
  agent: ["由本机助手设定", "neutral"],
};

export function orientation() {
  return state?.orientation || null;
}

export function chosenDirections() {
  return items(orientation()?.directions);
}

export function searchTerms() {
  return items(orientation()?.terms);
}

export function configKeywords() {
  const c = state?.config || {};
  return items(c.keywords).length ? items(c.keywords) : c.keyword ? [c.keyword] : [];
}

// A real search needs either keywords in the settings or the terms of chosen directions.
export function canSearch() {
  return configKeywords().length > 0 || searchTerms().length > 0;
}

export function provenance(by) {
  const [label, kind] = PROVENANCE[by] || ["来源未记录", "neutral"];
  return { label, kind };
}

export function directionTable() {
  return items(state?.direction_table);
}

export function tableFamilies() {
  const groups = new Map();
  for (const row of directionTable()) {
    if (!groups.has(row.family)) groups.set(row.family, []);
    groups.get(row.family).push(row);
  }
  return [...groups].map(([family, rows]) => ({ family, rows }));
}

export function factText(id) {
  return items(state?.candidate?.facts).find((f) => f.id === id)?.text;
}

// orient.py's fixed questions say 可多选 where several answers make sense; years and remote expect one string.
export function isMultiple(question) {
  return question.kind === "choice" && /多选/.test(question.text || "");
}

// The answers object orient_answer accepts: a string per text question, a string or a list per choice question.
// Unanswered questions are left out; the server treats them as unknown.
export function answersFrom(questions, readField) {
  const answers = {};
  for (const q of questions) {
    const values = readField(q);
    if (q.kind === "text") {
      const text = String(values[0] || "").trim();
      if (text) answers[q.id] = text.slice(0, ANSWER_CHARS);
    } else if (values.length) {
      answers[q.id] = isMultiple(q) ? values : values[0];
    }
  }
  return answers;
}

export function termsFrom(text) {
  return [
    ...new Set(
      String(text)
        .split(/[\n,，、]/)
        .map((x) => x.trim())
        .filter(Boolean),
    ),
  ];
}

// The search page's query and what it says about the results, without the DOM.
// Results come from GET /api/search; the server filters and sorts, this only builds the request and the words.
import { items } from "../shared/dom.js";
import { directionName, sourceName } from "../shared/names.js";
import { state } from "../shared/state.js";
import { monthDay } from "../shared/time.js";

export const FRESH = [
  [3, "最近 3 天"],
  [7, "最近 7 天"],
  [30, "最近 30 天"],
  [null, "不限"],
];
export const LIMIT = 100;

export function defaultQuery() {
  return {
    q: "",
    city: null,
    direction: null,
    source: null,
    fresh: 7,
    salaryMin: "",
    salaryMax: "",
    knownOnly: false,
    includeHidden: false,
  };
}

// A salary bound as a person types it: 15000, 15k, 1.5万. The same forms and range as the server's parse_amount, so a
// typo is told here instead of as a 400. Returns {value} (null when empty) or {error}.
export function parseSalary(text) {
  const t = String(text ?? "")
    .normalize("NFKC")
    .trim()
    .toLowerCase();
  if (!t) return { value: null };
  const m = /^(\d+(?:\.\d+)?)\s*(k|千|w|万)?$/.exec(t);
  if (!m) return { error: "薪资须是数字，例如 15000、15k、1.5万" };
  const amount = Number(m[1]) * ({ k: 1000, 千: 1000, w: 10000, 万: 10000 }[m[2]] || 1);
  if (amount > 1e8) return { error: "薪资超出范围" };
  return { value: Math.round(amount) };
}

// Both bounds, or the first error. A min above the max can match nothing, so it is an error too.
export function salaryBounds(query) {
  const lo = parseSalary(query.salaryMin);
  const hi = parseSalary(query.salaryMax);
  if (lo.error) return { error: `最低：${lo.error}` };
  if (hi.error) return { error: `最高：${hi.error}` };
  if (lo.value != null && hi.value != null && lo.value > hi.value)
    return { error: "最低不能高于最高" };
  return { min: lo.value, max: hi.value };
}

// 15000 -> "1.5 万", 20000 -> "2 万", 8500 -> "8500 元".
export function moneyText(n) {
  if (n >= 10000) return `${Number((n / 10000).toFixed(2))} 万`;
  return `${n} 元`;
}

// "月薪 1.5 万以上", "月薪 2 万以下", "月薪 1.5 万至 2.5 万"; "" when no bound is set or one is invalid.
export function salaryPhrase(query) {
  const b = salaryBounds(query);
  if (b.error || (b.min == null && b.max == null)) return "";
  if (b.min != null && b.max != null)
    return b.min === b.max
      ? `月薪 ${moneyText(b.min)}`
      : `月薪 ${moneyText(b.min)}至 ${moneyText(b.max)}`;
  return b.min != null ? `月薪 ${moneyText(b.min)}以上` : `月薪 ${moneyText(b.max)}以下`;
}

export const salaryActive = (query) => {
  const b = salaryBounds(query);
  return !b.error && (b.min != null || b.max != null);
};

// What the results header says about jobs the salary filter could not judge or left out.
export function salaryNotes(query, result) {
  const notes = [];
  const unknown = result?.salary_unknown || 0;
  const other = result?.salary_other_unit || 0;
  if (query.knownOnly) notes.push("没写或读不懂薪资的岗位已去掉");
  else if (salaryActive(query) && unknown)
    notes.push(`${unknown} 条没写或读不懂薪资，仍保留`);
  if (salaryActive(query) && other) notes.push(`${other} 条按日薪或年薪，未参与比较`);
  return notes;
}

export const hiddenText = (n) => `已隐藏 ${n} 条`;

export const HIDE_KIND = { company: "公司", title: "岗位名", recruiter: "招聘者" };
export const hideRuleText = (rule) =>
  `${HIDE_KIND[rule?.kind] || "内容"}含「${String(rule?.value ?? "")}」`;

// The text a hide rule stores for a group: the whole company name or the whole title; null when the group has none.
export function hideValue(group, kind) {
  const v = String((kind === "company" ? group?.company : group?.title) ?? "").trim();
  return v ? v.slice(0, 100) : null;
}

// The rules that hid a group, from the ids on its sources.
export function hiddenByRules(group, rules) {
  const ids = new Set(items(group?.sources).flatMap((s) => items(s.hidden_by)));
  return items(rules).filter((r) => ids.has(r.id));
}

// Empty values are left out; city is one value in the UI but the parameter may repeat.
export function searchParams(query, { withFresh = true } = {}) {
  const p = new URLSearchParams();
  if (query.q.trim()) p.set("q", query.q.trim());
  for (const city of query.city ? [query.city] : []) p.append("city", city);
  if (query.direction) p.set("direction", query.direction);
  if (query.source) p.set("source", query.source);
  const pay = salaryBounds(query);
  if (pay.min != null) p.set("salary_min", String(pay.min));
  if (pay.max != null) p.set("salary_max", String(pay.max));
  if (query.knownOnly) p.set("salary_known_only", "1");
  if (query.includeHidden) p.set("include_hidden", "1");
  if (withFresh && query.fresh) p.set("fresh", String(query.fresh));
  p.set("limit", String(LIMIT));
  return p.toString();
}

export const freshLabel = (fresh) => FRESH.find(([v]) => v === fresh)?.[1] || "不限";

// Filter menus: cities and sources the user has or the results show; directions are the chosen ones,
// because search filters by classification and jobs are only classified into chosen directions.
export function filterOptions(query, groups) {
  const cities = new Set([
    ...items(state?.orientation?.conditions?.cities),
    ...items(state?.config?.cities),
    ...items(groups)
      .map((g) => g.city)
      .filter(Boolean),
  ]);
  if (query.city) cities.add(query.city);
  const sources = new Set([
    ...items(state?.config?.sources),
    ...items(groups)
      .flatMap((g) => items(g.sources).map((s) => s.source))
      .filter(Boolean),
  ]);
  if (query.source) sources.add(query.source);
  const directions = items(state?.orientation?.directions).map((d) => d.id);
  if (query.direction && !directions.includes(query.direction)) directions.push(query.direction);
  return [
    { key: "city", label: "城市", opts: [[null, "不限"], ...[...cities].map((c) => [c, c])] },
    {
      key: "direction",
      label: "方向",
      opts: [[null, "不限"], ...directions.map((d) => [d, directionName(d)])],
    },
    {
      key: "source",
      label: "来源",
      opts: [[null, "全部来源"], ...[...sources].map((s) => [s, sourceName(s)])],
    },
    { key: "fresh", label: "搜到", opts: FRESH },
  ];
}

export const optionText = (filter, value) =>
  (filter.opts.find(([v]) => v === value) || filter.opts[0])[1];

// "在 上海 找 后端开发，看 全部来源，只看最近 7 天搜到过、仍在列表的：11 条记录合并成 7 组。"
// Returns plain-text parts; the view escapes them and bolds the values.
export function sentenceParts(query, result, hidden) {
  const records = items(result?.groups).reduce(
    (n, g) => n + items(g.sources).filter((s) => s.matched).length,
    0,
  );
  const when = query.fresh ? `只看${freshLabel(query.fresh)}搜到过、仍在列表的` : "不限时间";
  return {
    salary: salaryPhrase(query),
    city: query.city || "所有城市",
    direction: query.direction ? directionName(query.direction) : "所有方向",
    words: query.q.trim(),
    source: query.source ? sourceName(query.source) : "全部来源",
    when,
    records,
    groups: items(result?.groups).length,
    total: result?.total_groups ?? 0,
    hidden,
  };
}

export const salaryOf = (g) => items(g.sources).find((s) => s.salary)?.salary || "薪资没写";

// Only a date the source itself gave, said as that source's claim. The API has no posted_at yet.
export function postedLine(g) {
  return items(g.sources)
    .filter((s) => s.posted_at)
    .map((s) => `${sourceName(s.source)}写的发布日期：${monthDay(s.posted_at)}`)
    .join("；");
}

export const leadJobId = (g) => items(g.sources)[0]?.job_id || null;

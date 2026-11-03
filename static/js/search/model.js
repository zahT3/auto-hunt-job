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
  return { q: "", city: null, direction: null, source: null, fresh: 7 };
}

// Empty values are left out; city is one value in the UI but the parameter may repeat.
export function searchParams(query, { withFresh = true } = {}) {
  const p = new URLSearchParams();
  if (query.q.trim()) p.set("q", query.q.trim());
  for (const city of query.city ? [query.city] : []) p.append("city", city);
  if (query.direction) p.set("direction", query.direction);
  if (query.source) p.set("source", query.source);
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

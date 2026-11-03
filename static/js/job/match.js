// job_match results (POST /api/action {action:'job_match'} → result), kept for this page session.
import { action } from "../shared/api.js";
import { items } from "../shared/dom.js";
import { state } from "../shared/state.js";

const cache = new Map();

export function cachedMatch(jobId) {
  return cache.get(jobId) || null;
}

export function rememberMatch(jobId, result) {
  if (result) cache.set(jobId, result);
}

// The comparison itself is rules only, but without a cached JD structure job_match first runs jd_extract,
// which calls the model when 岗位原文 is consented for the current service. Then the user starts it.
export function matchMayUseModel() {
  const ai = state?.ai || {};
  return !!(ai.active && items(ai.consent?.kinds).includes("job_text"));
}

export async function loadMatch(jobId) {
  const data = await action("job_match", { job_id: jobId }, "正在对照…");
  rememberMatch(jobId, data?.result);
  return data?.result || null;
}

export function matchCounts(m) {
  const count = (rows, test) => items(rows).filter(test).length;
  return {
    hard: {
      met: count(m.hard, (r) => r.status === "met"),
      notMet: count(m.hard, (r) => r.status === "not_met"),
      unknown: count(m.hard, (r) => r.status === "unknown"),
      total: items(m.hard).length,
    },
    keywords: {
      explicit: count(m.keywords, (k) => k.coverage === "explicit"),
      related: count(m.keywords, (k) => k.coverage === "related"),
      total: items(m.keywords).length,
    },
    evidence: {
      facts: count(m.evidence, (r) => items(r.fact_ids).length > 0),
      total: items(m.evidence).length,
    },
  };
}

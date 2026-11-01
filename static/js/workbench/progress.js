// The latest run and what each source actually read; partial or blocked sources never read as an empty success.
import { $, dateOf, esc, items, replaceContent, safeUrl, textOf } from "../shared/dom.js";
import { isDemo, state } from "../shared/state.js";
import { channelNames, sourceStatus } from "./labels.js";
import { refreshRunButton } from "./settings.js";

export function sourceRows(run) {
  return items(run?.sources || run?.channel_results);
}

export function renderSourceRows(run) {
  return sourceRows(run)
    .map((s) => {
      const key = s.kind || s.source || s.channel || s.name;
      const name = channelNames[key] || key || "渠道";
      const effective =
        s.truncated && ["ok", "success", "completed", "empty", "filtered_empty"].includes(s.status)
          ? "partial"
          : s.status;
      const status = sourceStatus[effective] || effective || "待核验";
      const fetched = s.fetched_count ?? s.fetched ?? s.count;
      const pages = s.pages_read ?? s.pages;
      const url = s.search_url || s.url || s.help_url;
      const warn = [
        "blocked",
        "failed",
        "partial",
        "parse_error",
        "fetch_error",
        "needs_login",
        "login_required",
        "captcha",
        "blank_page",
        "needs_browser",
        "budget_exhausted",
      ].includes(effective);
      const counts =
        [
          fetched != null && (fetched > 0 || pages > 0) ? "读取 " + fetched + " 条" : null,
          s.returned != null && pages > 0 ? "保留 " + s.returned + " 条" : null,
          s.entry_requests ? "核验入口 " + s.entry_requests + " 次" : null,
          s.rendered_pages ? "渲染 " + s.rendered_pages + " 页" : null,
          pages != null ? "检查 " + (Array.isArray(pages) ? pages.length : pages) + " 页" : null,
          s.duration_ms != null ? "用时 " + Math.round(s.duration_ms / 1000) + " 秒" : null,
        ]
          .filter(Boolean)
          .map(esc)
          .join(" · ") || "尚无可确认的读取数量";
      const detail = s.company
        ? " · " + esc(s.company)
        : s.source_id?.includes(":")
          ? " · " + esc(s.source_id.split(":").slice(1).join(":"))
          : "";
      return (
        `<div class="source-result"><div><strong>${esc(name)}${detail}</strong>` +
        `<span class="badge ${warn ? "warn" : "neutral"}">${esc(status)}</span></div>` +
        `<p>${counts}</p>` +
        `${s.truncated ? "<p>已达到本轮数量或页数上限，仍可能有未检查的岗位。</p>" : ""}` +
        `${s.reason || s.error || s.message ? `<p>${esc(textOf(s.reason || s.error || s.message))}</p>` : ""}` +
        `${url && safeUrl(url) !== "#" ? `<a href="${safeUrl(url)}" target="_blank" rel="noopener noreferrer">打开该渠道核对</a>` : ""}` +
        `${s.finished_at || s.checked_at ? `<time>${esc(dateOf(s.finished_at || s.checked_at))}</time>` : ""}` +
        `</div>`
      );
    })
    .join("");
}

export function renderSearchProgress() {
  const run = items(state.runs)[0],
    running = !!state.search_running;
  const area = $("#search-progress");
  refreshRunButton();
  area.hidden = !running && !run;
  if (area.hidden) return;
  const sources = sourceRows(run);
  const runStatus =
    ["completed", "empty"].includes(run?.status) && sources.some((s) => s.truncated)
      ? "partial"
      : run?.status;
  const status = sourceStatus[runStatus] || runStatus || "等待结果";
  const blocked = sources.filter((s) =>
    [
      "blocked",
      "failed",
      "parse_error",
      "fetch_error",
      "needs_login",
      "login_required",
      "captcha",
      "blank_page",
      "needs_browser",
    ].includes(s.status),
  ).length;
  const heading = running
    ? isDemo()
      ? "正在准备合成岗位"
      : "正在搜索已选渠道"
    : "最近一轮：" + esc(status);
  const summary = running
    ? isDemo()
      ? "仅使用合成资料"
      : "只读搜索"
    : `发现 ${esc(run?.discovered ?? 0)} · 已准备 ${esc(run?.prepared ?? 0)}`;
  const body = sources.length
    ? `<div class="source-results">${renderSourceRows(run)}</div>`
    : running
      ? `<p class="small-note">${isDemo() ? "正在用合成岗位准备本地材料。" : "正在读取公开岗位，渠道结果会陆续显示。"}</p>`
      : "";
  replaceContent(
    "#search-progress",
    `<details class="run-disclosure" data-disclosure="run-${esc(run?.id || "active")}">` +
      `<summary><span class="search-progress-heading"><strong>${heading}</strong>` +
      `<span>${summary}${blocked ? " · " + blocked + " 个来源受阻" : ""}</span></span>` +
      `<span class="run-expand">${isDemo() ? "演示详情" : "渠道详情"}</span></summary>` +
      body +
      `${items(run?.failures).length ? `<p class="small-note">${esc(items(run.failures).map(textOf).join("；"))}</p>` : ""}` +
      `<p class="small-note">${esc(dateOf(run?.started_at))}</p></details>`,
  );
  refreshRunButton();
}

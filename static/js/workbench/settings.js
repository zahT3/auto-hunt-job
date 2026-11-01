// Search targets and channels, the task list, and the run controls in the header.
import { action } from "../shared/api.js";
import {
  $,
  $$,
  dateOf,
  esc,
  items,
  motionBehavior,
  replaceContent,
  safeUrl,
  textOf,
} from "../shared/dom.js";
import { notice, toast } from "../shared/feedback.js";
import { busy, isDemo, state } from "../shared/state.js";
import { setWorkbench } from "./layout.js";

export let configDirty = false;

export function refreshRunButton(label) {
  $("#run-button").disabled = busy || !!state?.search_running;
  $("#run-button").textContent = busy
    ? label || "正在处理…"
    : state?.search_running
      ? isDemo()
        ? "演示进行中"
        : "搜索进行中"
      : isDemo()
        ? configDirty
          ? "保存并运行演示"
          : "运行演示"
        : configDirty
          ? "保存并搜索"
          : "开始找岗位";
}

export function renderTasks() {
  const tasks = items(state.tasks);
  const fallback = [];
  if (!state.config?.targets_confirmed)
    fallback.push({
      title: "确认求职目标",
      reason: "方向、范围与硬条件待确认。",
      action: "target",
    });
  if (!items(state.candidate?.facts).some((f) => f.status === "confirmed"))
    fallback.push({
      title: "补充候选资料",
      reason: "先确认事实，再生成申请材料。",
      action: "candidate",
    });
  const list = tasks.length ? tasks : fallback;
  $("#task-count").textContent = list.length;
  $("#pending-count").textContent = list.length || "";
  const row = (t) =>
    `<div class="task-item"><strong>${esc(t.title || t.reason || t.kind || textOf(t))}</strong>` +
    `${t.reason && t.reason !== t.title ? `<p>${esc(t.reason)}</p>` : ""}` +
    `${["target", "config"].includes(t.action) ? '<button class="text-button" data-open-target>设置目标</button>' : t.action === "candidate" ? '<button class="text-button" data-open-candidate>补充资料</button>' : t.job_id ? `<button class="text-button" data-open-job="${esc(t.job_id)}">查看岗位</button>` : ""}` +
    `</div>`;
  const global = list.filter((t) => !t.job_id),
    jobs = list.filter((t) => t.job_id);
  replaceContent(
    "#task-list",
    global.map(row).join("") +
      (jobs.length
        ? `<details class="task-jobs" data-disclosure="task-jobs"><summary>${jobs.length} 个岗位等待处理</summary>${jobs.map(row).join("")}</details>`
        : "") || '<p class="small-note">暂无待办。</p>',
  );
}

export function renderSettings() {
  const f = $("#config-form"),
    c = state.config || {};
  for (const key of ["salary_min", "max_jobs", "max_pages", "interval_minutes", "submission_limit"])
    f.elements[key].value = c[key] ?? "";
  f.elements.keywords.value = items(c.keywords?.length ? c.keywords : [c.keyword || ""]).join("\n");
  $$("#config-form input[name=sources]").forEach(
    (x) => (x.checked = items(c.sources || ["anker"]).includes(x.value)),
  );
  f.elements.company_board_urls.value = items(c.company_boards)
    .map(boardUrl)
    .filter(Boolean)
    .join("\n");
  for (const kind of ["boss", "liepin"])
    f.elements[kind + "_mode"].value = c.source_modes?.[kind] || "public";
  f.elements.search_provider_url.value = c.search_provider?.url || "";
  f.elements.cities.value = items(c.cities).join("，");
  f.elements.targets_confirmed.checked = !!c.targets_confirmed;
  f.elements.official_only.checked = !!c.official_only;
  f.elements.check_entries.checked = c.check_entries !== false;
  f.elements.official_browser.checked = !!c.official_browser;
  f.elements.liepin_cards.checked = !!c.liepin_cards;
  $("#company-catalog").innerHTML = items(state.company_catalog)
    .map(
      (r) =>
        `<p><a href="${safeUrl(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.company)}</a> · ${esc(r.category)}<br>${esc(r.region)}${r.note ? " · " + esc(r.note) : ""}</p>`,
    )
    .join("");
  f.elements.browser_channel.value = c.browser_channel || "";
  $("#target-status").textContent = c.targets_confirmed ? "已确认" : "待确认";
  const facts = items(state.candidate?.facts);
  $("#fact-count").textContent = `${facts.length} 项`;
  $("#candidate-summary").innerHTML =
    `<p class="fact-summary">${esc(state.candidate?.name || "尚未建档")}${state.candidate?.synthetic || state.candidate?.is_demo ? " · 合成资料" : ""}<br>` +
    `${facts.filter((f) => f.status === "confirmed").length} 项已确认 · ${facts.filter((f) => f.disclosure === "public" || f.disclosure === "application").length} 项允许申请披露</p>`;
  const caps = items(state.capabilities);
  $("#capabilities").innerHTML =
    caps
      .map(
        (c) =>
          `<div class="capability"><strong>${esc(c.channel || c.name || c.title || "本地能力")}</strong>${esc(
            c.description ||
              c.status ||
              Object.entries(c)
                .filter(([k]) => k !== "channel")
                .map(
                  ([k, v]) =>
                    (({ discovery: "发现", details: "详情", execution: "执行", model: "材料生成" })[
                      k
                    ] || k) +
                    "：" +
                    textOf(v),
                )
                .join("；"),
          )}${c.scope ? `<br>${esc(textOf(c.scope))}` : ""}</div>`,
      )
      .join("") ||
    '<p class="small-note">本地草稿与导出可用；真实渠道能力以运行器检查结果为准。</p>';
  $("#run-history").innerHTML = items(state.runs)
    .slice(0, 5)
    .map((r) => {
      const failures = items(r.failures).length
        ? `<br>${items(r.failures)
            .map((reason) => esc(textOf(reason)))
            .join("<br>")}`
        : "";
      const discovery = r.discovery
        ? `<br>${esc(`源返回 ${r.discovery.fetched_count ?? r.discovery.count ?? 0} · 标题筛选保留 ${r.discovery.retained_count ?? r.discovered ?? 0}`)}${items(
            r.discovery.excluded,
          )
            .map((x) => `<br>${esc(x.title + "：" + x.reason)}`)
            .join("")}`
        : "";
      return (
        `<div class="capability"><strong>${esc(dateOf(r.started_at || r.created_at))} · ${esc(r.status || "已记录")}</strong>` +
        `${esc(`发现 ${r.discovered ?? 0} · 重复 ${r.duplicates ?? 0} · 已准备 ${r.prepared ?? 0} · 可申请 ${r.applicable ?? 0} · 已核验提交 ${r.verified_submissions ?? 0}`)}` +
        `<br>${esc(`失败 ${items(r.failures).length} · 人工介入 ${r.user_interventions ?? 0} 次`)}` +
        `${failures}${discovery}</div>`
      );
    })
    .join("");
}

export function profileQueries() {
  return items(state?.candidate_profile?.suggested_queries);
}

export function boardUrl(board) {
  const base = {
    greenhouse: "https://boards.greenhouse.io/",
    lever: "https://jobs.lever.co/",
    ashby: "https://jobs.ashbyhq.com/",
  }[board.type];
  return board.url || (base ? base + encodeURIComponent(board.slug || "") : "");
}

function publicHttpsInput(raw, label) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(label + "需要完整的 HTTPS 网址。");
  }
  const host = url.hostname.toLowerCase();
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    (url.port && url.port !== "443") ||
    !host.includes(".") ||
    host.endsWith(".local") ||
    host.endsWith(".localhost") ||
    host === "localhost" ||
    /^\d+(?:\.\d+){3}$/.test(host) ||
    host.startsWith("[")
  )
    throw new Error(label + "需要公开的 HTTPS 域名，不能包含凭据或本机地址。");
  url.hash = "";
  return url;
}

export function parseBoards(value) {
  return value
    .split(/\n/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map((raw) => {
      const url = publicHttpsInput(raw, "公司招聘页");
      const hosts = {
        "boards.greenhouse.io": "greenhouse",
        "job-boards.greenhouse.io": "greenhouse",
        "jobs.lever.co": "lever",
        "jobs.ashbyhq.com": "ashby",
      };
      const type = hosts[url.hostname],
        slug = url.pathname.split("/").filter(Boolean)[0];
      if (type && !slug) throw new Error("请填写具体公司的招聘主页，而非招聘服务首页。");
      if (type) {
        const previous = items(state.config.company_boards).find(
          (b) => b.type === type && b.slug === slug,
        );
        return previous || { type, slug, company: slug };
      }
      const previous = items(state.config.company_boards).find(
        (b) => b.type === "website" && b.url === url.href,
      );
      const entry = items(state.company_catalog).find((r) => r.url === url.href);
      return (
        previous || { type: "website", url: url.href, company: entry?.company || url.hostname }
      );
    });
}

export function searchProviderInput(value) {
  const raw = value.trim();
  return raw ? { provider: "searxng", url: publicHttpsInput(raw, "搜索服务").href } : null;
}

export function includeBoardSources(sources, boards) {
  return [
    ...new Set([...sources, ...boards.filter((b) => b.type === "website").map(() => "website")]),
  ];
}

export function configFromForm(f) {
  const keywords = f.elements.keywords.value
    .split(/[\n,，]/)
    .map((x) => x.trim())
    .filter(Boolean);
  if (!keywords.length) throw new Error("请填写至少一个岗位关键词，或采用画像建议。");
  if (keywords.length > 8) throw new Error("每轮最多 8 个关键词，请保留最相关的方向。");
  const boards = parseBoards(f.elements.company_board_urls.value);
  const sources = includeBoardSources(
    $$("#config-form input[name=sources]:checked").map((x) => x.value),
    boards,
  );
  if (!sources.length) throw new Error("请至少选择一个搜索渠道。");
  const c = {
    ...state.config,
    keyword: keywords[0],
    keywords,
    sources,
    company_boards: boards,
    source_modes: { boss: f.elements.boss_mode.value, liepin: f.elements.liepin_mode.value },
    official_only: f.elements.official_only.checked,
    check_entries: f.elements.check_entries.checked,
    official_browser: f.elements.official_browser.checked,
    liepin_cards: f.elements.liepin_cards.checked,
    browser_channel: f.elements.browser_channel.value || null,
    search_provider: searchProviderInput(f.elements.search_provider_url.value),
    cities: f.elements.cities.value
      .split(/[,，、]/)
      .map((x) => x.trim())
      .filter(Boolean),
    salary_min: f.elements.salary_min.value ? Number(f.elements.salary_min.value) : null,
    max_jobs: Number(f.elements.max_jobs.value),
    max_pages: Number(f.elements.max_pages.value),
    interval_minutes: Number(f.elements.interval_minutes.value),
    submission_limit: Number(f.elements.submission_limit.value),
    targets_confirmed: f.elements.targets_confirmed.checked,
  };
  return c;
}

export function markConfigDirty() {
  configDirty = true;
  refreshRunButton();
}

export async function saveSearchConfig(feedback = true) {
  const f = $("#config-form");
  try {
    if (f.checkValidity && !f.checkValidity()) {
      setWorkbench(true);
      $("#target-settings").open = true;
      f.reportValidity();
      return false;
    }
    const c = configFromForm(f);
    if (!(await action("config", { config: c }, "正在保存搜索条件…"))) return false;
    configDirty = false;
    renderSettings();
    refreshRunButton();
    if (feedback) toast("搜索目标与渠道已保存。");
    return true;
  } catch (error) {
    setWorkbench(true);
    $("#target-settings").open = true;
    notice(error.message, true);
    return false;
  }
}

export async function startSearch() {
  if (busy || state?.search_running) return;
  if (configDirty && !(await saveSearchConfig(false))) return;
  if (isDemo()) {
    if (await action("demo", {}, "正在运行合成演示…"))
      toast(
        state.search_running
          ? "合成演示已启动，正在准备本地材料。"
          : "合成演示已结束，请查看准备结果。",
      );
    return;
  }
  const r = await action("run", {}, "正在收集与准备…");
  if (r)
    toast(
      state.search_running ? "搜索已启动，结果会陆续显示。" : "本轮已完成，请查看岗位与渠道结果。",
    );
}

export function openTargetSettings() {
  setWorkbench(true);
  $("#target-settings").open = true;
  $("#target-settings").scrollIntoView({ behavior: motionBehavior() });
  $("#config-form textarea").focus();
}

$("#run-button").addEventListener("click", startSearch);
$("#control-button").addEventListener("click", () =>
  action("control", { value: state.control === "running" ? "paused" : "running" }),
);
$("#stop-button").addEventListener("click", () => action("control", { value: "stopped" }));
$("#demo-button").addEventListener("click", async () => {
  if (!isDemo()) {
    notice(
      "隔离演示启动：python3 run.py --demo 。在新窗口打开运行器给出的地址，合成记录不会进入真实数据库。",
    );
    return;
  }
  await action("demo", {}, "正在载入演示…");
});
$("#config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await saveSearchConfig();
});
$("#config-form").addEventListener("input", markConfigDirty);
$$("[data-catalog]").forEach((button) =>
  button.addEventListener("click", () => {
    const form = $("#config-form"),
      group = button.dataset.catalog,
      rows = items(state.company_catalog).filter((r) =>
        group === "ai" ? r.category.includes("AI") : r.category.includes("Web3"),
      );
    form.elements.company_board_urls.value = [
      ...new Set([
        ...form.elements.company_board_urls.value
          .split(/\n/)
          .map((x) => x.trim())
          .filter(Boolean),
        ...rows.map((r) => r.url),
      ]),
    ].join("\n");
    markConfigDirty();
    toast("已加入公司来源，保存目标后生效；是否可读取以本轮结果为准。");
  }),
);
$("#use-profile-queries").addEventListener("click", () => {
  const form = $("#config-form");
  form.elements.keywords.value = [
    ...new Set([
      ...form.elements.keywords.value
        .split(/[\n,，]/)
        .map((x) => x.trim())
        .filter(Boolean),
      ...profileQueries(),
    ]),
  ].join("\n");
  markConfigDirty();
  toast("已加入建议关键词，保存目标后生效。");
});

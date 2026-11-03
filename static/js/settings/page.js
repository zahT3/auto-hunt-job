// 设置 (#/settings): the model service, what may be sent to it, the sources and their last run, and the way
// into the frozen workbench (résumé, facts, targets, review and execution).
import { action } from "../shared/api.js";
import { $, esc, items, motionBehavior, replaceContent } from "../shared/dom.js";
import { toast } from "../shared/feedback.js";
import { sourceName } from "../shared/names.js";
import { state } from "../shared/state.js";
import { clock, monthDay } from "../shared/time.js";
import { stateWord } from "../shared/ui.js";
import { go, registerPage, setReturnTarget } from "../shell/router.js";
import { openTargetSettings } from "../workbench/settings.js";

export const CONSENT_KINDS = [
  ["resume_redacted", "脱敏简历", "姓名、电话、邮箱、住址替换成占位符后发送"],
  ["resume_full", "完整简历", "不脱敏，姓名和联系方式会原样发送"],
  ["job_text", "岗位原文", "用于 JD 结构化和匹配解释"],
  ["search_query", "搜索需求", "你用一句话描述想找的岗位时，发送这句话"],
];
// The sources the config accepts (hunt.app.config), in the order the old settings form listed them.
export const SOURCES = ["boss", "liepin", "anker", "greenhouse", "lever", "ashby", "website"];
const RUN_FAILED = [
  "failed",
  "fetch_error",
  "parse_error",
  "blank_page",
  "blocked",
  "needs_browser",
  "error",
];
const RUN_LOGIN = ["needs_login", "login_required", "captcha"];

export function serviceHost(baseUrl) {
  try {
    return new URL(baseUrl).hostname.toLowerCase();
  } catch {
    return "";
  }
}

// One row per source: the state word of its last run and why, and how many jobs it returned.
export function runState(kind) {
  const run = items(state?.runs)[0];
  const rows = items(run?.sources || run?.channel_results).filter(
    (s) => (s.kind || s.source || s.channel) === kind,
  );
  if (!run || !rows.length) return { tone: "muted", label: "还没运行", note: "", found: null };
  const failed = rows.find((s) => RUN_FAILED.includes(s.status));
  const login = rows.find((s) => RUN_LOGIN.includes(s.status));
  const cut = rows.find((s) => s.truncated);
  const found = rows.reduce(
    (n, s) => n + Number(s.returned ?? s.fetched_count ?? s.fetched ?? 0),
    0,
  );
  const why = (s) => String(s.reason || s.error || s.message || "");
  if (failed) return { tone: "bad", label: "失败", note: why(failed) || "读取失败", found };
  if (login)
    return {
      tone: "warn",
      label: "需要登录",
      note: why(login) || "需要本人在独立浏览器里登录",
      found,
    };
  if (cut)
    return {
      tone: "warn",
      label: "结果被截断",
      note: "达到本轮数量或页数上限，仍可能有没检查的岗位",
      found,
    };
  return { tone: "ok", label: "成功", note: "", found };
}

function aiSection() {
  const ai = state?.ai || {};
  const s = ai.settings || {};
  const key = ai.key_hint ? `已保存，尾号 ${esc(ai.key_hint)}。留空表示不改…` : "还没有保存密钥…";
  return (
    `<section id="s-ai" aria-labelledby="h-ai"><h2 id="h-ai" tabindex="-1">AI 服务</h2>` +
    `<p class="lead">定方向、JD 结构化会调用这个服务。没有设置、没有同意或预算用完时用本地规则，结果会标"本地规则"。</p>` +
    `<form class="form" id="ai-form">` +
    `<label for="ai-url">服务地址</label><input id="ai-url" name="base_url" type="text" value="${esc(s.base_url || "")}" spellcheck="false" autocomplete="off">` +
    `<label for="ai-model">模型</label><input id="ai-model" name="model" type="text" value="${esc(s.model || "")}" spellcheck="false" autocomplete="off">` +
    `<label for="ai-key">密钥</label><input id="ai-key" name="api_key" type="password" placeholder="${key}" autocomplete="off">` +
    `<p class="help">密钥只存本机，界面只显示尾号。${ai.key_mismatch ? `已保存的密钥属于 ${esc(ai.key_host || "另一个服务")}，对当前服务地址无效。` : ""}</p>` +
    `<label for="ai-budget">每轮花费上限（元）</label><input id="ai-budget" name="budget_cny" type="text" inputmode="decimal" value="${esc(s.budget_cny ?? "")}">` +
    `<p class="help">本机只按每一轮计花费，没有本月累计，这里不显示本月花费。</p>` +
    `<span></span><div><button class="btn btn-primary" type="submit">保存 AI 服务</button></div></form></section>`
  );
}

function consentSection() {
  const ai = state?.ai || {};
  const consent = ai.consent;
  const s = ai.settings || {};
  const kinds = items(consent?.kinds);
  const rows = CONSENT_KINDS.map(
    ([id, name, note]) =>
      `<label><input type="checkbox" name="kind" value="${id}" ${ai.consent_current && kinds.includes(id) ? "checked" : ""}><span>${name}</span>` +
      `<span class="n${id === "resume_full" ? " warn" : ""}">${note}</span></label>`,
  ).join("");
  const bound = consent
    ? ai.consent_current
      ? `这份同意只对 ${esc(consent.host)} 的 ${esc(consent.model)} 有效，${esc(monthDay(consent.granted_at))}授予。换服务地址或模型后要重新同意。`
      : `原来的同意给的是 ${esc(consent.host)} 的 ${esc(consent.model)}，和现在的服务不一样，已不生效。勾选后重新同意。`
    : `还没有同意。勾选后，同意只对 ${esc(serviceHost(s.base_url))} 的 ${esc(s.model || "")} 有效。`;
  return (
    `<section id="s-consent" aria-labelledby="h-consent"><h2 id="h-consent" tabindex="-1">发送同意</h2>` +
    `<p class="lead">勾选的内容才会发给上面的服务。默认都不勾。</p>` +
    `<form id="consent-form"><div class="consent">${rows}</div><p class="bound">${bound}</p>` +
    `<div class="actions"><button class="btn btn-primary" type="submit">保存同意</button>` +
    `${consent ? '<button class="btn" type="button" data-act="consent-revoke">撤销全部同意</button>' : ""}</div></form></section>`
  );
}

function sourcesSection() {
  const run = items(state?.runs)[0];
  const enabled = new Set(items(state?.config?.sources));
  const rows = SOURCES.map((kind) => {
    const r = runState(kind);
    return (
      `<tr><td><input type="checkbox" data-source="${kind}" aria-label="启用 ${esc(sourceName(kind))}" ${enabled.has(kind) ? "checked" : ""}></td>` +
      `<td>${esc(sourceName(kind))}</td><td>${stateWord(r.tone, r.label)}${r.note ? `<span class="note">${esc(r.note)}</span>` : ""}</td>` +
      `<td class="num">${r.found == null ? "—" : r.found}</td></tr>`
    );
  }).join("");
  const when = run?.finished_at || run?.started_at;
  return (
    `<section id="s-src" aria-labelledby="h-src"><h2 id="h-src" tabindex="-1">来源</h2>` +
    `<p class="lead">只读搜索，不会投递。失败或被截断的来源写出原因；那一轮不会把没取到的岗位标成"已不在列表"。</p>` +
    `<table class="srcs"><thead><tr><th>启用</th><th>来源</th><th>上次运行${when ? `（${esc(clock(when))}）` : ""}</th><th class="num">岗位</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></section>`
  );
}

function workbenchSection() {
  return (
    `<section id="s-wb" aria-labelledby="h-wb"><h2 id="h-wb" tabindex="-1">资料与工作台</h2>` +
    `<p class="lead">简历、事实资料、求职目标，以及审核、材料包、执行和入口核验，沿用原来的工作台。对外操作要逐项授权。</p>` +
    `<div class="actions">` +
    `<button class="btn" type="button" data-open-resume>上传简历</button>` +
    `<button class="btn" type="button" data-open-candidate>查看 / 编辑事实</button>` +
    `<button class="btn" type="button" data-act="edit-targets">修改求职目标和关键词</button>` +
    `<button class="btn" type="button" data-open-import>导入岗位</button>` +
    `<a class="btn" href="#/workbench">打开工作台</a>` +
    `<a class="btn" href="/bookmarklets">岗位书签</a></div></section>`
  );
}

export function settingsHtml() {
  return (
    `<div class="page"><header class="page-h"><h1 id="page-title" tabindex="-1">设置</h1><p>都保存在本机。</p></header>` +
    `<div class="set"><nav aria-label="设置分区">` +
    [
      ["s-ai", "AI 服务"],
      ["s-consent", "发送同意"],
      ["s-src", "来源"],
      ["s-wb", "资料与工作台"],
    ]
      .map(([id, t]) => `<a href="#/settings" data-jump="${id}">${t}</a>`)
      .join("") +
    `</nav><div>${aiSection()}${consentSection()}${sourcesSection()}${workbenchSection()}</div></div></div>`
  );
}

export function renderSettingsPage() {
  // While a field here has focus a poll must not rewrite what the user is typing.
  if (
    $("#view")?.contains?.(document.activeElement) &&
    document.activeElement.matches?.("input[type=text], input[type=password]")
  )
    return;
  replaceContent("#view", settingsHtml());
}

export function aiPayload(form) {
  const payload = {
    base_url: form.elements.base_url.value.trim(),
    model: form.elements.model.value.trim(),
  };
  const budget = form.elements.budget_cny.value.trim();
  if (budget) payload.budget_cny = Number(budget);
  const key = form.elements.api_key.value.trim();
  if (key) payload.api_key = key;
  return payload;
}

export function consentPayload(form) {
  const s = state?.ai?.settings || {};
  return {
    kinds: Array.from(form.querySelectorAll("input[name=kind]:checked")).map((x) => x.value),
    host: serviceHost(s.base_url),
    model: s.model,
  };
}

async function saveAi(form) {
  if (await action("ai_settings", aiPayload(form), "正在保存 AI 服务…")) {
    form.elements.api_key.value = "";
    toast("AI 服务已保存。换了服务地址或模型，要重新同意发送内容。");
  }
}

async function saveConsent(form) {
  const payload = consentPayload(form);
  if (!payload.kinds.length) {
    toast("一个都没勾，就不用保存同意；要撤销已有的同意，点「撤销全部同意」。");
    return;
  }
  if (await action("ai_consent", payload, "正在保存同意…")) toast("发送同意已保存。");
}

async function saveSources(kind, on) {
  const config = state?.config || {};
  const sources = new Set(items(config.sources));
  if (on) sources.add(kind);
  else sources.delete(kind);
  if (!sources.size) {
    toast("至少要启用一个来源。");
    renderSettingsPage();
    return;
  }
  const ordered = SOURCES.filter((s) => sources.has(s));
  if (await action("config", { config: { ...config, sources: ordered } }, "正在保存来源…"))
    toast(`${sourceName(kind)}已${on ? "启用" : "停用"}，下一轮搜索生效。`);
}

registerPage("settings", { title: "设置", render: renderSettingsPage });

document.addEventListener("submit", (e) => {
  if (e.target.id === "ai-form") {
    e.preventDefault();
    saveAi(e.target);
  }
  if (e.target.id === "consent-form") {
    e.preventDefault();
    saveConsent(e.target);
  }
});
document.addEventListener("change", (e) => {
  const kind = e.target.dataset?.source;
  if (kind && e.target.closest?.("#s-src")) saveSources(kind, e.target.checked);
});
document.addEventListener("click", (e) => {
  if (!e.target.closest?.("#view")) return;
  const jump = e.target.closest("[data-jump]");
  if (jump) {
    e.preventDefault();
    const section = $(`#${jump.dataset.jump}`);
    section?.scrollIntoView({ behavior: motionBehavior() });
    section?.querySelector("h2")?.focus({ preventScroll: true });
    return;
  }
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "consent-revoke")
    action("ai_revoke", {}, "正在撤销同意…").then((r) => r && toast("已撤销全部发送同意。"));
  if (act === "edit-targets") {
    openTargetSettings();
    setReturnTarget("#config-form textarea");
    go("workbench");
  }
});

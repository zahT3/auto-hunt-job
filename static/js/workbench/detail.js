import { action } from "../shared/api.js";
import { $, dateOf, esc, items, replaceContent, safeUrl, sourceOf, textOf } from "../shared/dom.js";
import { toast } from "../shared/feedback.js";
import { state } from "../shared/state.js";
import { badge, matchMap } from "./labels.js";
import { activeId, jobBadge, jobCurrent, materialNeedsAttention } from "./queue.js";
import {
  applicationRoute,
  availabilityNotice,
  executionSupported,
  syntheticCandidate,
} from "./routes.js";

export let activeTab = "match";

export function setActiveTab(tab) {
  activeTab = tab;
}

const summaryOf = (v) =>
  typeof v === "string"
    ? v
    : v
      ? `事实支持 ${v.supported || 0} 项，明确不符合 ${v.not_met || 0} 项；缺失证据 ${v.missing_evidence || 0} 项，需要确认 ${v.needs_confirmation || 0} 项。`
      : "";

export function renderDetail() {
  const j = jobCurrent();
  if (!j) {
    replaceContent(
      "#detail-pane",
      `<div class="welcome"><h2>找到机会，再决定。</h2>` +
        `<p>上传简历，确认搜索方向。岗位与材料会保存在这里，投递前由你审核。</p>` +
        `<button class="primary" data-open-resume>上传简历</button>` +
        `<button class="text-button spaced-top" data-open-import>已有岗位？直接导入</button></div>`,
    );
    return;
  }
  const p = j.package;
  const locked = ["unknown", "submission_unknown", "verification_required"].includes(j.status);
  const next = locked
    ? "核验上次结果，暂不重复发送"
    : j.status === "rejected"
      ? "已决定不申请"
      : j.approval
        ? "核对已批准的材料"
        : j.material_review_current
          ? materialNeedsAttention(j)
            ? "材料已复核，仍需补充"
            : "材料已复核，尚未投递"
          : p
            ? "材料已准备，等待复核"
            : "准备这份申请";
  const nextNote = locked
    ? "结果未确认前禁止重新执行。"
    : state.candidate?.synthetic || state.candidate?.is_demo
      ? "合成验收 · 禁止对外申请"
      : j.approval
        ? "授权只适用于当前快照。"
        : "对外操作需具体授权。";
  const tabButton = (tab, label) =>
    `<button data-tab="${tab}" aria-pressed="${activeTab === tab}" class="${activeTab === tab ? "active" : ""}">${label}</button>`;
  replaceContent(
    "#detail-pane",
    `<button class="text-button mobile-back" data-scroll-queue>返回机会列表</button>` +
      `<div class="detail-heading"><div><h2 id="detail-title" tabindex="-1">${esc(j.title)}</h2>` +
      `<p class="detail-company">${esc(j.company || "公司待确认")}<span>${esc(j.location || "地点未知")}</span>${j.salary ? `<span>${esc(textOf(j.salary))}</span>` : ""}</p>` +
      `</div>${jobBadge(j)}</div>` +
      `${availabilityNotice(j)}${recommendationSummary(j)}${applicationRoute(j)}` +
      `<div class="detail-next"><div><strong>${esc(next)}</strong><p>${nextNote}</p></div>${actionButton(j)}</div>` +
      `<nav class="detail-tabs" aria-label="岗位详情">` +
      tabButton("match", "匹配依据") +
      tabButton("materials", "申请材料") +
      tabButton("events", "进展记录") +
      `<a class="source-link" href="${safeUrl(j.url)}" target="_blank" rel="noopener noreferrer">岗位原文</a></nav>` +
      `<div id="detail-content">${activeTab === "materials" ? materials(j) : activeTab === "match" ? matches(j) : events(j)}</div>`,
  );
}

export function recommendationSummary(j) {
  const r = j.recommendation;
  if (!r) return "";
  const skills = items(r.skill_matches).map((x) => x.name),
    directions = items(r.direction_matches).map((x) => x.name),
    missing = items(r.missing_skills);
  const hard = items(j.match?.hard).filter((x) => x.status === "not_met");
  const related = skills.length
    ? `<p><strong>相关经历</strong><span>${skills.map(esc).join(" · ")}</span></p>`
    : directions.length
      ? `<p><strong>相关方向</strong><span>${directions.map(esc).join(" · ")}</span></p>`
      : "<p>尚无已确认事实与岗位的直接关联。</p>";
  const blockers = hard.length
    ? `<div class="blocker-box">${hard.map((x) => esc(textOf(x.reason || x.requirement || x))).join("；")}</div>`
    : "";
  const more = missing.length
    ? `<details data-disclosure="skills-${esc(j.id || "")}"><summary>${missing.length} 项技能待补充依据</summary>` +
      `<p>${missing.map(esc).join("、")}</p>` +
      `<p class="small-note">缺少原文提及不代表你不具备这些技能；可在事实资料中补充依据。</p>` +
      `${r.note ? `<p class="small-note">${esc(r.note)}</p>` : ""}</details>`
    : r.note
      ? `<details data-disclosure="recommendation-${esc(j.id || "")}"><summary>推荐依据说明</summary><p class="small-note">${esc(r.note)}</p></details>`
      : "";
  return `<section class="recommendation-note" aria-label="推荐依据">${related}${blockers}${more}</section>`;
}

export function defaultNext(j) {
  if (["unknown", "submission_unknown", "verification_required"].includes(j.status))
    return "核验上一轮执行结果，暂不重复发送";
  if (j.status === "rejected") return "已决定不申请";
  if (j.approval) return "执行前核对岗位状态与批准快照";
  if (j.package) return "核对材料、事实缺口与披露范围";
  return "准备这一岗位的申请材料";
}

export function actionButton(j) {
  if (
    [
      "unknown",
      "submission_unknown",
      "verification_required",
      "sending",
      "submitted",
      "verified",
      "rejected",
    ].includes(j.status)
  )
    return "";
  if (j.approval)
    return executionSupported(j) && !syntheticCandidate()
      ? '<button class="primary" data-execute>执行已批准操作</button>'
      : '<p class="small-note">此渠道当前仅支持岗位发现与材料准备。</p>';
  if (j.package)
    return `<button class="${j.material_review_current ? "secondary" : "primary"}" data-review-current>${j.material_review_current ? "查看复核材料" : "复核材料"}</button>`;
  return '<button class="secondary" data-prepare>准备材料</button>';
}

export function listBox(list, kind = "warning") {
  if (!list?.length) return "";
  const rows = [...list].sort(
    (a, b) => Number(b?.status === "not_met") - Number(a?.status === "not_met"),
  );
  const renderRows = (xs) =>
    `<ul>${xs.map((x) => `<li>${esc(textOf(x) + (x?.reason ? "：" + x.reason : ""))}</li>`).join("")}</ul>`;
  return (
    `<div class="${kind === "blocker" ? "blocker-box" : "warning-box"}">` +
    `<strong>${kind === "blocker" ? "执行前必须补齐" : "需要留意"} · ${rows.length} 项</strong>` +
    `${renderRows(rows.slice(0, 3))}` +
    `${rows.length > 3 ? `<details><summary>查看其余 ${rows.length - 3} 项</summary>${renderRows(rows.slice(3))}</details>` : ""}` +
    `</div>`
  );
}

export function materials(j) {
  const p = j.package;
  if (!p)
    return (
      `<div class="detail-section"><h3>还没有申请材料</h3>` +
      `<p class="muted">完成资料建档后，运行器会按岗位要求准备可审阅草稿。</p>` +
      `<button class="secondary spaced-top" data-prepare>准备材料</button></div>${rawJob(j)}`
    );
  const claims = items(p.claims);
  const facts = state.candidate?.facts || [];
  const fileBase = `/api/file/${encodeURIComponent(p.id)}`;
  const claimRows =
    claims
      .map(
        (c) =>
          `<div class="evidence-row"><p>${esc(c.text)}</p>${items(c.fact_ids)
            .map((id) => {
              const f = facts.find((f) => f.id === id);
              return `<p><small>${esc(id)} · ${esc(f ? sourceOf(f) : "来源缺失")} · ${esc(f?.status || "待确认")} · ${esc(f?.disclosure || "披露范围待确认")}</small></p>`;
            })
            .join("")}</div>`,
      )
      .join("") || '<p class="small-note">尚无可使用的已确认主张。</p>';
  const cover = p.cover_letter
    ? `<div class="material-heading"><h3>求职信草稿</h3><span class="small-note">随申请包保存</span></div>` +
      `<pre class="document-preview">${esc(textOf(p.cover_letter))}</pre>`
    : "";
  const answers = items(p.answers).length
    ? `<section class="detail-section"><h3>筛选问题回答</h3>${p.answers.map((a) => `<div class="evidence-row"><strong>${esc(a.question || a.field || "问题")}</strong><p>${esc(a.answer || a.value || "尚待补充")}</p></div>`).join("")}</section>`
    : "";
  return (
    `<section class="detail-section">` +
    `<div class="material-heading material-first"><h3>这一份申请</h3><button class="text-button" data-prepare>重新准备</button></div>` +
    `<p class="muted">${esc(summaryOf(j.match?.summary) || "材料按已确认、允许披露的事实生成。请核对岗位要求与事实范围。")}</p>` +
    `<p class="small-note">${state.candidate?.synthetic || state.candidate?.is_demo ? "合成候选人 · 仅用于开发验收。" : "本地规则草稿 · 未调用外部模型。"} 事实版本 ${esc(p.candidate_version || "未知")}</p>` +
    `${j.material_review_current ? '<p class="small-note">当前材料已在本地复核；缺口与外发限制仍保留。</p>' : ""}` +
    `${listBox(p.blockers, "blocker")}${listBox(p.gaps)}</section>` +
    `<div class="material-heading"><h3>定制简历</h3><div class="download-links">` +
    `<a href="${fileBase}/resume.txt" download>可编辑文本</a>` +
    `<a href="${fileBase}/resume.pdf" target="_blank" rel="noopener">查看 PDF</a></div></div>` +
    `<pre class="document-preview">${esc(textOf(p.resume))}</pre>` +
    `<details class="evidence-details"><summary>查看个人主张与事实来源 · ${claims.length} 项</summary>${claimRows}</details>` +
    cover +
    answers +
    `<details class="evidence-details"><summary>材料与岗位版本</summary>` +
    `<p class="small-note">岗位 ID：${esc(j.id)}<br>申请包：${esc(p.id)}<br>采集时间：${esc(dateOf(j.collected_at))}<br>发布时间：${esc(j.published_at ? dateOf(j.published_at) : "来源未提供")}</p>` +
    `<p class="snapshot">快照 ${esc(p.snapshot)}</p></details>` +
    rawJob(j)
  );
}

export function rawJob(j) {
  return (
    `<details class="evidence-details"><summary>展开岗位原文与采集信息</summary>` +
    `<p class="small-note">${esc(j.channel || "手工导入")} · ${esc(dateOf(j.collected_at))}${j.duplicate_hint ? `<br>疑似重复：${esc(textOf(j.duplicate_hint))}` : ""}</p>` +
    `<div class="raw-text">${esc(j.jd || "尚未获取岗位原文。")}</div></details>`
  );
}

export function matches(j) {
  const reqs = [...items(j.match?.hard), ...items(j.match?.requirements)];
  const counts = Object.entries(matchMap)
    .map(([key, [label]]) => {
      const count = reqs.filter((r) => r.status === key).length;
      return count ? `<span>${esc(label)} ${count}</span>` : "";
    })
    .join("");
  const rows = reqs.length
    ? reqs
        .map(
          (r, i) =>
            `<details class="match-row" data-disclosure="match-${esc(j.id)}-${i}">` +
            `<summary><strong>${esc(r.text || r.requirement)}</strong>${badge(r.status, matchMap)}</summary>` +
            `<div class="match-evidence"><p>${esc(r.reason || "尚无进一步依据")}</p>` +
            `${items(r.fact_ids).length ? `<p class="fact-ref">事实 ${r.fact_ids.map(esc).join("、")}</p>` : ""}</div></details>`,
        )
        .join("")
    : '<p class="small-note">准备材料后显示逐项依据。</p>';
  return (
    `<section class="detail-section"><div class="match-summary">${counts || "<span>尚未进行事实对照</span>"}</div>${rows}</section>` +
    rawJob(j)
  );
}

export function events(j) {
  const all = [
    ...items(j.events),
    ...items(j.attempts).map((a) => ({
      ...a,
      kind: a.status,
      note: a.error || a.result || a.reason,
      time: a.updated_at || a.created_at,
    })),
  ];
  const rows =
    all
      .map(
        (e) =>
          `<li><time>${esc(dateOf(e.time || e.created_at || e.timestamp || e.at))}</time>` +
          `<strong>${esc(e.kind || e.type || e.action || "记录")}</strong>` +
          `<p>${esc(textOf(e.note || e.detail || e.message || ""))}</p>` +
          `${e.evidence ? `<details class="evidence-details"><summary>查看证据</summary><div class="raw-text">${esc(textOf(e.evidence))}</div></details>` : ""}</li>`,
      )
      .join("") || "<li><p>暂无进展记录。</p></li>";
  return (
    `<section class="detail-section"><h3>进展</h3>` +
    `<p class="muted">准备、填写、上传和正式提交分别记录。只有对应岗位的回执才能核验投递。</p>` +
    `<ul class="timeline">${rows}</ul>` +
    `<form id="event-form" class="event-form"><h3>补充进展</h3>` +
    `<label class="spaced-top">事件类型<select name="kind">` +
    `<option value="reply">收到回复</option><option value="interview">面试安排</option>` +
    `<option value="followup_draft">跟进记录</option><option value="note">补充说明</option></select></label>` +
    `<label>具体情况<textarea name="note" rows="3" required placeholder="记录发生了什么，以及下一步。"></textarea></label>` +
    `<label>对应证据（可选）<textarea name="evidence" rows="2" placeholder="回执编号、官方记录链接或原文；不填写凭据。"></textarea></label>` +
    `<button class="secondary" type="submit">保存记录</button>` +
    `<p class="small-note">手工记录保留为用户提供的事件，不自动升级为平台核验成功。</p></form></section>`
  );
}

$("#detail-pane").addEventListener("submit", async (e) => {
  if (e.target.id !== "event-form") return;
  e.preventDefault();
  if (await action("event", { job_id: activeId, ...Object.fromEntries(new FormData(e.target)) }))
    toast("进展已记录。");
});

// Where an application goes and whether anything may be sent there: entry checks, Moka login checks, execution support.
import { dateOf, esc, safeUrl } from "../shared/dom.js";
import { isDemo, state } from "../shared/state.js";

export function syntheticCandidate() {
  return isDemo() || !!(state?.candidate?.synthetic || state?.candidate?.is_demo);
}

export function canAuthorizeReview(jobs) {
  return jobs.length > 0 && !syntheticCandidate() && jobs.every(executionSupported);
}

export function executionSupported(j) {
  if (j?.channel !== "anker") return false;
  try {
    const url = new URL(j.application_url);
    return (
      url.protocol === "https:" &&
      url.hostname === "anker-in.jobs.feishu.cn" &&
      /^\/index\/resume\/[^/]+\/apply\/?$/.test(url.pathname)
    );
  } catch {
    return false;
  }
}

export function availabilityNotice(j) {
  if (j.availability !== "unverified") return "";
  return (
    `<div class="availability-note"><span class="badge warn">在招待确认</span>` +
    `<details data-disclosure="availability-${esc(j.id || "")}"><summary>来源说明</summary>` +
    `<p class="small-note">${esc(j.raw?.availability_note || "已找到岗位页面，尚未确认当前是否仍在招聘。")}</p>` +
    `</details></div>`
  );
}

export function applicationRoute(j) {
  const r = j.raw?.application_route || {},
    check = r.entry_check,
    url = safeUrl(j.application_url),
    valid =
      check?.url === j.application_url &&
      Date.now() - new Date(check.checked_at).getTime() >= 0 &&
      Date.now() - new Date(check.checked_at).getTime() < 86400000;
  const status = valid ? check.status : "unverified",
    unavailable = ["not_found", "identity_mismatch"].includes(status);
  const labels = {
    form_incomplete: "表单未完整加载",
    session_unconfirmed: "登录状态未确认",
    form_seen: "已看到同职位表单",
    job_page_seen: "表单待核验",
    login_required: "需本人登录 · 表单未核验",
    not_found: "入口暂不可用",
    identity_mismatch: "入口身份待核对",
    blocked: "入口访问受阻",
    captcha: "需本人验证",
    check_failed: "入口读取失败",
    needs_browser: "需浏览器核验",
    budget_exhausted: "本轮未核验",
  };
  const explanations = {
    form_incomplete: "页面仍有未成功加载的申请内容，暂不能确认完整表单。",
    session_unconfirmed: "本次未能确认登录状态，申请表单仍需核验。",
    form_seen: "已只读看到同职位申请表单；资格与最终材料仍需核对。",
    job_page_seen: "已看到同职位页面；尚未确认申请表单。",
    login_required: "入口要求本人登录，申请表单尚未核验。",
    not_found: "申请入口返回页面不存在，暂不可用；不据此判定岗位已关闭。",
    identity_mismatch: "入口页面与本职位身份未能对应，暂不显示申请链接。",
    blocked: "入口访问受阻；不据此判定岗位已关闭。",
    captcha: "入口要求本人验证；申请表单尚未核验。",
    check_failed: "入口读取失败；请从来源招聘页核对。",
    needs_browser: "入口需要页面渲染，尚未确认申请表单。",
    budget_exhausted: "本轮入口核验达到上限，此地址尚未核验。",
  };
  const note =
    explanations[status] ||
    (r.status === "careers_linked"
      ? "已读取关联看板的岗位正文；申请表单尚需核验。"
      : "入口来自岗位记录，官网关联与表单尚需核验。");
  const source = safeUrl(r.career_url);
  if (url === "#") return "";
  const email = r.entry_type === "email" && /^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/.test(r.email || "");
  const statusClass = status === "form_seen" ? "verified" : unavailable ? "unavailable" : "pending";
  const link = email
    ? `<strong>${esc(r.email)}</strong>`
    : unavailable
      ? ""
      : `<a href="${url}" target="_blank" rel="noopener noreferrer">打开申请入口（人工操作）</a>`;
  return (
    `<section class="application-route" aria-label="申请入口">` +
    `<div class="entry-line"><span class="entry-status ${statusClass}">${esc(email ? "官网招聘邮箱" : labels[status] || "表单尚需核验")}</span>${link}</div>` +
    `<div class="entry-actions" data-entry-actions="${esc(j.id || "")}">${entryVerificationControls(j)}</div>` +
    `<details class="entry-evidence" data-disclosure="entry-${esc(j.id || "")}">` +
    `<summary>核验详情${valid ? " · " + esc(dateOf(check.checked_at)) : ""}</summary>` +
    `${valid && check.authenticated === true ? '<p class="small-note">独立会话已确认登录。表单可见不表示已申请。</p>' : ""}` +
    `<p class="small-note">${email ? "仅提供邮箱，不自动发送。请在来源页核对职位名称和材料要求。" : esc(note) + " 仅打开网页，不会代填、上传或提交。"}</p>` +
    `${r.repair && status === "form_seen" ? '<p class="small-note">已改用官网明确关联的同职位表单，原入口核验记录已保留。</p>' : ""}` +
    `${source !== "#" ? `<p class="small-note">关联来源：<a href="${source}" target="_blank" rel="noopener noreferrer">${esc(new URL(r.career_url).hostname)}</a> · ${esc(dateOf(r.checked_at))}</p>` : ""}` +
    `</details></section>`
  );
}

export function supportsEntryVerification(j) {
  try {
    const u = new URL(j.application_url);
    return (
      u.protocol === "https:" &&
      !u.username &&
      !u.password &&
      (!u.port || u.port === "443") &&
      ["app.mokahr.com", "hire-r1.mokahr.com"].includes(u.hostname) &&
      /^\/(?:apply|social-recruitment)\/[^/]+\/\d+\/?$/.test(u.pathname) &&
      /^#\/job\/[^/]+\/apply\/?$/.test(u.hash)
    );
  } catch {
    return false;
  }
}

export function entryVerificationControls(j) {
  if (!supportsEntryVerification(j)) return "";
  const task = state?.entry_verifications?.[j.id],
    status = task?.status;
  const running = ["opening", "awaiting_login", "checking"].includes(status);
  if (running) {
    const message =
      task.message ||
      {
        opening: "正在打开独立窗口",
        awaiting_login: "请在独立窗口完成本人登录",
        checking: "正在只读核验表单",
      }[status];
    return (
      `<div class="entry-session"><span class="small-note">${esc(message)}</span><div>` +
      `${status === "awaiting_login" ? `<button class="secondary" data-entry-action="entry_finish" data-entry-job="${esc(j.id)}">已登录，核验入口</button>` : ""}` +
      `<button class="text-button" data-entry-action="entry_cancel" data-entry-job="${esc(j.id)}">结束核验</button>` +
      `</div></div>`
    );
  }
  return (
    `<button class="text-button" data-entry-action="entry_verify" data-entry-job="${esc(j.id)}">${status === "complete" ? "重新只读核验" : "登录核验"}</button>` +
    `${task?.message ? `<p>${esc(task.message)}</p>` : ""}`
  );
}

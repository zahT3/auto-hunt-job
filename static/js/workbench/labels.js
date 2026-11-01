import { esc } from "../shared/dom.js";

export const statusMap = {
  new: ["待准备", "neutral"],
  discovered: ["待准备", "neutral"],
  imported: ["待准备", "neutral"],
  prepared: ["待审核", ""],
  ready: ["待审核", ""],
  review_pending: ["待审核", ""],
  review: ["待审核", ""],
  sending: ["正在执行", "warn"],
  not_sent: ["已确认未发送", "warn"],
  approved: ["已批准", ""],
  rejected: ["不申请", "neutral"],
  blocked: ["待处理", "warn"],
  needs_input: ["待补充", "warn"],
  awaiting_user: ["待处理", "warn"],
  submission_unknown: ["结果待查证", "warn"],
  unknown: ["结果待查证", "warn"],
  verification_required: ["结果待查证", "warn"],
  submitted: ["已核验提交", ""],
  verified: ["已核验提交", ""],
  failed: ["执行失败", "danger"],
  closed: ["已下线", "neutral"],
  not_eligible: ["条件不符", "neutral"],
  duplicate: ["重复岗位", "neutral"],
  draft: ["草稿", "neutral"],
  running: ["正在处理", ""],
  paused: ["已暂停", "warn"],
};

export const matchMap = {
  supported: ["事实支持", ""],
  not_met: ["明确不符合", "danger"],
  missing_evidence: ["缺失证据", "warn"],
  needs_confirmation: ["需要确认", "warn"],
};

export const channelNames = {
  website: "公司官网",
  websearch: "扩展网页搜索",
  boss: "BOSS 直聘",
  liepin: "猎聘",
  anker: "安克官网",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  fixture: "合成验收",
};

export const sourceStatus = {
  needs_browser: "需开启公开页面渲染",
  filtered_empty: "未找到相关岗位",
  budget_exhausted: "达到本轮读取上限",
  ok: "读取成功",
  fetch_error: "读取失败",
  parse_error: "页面未能解析",
  needs_login: "需要登录",
  login_required: "需要登录",
  captcha: "需本人验证",
  blank_page: "页面退回空白",
  success: "读取成功",
  completed: "已完成",
  empty: "未找到结果",
  blocked: "需要处理",
  failed: "读取失败",
  partial: "部分完成",
  running: "正在搜索",
  unsupported: "暂不支持",
  not_configured: "待配置",
  skipped: "已跳过",
  cancelled: "已停止",
  interrupted: "运行中断",
  paused: "已暂停",
};

export function badge(status, map = statusMap) {
  const [label, kind] = map[status] || [status || "待确认", "neutral"];
  return `<span class="badge ${kind}">${esc(label)}</span>`;
}

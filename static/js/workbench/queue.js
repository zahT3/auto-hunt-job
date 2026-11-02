import { $, $$, esc, items, motionBehavior, replaceContent, textOf } from "../shared/dom.js";
import { state } from "../shared/state.js";
import { renderDetail, setActiveTab } from "./detail.js";
import { countsLine, groupedRows } from "../triage/view.js";
import { badge } from "./labels.js";
import { setMobileDetail } from "./layout.js";
import { openReview } from "./review.js";

export let activeId = null;
export let filter = "all";
export let query = "";
export let selected = new Set();

export function setActiveId(id) {
  activeId = id;
}

// Drops selections and the active job when they are no longer in the state.
export function syncQueueSelection(jobs) {
  selected = new Set([...selected].filter((id) => jobs.some((j) => j.id === id)));
  if (!jobs.some((j) => j.id === activeId)) activeId = jobs[0]?.id || null;
}

export function filteredJobs() {
  const needle = query.trim().toLocaleLowerCase();
  return (state.jobs || []).filter(
    (j) =>
      (filter === "all" ||
        (filter === "review" &&
          j.package &&
          !j.material_review_current &&
          !["rejected", "submitted", "verified"].includes(j.status)) ||
        (filter === "unknown" &&
          ["submission_unknown", "unknown", "verification_required"].includes(j.status))) &&
      (!needle ||
        [j.title, j.company, j.location]
          .filter(Boolean)
          .join(" ")
          .toLocaleLowerCase()
          .includes(needle)),
  );
}

export function renderQueue() {
  const jobs = filteredJobs();
  replaceContent(
    "#job-list",
    jobs.length
      ? countsLine() +
          groupedRows(
            jobs,
            (j) =>
              `<article class="job-row ${j.id === activeId ? "selected" : ""}">` +
              `<input type="checkbox" class="job-checkbox" data-id="${esc(j.id)}" aria-label="选择 ${esc(j.title)}" ${selected.has(j.id) ? "checked" : ""}>` +
              `<button type="button" class="job-select" data-id="${esc(j.id)}" aria-current="${j.id === activeId ? "true" : "false"}">` +
              `<div class="job-title">${esc(j.title || "岗位名称待确认")}</div>` +
              `<div class="job-company">${esc(j.company || "公司待确认")}</div>` +
              `<div class="job-meta">${esc(j.location || "地点未知")}${j.salary ? " · " + esc(textOf(j.salary)) : ""}</div>` +
              `<div class="job-foot">${jobBadge(j)}${j.prepare_error ? '<span class="badge warn">准备失败</span>' : ""}<span class="job-entry-state">${esc(queueEntryLabel(j))}</span></div>` +
              `</button></article>`,
          )
      : `<div class="empty-state">` +
          `<h3>${query ? "没有找到匹配岗位" : filter === "all" ? "开始寻找下一份机会" : "暂无符合此筛选的岗位"}</h3>` +
          `<p>${query ? "换一个关键词，或清空搜索。" : filter === "all" ? "上传简历并确认搜索方向。也可以导入岗位。" : "切换到「全部」查看其他岗位。"}</p>` +
          `${filter === "all" ? '<button class="secondary" type="button" data-open-import>导入岗位</button>' : ""}` +
          `</div>`,
  );
  $("#selected-count").textContent = selected.size ? String(selected.size) : "";
  $("#batch-review").disabled = !selected.size;
  $("#select-all").checked = jobs.length > 0 && jobs.every((j) => selected.has(j.id));
  $("#select-all").indeterminate =
    jobs.some((j) => selected.has(j.id)) && !$("#select-all").checked;
}

export function jobCurrent() {
  return (state.jobs || []).find((j) => j.id === activeId);
}

export function materialNeedsAttention(j) {
  return (
    items(j.package?.blockers).length > 0 ||
    items(j.package?.gaps).length > 0 ||
    items(j.match?.hard).some((h) => h.status === "not_met")
  );
}

export function jobBadge(j) {
  if (!j.material_review_current) return badge(j.status);
  const normal = ["prepared", "ready", "review_pending", "review", "reviewed"].includes(j.status);
  return `${normal ? "" : badge(j.status)}<span class="badge ${materialNeedsAttention(j) ? "warn" : ""}">已复核${materialNeedsAttention(j) ? " · 待补充" : ""}</span>`;
}

export function queueEntryLabel(j) {
  if (j.availability === "unverified") return "在招待确认";
  const r = j.raw?.application_route || {},
    c = r.entry_check;
  if (r.entry_type === "email") return "招聘邮箱";
  if (
    !c ||
    c.url !== j.application_url ||
    Date.now() - new Date(c.checked_at).getTime() < 0 ||
    Date.now() - new Date(c.checked_at).getTime() >= 86400000
  )
    return "入口待核验";
  return (
    {
      form_seen: "已见表单",
      login_required: "需登录",
      not_found: "入口失效",
      identity_mismatch: "入口待核对",
      blocked: "访问受阻",
      captcha: "需本人验证",
      check_failed: "入口读取失败",
    }[c.status] || "表单待核验"
  );
}

export function showJob(id) {
  activeId = id;
  setActiveTab("match");
  setMobileDetail(true);
  renderQueue();
  renderDetail();
  if (matchMedia("(max-width:700px)").matches)
    $("#detail-pane").scrollIntoView({ behavior: motionBehavior(), block: "start" });
  $("#detail-title")?.focus({ preventScroll: true });
}

$("#select-all").addEventListener("change", (e) => {
  filteredJobs().forEach((j) => (e.target.checked ? selected.add(j.id) : selected.delete(j.id)));
  renderQueue();
});
$("#batch-review").addEventListener("click", () => openReview([...selected]));
$(".filter-row").addEventListener("click", (e) => {
  const b = e.target.closest("[data-filter]");
  if (!b) return;
  filter = b.dataset.filter;
  $$(".filter").forEach((x) => x.classList.toggle("active", x === b));
  renderQueue();
});
$("#job-list").addEventListener("click", (e) => {
  const b = e.target.closest(".job-select");
  if (b) showJob(b.dataset.id);
});
$("#job-list").addEventListener("change", (e) => {
  if (!e.target.matches(".job-checkbox")) return;
  const id = e.target.dataset.id;
  e.target.checked ? selected.add(id) : selected.delete(id);
  renderQueue();
  $('.job-checkbox[data-id="' + CSS.escape(id) + '"]')?.focus({ preventScroll: true });
});
$("#queue-search").addEventListener("input", (e) => {
  query = e.target.value;
  renderQueue();
});

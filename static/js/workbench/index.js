// The job workbench: queue, detail, settings and dialogs. Registers itself as a view of the shared state.
import { action } from "../shared/api.js";
import { $, $$, motionBehavior, openDialog } from "../shared/dom.js";
import { notice, toast } from "../shared/feedback.js";
import { isDemo, registerView, render, state } from "../shared/state.js";
import { openCandidate, removeFact } from "./candidate.js";
import { renderDetail, setActiveTab, activeTab } from "./detail.js";
import { setMobileDetail, setWorkbench } from "./layout.js";
import { renderSearchProgress } from "./progress.js";
import {
  activeId,
  jobCurrent,
  renderQueue,
  setActiveId,
  showJob,
  syncQueueSelection,
} from "./queue.js";
import { renderProfile, openResume, updateResumeConfirm } from "./resume.js";
import { openReview, updateApprove, updateLocalReview } from "./review.js";
import { executionSupported, syntheticCandidate } from "./routes.js";
import {
  configDirty,
  openTargetSettings,
  refreshRunButton,
  renderSettings,
  renderTasks,
} from "./settings.js";

function renderWorkbench() {
  const jobs = state.jobs || [];
  syncQueueSelection(jobs);
  $("#queue-count").textContent = jobs.length;
  $("#dataset-warning").hidden = !isDemo();
  $("#queue-subtitle").textContent = isDemo()
    ? "用合成资料检查整个准备流程。"
    : "把精力留给值得申请的机会。";
  $("#demo-button").textContent = isDemo() ? "载入合成演示" : "查看演示启动方式";
  $("#control-button").textContent = state.control === "running" ? "暂停" : "继续";
  $("#runner-status").className = "runner-status " + state.control;
  $("#runner-status").innerHTML =
    `<i></i>${state.search_running ? "搜索中" : state.control === "running" ? "就绪" : state.control === "paused" ? "已暂停" : "已停止"}`;
  renderQueue();
  renderDetail();
  renderTasks();
  if (!configDirty) renderSettings();
  renderProfile();
  renderSearchProgress();
}

function applyBusy(value, label) {
  refreshRunButton(label);
  $$("dialog button[type=submit]").forEach((b) => {
    b.disabled = value;
  });
  const resumeOpen = $("#resume-dialog").open;
  $("#resume-operation-status").hidden = !value || !resumeOpen;
  $("#resume-operation-status").textContent = value ? label || "正在处理…" : "";
  $("#resume-dialog").setAttribute("aria-busy", String(value && resumeOpen));
  $("#resume-upload-button").textContent =
    value && resumeOpen ? label || "正在处理…" : "读取并理解简历";
  $("#resume-file").disabled = value;
  $("#resume-upload-form").elements.synthetic.disabled = value;
  updateResumeConfirm();
  updateLocalReview();
  updateApprove();
}

registerView({
  render: renderWorkbench,
  renderPassive() {
    renderSearchProgress();
    renderProfile();
  },
  busy: applyBusy,
});

$("#import-button").addEventListener("click", () => openDialog("#import-dialog"));
$("#import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  if (!data.url && !data.jd.trim()) {
    notice("请提供岗位链接或完整岗位原文。", true);
    return;
  }
  const r = await action("import", data, "正在导入与准备…");
  if (r) {
    $("#import-dialog").close();
    e.target.reset();
    const j = state.jobs?.[0];
    if (j) setActiveId(j.id);
    render();
    toast("岗位已导入，当前材料与缺口可在详情中查看。");
  }
});
$("#jd-file").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) {
    notice("文件超过 2 MB，请选择较小的文本文件。", true);
    return;
  }
  $("#import-form").elements.jd.value = await file.text();
  toast("岗位原文已读入本地表单。");
});

document.addEventListener("click", (e) => {
  const entry = e.target.closest("[data-entry-action]");
  if (
    entry &&
    ["entry_verify", "entry_finish", "entry_cancel"].includes(entry.dataset.entryAction)
  ) {
    action(entry.dataset.entryAction, { job_id: entry.dataset.entryJob }, "正在处理入口核验…");
    return;
  }
  if (e.target.closest("[data-close]")) {
    e.target.closest("dialog").close();
    return;
  }
  if (e.target.closest("[data-open-resume]")) openResume();
  if (e.target.closest("[data-open-import]")) openDialog("#import-dialog");
  if (e.target.closest("[data-open-candidate]")) openCandidate();
  if (e.target.closest("[data-open-target]")) openTargetSettings();
  const jb = e.target.closest("[data-open-job]");
  if (jb) {
    showJob(jb.dataset.openJob);
    if (matchMedia("(max-width:700px)").matches) setWorkbench(false);
  }
  if (e.target.closest("[data-review-current]")) openReview([activeId]);
  if (e.target.closest("[data-prepare]")) action("prepare", { job_id: activeId }, "正在准备…");
  if (e.target.closest("[data-execute]")) {
    if (executionSupported(jobCurrent()) && !syntheticCandidate())
      action("execute", { job_id: activeId }, "正在检查与执行…");
    else notice("此渠道尚未支持自动申请，请先核对本地材料。", true);
  }
  const tab = e.target.closest("[data-tab]");
  if (tab) {
    setActiveTab(tab.dataset.tab);
    renderDetail();
    $('[data-tab="' + activeTab + '"]')?.focus({ preventScroll: true });
  }
  if (e.target.closest("[data-scroll-queue]")) {
    setMobileDetail(false);
    $(".queue-pane").scrollIntoView({ behavior: motionBehavior() });
    $('.job-select[data-id="' + CSS.escape(activeId) + '"]')?.focus({ preventScroll: true });
  }
  const rem = e.target.closest("[data-remove-fact]");
  if (rem) removeFact(Number(rem.dataset.removeFact));
});

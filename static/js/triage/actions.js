// Card choice from anywhere (bottom bar, 1/2/3, the triage page), with U to undo the last choice made here.
import { action } from "../shared/api.js";
import { toast } from "../shared/feedback.js";
import { state } from "../shared/state.js";
import { CHOICES, triageLocked, triagePayload } from "./model.js";

const history = [];

export const choiceLabel = (value) => CHOICES.find(([v]) => v === value)?.[1] || "待选";

export function jobById(id) {
  return (state?.jobs || []).find((j) => j.id === id) || null;
}

// The same key twice clears the choice, as in DESIGN.md §7.
export async function toggleTriage(job, value) {
  if (!job) return false;
  if (triageLocked(job)) {
    toast(`「${job.title}」已锁定，不能改选择。`);
    return false;
  }
  const prev = job.triage || null;
  const next = prev === value ? null : value;
  if (!(await action("triage", triagePayload(job.id, next), "正在保存选择…"))) return false;
  history.push({ id: job.id, prev, title: job.title });
  toast(next ? `已移到「${choiceLabel(next)}」：${job.title}` : `已放回待选：${job.title}`, {
    undo: true,
  });
  return true;
}

export async function undoTriage() {
  const last = history.pop();
  if (!last) {
    toast("没有可以撤销的分拣");
    return false;
  }
  if (!(await action("triage", triagePayload(last.id, last.prev), "正在撤销…"))) {
    history.push(last);
    return false;
  }
  toast(`已撤销：${last.title} 回到「${choiceLabel(last.prev)}」`);
  return true;
}

export function triageHistoryLength() {
  return history.length;
}

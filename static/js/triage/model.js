// Card choice (triage) without the DOM: buckets, counts and which choices a job still allows.
// The server decides each job's bucket (job.bucket) and the counts (state.counts); this only reads them.
import { items } from "../shared/dom.js";
import { state } from "../shared/state.js";

export const BUCKETS = [
  ["pending", "待选"],
  ["chosen", "已选"],
  ["materials", "材料"],
  ["sent", "已投"],
  ["skipped", "已跳过"],
];

export const CHOICES = [
  ["interested", "感兴趣"],
  ["later", "稍后"],
  ["skipped", "跳过"],
];

// Mirrors the server's guard: a job being sent, sent, or rejected keeps its choice.
const LOCKED = ["sending", "unknown", "submitted", "rejected"];

export function bucketOf(job) {
  return BUCKETS.some(([key]) => key === job.bucket) ? job.bucket : "pending";
}

export function bucketLabel(key) {
  return BUCKETS.find(([k]) => k === key)?.[1] || key;
}

export function groupByBucket(jobs) {
  return BUCKETS.map(([key, label]) => ({
    key,
    label,
    jobs: items(jobs).filter((j) => bucketOf(j) === key),
  })).filter((group) => group.jobs.length);
}

// Counts as the server computed them over all jobs; missing keys read as 0.
export function bucketCounts() {
  const c = state?.counts || {};
  return {
    ...Object.fromEntries(BUCKETS.map(([key]) => [key, Number(c[key]) || 0])),
    new_today: Number(c.new_today) || 0,
  };
}

export function triageLocked(job) {
  return LOCKED.includes(job.status);
}

// Undoing 感兴趣 drops prepared materials on the server, and approved materials cannot be undone at all.
export function undoBlocked(job) {
  return job.triage === "interested" && (job.status === "approved" || !!job.approval);
}

export function triagePayload(jobId, value) {
  return { job_id: jobId, value: value || null };
}

export function preparing(job) {
  return job.triage === "interested" && !job.package && !job.prepare_error;
}

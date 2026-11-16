// Pure helpers of the tailoring page (#/tailor/<job id>): labels, the before/after diff, keyboard movement.
// No DOM and no network, so the frontend tests can run them directly.
import { esc, items } from "../shared/dom.js";

export const TAILOR_OPS = {
  reorder: "调序",
  alias: "换成岗位原词",
  hide: "隐藏",
  rephrase: "AI 改写",
};
export const TAILOR_STATUS = {
  accepted: ["ok", "已接受"],
  pending: ["unknown", "待审核"],
  rejected: ["bad", "已撤销"],
  stale: ["near", "事实已变，需重新生成"],
};
export const TAILOR_FLAGS = {
  strength_up: "职责强度升级",
  negation_dropped: "否定变肯定",
  close_to_jd: "贴近岗位原句",
};
export const TAILOR_REVIEWER = {
  unsupported: "审稿人：事实撑不起这句话",
  overstated: "审稿人：说得比事实重",
  off_topic: "审稿人：和这条要求无关",
};
export const TAILOR_GAP = {
  absent: "事实里没有",
  related: "只有相近说法",
  hard_not_met: "硬条件不符合",
  hard_unknown: "硬条件不知道",
};
export const TAILOR_HARD_GATE = {
  new_number: "出现了事实里没有的数字或量化",
  new_term: "出现了事实里没有的工具或技术名",
  new_project: "出现了事实里没有的雇主、学校或项目名",
  new_title: "出现了事实里没有的职位或头衔",
  new_award: "出现了事实里没有的奖项",
  new_certificate: "出现了事实里没有的证书",
  new_contact: "出现了链接或手机号",
  job_only_term: "用了岗位里有、事实里没有的词",
  missing_fact: "引用的事实不存在",
  stale_fact: "引用的事实已变",
  bad_fact: "引用的事实不存在",
  bad_requirement: "引用的岗位要求不存在",
  empty_after: "改写后的文字为空",
  bad_op: "操作不在允许范围内",
  too_long: "改写太长",
};

// Character diff by longest common subsequence: [{t: "same" | "del" | "add", s}]. Long texts fall back to a whole swap.
export function tailorDiff(before, after) {
  const a = Array.from(before ?? "");
  const b = Array.from(after ?? "");
  if (a.length * b.length > 1_500_000) {
    return [
      { t: "del", s: a.join("") },
      { t: "add", s: b.join("") },
    ];
  }
  const w = b.length + 1;
  const table = new Uint16Array((a.length + 1) * w);
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      table[i * w + j] =
        a[i] === b[j] ? table[(i + 1) * w + j + 1] + 1 : Math.max(table[(i + 1) * w + j], table[i * w + j + 1]);
  const out = [];
  const push = (t, s) => {
    if (out.length && out[out.length - 1].t === t) out[out.length - 1].s += s;
    else out.push({ t, s });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push("same", a[i]);
      i++;
      j++;
    } else if (table[(i + 1) * w + j] >= table[i * w + j + 1]) push("del", a[i++]);
    else push("add", b[j++]);
  }
  while (i < a.length) push("del", a[i++]);
  while (j < b.length) push("add", b[j++]);
  return out;
}

// Deleted words with a line through them, added words underlined (shape first, colour second).
export function tailorDiffHtml(before, after) {
  return tailorDiff(before, after)
    .map((p) =>
      p.t === "del"
        ? `<del>${esc(p.s)}</del>`
        : p.t === "add"
          ? `<ins>${esc(p.s)}</ins>`
          : esc(p.s),
    )
    .join("")
    .replace(/\n/g, "<br>");
}

// What a card shows for an edit: reorder lists the lines in both orders, hide strikes the line, the rest is a diff.
export function tailorChangeHtml(edit) {
  const lines = (text) =>
    `<ol>${String(text ?? "")
      .split("\n")
      .map((l) => `<li>${esc(l)}</li>`)
      .join("")}</ol>`;
  if (edit.op === "reorder")
    return (
      `<div class="tl-order"><div><p class="tl-cap">原顺序</p>${lines(edit.before)}</div>` +
      `<div><p class="tl-cap">新顺序</p>${lines(edit.after)}</div></div>`
    );
  if (edit.op === "hide")
    return `<p class="tl-text"><del>${esc(edit.before)}</del></p><p class="sub">这一版里隐藏这一行，事实本身不动。</p>`;
  return `<p class="tl-text">${tailorDiffHtml(edit.before, edit.after)}</p>`;
}

// Edit ids in document order; `current` moves by `step` and stops at either end. No current: the first one.
export function tailorMove(ids, current, step) {
  if (!ids.length) return null;
  const at = ids.indexOf(current);
  if (at < 0) return ids[0];
  return ids[Math.min(ids.length - 1, Math.max(0, at + step))];
}

// A reviewer verdict or soft flag marks the edit in red: the user has to read these first.
export function tailorWarnings(edit) {
  const checks = edit.checks || {};
  return [
    ...items(checks.flags).map((f) => TAILOR_FLAGS[f] || f),
    ...(TAILOR_REVIEWER[checks.reviewer] ? [TAILOR_REVIEWER[checks.reviewer]] : []),
  ];
}

export function tailorHardText(rejected) {
  const first = items(rejected.detail)[0];
  const code = first?.code || rejected.reason;
  return (TAILOR_HARD_GATE[code] || code) + (first?.text ? `：${first.text}` : "");
}

// Small HTML pieces of DESIGN.md §5: state words, correction marks, key caps, fact chips. All input is escaped.
import { esc } from "./dom.js";
import { factById } from "./names.js";

// Shape + text; colour is only the third cue.
export const stateWord = (tone, label) => `<span class="st st-${esc(tone)}">${esc(label)}</span>`;

// ✓ ✗ ？ ～ drawn by CSS from the tone, with the words next to them.
export const mark = (tone, label) => `<span class="mark ${esc(tone)}">${esc(label)}</span>`;

export const kbd = (key) => `<span class="kbd" aria-hidden="true">${esc(key)}</span>`;

// Dashed when the fact is not confirmed; the tip shows its text and where it came from.
export function factChip(id) {
  const f = factById(id);
  if (!f)
    return `<span class="fact pending" tabindex="0" data-tip="${esc(id)}：这条事实已不在资料里">${esc(id)}</span>`;
  const confirmed = f.status === "confirmed";
  const source = typeof f.source === "string" ? f.source : f.source?.reference || "来源待补充";
  const tip = `${id}：${f.text}（${source}${confirmed ? "" : "，还没确认"}）`;
  return `<span class="fact${confirmed ? "" : " pending"}" tabindex="0" data-tip="${esc(tip)}">${esc(id)}</span>`;
}

export function jdRefs(refs, companyOf = () => "") {
  if (!refs?.length) return "";
  const tip = refs.map((r) => `${companyOf(r.job_id) || "本机岗位"}：「${r.evidence}」`).join("；");
  return `<span class="jdref" tabindex="0" data-tip="${esc(tip)}">JD ${refs.length} 处</span>`;
}

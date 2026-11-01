// Query, escape and format helpers shared by every view. No state, no network.
export const $ = (s) => document.querySelector(s);
export const $$ = (s) => Array.from(document.querySelectorAll(s));
export const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
export const safeUrl = (v) => {
  try {
    const u = new URL(v);
    return ["http:", "https:"].includes(u.protocol) ? u.href : "#";
  } catch {
    return "#";
  }
};
export const textOf = (v) =>
  typeof v === "string"
    ? v
    : v?.text || v?.reason || v?.message || v?.title || JSON.stringify(v ?? "");
export const dateOf = (v) => {
  if (!v) return "时间未知";
  const d = new Date(v);
  return Number.isNaN(d.getTime())
    ? String(v)
    : d.toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
};
export const fieldValue = (v) => (v && typeof v === "object" ? (v.value ?? "") : (v ?? ""));
export const sourceOf = (f) =>
  typeof f.source === "string"
    ? f.source
    : f.source?.reference ||
      f.source?.path ||
      f.source?.description ||
      f.source?.type ||
      "来源待补充";

export function items(v) {
  return Array.isArray(v) ? v : [];
}

export function motionBehavior() {
  return matchMedia("(prefers-reduced-motion:reduce)").matches ? "auto" : "smooth";
}

// Skips identical HTML so polling never resets focus, and keeps open <details> open across re-renders.
export function replaceContent(selector, html) {
  const node = $(selector);
  if (node._renderedHtml === html) return;
  const open = new Set(
    Array.from(node.querySelectorAll?.("details[open]") || []).map(
      (d) => d.dataset.disclosure || d.querySelector("summary")?.textContent,
    ),
  );
  node.innerHTML = html;
  node._renderedHtml = html;
  Array.from(node.querySelectorAll?.("details") || []).forEach((d) => {
    if (open.has(d.dataset.disclosure || d.querySelector("summary")?.textContent)) d.open = true;
  });
}

export function openDialog(id) {
  $(id).querySelector(".dialog-error")?.remove();
  $(id).showModal();
}

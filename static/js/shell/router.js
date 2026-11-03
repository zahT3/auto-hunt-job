// Hash routes (#/search, #/job/<id>, #/triage, #/orient, #/settings, #/workbench) and the page each one shows.
// A page is {title, render(id), enter?(id), leave?(), currentJob?(), move?(step), open?()}; it renders into #view,
// except the frozen workbench, which keeps its own static markup in #workbench-page.
import { $ } from "../shared/dom.js";

const pages = new Map();
let current = null;
// Set by a page before navigating away so the next page can put focus back on the row the user came from.
let returnTarget = null;

export function registerPage(name, page) {
  pages.set(name, page);
}

export function route() {
  const parts = (location.hash || "#/search").replace(/^#\/?/, "").split("/");
  const page = pages.has(parts[0]) ? parts[0] : "search";
  return { page, id: parts[1] ? decodeURIComponent(parts[1]) : null };
}

export function go(path) {
  location.hash = "#/" + path;
}

export function currentPage() {
  return pages.get(route().page);
}

export function setReturnTarget(selector) {
  returnTarget = selector;
}

export function takeReturnTarget() {
  const target = returnTarget;
  returnTarget = null;
  return target;
}

// Re-render the current page in place (state polls); never moves focus.
export function renderCurrent() {
  const r = route();
  pages.get(r.page)?.render(r.id);
}

// A real route change: swap pages, then move focus to the new page's heading (or back to the row the user left).
export function changeRoute() {
  const r = route();
  const key = r.page + "/" + (r.id || "");
  const page = pages.get(r.page);
  if (current && current !== key) pages.get(current.split("/")[0])?.leave?.();
  current = key;
  const workbench = r.page === "workbench";
  $("#view").hidden = workbench;
  $("#workbench-page").hidden = !workbench;
  document.title = `${page.title} · auto-hunt-job`;
  for (const a of document.querySelectorAll(".nav a[data-page]")) {
    const on = a.dataset.page === r.page || (r.page === "job" && a.dataset.page === "search");
    if (on) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  page.enter?.(r.id);
  page.render(r.id);
  const back = takeReturnTarget();
  const target = (back && document.querySelector(back)) || null;
  if (target) {
    target.focus();
    target.scrollIntoView?.({ block: "nearest" });
    return;
  }
  const heading = (workbench ? $("#workbench-page") : $("#view")).querySelector("h1");
  if (heading) {
    heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
  }
  globalThis.scrollTo?.(0, 0);
}

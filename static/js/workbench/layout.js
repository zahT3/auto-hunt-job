import { $, motionBehavior } from "../shared/dom.js";

export let workbenchOpen = false;
export let mobileDetail = false;

// The settings and tasks pane; below 700px it is its own view, so it is scrolled into place.
export function setWorkbench(open) {
  workbenchOpen = open;
  $("#task-pane").hidden = !open;
  $("#workspace").classList.toggle("with-settings", open);
  $("#workspace-toggle").setAttribute("aria-expanded", String(open));
  if (open && matchMedia("(max-width:700px)").matches)
    $("#task-pane").scrollIntoView({ behavior: motionBehavior(), block: "start" });
}

export function setMobileDetail(show) {
  mobileDetail = show;
  $("#workspace").classList.toggle("show-detail", show);
}

$("#workspace-toggle").addEventListener("click", () => setWorkbench(!workbenchOpen));
$("#workspace-close").addEventListener("click", () => {
  setWorkbench(false);
  $("#workspace-toggle").focus();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && workbenchOpen && !document.querySelector("dialog[open]")) {
    setWorkbench(false);
    $("#workspace-toggle").focus();
  }
});

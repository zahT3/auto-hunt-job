// Entry point: each page and view module registers itself on import; then the page loads state, shows the
// current route and polls the state.
import { loadState } from "./shared/api.js";
import { busy } from "./shared/state.js";
import "./workbench/index.js";
import "./orient/page.js";
import "./search/page.js";
import "./job/page.js";
import "./triage/page.js";
import "./settings/page.js";
import { startShell } from "./shell/index.js";
import { registerPage } from "./shell/router.js";

// The frozen workbench keeps its static markup in #workbench-page; its view renders it on every state change.
registerPage("workbench", { title: "工作台", render() {} });

export async function start() {
  await loadState();
  startShell();
  setInterval(() => {
    if (!busy && !document.hidden) loadState(true);
  }, 3000);
}

start();

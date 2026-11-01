// Entry point: each view module registers itself on import; then the page loads state and polls it.
import { loadState } from "./shared/api.js";
import { busy } from "./shared/state.js";
import "./workbench/index.js";

export function start() {
  loadState();
  setInterval(() => {
    if (!busy && !document.hidden) loadState(true);
  }, 3000);
}

start();

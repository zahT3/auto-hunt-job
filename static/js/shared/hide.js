// The "don't show me" list the user keeps by hand (hide_add / hide_remove / hide_list on /api/action).
// Separate from api.js's action(): a rule change must not redraw the whole app or block on its busy flag.
import { state } from "./state.js";

export let hideRules = [];

async function call(name, payload = {}) {
  const r = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Local-Token": state?.csrf_token || "" },
    body: JSON.stringify({ action: name, ...payload }),
  });
  const data = await r.json();
  if (!r.ok || data.error)
    throw new Error(typeof data.error === "string" ? data.error : "不想看清单没有更新。");
  hideRules = Array.isArray(data.result?.rules) ? data.result.rules : hideRules;
  return data.result;
}

export const loadHideRules = () => call("hide_list");
export const addHideRule = (kind, value) => call("hide_add", { kind, value });
export const removeHideRule = (id) => call("hide_remove", { id });

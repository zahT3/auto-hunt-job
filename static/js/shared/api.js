import { $ } from "./dom.js";
import { clearFeedback, notice } from "./feedback.js";
import { busy, render, renderPassive, setBusy, setState, state } from "./state.js";

// One local action at a time: POST /api/action with the page's CSRF token, then redraw from the returned state.
export async function action(actionName, payload = {}, label = "正在处理…") {
  if (busy) return null;
  clearFeedback("dialog[open]");
  setBusy(true, label);
  try {
    const r = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Local-Token": state?.csrf_token || "" },
      body: JSON.stringify({ action: actionName, ...payload }),
    });
    const data = await r.json();
    if (!r.ok || data.error)
      throw new Error(typeof data.error === "string" ? data.error : JSON.stringify(data.error));
    if (data.state)
      setState({
        ...data.state,
        csrf_token: data.csrf_token || data.state.csrf_token || state?.csrf_token,
      });
    else if (data.jobs) setState(data);
    else await loadState();
    render();
    return data;
  } catch (e) {
    notice(e.message || "操作未完成，请检查本地运行器后重试。", true);
    return null;
  } finally {
    setBusy(false);
  }
}

export async function loadState(background = false) {
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    if (!r.ok) throw new Error("本地服务返回异常。");
    setState(await r.json());
    if ($("#notice").textContent.startsWith("无法读取本地工作台。")) $("#notice").hidden = true;
    if (
      background &&
      (document.querySelector("dialog[open]") || document.activeElement?.closest("form"))
    )
      renderPassive();
    else render();
  } catch (e) {
    notice("无法读取本地工作台。请确认运行器仍在运行，然后刷新页面。", true);
    $("#runner-status").textContent = "连接中断";
  }
}

import { $ } from "./dom.js";

let noticeTimer;

// Inside an open dialog the message is repeated next to its heading, where the user is looking.
export function notice(message, error = false) {
  const modal = document.querySelector("dialog[open]");
  if (modal) {
    let box = modal.querySelector(".dialog-error");
    if (!box) {
      box = document.createElement("div");
      box.className = "dialog-error blocker-box";
      box.setAttribute("role", "alert");
      modal.querySelector(".dialog-heading").after(box);
    }
    box.textContent = message;
    box.scrollIntoView({ block: "nearest" });
  }
  $("#notice").textContent = message;
  $("#notice").className = "notice" + (error ? " error" : "");
  $("#notice").hidden = false;
}

export function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => ($("#toast").hidden = true), 4500);
}

export function clearFeedback(dialog) {
  $(dialog)?.querySelector(".dialog-error")?.remove();
  $("#notice").hidden = true;
}

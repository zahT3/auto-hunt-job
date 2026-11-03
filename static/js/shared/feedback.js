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

// With {undo: true} the toast carries 撤销（U）; the shell listens for its data-act.
export function toast(message, { undo = false } = {}) {
  const box = $("#toast");
  box.textContent = message;
  if (undo) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.act = "undo";
    button.textContent = "撤销（U）";
    box.append(button);
  }
  box.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => (box.hidden = true), 5000);
}

export function clearFeedback(dialog) {
  $(dialog)?.querySelector(".dialog-error")?.remove();
  $("#notice").hidden = true;
}

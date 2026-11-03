// data-tip hints: the first hover waits 400ms (intent); within 600ms of closing one, the next shows at once with no
// animation; leaving hides it at once; keyboard focus shows it too and Esc closes it.
const tip = document.createElement("div");
tip.className = "tip";
tip.id = "tip";
tip.setAttribute("role", "tooltip");
tip.hidden = true;
document.body?.append(tip);

let timer = null;
let lastClose = 0;
let owner = null;

function show(target, instant) {
  owner = target;
  tip.textContent = target.dataset.tip;
  tip.hidden = false;
  tip.classList.toggle("instant", instant);
  const r = target.getBoundingClientRect();
  const w = tip.offsetWidth;
  tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + "px";
  tip.style.top = r.bottom + 8 + "px";
  target.setAttribute("aria-describedby", "tip");
}

export function hideTip() {
  clearTimeout(timer);
  if (owner) {
    owner.removeAttribute("aria-describedby");
    lastClose = Date.now();
  }
  owner = null;
  tip.hidden = true;
}

export function tipOpen() {
  return !!owner;
}

function enter(e) {
  const target = e.target.closest?.("[data-tip]");
  if (!target || target === owner) return;
  clearTimeout(timer);
  if (Date.now() - lastClose < 600 || owner) show(target, true);
  else timer = setTimeout(() => show(target, false), 400);
}

function leave(e) {
  const target = e.target.closest?.("[data-tip]");
  if (target && (!e.relatedTarget || !target.contains(e.relatedTarget))) hideTip();
}

document.addEventListener("pointerover", enter);
document.addEventListener("pointerout", leave);
document.addEventListener("focusin", enter);
document.addEventListener("focusout", leave);
globalThis.addEventListener?.("scroll", hideTip, true);

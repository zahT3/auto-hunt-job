// 提示框：第一次悬停等 400ms 再出现（意图延迟，扫过去不触发）；刚关掉一个、600ms 内再指向别的，立即出现且不播动画。
// 键盘聚焦也会出现，Esc 关掉。用 data-tip 写内容。
(function () {
  const el = document.createElement('div');
  el.className = 'tip';
  el.setAttribute('role', 'tooltip');
  el.id = 'tip';
  el.hidden = true;
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(el));
  let timer = null;
  let lastClose = 0;
  let owner = null;
  const show = (t, instant) => {
    owner = t;
    el.textContent = t.dataset.tip;
    el.hidden = false;
    el.classList.toggle('instant', instant);
    const r = t.getBoundingClientRect();
    const w = el.offsetWidth;
    el.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + 'px';
    el.style.top = (r.bottom + 8) + 'px';
    t.setAttribute('aria-describedby', 'tip');
  };
  const hide = () => {
    clearTimeout(timer);
    if (owner) { owner.removeAttribute('aria-describedby'); lastClose = Date.now(); }
    owner = null;
    el.hidden = true;
  };
  const enter = (e) => {
    const t = e.target.closest && e.target.closest('[data-tip]');
    if (!t || t === owner) return;
    clearTimeout(timer);
    if (Date.now() - lastClose < 600 || owner) show(t, true);
    else timer = setTimeout(() => show(t, false), 400);
  };
  const leave = (e) => {
    const t = e.target.closest && e.target.closest('[data-tip]');
    if (t && (!e.relatedTarget || !t.contains(e.relatedTarget))) hide();
  };
  document.addEventListener('pointerover', enter);
  document.addEventListener('pointerout', leave);
  document.addEventListener('focusin', enter);
  document.addEventListener('focusout', leave);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && owner) { hide(); e.stopPropagation(); } }, true);
  window.addEventListener('scroll', hide, true);
})();

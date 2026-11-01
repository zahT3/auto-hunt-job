// The last state the local server returned, the busy flag, and the views that redraw from them.
// Imported bindings are read-only, so other modules change these through the setters below.
export let state = null;
export let busy = false;
const views = [];

export function setState(next) {
  state = next;
}

export function isDemo() {
  return state?.dataset === "demo";
}

// A view is {render, renderPassive?, busy?}. renderPassive runs on background polls while the user is
// in a dialog or a form, so it must not replace anything the user may be editing.
export function registerView(view) {
  views.push(view);
}

export function render() {
  if (!state) return;
  for (const view of views) view.render();
}

export function renderPassive() {
  if (!state) return;
  for (const view of views) view.renderPassive?.();
}

export function setBusy(value, label) {
  busy = value;
  for (const view of views) view.busy?.(value, label);
}

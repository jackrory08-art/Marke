// Tiny DOM builder. Text is always added as text nodes, never as HTML, so
// anything that came from a market title, rules text or a model is inert.
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (value === true) el.setAttribute(key, '');
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function badge(text, kind) {
  return h('span', { class: `badge ${String(kind).replace(/[^a-z_-]/gi, '-').toLowerCase()}` }, text);
}

export function statePanel(kind, title, text) {
  return h('div', { class: `state ${kind}`, role: kind === 'error' ? 'alert' : 'status' },
    h('strong', null, title), text || null);
}

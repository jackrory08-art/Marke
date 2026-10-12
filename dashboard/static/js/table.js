// Sortable, keyboard-friendly table with expandable rows. Rebuilds on update
// but keeps sort order, expanded rows and keyboard focus.
import { h, clear } from './dom.js';

let uid = 0;

export function dataTable({ columns, rowKey, caption, expandable = false, renderDetail, initialSort, rowClass }) {
  const id = `t${++uid}`;
  let rows = [];
  let sort = initialSort || null;     // { key, dir: 'asc' | 'desc' }
  const expanded = new Set();

  const thead = h('thead');
  const tbody = h('tbody');
  const table = h('table', { class: 'data' },
    caption ? h('caption', null, caption) : null, thead, tbody);
  const el = h('div', { class: 'table-wrap' }, table);

  function sorted() {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return rows;
    const val = col.sortValue || ((r) => r[col.key]);
    const dir = sort.dir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = val(a), y = val(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;      // empty values always last
      if (y == null) return -1;
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
      return String(x).localeCompare(String(y)) * dir;
    });
  }

  function renderHead() {
    clear(thead);
    const tr = h('tr');
    if (expandable) tr.append(h('th', { scope: 'col' }, h('span', { class: 'visually-hidden' }, 'Details')));
    for (const col of columns) {
      const th = h('th', { scope: 'col', class: col.numeric ? 'numeric' : null });
      if (col.sortable === false) {
        th.append(col.label);
      } else {
        const active = sort && sort.key === col.key;
        th.setAttribute('aria-sort', active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none');
        th.append(h('button', {
          type: 'button',
          dataset: { sortKey: col.key },
          onclick: () => {
            const dir = active && sort.dir === 'desc' ? 'asc' : active ? 'desc' : (col.numeric ? 'desc' : 'asc');
            sort = { key: col.key, dir };
            render();
            const btn = thead.querySelector(`[data-sort-key="${CSS.escape(col.key)}"]`);
            if (btn) btn.focus();
          },
        }, col.label));
      }
      tr.append(th);
    }
    thead.append(tr);
  }

  function render() {
    const active = document.activeElement;
    const focusKey = active && table.contains(active) ? active.dataset.key : null;
    renderHead();
    clear(tbody);
    let n = 0;
    for (const row of sorted()) {
      const key = String(rowKey(row));
      const open = expandable && expanded.has(key);
      const detailId = `${id}-d-${n++}`;
      const tr = h('tr', { class: rowClass ? rowClass(row) : null });
      if (expandable) {
        tr.append(h('td', null, h('button', {
          type: 'button', class: 'row-toggle', 'aria-expanded': String(open),
          'aria-controls': open ? detailId : null, 'aria-label': 'Show details', dataset: { key },
          onclick: () => {
            if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
            render();
          },
        })));
      }
      for (const col of columns) {
        const content = col.render ? col.render(row) : row[col.key];
        tr.append(h('td', { class: col.numeric ? 'numeric' : col.class }, content));
      }
      tbody.append(tr);
      if (open) {
        tbody.append(h('tr', { class: 'detail', id: detailId },
          h('td', { colspan: columns.length + 1 }, h('div', { class: 'detail-inner' }, renderDetail(row)))));
      }
    }
    if (focusKey) {
      const again = tbody.querySelector(`[data-key="${CSS.escape(focusKey)}"]`);
      if (again) again.focus();
    }
  }

  renderHead();
  return {
    el,
    get count() { return rows.length; },
    setRows(next) { rows = next || []; render(); },
    expand(key) { expanded.add(String(key)); render(); },
  };
}

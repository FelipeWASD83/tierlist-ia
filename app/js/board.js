// The board: rows, cards, drag and drop and the keyboard.
// `doc` is the tier list as the server stores it; every change calls `onChange()` (which saves).

import { imageUrl } from './api.js';

const PALETTE = 10;
let doc = null;
let onChange = () => {};
let onEditItem = () => {};
let selected = null;          // item id
let dragId = null;
let openSwatch = null;        // tier id with the color picker open

const $ = (sel) => document.querySelector(sel);

export function setup(handlers) {
  onChange = handlers.onChange;
  onEditItem = handlers.onEditItem;
  document.addEventListener('keydown', onKey);
  document.addEventListener('click', (e) => {
    if (openSwatch && !e.target.closest('.swatches') && !e.target.closest('[data-act="color"]')) {
      openSwatch = null;
      render();
    }
  });
  const pool = $('#pool');
  bindZone(pool);
}

export function show(newDoc) {
  doc = newDoc;
  selected = null;
  openSwatch = null;
  render();
}

export function current() {
  return doc;
}

export function selectItem(id) {
  selected = id;
  render();
  const el = document.querySelector(`.card[data-id="${id}"]`);
  if (el) el.focus({ preventScroll: false });
}

// ── Rendering ─────────────────────────────────────────────────────────────

function cardEl(id) {
  const item = doc.items[id];
  const el = document.createElement('div');
  el.className = 'card';
  el.dataset.id = id;
  el.tabIndex = 0;
  el.draggable = true;
  el.setAttribute('role', 'option');
  el.setAttribute('aria-selected', String(selected === id));
  el.setAttribute('aria-label', item.name);
  el.title = `${item.name} (duplo clique para editar)`;
  if (item.image) {
    const img = document.createElement('img');
    img.src = imageUrl(item.image);
    img.alt = '';
    img.loading = 'lazy';
    img.draggable = false;
    img.addEventListener('error', () => img.replaceWith(noImage()), { once: true });
    el.append(img);
  } else {
    el.append(noImage());
  }
  const name = document.createElement('span');
  name.className = 'card-name';
  name.textContent = item.name;
  el.append(name);

  el.addEventListener('click', () => { selected = selected === id ? null : id; render(); refocus(id); });
  el.addEventListener('dblclick', () => onEditItem(id));
  el.addEventListener('dragstart', (e) => {
    dragId = id;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', id);
    requestAnimationFrame(() => el.classList.add('dragging'));
  });
  el.addEventListener('dragend', () => {
    dragId = null;
    el.classList.remove('dragging');
    clearMarks();
  });
  return el;
}

function noImage() {
  const none = document.createElement('div');
  none.className = 'card-noimg';
  none.textContent = 'Sem imagem';
  return none;
}

function refocus(id) {
  const el = document.querySelector(`.card[data-id="${id}"]`);
  if (el) el.focus({ preventScroll: true });
}

function svgIcon(name) {
  return `<svg class="ico"><use href="#i-${name}"/></svg>`;
}

function tierEl(tier, index) {
  const row = document.createElement('div');
  row.className = 'tier';
  row.dataset.tier = tier.id;

  const plate = document.createElement('div');
  plate.className = 'tier-plate';
  plate.style.setProperty('--cor', `var(--fileira-${tier.color % PALETTE})`);

  const label = document.createElement('input');
  label.className = 'tier-label' + (tier.label.length > 3 ? ' long' : '');
  label.value = tier.label;
  label.maxLength = 24;
  label.name = `fileira-${tier.id}`;
  label.setAttribute('aria-label', `Nome da fileira ${index + 1}`);
  label.addEventListener('change', () => {
    tier.label = label.value.trim() || '?';
    onChange();
    render();
  });
  label.addEventListener('keydown', (e) => { if (e.key === 'Enter') label.blur(); e.stopPropagation(); });

  const ctrl = document.createElement('div');
  ctrl.className = 'tier-ctrl';
  ctrl.innerHTML = `
    <button type="button" data-act="up" aria-label="Subir fileira" title="Subir">${svgIcon('up')}</button>
    <button type="button" data-act="down" aria-label="Descer fileira" title="Descer">${svgIcon('down')}</button>
    <button type="button" data-act="color" aria-label="Trocar cor" title="Cor">${svgIcon('palette')}</button>
    <button type="button" data-act="remove" aria-label="Apagar fileira" title="Apagar fileira (as cartas voltam para Sem fileira)">${svgIcon('trash')}</button>`;
  ctrl.addEventListener('click', (e) => {
    const act = e.target.closest('button')?.dataset.act;
    if (!act) return;
    e.stopPropagation();
    const i = doc.tiers.indexOf(tier);
    if (act === 'up' && i > 0) [doc.tiers[i - 1], doc.tiers[i]] = [doc.tiers[i], doc.tiers[i - 1]];
    else if (act === 'down' && i < doc.tiers.length - 1) [doc.tiers[i + 1], doc.tiers[i]] = [doc.tiers[i], doc.tiers[i + 1]];
    else if (act === 'color') { openSwatch = openSwatch === tier.id ? null : tier.id; render(); return; }
    else if (act === 'remove') {
      doc.pool.push(...tier.items);
      doc.tiers.splice(i, 1);
    } else return;
    onChange();
    render();
  });

  plate.append(label, ctrl);
  if (openSwatch === tier.id) {
    const sw = document.createElement('div');
    sw.className = 'swatches';
    for (let c = 0; c < PALETTE; c++) {
      const b = document.createElement('button');
      b.type = 'button';
      b.style.setProperty('--cor', `var(--fileira-${c})`);
      b.setAttribute('aria-label', `Cor ${c + 1}`);
      b.setAttribute('aria-pressed', String(tier.color === c));
      b.addEventListener('click', () => { tier.color = c; openSwatch = null; onChange(); render(); });
      sw.append(b);
    }
    plate.append(sw);
  }

  const zone = document.createElement('div');
  zone.className = 'zone';
  zone.dataset.zone = tier.id;
  zone.setAttribute('role', 'listbox');
  zone.setAttribute('aria-label', `Fileira ${tier.label}`);
  for (const id of tier.items) zone.append(cardEl(id));
  bindZone(zone);

  row.append(plate, zone);
  return row;
}

export function render() {
  if (!doc) return;
  const tiers = $('#tiers');
  tiers.replaceChildren(...doc.tiers.map(tierEl));
  tiers.hidden = doc.tiers.length === 0;
  const pool = $('#pool');
  pool.replaceChildren(...doc.pool.map(cardEl));
  pool.setAttribute('role', 'listbox');
  pool.setAttribute('aria-label', 'Sem fileira');
  $('#pool-count').textContent = doc.pool.length ? `(${doc.pool.length})` : '';
}

// ── Moving cards ──────────────────────────────────────────────────────────

function listOf(zoneId) {
  if (zoneId === 'pool') return doc.pool;
  return doc.tiers.find((t) => t.id === zoneId)?.items;
}

function zoneOfItem(id) {
  if (doc.pool.includes(id)) return 'pool';
  return doc.tiers.find((t) => t.items.includes(id))?.id;
}

export function moveItem(id, zoneId, index) {
  const from = listOf(zoneOfItem(id));
  const to = listOf(zoneId);
  if (!from || !to) return;
  const oldIndex = from.indexOf(id);
  from.splice(oldIndex, 1);
  if (from === to && index > oldIndex) index -= 1;
  index = Math.max(0, Math.min(index ?? to.length, to.length));
  to.splice(index, 0, id);
  onChange();
  render();
}

function insertionIndex(zone, x, y) {
  const cards = [...zone.querySelectorAll('.card:not(.dragging)')];
  let index = 0;
  for (const card of cards) {
    const r = card.getBoundingClientRect();
    const sameLine = y >= r.top && y <= r.bottom;
    if (y > r.bottom || (sameLine && x > r.left + r.width / 2)) index++;
  }
  // index counts cards without the dragged one; convert to an index in the real list
  const ids = cards.map((c) => c.dataset.id);
  const list = listOf(zone.dataset.zone);
  if (index >= ids.length) return list.length;
  return list.indexOf(ids[index]);
}

function clearMarks() {
  document.querySelectorAll('.drop-mark').forEach((m) => m.remove());
  document.querySelectorAll('.zone.over').forEach((z) => z.classList.remove('over'));
}

function bindZone(zone) {
  if (zone.dataset.bound) return;
  zone.dataset.bound = '1';
  zone.addEventListener('dragover', (e) => {
    if (!dragId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    document.querySelectorAll('.zone.over').forEach((z) => z !== zone && z.classList.remove('over'));
    zone.classList.add('over');
    const index = insertionIndex(zone, e.clientX, e.clientY);
    const list = listOf(zone.dataset.zone);
    let mark = zone.querySelector('.drop-mark');
    if (!mark) { mark = document.createElement('div'); mark.className = 'drop-mark'; }
    const before = index < list.length ? zone.querySelector(`.card[data-id="${list[index]}"]`) : null;
    if (before) zone.insertBefore(mark, before); else zone.append(mark);
    document.querySelectorAll('.drop-mark').forEach((m) => m !== mark && m.remove());
  });
  zone.addEventListener('dragleave', (e) => {
    if (!zone.contains(e.relatedTarget)) { zone.classList.remove('over'); zone.querySelector('.drop-mark')?.remove(); }
  });
  zone.addEventListener('drop', (e) => {
    if (!dragId) return;
    e.preventDefault();
    const index = insertionIndex(zone, e.clientX, e.clientY);
    const id = dragId;
    clearMarks();
    moveItem(id, zone.dataset.zone, index);
    selected = id;
    render();
  });
}

// ── Keyboard ──────────────────────────────────────────────────────────────

function onKey(e) {
  if (!doc || !selected || !doc.items[selected]) return;
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (document.querySelector('.drawer.open')) return;
  const id = selected;
  const zoneId = zoneOfItem(id);
  const list = listOf(zoneId);
  if (/^[1-9]$/.test(e.key)) {
    const tier = doc.tiers[Number(e.key) - 1];
    if (tier) { moveItem(id, tier.id, tier.items.length); refocus(id); }
  } else if (e.key === '0') {
    moveItem(id, 'pool', doc.pool.length); refocus(id);
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    const i = list.indexOf(id);
    const j = e.key === 'ArrowLeft' ? i - 1 : i + 1;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    onChange(); render(); refocus(id);
  } else if (e.key === 'Enter') {
    onEditItem(id);
  } else if (e.key === 'Escape') {
    selected = null; render();
  } else return;
  e.preventDefault();
}

// ── Editing helpers used by the drawer and the toolbar ────────────────────

export function newId() {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export function addTier() {
  const used = new Set(doc.tiers.map((t) => t.color));
  let color = 0;
  while (used.has(color) && color < PALETTE - 1) color++;
  doc.tiers.push({ id: newId(), label: 'Nova', color, items: [] });
  onChange();
  render();
  const labels = document.querySelectorAll('.tier-label');
  labels[labels.length - 1]?.select();
}

export function addItem(name, image, query) {
  const id = newId();
  doc.items[id] = { name, image, query: query || name };
  doc.pool.push(id);
  onChange();
  selected = id;
  render();
  return id;
}

export function removeItem(id) {
  for (const list of [doc.pool, ...doc.tiers.map((t) => t.items)]) {
    const i = list.indexOf(id);
    if (i >= 0) list.splice(i, 1);
  }
  delete doc.items[id];
  if (selected === id) selected = null;
  onChange();
  render();
}

export function updateItem(id, changes) {
  Object.assign(doc.items[id], changes);
  onChange();
  render();
}

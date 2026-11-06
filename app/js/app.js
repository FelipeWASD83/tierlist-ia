// Tierlist IA: the sidebar, the request box, the generation and saving.

import { api, imageUrl } from './api.js';
import * as board from './board.js';
import * as drawer from './drawer.js';
import { exportPng } from './export.js';

const $ = (sel) => document.querySelector(sel);
const fmtDate = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
const fmtUsd = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 3 });

let state = null;
let currentId = null;
let saveTimer = null;
let saving = Promise.resolve();
let generating = false;

// ── Saved lists ───────────────────────────────────────────────────────────

async function refreshSaved() {
  const { tierlists } = await api('tierlists');
  const ul = $('#saved');
  ul.replaceChildren(...tierlists.map((t) => {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'saved-item';
    b.setAttribute('aria-current', String(t.id === currentId));
    const covers = document.createElement('span');
    covers.className = 'saved-covers';
    for (const c of t.covers) {
      const img = document.createElement('img');
      img.src = imageUrl(c);
      img.alt = '';
      img.loading = 'lazy';
      covers.append(img);
    }
    const text = document.createElement('span');
    const name = document.createElement('span');
    name.className = 'saved-name';
    name.textContent = t.title;
    const count = document.createElement('span');
    count.className = 'saved-count';
    count.textContent = `${t.count} ${t.count === 1 ? 'item' : 'itens'} · ${fmtDate.format(new Date(t.updated * 1000))}`;
    text.append(name, count);
    b.append(covers, text);
    b.addEventListener('click', () => openList(t.id));
    li.append(b);
    return li;
  }));
  $('#saved-empty').hidden = tierlists.length > 0;
  return tierlists;
}

async function openList(id) {
  await flushSave();
  try {
    const doc = await api(`tierlists/${id}`);
    currentId = id;
    showDoc(doc);
    localStorageSet('ultima', id);
    refreshSaved();
  } catch (err) {
    drawer.toast(err.message);
  }
}

function showDoc(doc) {
  $('#board-empty').hidden = true;
  $('#board').hidden = false;
  $('#board-title').value = doc.title;
  const meta = [];
  if (doc.request) meta.push(`Pedido: “${doc.request}”`);
  if (doc.model) meta.push(`montada por ${doc.model}`);
  if (typeof doc.cost === 'number') meta.push(`custou cerca de ${fmtUsd.format(doc.cost)}`);
  $('#board-meta').textContent = meta.join(' · ');
  $('#board-meta').hidden = meta.length === 0;
  $('#save-state').textContent = '';
  board.show(doc);
}

function showEmpty() {
  currentId = null;
  $('#board').hidden = true;
  $('#board-empty').hidden = false;
}

// ── Saving (debounced) ────────────────────────────────────────────────────

function scheduleSave() {
  $('#save-state').textContent = 'Salvando...';
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { saveTimer = null; saving = saveNow(); }, 500);
}

async function saveNow() {
  const doc = board.current();
  if (!doc) return;
  try {
    await api(`tierlists/${doc.id}`, { method: 'PUT', body: doc });
    $('#save-state').textContent = 'Salvo';
    refreshSaved();
  } catch (err) {
    $('#save-state').textContent = 'Não salvou';
    drawer.toast(err.message);
  }
}

async function flushSave() {
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; saving = saveNow(); }
  await saving;
}

window.addEventListener('beforeunload', () => {
  if (saveTimer) {
    const doc = board.current();
    // last chance: the regular fetch would be cancelled with the page
    fetch(`/api/tierlists/${doc.id}`, { method: 'PUT', keepalive: true, headers: { 'X-Tierlist': '1', 'Content-Type': 'application/json' }, body: JSON.stringify(doc) });
  }
});

// ── Request box ───────────────────────────────────────────────────────────

function setCount(n) {
  const min = Number($('#count').min);
  const max = Number($('#count').max);
  n = Math.max(min, Math.min(max, Math.round(n)));
  $('#count').value = n;
  $('#count-value').textContent = n;
  $('#count-minus').disabled = n <= min;
  $('#count-plus').disabled = n >= max;
  return n;
}

let cfgTimer = null;
function saveComposerPrefs() {
  clearTimeout(cfgTimer);
  cfgTimer = setTimeout(() => {
    api('config', { method: 'POST', body: {
      itens: Number($('#count').value), classificar: $('#opt-rank').checked, busca_web: $('#opt-web').checked,
    } }).catch(() => {});
  }, 400);
}

function message(text, ok = false) {
  const el = $('#composer-msg');
  el.textContent = text || '';
  el.classList.toggle('ok', ok);
  el.hidden = !text;
}

function progress(text, done, total) {
  $('#progress').hidden = false;
  const bar = $('#progress .progress-bar');
  const fill = $('#progress-fill');
  if (total) {
    bar.classList.remove('indeterminate');
    fill.style.width = `${Math.round((done / total) * 100)}%`;
    $('#progress-text').textContent = `${text}: ${done} de ${total}`;
  } else {
    bar.classList.add('indeterminate');
    fill.style.width = '';
    $('#progress-text').textContent = `${text}...`;
  }
}

async function generate() {
  if (generating) return;
  const request = $('#request').value.trim();
  if (request.length < 3) { message('Escreve sobre o que é a tierlist.'); $('#request').focus(); return; }
  if (!state.chaves.claude && !state.chaves.openai) {
    message('Falta a chave da IA. Abrindo as Configurações para você colar.');
    drawer.settings(state, (s) => { state = s; });
    return;
  }
  message('');
  generating = true;
  $('#btn-generate').disabled = true;
  $('#btn-generate').textContent = 'Montando...';
  progress('Começando');
  const started = performance.now();
  try {
    const { tarefa } = await api('gerar', { method: 'POST', body: {
      pedido: request, itens: Number($('#count').value), classificar: $('#opt-rank').checked, busca_web: $('#opt-web').checked,
    } });
    let task;
    for (;;) {
      await new Promise((r) => setTimeout(r, 700));
      task = await api(`tarefas/${tarefa}`);
      if (task.estado !== 'rodando') break;
      progress(task.fase, task.feito, task.total);
    }
    if (task.estado === 'erro') throw new Error(task.erro);
    await openList(task.tierlist);
    const secs = Math.round((performance.now() - started) / 1000);
    const notes = [`Pronta em ${secs} s`];
    if (task.trocou) notes.push(`o crédito acabou e quem montou foi ${task.modelo}`);
    if (task.sem_imagem) notes.push(`${task.sem_imagem} sem imagem (clique duas vezes na carta para escolher)`);
    message(`${notes.join('; ')}.`, true);
  } catch (err) {
    message(err.message);
  } finally {
    generating = false;
    $('#progress').hidden = true;
    $('#btn-generate').disabled = false;
    $('#btn-generate').textContent = 'Montar tierlist';
  }
}

// ── Small helpers ─────────────────────────────────────────────────────────

function localStorageGet(key) {
  try { return localStorage.getItem(`tierlist-ia.${key}`); } catch { return null; }
}
function localStorageSet(key, value) {
  try { localStorage.setItem(`tierlist-ia.${key}`, value); } catch { /* private mode */ }
}

// ── Start ─────────────────────────────────────────────────────────────────

async function start() {
  board.setup({ onChange: scheduleSave, onEditItem: (id) => drawer.editItem(id) });
  try {
    state = await api('estado');
  } catch (err) {
    message(err.message);
    return;
  }
  $('#version').textContent = `Versão ${state.versao}`;
  $('#count').min = state.limites.min;
  $('#count').max = state.limites.max;
  setCount(state.config.itens);
  $('#opt-rank').checked = state.config.classificar;
  $('#opt-web').checked = state.config.busca_web;

  $('#count').addEventListener('input', () => { setCount(Number($('#count').value)); saveComposerPrefs(); });
  $('#count-minus').addEventListener('click', () => { setCount(Number($('#count').value) - 1); saveComposerPrefs(); });
  $('#count-plus').addEventListener('click', () => { setCount(Number($('#count').value) + 1); saveComposerPrefs(); });
  $('#opt-rank').addEventListener('change', saveComposerPrefs);
  $('#opt-web').addEventListener('change', saveComposerPrefs);
  $('#btn-generate').addEventListener('click', generate);
  $('#request').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) generate(); });

  $('#btn-new-ai').addEventListener('click', () => { $('#request').focus(); $('#request').select(); });
  $('#btn-new-empty').addEventListener('click', async () => {
    await flushSave();
    const doc = await api('tierlists', { method: 'POST', body: { title: 'Tierlist nova' } });
    await openList(doc.id);
    $('#board-title').select();
  });
  $('#btn-settings').addEventListener('click', () => drawer.settings(state, (s) => { state = s; }));

  $('#board-title').addEventListener('change', () => {
    const doc = board.current();
    doc.title = $('#board-title').value.trim() || 'Tierlist';
    $('#board-title').value = doc.title;
    scheduleSave();
  });
  $('#board-title').addEventListener('keydown', (e) => { if (e.key === 'Enter') e.target.blur(); });
  $('#btn-add-tier').addEventListener('click', () => board.addTier());
  $('#btn-add-item').addEventListener('click', () => drawer.newItem());
  $('#btn-export').addEventListener('click', async () => {
    const btn = $('#btn-export');
    btn.disabled = true;
    try { await exportPng(board.current()); } catch (err) { drawer.toast(`Não deu para exportar: ${err.message}`); }
    finally { btn.disabled = false; }
  });
  $('#btn-delete-list').addEventListener('click', async () => {
    const doc = board.current();
    if (!confirm(`Apagar a tierlist "${doc.title}"? Não dá para desfazer.`)) return;
    clearTimeout(saveTimer); saveTimer = null;
    await api(`tierlists/${doc.id}`, { method: 'DELETE' });
    showEmpty();
    const lists = await refreshSaved();
    drawer.toast('Tierlist apagada.');
    if (lists[0]) openList(lists[0].id);
  });

  const lists = await refreshSaved();
  const last = localStorageGet('ultima');
  const pick = lists.find((t) => t.id === last) || lists[0];
  if (pick) await openList(pick.id);
  else $('#request').focus();
  if (!state.chaves.claude && !state.chaves.openai) {
    message('Antes da primeira tierlist, cole a chave da Anthropic em Configurações (botão no canto de baixo).');
  }
}

start();

// Side drawer: edit a card (name, picture) and the settings (keys, model, update).

import { api, imageUrl } from './api.js';
import * as board from './board.js';

const drawer = document.getElementById('drawer');
const scrim = document.getElementById('scrim');
const body = document.getElementById('drawer-body');
const title = document.getElementById('drawer-title');
let lastFocus = null;
let toastTimer = null;
let fieldCount = 0;

export function toast(text) {
  document.querySelector('.toast')?.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  el.textContent = text;
  document.body.append(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 3200);
}

function open(heading) {
  lastFocus = document.activeElement;
  title.textContent = heading;
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
  scrim.hidden = false;
}

export function close() {
  drawer.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
  scrim.hidden = true;
  body.replaceChildren();
  lastFocus?.focus?.({ preventScroll: true });
}

document.getElementById('drawer-close').addEventListener('click', close);
scrim.addEventListener('click', close);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && drawer.classList.contains('open')) close(); });

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, '');
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) el.append(c);
  if ((tag === 'input' || tag === 'select') && !el.name) el.name = `campo-${++fieldCount}`;
  return el;
}

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'ico');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

function preview(item) {
  const card = h('div', { class: 'card', 'aria-hidden': 'true' });
  if (item.image) card.append(h('img', { src: imageUrl(item.image), alt: '' }));
  else card.append(h('div', { class: 'card-noimg' }, 'Sem imagem'));
  card.append(h('span', { class: 'card-name' }, item.name));
  return card;
}

// ── Edit a card ───────────────────────────────────────────────────────────

export function editItem(id) {
  const doc = board.current();
  const item = doc?.items[id];
  if (!item) return;
  open('Editar carta');

  const status = h('p', { class: 'note', 'aria-live': 'polite' });
  const pic = h('div', { class: 'current-pic' }, preview(item),
    h('p', { class: 'note' }, 'A IA não vê as imagens. Se a foto veio errada, escolha outra abaixo, cole um link ou solte um arquivo.'));

  const setImage = (name) => {
    board.updateItem(id, { image: name });
    pic.firstChild.replaceWith(preview(doc.items[id]));
    status.textContent = 'Imagem trocada.';
  };

  const nameInput = h('input', { class: 'input', value: item.name, maxlength: '80' });
  nameInput.addEventListener('change', () => {
    const v = nameInput.value.trim();
    if (!v) { nameInput.value = item.name; return; }
    board.updateItem(id, { name: v });
    pic.firstChild.replaceWith(preview(doc.items[id]));
  });

  const queryInput = h('input', { class: 'input', value: item.query || item.name, maxlength: '200', 'aria-label': 'Buscar imagem' });
  const grid = h('div', { class: 'candidates' });
  const search = async () => {
    const q = queryInput.value.trim();
    if (!q) return;
    grid.replaceChildren(h('p', { class: 'note' }, 'Buscando...'));
    try {
      const { resultados } = await api(`imagens/buscar?q=${encodeURIComponent(q)}`);
      board.updateItem(id, { query: q });
      if (!resultados.length) { grid.replaceChildren(h('p', { class: 'note' }, 'Nada encontrado. Tenta outras palavras.')); return; }
      grid.replaceChildren(...resultados.map((r) => {
        const b = h('button', { class: 'candidate', type: 'button', title: r.title || '' },
          h('img', { src: r.thumb, alt: r.title || 'Opção de imagem', loading: 'lazy', referrerpolicy: 'no-referrer' }));
        b.addEventListener('click', async () => {
          b.setAttribute('aria-busy', 'true');
          status.textContent = 'Baixando...';
          try {
            const { image } = await api('imagens/baixar', { method: 'POST', body: { url: r.full } })
              .catch(() => api('imagens/baixar', { method: 'POST', body: { url: r.thumb } }));
            setImage(image);
          } catch (err) {
            status.textContent = err.message;
          } finally {
            b.removeAttribute('aria-busy');
          }
        });
        return b;
      }));
    } catch (err) {
      grid.replaceChildren(h('p', { class: 'note danger' }, err.message));
    }
  };
  queryInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });

  const linkInput = h('input', { class: 'input', placeholder: 'https://...', 'aria-label': 'Link da imagem' });
  const useLink = async () => {
    const url = linkInput.value.trim();
    if (!url) return;
    status.textContent = 'Baixando...';
    try { setImage((await api('imagens/baixar', { method: 'POST', body: { url } })).image); linkInput.value = ''; }
    catch (err) { status.textContent = err.message; }
  };
  linkInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') useLink(); });

  const fileInput = h('input', { type: 'file', accept: 'image/*', hidden: true });
  const upload = async (file) => {
    if (!file) return;
    status.textContent = 'Enviando...';
    try { setImage((await api('imagens/enviar', { method: 'POST', raw: file })).image); }
    catch (err) { status.textContent = err.message; }
  };
  fileInput.addEventListener('change', () => upload(fileInput.files[0]));
  const drop = h('div', { class: 'dropzone' },
    h('span', {}, 'Solte uma imagem aqui ou cole com Ctrl+V'),
    h('button', { class: 'btn', type: 'button', onclick: () => fileInput.click() }, icon('image'), 'Escolher arquivo'));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); upload(e.dataTransfer.files[0]); });
  const onPaste = (e) => {
    if (!drawer.classList.contains('open')) { document.removeEventListener('paste', onPaste); return; }
    const file = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith('image/'));
    if (file) { e.preventDefault(); upload(file); }
  };
  document.addEventListener('paste', onPaste);

  body.replaceChildren(
    pic,
    h('label', { class: 'field' }, h('span', {}, 'Nome'), nameInput),
    h('div', { class: 'field' },
      h('span', {}, 'Buscar outra imagem'),
      h('div', { class: 'inline' }, queryInput,
        h('button', { class: 'btn', type: 'button', onclick: search }, icon('search'), 'Buscar')),
      grid),
    h('label', { class: 'field' }, h('span', {}, 'Ou cole o link de uma imagem'),
      h('div', { class: 'inline' }, linkInput, h('button', { class: 'btn', type: 'button', onclick: useLink }, 'Usar'))),
    drop, fileInput, status,
    h('div', { class: 'row-end' },
      h('span'),
      h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => { board.removeItem(id); close(); toast('Carta removida.'); } },
        icon('trash'), 'Remover carta')),
  );
  search();
  nameInput.focus();
}

// ── New card ──────────────────────────────────────────────────────────────

export function newItem() {
  open('Nova carta');
  const nameInput = h('input', { class: 'input', maxlength: '80', placeholder: 'Ex.: Nico Robin' });
  const queryInput = h('input', { class: 'input', maxlength: '200', placeholder: 'Opcional: Nico Robin One Piece' });
  const status = h('p', { class: 'note', 'aria-live': 'polite' });
  const add = h('button', { class: 'btn btn-primary', type: 'button' }, icon('plus'), 'Adicionar');
  const go = async () => {
    const name = nameInput.value.trim();
    if (!name) { status.textContent = 'Dá um nome para a carta.'; nameInput.focus(); return; }
    add.disabled = true;
    status.textContent = 'Buscando a imagem...';
    let image = null;
    try { image = (await api('imagens/item', { method: 'POST', body: { nome: name, busca: queryInput.value.trim() } })).image; }
    catch { /* card without picture is still useful */ }
    const id = board.addItem(name, image, queryInput.value.trim() || name);
    close();
    toast(image ? 'Carta adicionada em Sem fileira.' : 'Carta adicionada, sem imagem: clique duas vezes nela para escolher.');
    board.selectItem(id);
  };
  add.addEventListener('click', go);
  nameInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  queryInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  body.replaceChildren(
    h('label', { class: 'field' }, h('span', {}, 'Nome'), nameInput),
    h('label', { class: 'field' }, h('span', {}, 'Busca da imagem'), queryInput,
      h('small', {}, 'Ajuda quando o nome sozinho é ambíguo.')),
    h('div', {}, add), status,
  );
  nameInput.focus();
}

// ── Settings ──────────────────────────────────────────────────────────────

export function settings(state, onSaved) {
  open('Configurações');
  const status = h('p', { class: 'note', 'aria-live': 'polite' });

  const keyField = (name, label, help, placeholder) => {
    const input = h('input', { class: 'input', type: 'password', autocomplete: 'off', placeholder, 'aria-label': label });
    const shown = h('span', { class: 'key-state' }, state.chaves[name] ? `Guardada (${state.chaves[name]})` : 'Nenhuma');
    const save = async (value) => {
      try {
        const next = await api('chave', { method: 'POST', body: { nome: name, valor: value } });
        Object.assign(state, next);
        shown.textContent = next.chaves[name] ? `Guardada (${next.chaves[name]})` : 'Nenhuma';
        input.value = '';
        status.textContent = value ? 'Chave guardada.' : 'Chave apagada.';
        onSaved(state);
      } catch (err) { status.textContent = err.message; }
    };
    return h('div', { class: 'field' },
      h('div', { class: 'row-end' }, h('span', { style: 'font-weight:700' }, label), shown),
      h('div', { class: 'inline' }, input,
        h('button', { class: 'btn', type: 'button', onclick: () => input.value.trim() && save(input.value.trim()) }, 'Guardar'),
        h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => save(''), 'aria-label': `Apagar ${label}` }, icon('trash'))),
      h('small', {}, help));
  };

  const modelSelect = h('select', { class: 'select', 'aria-label': 'Modelo' },
    state.modelos.map((m) => h('option', { value: m.id, selected: m.id === state.config.modelo }, m.nome)));
  if (!state.modelos.some((m) => m.id === state.config.modelo)) {
    modelSelect.append(h('option', { value: state.config.modelo, selected: true }, state.config.modelo));
  }
  const effortSelect = h('select', { class: 'select', 'aria-label': 'Esforço' },
    [['low', 'Baixo (mais rápido e barato)'], ['medium', 'Médio'], ['high', 'Alto (pensa mais)']]
      .map(([v, n]) => h('option', { value: v, selected: v === state.config.esforco }, n)));
  const saveCfg = async (changes) => {
    try { state.config = (await api('config', { method: 'POST', body: changes })).config; status.textContent = 'Salvo.'; onSaved(state); }
    catch (err) { status.textContent = err.message; }
  };
  modelSelect.addEventListener('change', () => saveCfg({ modelo: modelSelect.value }));
  effortSelect.addEventListener('change', () => saveCfg({ esforco: effortSelect.value }));

  const updateBox = h('div', { class: 'field' });
  const renderUpdate = (info, busy) => {
    const parts = [h('div', { class: 'row-end' }, h('span', { style: 'font-weight:700' }, 'Atualização'),
      h('span', { class: 'key-state' }, `Versão ${state.versao}`))];
    if (busy) parts.push(h('p', { class: 'note' }, busy));
    else if (info?.erro) parts.push(h('p', { class: 'note' }, info.erro));
    else if (info?.nova) {
      parts.push(h('p', { class: 'note' }, `Tem versão nova: ${info.ultima}.`));
      parts.push(h('div', {}, h('button', { class: 'btn btn-primary', type: 'button', onclick: install }, icon('download'), `Instalar ${info.ultima}`)));
    } else if (info) parts.push(h('p', { class: 'note' }, 'Você está na versão mais nova.'));
    if (!busy) parts.push(h('div', {}, h('button', { class: 'btn', type: 'button', onclick: () => check(true) }, 'Procurar atualização')));
    updateBox.replaceChildren(...parts);
  };
  const check = async (force) => {
    renderUpdate(null, 'Perguntando ao GitHub...');
    try { renderUpdate(await api(`atualizacao${force ? '?forcar=1' : ''}`)); }
    catch (err) { renderUpdate({ erro: err.message }); }
  };
  const install = async () => {
    renderUpdate(null, 'Baixando e conferindo a versão nova...');
    try {
      await api('atualizacao/baixar', { method: 'POST' });
      renderUpdate(null, 'Reiniciando o app...');
      await api('atualizacao/reiniciar', { method: 'POST' });
      setTimeout(() => waitAndReload(), 1500);
    } catch (err) { renderUpdate({ erro: err.message }); }
  };
  renderUpdate(null);

  body.replaceChildren(
    h('p', { class: 'section-title' }, 'Chaves da IA'),
    keyField('claude', 'Chave da Anthropic (Claude)', 'Crie em console.anthropic.com (com plano Max, na organização ligada a ele, para usar o crédito do plano). Fica guardada criptografada pelo Windows, só neste PC.', 'sk-ant-...'),
    keyField('openai', 'Chave da OpenAI (opcional)', 'Só serve de reserva: se o crédito do Claude acabar, a tierlist sai pelo GPT.', 'sk-...'),
    h('p', { class: 'section-title' }, 'Modelo'),
    h('label', { class: 'field' }, h('span', {}, 'Quem monta a tierlist'), modelSelect,
      h('small', {}, 'Sonnet 5.5 é o padrão: forte e rápido. Opus pensa melhor e custa o dobro; Haiku é o mais barato.')),
    h('label', { class: 'field' }, h('span', {}, 'Esforço'), effortSelect),
    updateBox,
    keyField('github', 'Token do GitHub (só se o repositório for privado)', 'Token de leitura do repositório tierlist-ia, para o botão de atualizar enxergar as versões.', 'github_pat_...'),
    status,
  );
}

async function waitAndReload() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch('/api/estado', { headers: { 'X-Tierlist': '1' } });
      if (r.ok) { location.reload(); return; }
    } catch { /* still restarting */ }
    await new Promise((res) => setTimeout(res, 500));
  }
  toast('O app não voltou sozinho. Feche e abra de novo.');
}

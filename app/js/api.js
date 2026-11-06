// Talks to the local server. Every call carries the X-Tierlist header the server requires.

export class ApiError extends Error {}

export async function api(path, { method = 'GET', body, raw } = {}) {
  const headers = { 'X-Tierlist': '1' };
  let payload;
  if (raw) {
    payload = raw;
    headers['Content-Type'] = raw.type || 'application/octet-stream';
  } else if (body !== undefined) {
    payload = JSON.stringify(body);
    headers['Content-Type'] = 'application/json';
  }
  let resp;
  try {
    resp = await fetch(`/api/${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError('O servidor do app não respondeu. Ele foi fechado?');
  }
  let data = {};
  try { data = await resp.json(); } catch { /* empty body */ }
  if (!resp.ok) throw new ApiError(data.erro || `Erro ${resp.status}`);
  return data;
}

export const imageUrl = (name) => (name ? `/imagens/${name}` : '');

// Downloads a picture here in the app (a normal browser request) and hands the bytes to the server to keep.
// Used for Fandom: its image server serves browsers and refuses scripts like the app's server.
export async function keepFromBrowser(url) {
  let blob;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(String(resp.status));
    blob = await resp.blob();
  } catch {
    throw new ApiError('Não deu para baixar essa imagem.');
  }
  if (!blob.type.startsWith('image/') || !blob.size) throw new ApiError('Isso não é uma imagem.');
  return (await api('imagens/enviar', { method: 'POST', raw: blob })).image;
}

// The picture for one card from its pending addresses: Fandom through the browser, anything else through the
// server; when none works, the server's own search (Bing, filtered by name). Returns the stored name or null.
export async function resolvePicture(item) {
  for (const url of item.pending || []) {
    try {
      if (new URL(url).hostname.endsWith('wikia.nocookie.net')) return await keepFromBrowser(url);
      return (await api('imagens/baixar', { method: 'POST', body: { url } })).image;
    } catch { /* next address */ }
  }
  try {
    return (await api('imagens/item', { method: 'POST', body: { nome: item.name, busca: item.query || item.name } })).image;
  } catch {
    return null;
  }
}

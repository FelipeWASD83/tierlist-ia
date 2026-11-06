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

// Draws the tier list on a canvas and saves it as PNG. The pictures come from /imagens (same origin).

import { imageUrl } from './api.js';

const WIDTH = 2400;
const PAD = 48;
const PLATE = 220;
const CARD = 150;
const GAP = 10;
const BORDER = 6;

function loadImage(src) {
  return new Promise((resolve) => {
    if (!src) { resolve(null); return; }
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

function cover(ctx, img, x, y, size) {
  const s = Math.min(img.naturalWidth, img.naturalHeight);
  const sx = (img.naturalWidth - s) / 2;
  const sy = (img.naturalHeight - s) * 0.12;     // same top-leaning crop as the cards on screen
  ctx.drawImage(img, sx, sy, s, s, x, y, size, size);
}

function fitText(ctx, text, max) {
  if (ctx.measureText(text).width <= max) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(`${t}…`).width > max) t = t.slice(0, -1);
  return `${t}…`;
}

export async function exportPng(doc) {
  await document.fonts.ready;
  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();
  const ink = color('--tinta');
  const paper = color('--papel');

  const perRow = Math.floor((WIDTH - PAD * 2 - PLATE - BORDER * 2 - GAP) / (CARD + GAP));
  const rows = doc.tiers.map((t) => Math.max(1, Math.ceil(t.items.length / perRow)));
  const titleH = 120;
  const tiersH = rows.reduce((sum, n) => sum + n * (CARD + GAP) + GAP, 0) + BORDER * (doc.tiers.length + 1);
  const height = PAD + titleH + tiersH + PAD + 40;

  const canvas = document.createElement('canvas');
  canvas.width = WIDTH;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = paper;
  ctx.fillRect(0, 0, WIDTH, height);

  ctx.fillStyle = ink;
  ctx.textBaseline = 'alphabetic';
  ctx.font = '900 76px Archivo';
  ctx.fontStretch = 'expanded';
  ctx.fillText(fitText(ctx, doc.title, WIDTH - PAD * 2), PAD, PAD + 80);
  ctx.fontStretch = 'normal';

  const images = new Map();
  await Promise.all(Object.entries(doc.items).map(async ([id, item]) => {
    images.set(id, await loadImage(imageUrl(item.image)));
  }));

  // board frame
  const top = PAD + titleH;
  ctx.fillStyle = ink;
  ctx.fillRect(PAD + 8, top + 8, WIDTH - PAD * 2, tiersH);     // hard shadow
  ctx.fillRect(PAD, top, WIDTH - PAD * 2, tiersH);

  let y = top + BORDER;
  doc.tiers.forEach((tier, i) => {
    const rowH = rows[i] * (CARD + GAP) + GAP;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(PAD + BORDER, y, WIDTH - PAD * 2 - BORDER * 2, rowH);
    ctx.fillStyle = color(`--fileira-${tier.color % 10}`);
    ctx.fillRect(PAD + BORDER, y, PLATE, rowH);
    ctx.fillStyle = ink;
    ctx.fillRect(PAD + BORDER + PLATE, y, BORDER, rowH);
    const big = tier.label.length <= 3;
    ctx.font = big ? '900 84px Archivo' : '800 34px Archivo';
    ctx.fontStretch = big ? 'expanded' : 'normal';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(fitText(ctx, tier.label, PLATE - 24), PAD + BORDER + PLATE / 2, y + rowH / 2);
    ctx.fontStretch = 'normal';
    ctx.textAlign = 'left';

    tier.items.forEach((id, k) => {
      const col = k % perRow;
      const line = Math.floor(k / perRow);
      const x = PAD + BORDER + PLATE + BORDER + GAP + col * (CARD + GAP);
      const cy = y + GAP + line * (CARD + GAP);
      ctx.fillStyle = ink;
      ctx.fillRect(x - 3, cy - 3, CARD + 6, CARD + 6);
      const img = images.get(id);
      if (img) cover(ctx, img, x, cy, CARD);
      else { ctx.fillStyle = '#26252c'; ctx.fillRect(x, cy, CARD, CARD); }
      ctx.fillStyle = ink;
      ctx.fillRect(x, cy + CARD - 30, CARD, 30);
      ctx.fillStyle = '#ffffff';
      ctx.font = '650 17px Archivo';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(fitText(ctx, doc.items[id].name, CARD - 10), x + CARD / 2, cy + CARD - 15);
      ctx.textAlign = 'left';
    });
    y += rowH + BORDER;
  });

  ctx.fillStyle = ink;
  ctx.globalAlpha = 0.55;
  ctx.font = '600 20px Archivo';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText('Feita no Tierlist IA', PAD, height - PAD + 12);
  ctx.globalAlpha = 1;

  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
  const a = document.createElement('a');
  const safe = doc.title.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\w-]+/g, '-').replace(/^-|-$/g, '').toLowerCase();
  a.download = `${safe || 'tierlist'}.png`;
  a.href = URL.createObjectURL(blob);
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

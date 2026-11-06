"""Tier lists on disk: one JSON per list in dados/tierlists/<id>.json.

Shape:
    {id, title, request, model, cost, created, updated,
     tiers: [{id, label, color, items: [item id, ...]}],
     pool:  [item id, ...],                  # unranked
     items: {item id: {name, image, query}}}
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time

import config
import imagens

PALETTE_SIZE = 10
_ID = re.compile(r"^[a-z0-9]{6,32}$")
_lock = threading.Lock()


class StoreError(Exception):
    pass


def new_id() -> str:
    return secrets.token_hex(6)


def _file(list_id: str):
    if not _ID.match(list_id or ""):
        raise StoreError("Tierlist inexistente.")
    return config.LISTS / f"{list_id}.json"


def from_ai(result: dict, request: str) -> dict:
    """Turns the AI result (already with pictures) into a stored tier list."""
    tiers = [{"id": new_id(), "label": label, "color": i % PALETTE_SIZE, "items": []}
             for i, label in enumerate(result["tiers"])]
    items, pool = {}, []
    for item in result["items"]:
        item_id = new_id()
        items[item_id] = {"name": item["name"], "image": item.get("image"), "query": item.get("image_query") or item["name"]}
        if 0 <= item["tier"] < len(tiers):
            tiers[item["tier"]]["items"].append(item_id)
        else:
            pool.append(item_id)
    now = time.time()
    return {"id": new_id(), "title": result["title"], "request": request, "model": result.get("model"),
            "cost": result.get("cost"), "created": now, "updated": now, "tiers": tiers, "pool": pool, "items": items}


def clean(doc: dict, list_id: str) -> dict:
    """Validates a list that came from the screen. Every item ends up in exactly one place."""
    if not isinstance(doc, dict):
        raise StoreError("Formato inválido.")
    raw_items = doc.get("items") if isinstance(doc.get("items"), dict) else {}
    items = {}
    for item_id, item in raw_items.items():
        if not _ID.match(str(item_id)) or not isinstance(item, dict):
            continue
        image = item.get("image")
        items[item_id] = {
            "name": str(item.get("name") or "").strip()[:80] or "Sem nome",
            "image": image if isinstance(image, str) and imagens.path_of(image) else None,
            "query": str(item.get("query") or item.get("name") or "").strip()[:200],
        }
    placed = set()

    def take(ids):
        out = []
        for item_id in ids if isinstance(ids, list) else []:
            if item_id in items and item_id not in placed:
                placed.add(item_id)
                out.append(item_id)
        return out

    tiers = []
    for tier in (doc.get("tiers") if isinstance(doc.get("tiers"), list) else [])[:20]:
        if not isinstance(tier, dict):
            continue
        try:
            color = int(tier.get("color", 0)) % PALETTE_SIZE
        except (TypeError, ValueError):
            color = 0
        tier_id = str(tier.get("id") or "")
        tiers.append({"id": tier_id if _ID.match(tier_id) else new_id(),
                      "label": str(tier.get("label") or "").strip()[:24] or "?",
                      "color": color, "items": take(tier.get("items"))})
    pool = take(doc.get("pool"))
    pool += [item_id for item_id in items if item_id not in placed]
    old = {}
    try:
        old = load(list_id)
    except StoreError:
        pass
    return {"id": list_id, "title": str(doc.get("title") or "").strip()[:120] or "Tierlist",
            "request": old.get("request") or str(doc.get("request") or "")[:4000],
            "model": old.get("model"), "cost": old.get("cost"),
            "created": old.get("created") or time.time(), "updated": time.time(),
            "tiers": tiers, "pool": pool, "items": items}


def save(doc: dict) -> dict:
    path = _file(doc["id"])
    with _lock:
        config.LISTS.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return doc


def load(list_id: str) -> dict:
    try:
        doc = json.loads(_file(list_id).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StoreError("Tierlist inexistente.") from e
    if not isinstance(doc, dict):
        raise StoreError("Tierlist inexistente.")
    return doc


def delete(list_id: str) -> None:
    with _lock:
        try:
            _file(list_id).unlink()
        except FileNotFoundError as e:
            raise StoreError("Tierlist inexistente.") from e


def summaries() -> list[dict]:
    out = []
    if not config.LISTS.is_dir():
        return out
    for path in config.LISTS.glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = doc.get("items") or {}
        order = [i for t in doc.get("tiers") or [] for i in t.get("items") or []] + list(doc.get("pool") or [])
        covers = [items[i]["image"] for i in order if i in items and items[i].get("image")][:4]
        out.append({"id": doc.get("id"), "title": doc.get("title"), "updated": doc.get("updated") or 0,
                    "count": len(items), "covers": covers})
    out.sort(key=lambda s: s["updated"], reverse=True)
    return out

"""Paths, version and the app settings file (dados/config.json)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
DATA = Path(os.environ.get("TIERLIST_IA_DADOS") or (ROOT / "dados"))
IMAGES = DATA / "imagens"
LISTS = DATA / "tierlists"
PORT = 4362

DEFAULT_MODEL = "claude-sonnet-5-5"
MODELS = [
    ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ("claude-opus-5-5", "Claude Opus 5.5"),
    ("claude-haiku-5-5", "Claude Haiku 5.5"),
    ("claude-fable-5-1", "Claude Fable 5.1"),
    ("gpt-6.1-sol", "GPT-6.1 Sol"),
    ("gpt-6-luna", "GPT-6 Luna"),
    ("gpt-6-astra", "GPT-6 Astra"),
]
EFFORTS = ("low", "medium", "high")

DEFAULTS = {
    "modelo": DEFAULT_MODEL,
    "esforco": "medium",
    "reserva": "auto",
    "busca_web": True,
    "itens": 20,
    "classificar": True,
}

_lock = threading.Lock()


def version_info() -> dict:
    try:
        return json.loads((ROOT / "versao.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


VERSION = version_info().get("versao", "0.0.0")


def _settings_file() -> Path:
    return DATA / "config.json"


def load() -> dict:
    try:
        saved = json.loads(_settings_file().read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            saved = {}
    except (OSError, ValueError):
        saved = {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def save(changes: dict) -> dict:
    with _lock:
        current = load()
        for key, value in changes.items():
            if key not in DEFAULTS:
                continue
            if key == "modelo":
                value = str(value or "").strip() or DEFAULT_MODEL
            elif key == "esforco":
                value = value if value in EFFORTS else "medium"
            elif key == "reserva":
                value = str(value or "auto").strip() or "auto"
            elif key in ("busca_web", "classificar"):
                value = bool(value)
            elif key == "itens":
                value = clamp_items(value)
            current[key] = value
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = _settings_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, _settings_file())
        return current


MIN_ITEMS, MAX_ITEMS = 5, 60


def clamp_items(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = DEFAULTS["itens"]
    return max(MIN_ITEMS, min(MAX_ITEMS, n))

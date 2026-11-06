"""Finds and stores the item pictures.

Order for each item: the main image of its Fandom wiki article (fiction: characters, weapons, bosses...), then
the lead image of its Wikipedia article (both titles come from the AI), then Bing Images, accepted only when
the result's title or page mentions the item. Every picture is downloaded into dados/imagens/<sha1>.<ext>, so
a tier list keeps working when the original site changes, and the PNG export can read it (same origin).

DuckDuckGo is not used: in 2026-11 its image endpoint answers automated requests with an anti-bot challenge.
Bing goes through /images/async (the endpoint its own page uses for more results): in 2026-11 the regular
/images/search page sometimes answered scripts with results for only the first word of the query.
"""

from __future__ import annotations

import hashlib
import html
import http.cookiejar
import ipaddress
import json
import re
import socket
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import config

USER_AGENT = "TierlistIA/1.0 (personal local app; https://github.com/FelipeWASD83/tierlist-ia)"
BROWSER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/131.0 Safari/537.36")
MAX_BYTES = 8 * 1024 * 1024
WIKI_THUMB = 600
TIMEOUT = 20
_LANG = re.compile(r"^[a-z]{2,3}(-[a-z]{2,8})?$")
_WIKI = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
_BING_ITEM = re.compile(r'class="iusc"[^>]*?\sm="([^"]+)"')
_OWN_AGENT_HOSTS = ("wikipedia.org", "wikimedia.org", "fandom.com", "wikia.nocookie.net")


class ImageError(Exception):
    pass


# ── Safety: only public hosts, only real image bytes ─────────────────────────


def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return bool(infos)


def check_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ImageError("O link precisa começar com http:// ou https://.")
    if parts.username or parts.password:
        raise ImageError("Link com usuário e senha não serve.")
    if not _host_is_public(parts.hostname):
        raise ImageError("Esse endereço não é um site público da internet.")
    return url.strip()


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def image_type(data: bytes) -> str | None:
    """Extension from the magic bytes. SVG is refused on purpose (it can carry scripts)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    if data.startswith(b"BM"):
        return "bmp"
    return None


def store(data: bytes) -> str:
    """Saves the bytes under their hash and returns the file name (the same picture is stored once)."""
    if len(data) > MAX_BYTES:
        raise ImageError("A imagem passa de 8 MB.")
    ext = image_type(data)
    if not ext:
        raise ImageError("Isso não é uma imagem (aceito JPG, PNG, GIF, WebP, AVIF e BMP).")
    name = f"{hashlib.sha1(data).hexdigest()}.{ext}"
    config.IMAGES.mkdir(parents=True, exist_ok=True)
    target = config.IMAGES / name
    if not target.exists():
        tmp = target.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
    return name


def download(url: str, referer: str | None = None) -> str:
    url = check_url(url)
    host = urllib.parse.urlsplit(url).hostname or ""
    # Wikimedia asks for an agent that says who the client is; the rest gets a browser's.
    agent = USER_AGENT if host.endswith(_OWN_AGENT_HOSTS) else BROWSER_AGENT
    headers = {"User-Agent": agent, "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    for attempt in range(2):
        try:
            with _opener.open(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as resp:
                data = resp.read(MAX_BYTES + 1)
            return store(data)
        except ImageError:
            raise
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt == 0:
                time.sleep(1.5)
                continue
            raise ImageError(f"Não consegui baixar a imagem (erro {e.code}).") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ImageError(f"Não consegui baixar a imagem ({e}).") from e
    raise ImageError("Não consegui baixar a imagem.")


def path_of(name: str) -> Path | None:
    """The stored file for a name that came from the screen, or None if the name is not one of ours."""
    if not re.fullmatch(r"[0-9a-f]{40}\.(jpg|png|gif|webp|avif|bmp)", name or ""):
        return None
    path = config.IMAGES / name
    return path if path.is_file() else None


# ── Wikis (Wikipedia and Fandom speak the same MediaWiki API) ────────────────


def _get_json(url: str, agent: str = USER_AGENT) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _page_images(api_url: str, titles: list[str]) -> dict[str, str]:
    """{title as asked: thumbnail URL}, 50 titles per request."""
    found: dict[str, str] = {}
    unique = list(dict.fromkeys(t for t in titles if t))
    for start in range(0, len(unique), 50):
        batch = unique[start:start + 50]
        query = urllib.parse.urlencode({
            "action": "query", "format": "json", "formatversion": "2", "prop": "pageimages",
            "piprop": "thumbnail", "pithumbsize": WIKI_THUMB, "pilicense": "any", "redirects": "1",
            "titles": "|".join(batch),
        })
        try:
            data = _get_json(f"{api_url}?{query}")
        except (urllib.error.URLError, OSError, ValueError):
            continue
        q = data.get("query") or {}
        # Follow what the API did to each title: normalized (case, underscores), then redirected.
        alias: dict[str, str | None] = {t: t for t in batch}
        for step in ("normalized", "redirects"):
            for change in q.get(step) or []:
                for asked, current in list(alias.items()):
                    if current is not None and current == change.get("from"):
                        # A redirect into a section ("Trafalgar Law" -> "List of One Piece characters#...") lands on
                        # a list whose picture is a group shot, not the item's own picture.
                        alias[asked] = None if (step == "redirects" and change.get("tofragment")) else change.get("to")
        by_title = {}
        for page in q.get("pages") or []:
            thumb = (page.get("thumbnail") or {}).get("source")
            if thumb and not page.get("missing"):
                by_title[page.get("title")] = thumb
        for asked, current in alias.items():
            if current in by_title:
                found[asked] = by_title[current]
    return found


def wikipedia_images(titles: list[str], lang: str = "en") -> dict[str, str]:
    lang = lang if _LANG.match(lang or "") else "en"
    return _page_images(f"https://{lang}.wikipedia.org/w/api.php", titles)


def fandom_images(titles: list[str], wiki: str) -> dict[str, str]:
    """Main image of each article on <wiki>.fandom.com (the infobox picture of a character, weapon, boss...)."""
    if not _WIKI.match(wiki or ""):
        return {}
    return _page_images(f"https://{wiki}.fandom.com/api.php", titles)


# ── Bing ─────────────────────────────────────────────────────────────────────

_bing_lock = threading.Lock()
_bing_opener = None


def _bing():
    """One cookie session per run, like a browser tab: the first request picks up Bing's cookies."""
    global _bing_opener
    with _bing_lock:
        if _bing_opener is None:
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            opener.addheaders = [("User-Agent", BROWSER_AGENT), ("Accept-Language", "pt-BR,pt;q=0.9,en;q=0.8")]
            try:
                opener.open("https://www.bing.com/", timeout=TIMEOUT).read()
            except (urllib.error.URLError, OSError):
                pass
            _bing_opener = opener
        return _bing_opener


def bing_search(query: str, limit: int = 12) -> list[dict]:
    """Image results: thumbnail (Bing's own copy, reliable), original, title, source page."""
    params = urllib.parse.urlencode({"q": query, "first": "0", "count": str(max(limit, 10)), "mmasync": "1",
                                     "adlt": "moderate"})
    try:
        with _bing().open(f"https://www.bing.com/images/async?{params}", timeout=TIMEOUT) as resp:
            page = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise ImageError(f"A busca de imagens falhou ({e}).") from e
    results = []
    for raw in _BING_ITEM.findall(page):
        try:
            data = json.loads(html.unescape(raw))
        except ValueError:
            continue
        thumb, full = data.get("turl"), data.get("murl")
        if not thumb and not full:
            continue
        results.append({"thumb": thumb or full, "full": full or thumb,
                        "title": (data.get("t") or "").replace("‎", "").strip(), "page": data.get("purl") or ""})
        if len(results) >= limit:
            break
    return results


_STOP = {"the", "and", "of", "de", "da", "do", "das", "dos", "for", "com", "con", "del", "la", "le", "les", "el"}


def _words(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]+", plain) if len(w) >= 3 and w not in _STOP}


def mentions(result: dict, name: str) -> bool:
    """Does the Bing result talk about the item? (its title or page address shares a word with the name)"""
    wanted = _words(name)
    if not wanted:
        return True
    return bool(wanted & (_words(result.get("title", "")) | _words(result.get("page", ""))))


# ── Putting it together ──────────────────────────────────────────────────────


def picture_for(item: dict, wiki_urls: list[tuple[str, str]] | None = None) -> tuple[str | None, str]:
    """(stored file name or None, where it came from). `wiki_urls`: [(url, source)], Fandom first, then Wikipedia."""
    for url, source in wiki_urls or []:
        try:
            return download(url), source
        except ImageError:
            pass
    try:
        results = bing_search(item.get("image_query") or item.get("name") or "", limit=10)
    except ImageError:
        return None, ""
    for result in [r for r in results if mentions(r, item.get("name") or "")][:4]:
        for url in (result["thumb"], result["full"]):
            try:
                return download(url), "bing"
            except ImageError:
                continue
    return None, ""


def fill_pictures(items: list[dict], progress: Callable[[int, int], None] | None = None) -> None:
    """Sets `image` (and `image_source`) on each item in place. Items without a picture keep `image` = None."""
    by_fandom: dict[str, list[str]] = {}
    by_lang: dict[str, list[str]] = {}
    for item in items:
        if item.get("fandom_wiki") and item.get("fandom_title"):
            by_fandom.setdefault(item["fandom_wiki"], []).append(item["fandom_title"])
        if item.get("wikipedia_title"):
            by_lang.setdefault(item.get("wikipedia_lang") or "en", []).append(item["wikipedia_title"])
    fandom = {(w, t): u for w, titles in by_fandom.items() for t, u in fandom_images(titles, w).items()}
    wiki = {(lang, t): u for lang, titles in by_lang.items() for t, u in wikipedia_images(titles, lang).items()}

    def one(item):
        urls = []
        f = fandom.get((item.get("fandom_wiki") or "", item.get("fandom_title") or ""))
        if f:
            urls.append((f, "fandom"))
        w = wiki.get((item.get("wikipedia_lang") or "en", item.get("wikipedia_title") or ""))
        if w:
            urls.append((w, "wikipedia"))
        return picture_for(item, urls)

    done = 0
    # 4 at a time: upload.wikimedia.org answers 429 to bigger bursts.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for item, (name, source) in zip(items, pool.map(one, items)):
            item["image"] = name
            item["image_source"] = source
            done += 1
            if progress:
                progress(done, len(items))

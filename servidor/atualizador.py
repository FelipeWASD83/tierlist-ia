"""Updating through the GitHub repository's releases (model: clave/servidor/atualizador.py).

1. `check` asks GitHub for the newest release.
2. `download_and_prepare` downloads the .zip, checks the SHA-256 GitHub publishes and unpacks it in
   dados/atualizacao/novo.
3. The server exits with code 3; `iniciar.py` calls `apply_pending`, which keeps the current files in
   dados/atualizacao/anterior (to go back if the new version does not open), swaps them and starts again.
dados/ (the person's lists, pictures and keys) is never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import config

MANAGED = ["servidor", "app", "iniciar.py", "versao.json", "abrir-no-navegador.bat", "README.md", "CHANGELOG.md",
           "CLAUDE.md"]
FOLDER = config.DATA / "atualizacao"
_CACHE = FOLDER / "checagem.json"
_READY = FOLDER / "pronta.json"


class UpdateError(Exception):
    pass


def _version_tuple(v: str) -> tuple:
    parts = []
    for p in (v or "0").lstrip("vV").split("."):
        parts.append(int("".join(ch for ch in p if ch.isdigit()) or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def newer(a: str, b: str) -> bool:
    return _version_tuple(a) > _version_tuple(b)


def dev_copy() -> bool:
    return (config.ROOT / ".git").exists()


def _headers(token: str, accept: str) -> dict:
    headers = {"Accept": accept, "User-Agent": f"TierlistIA/{config.VERSION}", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def check(token: str = "", force: bool = False) -> dict:
    repo = config.version_info().get("repositorio", "")
    current = config.VERSION
    base = {"atual": current, "repositorio": repo, "dev": dev_copy()}
    if not repo:
        return {**base, "erro": "Sem repositório configurado no versao.json."}
    if not force:
        try:
            cache = json.loads(_CACHE.read_text(encoding="utf-8"))
            if time.time() - cache.get("checado_em", 0) < 6 * 3600 and cache.get("atual") == current:
                return cache
        except (OSError, ValueError):
            pass
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                     headers=_headers(token, "application/vnd.github+json"))
        with urllib.request.urlopen(req, timeout=20) as r:
            rel = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            hint = "" if token else " Se o repositório for privado, cole um token de leitura no campo do GitHub."
            return {**base, "erro": "O repositório ainda não tem nenhuma versão publicada." + hint}
        return {**base, "erro": f"O GitHub respondeu {e.code}."}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {**base, "erro": f"Sem conexão com o GitHub ({e})."}
    version = (rel.get("tag_name") or "").lstrip("vV")
    package = None
    for asset in rel.get("assets") or []:
        if asset.get("name", "").endswith(".zip"):
            package = {"url": asset.get("url") if token else asset.get("browser_download_url"),
                       "digest": asset.get("digest")}
            break
    info = {**base, "ultima": version, "nova": newer(version, current), "notas": rel.get("body") or "",
            "pagina": rel.get("html_url"), "pacote": package, "checado_em": time.time()}
    FOLDER.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


def _package_root(folder: Path) -> Path:
    if (folder / "versao.json").is_file():
        return folder
    for d in folder.iterdir():
        if d.is_dir() and (d / "versao.json").is_file():
            return d
    raise UpdateError("O pacote baixado não parece ser do Tierlist IA (falta versao.json).")


def download_and_prepare(token: str = "") -> dict:
    if dev_copy():
        raise UpdateError("Esta é a cópia de desenvolvimento (tem .git): atualize pelo git.")
    info = check(token, force=True)
    if info.get("erro"):
        raise UpdateError(info["erro"])
    if not info.get("nova"):
        raise UpdateError("Você já está na versão mais nova.")
    if not info.get("pacote") or not info["pacote"].get("url"):
        raise UpdateError("A versão nova não tem o pacote .zip anexado.")
    FOLDER.mkdir(parents=True, exist_ok=True)
    zip_path = FOLDER / "pacote.zip"
    new = FOLDER / "novo"
    shutil.rmtree(new, ignore_errors=True)
    req = urllib.request.Request(info["pacote"]["url"], headers=_headers(token, "application/octet-stream"))
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(zip_path, "wb") as f:
            shutil.copyfileobj(r, f)
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"Não consegui baixar a versão nova ({e}).") from e
    digest = info["pacote"].get("digest") or ""
    if digest.startswith("sha256:"):
        if hashlib.sha256(zip_path.read_bytes()).hexdigest() != digest.split(":", 1)[1]:
            zip_path.unlink(missing_ok=True)
            raise UpdateError("O pacote baixado não confere com o SHA-256 do GitHub. Tente de novo.")
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if not (new / name).resolve().is_relative_to(new.resolve()):
                raise UpdateError("Pacote com caminho inválido.")
        z.extractall(new)
    root = _package_root(new)
    package_version = json.loads((root / "versao.json").read_text(encoding="utf-8")).get("versao", "")
    if not (root / "servidor" / "servidor.py").is_file() or not (root / "app" / "index.html").is_file():
        raise UpdateError("Pacote incompleto.")
    if package_version and _version_tuple(package_version) != _version_tuple(info["ultima"]):
        raise UpdateError(f"O pacote diz {package_version}, mas a versão publicada é {info['ultima']}.")
    _READY.write_text(json.dumps({"versao": info["ultima"], "pasta": str(root)}, ensure_ascii=False), encoding="utf-8")
    zip_path.unlink(missing_ok=True)
    return {"versao": info["ultima"]}


def pending() -> dict | None:
    try:
        return json.loads(_READY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _copy(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=False)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def apply_pending(app_root: Path | None = None) -> dict | None:
    """Swaps the files for the downloaded version. None when nothing was waiting."""
    p = pending()
    if not p:
        return None
    app_root = app_root or config.ROOT
    try:
        os.chdir(app_root)
    except OSError:
        pass
    new = Path(p["pasta"])
    previous = FOLDER / "anterior"
    shutil.rmtree(previous, ignore_errors=True)
    previous.mkdir(parents=True)
    try:
        for name in MANAGED:
            if (app_root / name).exists():
                shutil.move(str(app_root / name), str(previous / name))
        for name in MANAGED:
            if (new / name).exists():
                _copy(new / name, app_root / name)
    except Exception as e:
        revert(app_root)
        _READY.unlink(missing_ok=True)
        raise UpdateError(f"Não deu para trocar os arquivos ({e}); a versão anterior voltou.") from e
    _READY.unlink(missing_ok=True)
    shutil.rmtree(FOLDER / "novo", ignore_errors=True)
    return {"versao": p["versao"]}


def revert(app_root: Path | None = None) -> bool:
    app_root = app_root or config.ROOT
    previous = FOLDER / "anterior"
    if not previous.is_dir() or not any(previous.iterdir()):
        return False
    for name in MANAGED:
        if (previous / name).exists():
            target = app_root / name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
            shutil.move(str(previous / name), str(target))
    return True

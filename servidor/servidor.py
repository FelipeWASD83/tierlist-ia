"""Tierlist IA local server: the screen (app/), the pictures (dados/imagens) and the JSON API.

Only 127.0.0.1. Every /api request needs the `X-Tierlist: 1` header (a page from another site cannot send it
without a CORS preflight, which this server never approves), the Host must be this server, and a request that
changes something with an Origin from somewhere else is refused.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import traceback
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import armazem  # noqa: E402
import atualizador  # noqa: E402
import config  # noqa: E402
import ia  # noqa: E402
import imagens  # noqa: E402
from provedor import Disjuntor  # noqa: E402
from segredos import Segredos  # noqa: E402

RESTART = 3
MAX_BODY = 9 * 1024 * 1024
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                ".ico": "image/x-icon", ".woff2": "font/woff2", ".json": "application/json"}


class State:
    def __init__(self, url_claude: str, url_openai: str):
        self.secrets = Segredos(config.DATA)
        self.breaker = Disjuntor()
        self.url_claude = url_claude
        self.url_openai = url_openai
        self.tasks: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None
        self.exit_code = 0

    def client(self, model: str | None = None) -> ia.AIClient:
        cfg = config.load()
        return ia.AIClient(model or cfg["modelo"], cfg["esforco"], cfg["reserva"],
                           claude_key=self.secrets.obter("claude"), openai_key=self.secrets.obter("openai"),
                           url_claude=self.url_claude, url_openai=self.url_openai, breaker=self.breaker)


STATE: State | None = None


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ── Generation in the background ─────────────────────────────────────────────


def start_generation(body: dict) -> str:
    request = str(body.get("pedido") or "").strip()
    if len(request) < 3:
        raise ApiError("Escreve sobre o que é a tierlist.")
    if len(request) > 4000:
        raise ApiError("O pedido passou de 4.000 caracteres.")
    count = config.clamp_items(body.get("itens"))
    web = bool(body.get("busca_web", True))
    model = str(body.get("modelo") or "").strip() or None
    client = STATE.client(model)
    if not client.order():
        raise ApiError("Falta a chave da IA. Abra Configurações e cole a chave da Anthropic.")
    task_id = armazem.new_id()
    task = {"id": task_id, "estado": "rodando", "fase": "Começando", "feito": 0, "total": 0,
            "tierlist": None, "erro": None, "inicio": time.time()}
    with STATE.lock:
        STATE.tasks[task_id] = task

    def phase(text, done=0, total=0):
        task.update({"fase": text, "feito": done, "total": total})

    def run():
        try:
            result = client.build_tierlist(request, count, web, progress=phase)
            phase("Buscando as imagens", 0, len(result["items"]))
            imagens.fill_pictures(result["items"], lambda d, t: phase("Buscando as imagens", d, t))
            doc = armazem.save(armazem.from_ai(result, request))
            task.update({"estado": "pronto", "tierlist": doc["id"], "modelo": result["model"],
                         "trocou": result["replaced"], "custo": result["cost"], "buscas": result["searches"],
                         "pendentes": sum(1 for i in result["items"] if i.get("pending"))})
        except ia.AIError as e:
            task.update({"estado": "erro", "erro": str(e)})
        except Exception as e:  # anything else still has to reach the screen, not hang the spinner
            traceback.print_exc()
            task.update({"estado": "erro", "erro": f"Erro inesperado: {e}"})

    threading.Thread(target=run, daemon=True, name=f"gerar-{task_id}").start()
    return task_id


# ── HTTP ─────────────────────────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    server_version = "TierlistIA"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("TIERLIST_IA_LOG"):
            super().log_message(fmt, *args)

    # helpers
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if status >= 400:
            # A refused request may still have its body waiting. Read it first (closing a Windows socket with
            # unread data resets the connection before the client sees the answer), then close, so a body that
            # was too big to read is never parsed as the next request.
            if not getattr(self, "_body_read", True):
                length = int(self.headers.get("Content-Length") or 0)
                if 0 < length <= MAX_BODY:
                    self.rfile.read(length)
                self._body_read = True
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
                   {"Cache-Control": "no-store"})

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin.lower() == f"http://{(self.headers.get('Host') or '').lower()}"

    def _body_bytes(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError("Arquivo grande demais (máximo 8 MB).", 413)
        self._body_read = True
        return self.rfile.read(length) if length else b""

    def _body(self) -> dict:
        raw = self._body_bytes()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ApiError("JSON inválido.") from e
        return data if isinstance(data, dict) else {}

    # dispatch
    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, method: str):
        self._body_read = False
        if not self._host_ok():
            return self._send(421, b"host recusado", "text/plain")
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        try:
            if path.startswith("/api/"):
                if self.headers.get("X-Tierlist") != "1" or not self._origin_ok():
                    return self._json({"erro": "Pedido recusado."}, 403)
                return self._api(method, path, urllib.parse.parse_qs(url.query))
            if method != "GET":
                return self._send(405, b"", "text/plain")
            if path.startswith("/imagens/"):
                return self._image(path[len("/imagens/"):])
            return self._static(path)
        except ApiError as e:
            return self._json({"erro": str(e)}, e.status)
        except (armazem.StoreError, imagens.ImageError, atualizador.UpdateError) as e:
            return self._json({"erro": str(e)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as e:
            traceback.print_exc()
            return self._json({"erro": f"Erro no servidor: {e}"}, 500)

    def _static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"
        target = (config.APP_DIR / path.lstrip("/")).resolve()
        if not target.is_relative_to(config.APP_DIR.resolve()) or not target.is_file():
            return self._send(404, b"nao achei", "text/plain")
        ctype = STATIC_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    def _image(self, name: str):
        path = imagens.path_of(name)
        if not path:
            return self._send(404, b"", "text/plain")
        ctype = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp",
                 "avif": "image/avif", "bmp": "image/bmp"}[path.suffix[1:]]
        self._send(200, path.read_bytes(), ctype, {"Cache-Control": "public, max-age=31536000, immutable"})

    def _api(self, method: str, path: str, query: dict):
        parts = [p for p in path.split("/") if p][1:]   # without "api"
        route = (method, parts[0] if parts else "")

        if route == ("GET", "estado"):
            return self._json(state_payload())

        if route == ("POST", "config"):
            return self._json({"config": config.save(self._body())})

        if route == ("POST", "chave"):
            body = self._body()
            name = body.get("nome")
            if name not in ("claude", "openai", "github"):
                raise ApiError("Chave desconhecida.")
            STATE.secrets.guardar(name, str(body.get("valor") or ""))
            return self._json(state_payload())

        if route == ("POST", "gerar"):
            return self._json({"tarefa": start_generation(self._body())})

        if route == ("GET", "tarefas") and len(parts) == 2:
            task = STATE.tasks.get(parts[1])
            if not task:
                raise ApiError("Tarefa inexistente.", 404)
            return self._json(task)

        if parts[:1] == ["tierlists"]:
            if method == "GET" and len(parts) == 1:
                return self._json({"tierlists": armazem.summaries()})
            if method == "POST" and len(parts) == 1:
                body = self._body()
                doc = armazem.clean({"title": body.get("title") or "Tierlist nova",
                                     "tiers": [{"label": label, "color": i}
                                               for i, label in enumerate(ia.DEFAULT_TIERS)],
                                     "pool": [], "items": {}}, armazem.new_id())
                return self._json(armazem.save(doc))
            if len(parts) == 2:
                list_id = parts[1]
                if method == "GET":
                    return self._json(armazem.load(list_id))
                if method == "PUT":
                    armazem.load(list_id)    # only lists that exist
                    return self._json(armazem.save(armazem.clean(self._body(), list_id)))
                if method == "DELETE":
                    armazem.delete(list_id)
                    return self._json({"ok": True})

        if parts[:1] == ["imagens"]:
            action = parts[1] if len(parts) > 1 else ""
            if method == "GET" and action == "buscar":
                q = (query.get("q") or [""])[0].strip()
                if not q:
                    raise ApiError("Escreve o que buscar.")
                wiki = (query.get("wiki") or [""])[0].strip().lower()
                lang = (query.get("lang") or ["en"])[0].strip().lower()
                return self._json({"resultados": imagens.search_candidates(q[:200], wiki, lang)})
            if method == "POST" and action == "baixar":
                body = self._body()
                return self._json({"image": imagens.download(str(body.get("url") or ""))})
            if method == "POST" and action == "enviar":
                return self._json({"image": imagens.store(self._body_bytes())})
            if method == "POST" and action == "item":
                body = self._body()
                name = str(body.get("nome") or "").strip()[:80]
                if not name:
                    raise ApiError("Dá um nome para o item.")
                item = {"name": name, "image_query": str(body.get("busca") or name)[:200]}
                image, _source = imagens.picture_for(item, None)
                return self._json({"image": image})

        if parts[:1] == ["atualizacao"]:
            token = STATE.secrets.obter("github")
            action = parts[1] if len(parts) > 1 else ""
            if method == "GET" and not action:
                return self._json(atualizador.check(token, force=bool(query.get("forcar"))))
            if method == "POST" and action == "baixar":
                return self._json(atualizador.download_and_prepare(token))
            if method == "POST" and action == "reiniciar":
                if not atualizador.pending():
                    raise ApiError("Não tem atualização baixada.")
                STATE.exit_code = RESTART
                threading.Thread(target=STATE.server.shutdown, daemon=True).start()
                return self._json({"ok": True})

        raise ApiError("Rota inexistente.", 404)


def state_payload() -> dict:
    s = STATE.secrets
    return {
        "versao": config.VERSION,
        "config": config.load(),
        "modelos": [{"id": m, "nome": n} for m, n in config.MODELS],
        "limites": {"min": config.MIN_ITEMS, "max": config.MAX_ITEMS},
        "chaves": {name: s.fim(name) for name in ("claude", "openai", "github")},
        "dev": atualizador.dev_copy(),
    }


def main(argv=None) -> int:
    global STATE
    parser = argparse.ArgumentParser(description="Servidor do Tierlist IA")
    parser.add_argument("--porta", type=int, default=config.PORT)
    parser.add_argument("--url-claude", default=ia.URL_CLAUDE, help="só para teste")
    parser.add_argument("--url-openai", default=ia.URL_OPENAI, help="só para teste")
    args = parser.parse_args(argv)
    STATE = State(args.url_claude, args.url_openai)
    config.DATA.mkdir(parents=True, exist_ok=True)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.porta), Handler)
    except OSError as e:
        print(f"Não consegui abrir a porta {args.porta}: {e}", file=sys.stderr)
        return 1
    server.daemon_threads = True
    STATE.server = server
    print(f"Tierlist IA {config.VERSION} em http://127.0.0.1:{args.porta}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return STATE.exit_code


if __name__ == "__main__":
    sys.exit(main())

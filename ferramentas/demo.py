"""Demo without spending credit: the real server with data in %TEMP%\\tierlist-ia-demo and a fake Claude that
always answers the same tier list (One Piece characters). The pictures are searched for real.

    python ferramentas\\demo.py [--porta 4363]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(tempfile.gettempdir()) / "tierlist-ia-demo"
os.environ["TIERLIST_IA_DADOS"] = str(DATA)
sys.path.insert(0, str(ROOT / "servidor"))

# (name, Wikipedia title, Fandom title, tier): close to what the real model answers for this request.
CHARACTERS = [
    ("Monkey D. Luffy", "Monkey D. Luffy", "Monkey D. Luffy", 0), ("Roronoa Zoro", "Roronoa Zoro", "Roronoa Zoro", 0),
    ("Sanji", "Sanji (One Piece)", "Sanji", 1), ("Nami", "Nami (One Piece)", "Nami", 2),
    ("Usopp", "Usopp", "Usopp", 3), ("Tony Tony Chopper", "Tony Tony Chopper", "Tony Tony Chopper", 3),
    ("Nico Robin", "Nico Robin", "Nico Robin", 1), ("Franky", "Franky (One Piece)", "Franky", 2),
    ("Brook", "Brook (One Piece)", "Brook", 2), ("Jinbe", "", "Jinbe", 1), ("Shanks", "Shanks", "Shanks", 0),
    ("Trafalgar Law", "Trafalgar Law", "Trafalgar D. Water Law", 1), ("Boa Hancock", "Boa Hancock", "Boa Hancock", 2),
    ("Portgas D. Ace", "Portgas D. Ace", "Portgas D. Ace", 1), ("Buggy", "Buggy (One Piece)", "Buggy", 5),
    ("Kaido", "", "Kaidou", 0), ("Marshall D. Teach", "", "Marshall D. Teach", 0),
    ("Charlotte Linlin", "", "Charlotte Linlin", 0), ("Dracule Mihawk", "", "Dracule Mihawk", 0),
    ("Crocodile", "", "Crocodile", 2),
]


def tierlist(count: int) -> dict:
    items = [{"name": n, "wikipedia_title": w, "wikipedia_lang": "en", "fandom_wiki": "onepiece", "fandom_title": f,
              "image_query": f"{n} One Piece anime", "tier": t} for n, w, f, t in CHARACTERS[:count]]
    return {"title": "Personagens de One Piece", "tiers": [{"label": x} for x in "SABCDF"], "items": items}


class FakeClaude(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        system = body.get("system", [{}])[0].get("text", "")
        count = int(system.split("Exactly ", 1)[1].split(" ", 1)[0]) if "Exactly " in system else 12
        time.sleep(2)   # long enough to see the progress bar
        raw = json.dumps({"content": [{"type": "tool_use", "id": "toolu_demo", "name": "deliver_tierlist",
                                       "input": tierlist(count)}],
                          "stop_reason": "tool_use", "usage": {"input_tokens": 3000, "output_tokens": 900,
                                                               "server_tool_use": {"web_search_requests": 1}}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--porta", default="4363")
    args = parser.parse_args()
    fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeClaude)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    from segredos import Segredos
    DATA.mkdir(parents=True, exist_ok=True)
    Segredos(DATA).guardar("claude", "sk-ant-demo-chave-falsa-0000")
    import servidor
    print(f"Demonstração: dados em {DATA}, IA falsa (não gasta crédito).", flush=True)
    return servidor.main(["--porta", args.porta, "--url-claude", f"http://127.0.0.1:{fake.server_address[1]}/v1/messages"])


if __name__ == "__main__":
    sys.exit(main())

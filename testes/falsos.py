"""A fake AI API (Claude and OpenAI) on a local port. Each test queues the answers it wants."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TIERLIST = {
    "title": "Doces brasileiros",
    "tiers": [{"label": "S"}, {"label": "A"}, {"label": "B"}],
    "items": [
        {"name": "Brigadeiro", "wikipedia_title": "Brigadeiro", "wikipedia_lang": "en",
         "image_query": "brigadeiro doce", "tier": 0},
        {"name": "Beijinho", "wikipedia_title": "", "wikipedia_lang": "en", "image_query": "beijinho doce", "tier": 1},
        {"name": "Pé de moleque", "wikipedia_title": "Pé-de-moleque", "wikipedia_lang": "pt",
         "image_query": "pé de moleque doce", "tier": 7},
    ],
}


def claude_tool_answer(data=None):
    return 200, {"content": [{"type": "thinking", "thinking": "", "signature": "x"},
                             {"type": "tool_use", "id": "toolu_1", "name": "deliver_tierlist", "input": data or TIERLIST}],
                 "stop_reason": "tool_use",
                 "usage": {"input_tokens": 1000, "output_tokens": 500, "server_tool_use": {"web_search_requests": 2}}}


def claude_text_answer():
    return 200, {"content": [{"type": "text", "text": "Aqui está a lista..."}], "stop_reason": "end_turn",
                 "usage": {"input_tokens": 10, "output_tokens": 10}}


CREDIT = (400, {"type": "error", "error": {"type": "invalid_request_error", "message":
                "Your credit balance is too low to access the Anthropic API."}})


def openai_tool_answer(data=None):
    return 200, {"status": "completed", "output": [
        {"type": "web_search_call", "id": "ws_1"},
        {"type": "function_call", "name": "deliver_tierlist", "arguments": json.dumps(data or TIERLIST)}],
        "usage": {"input_tokens": 100, "output_tokens": 50}}


class FakeAPI:
    def __init__(self):
        self.answers: list[tuple[int, dict]] = []
        self.requests: list[dict] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                fake.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                status, data = fake.answers.pop(0) if fake.answers else (500, {"error": {"message": "sem resposta"}})
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def claude_url(self):
        return f"http://127.0.0.1:{self.port}/v1/messages"

    @property
    def openai_url(self):
        return f"http://127.0.0.1:{self.port}/v1/responses"

    def close(self):
        self.server.shutdown()
        self.server.server_close()

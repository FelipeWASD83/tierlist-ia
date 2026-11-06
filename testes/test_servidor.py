"""The real server in this process, with temporary data, the fake AI and no picture downloads."""

import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import config
import imagens
import servidor
from testes import falsos


def no_pictures(items, progress=None):
    for i, item in enumerate(items):
        item["image"] = None
        item["image_source"] = ""
        item["pending"] = []
        if progress:
            progress(i + 1, len(items))


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.patches = [mock.patch.object(config, "DATA", base), mock.patch.object(config, "IMAGES", base / "imagens"),
                       mock.patch.object(config, "LISTS", base / "tierlists"),
                       mock.patch.object(imagens, "fill_pictures", no_pictures)]
        for p in cls.patches:
            p.start()
        cls.api = falsos.FakeAPI()
        cls.thread = threading.Thread(target=servidor.main, args=(
            ["--porta", "0", "--url-claude", cls.api.claude_url, "--url-openai", cls.api.openai_url],), daemon=True)
        cls.thread.start()
        for _ in range(100):
            if servidor.STATE and servidor.STATE.server:
                break
            time.sleep(0.05)
        cls.port = servidor.STATE.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        servidor.STATE.server.shutdown()
        cls.thread.join(5)
        cls.api.close()
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"X-Tierlist": "1", "Host": host or f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        if data is not None:
            h["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def test_guards(self):
        self.assertEqual(self.call("GET", "/api/estado", headers={"X-Tierlist": "0"})[0], 403)
        self.assertEqual(self.call("GET", "/api/estado", host="evil.com")[0], 421)
        self.assertEqual(self.call("POST", "/api/config", {"itens": 9}, headers={"Origin": "https://evil.com"})[0], 403)
        self.assertEqual(self.call("GET", "/../servidor/config.py")[0], 404)
        self.assertEqual(self.call("GET", "/imagens/..%5Csegredos.json")[0], 404)

    def test_static_index(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body)

    def test_key_is_never_returned(self):
        status, data = self.call("POST", "/api/chave", {"nome": "claude", "valor": "sk-ant-api03-segredo-1234"})
        self.assertEqual(status, 200)
        self.assertEqual(data["chaves"]["claude"], "…1234")
        self.assertNotIn("segredo", json.dumps(data))
        self.assertNotIn(b"segredo", (Path(self.tmp.name) / "segredos.json").read_bytes())

    def test_generate_edit_and_delete(self):
        self.call("POST", "/api/chave", {"nome": "claude", "valor": "sk-ant-teste-0000"})
        self.api.answers.append(falsos.claude_tool_answer())
        status, data = self.call("POST", "/api/gerar", {"pedido": "doces brasileiros", "itens": 3})
        self.assertEqual(status, 200, data)
        for _ in range(100):
            _, task = self.call("GET", f"/api/tarefas/{data['tarefa']}")
            if task["estado"] != "rodando":
                break
            time.sleep(0.05)
        self.assertEqual(task["estado"], "pronto", task)
        self.assertEqual(task["pendentes"], 0)
        _, doc = self.call("GET", f"/api/tierlists/{task['tierlist']}")
        self.assertEqual(doc["title"], "Doces brasileiros")
        self.assertEqual(doc["request"], "doces brasileiros")
        doc["title"] = "Editada"
        doc["tiers"].reverse()
        status, saved = self.call("PUT", f"/api/tierlists/{doc['id']}", doc)
        self.assertEqual(status, 200)
        self.assertEqual(saved["title"], "Editada")
        self.assertEqual(saved["request"], "doces brasileiros")
        _, listing = self.call("GET", "/api/tierlists")
        self.assertIn(doc["id"], [t["id"] for t in listing["tierlists"]])
        self.assertEqual(self.call("DELETE", f"/api/tierlists/{doc['id']}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/tierlists/{doc['id']}")[0], 400)

    def test_generation_error_reaches_screen(self):
        self.call("POST", "/api/chave", {"nome": "claude", "valor": "sk-ant-teste-0000"})
        self.api.answers.append((401, {"error": {"message": "invalid x-api-key"}}))
        _, data = self.call("POST", "/api/gerar", {"pedido": "qualquer coisa", "itens": 5})
        for _ in range(100):
            _, task = self.call("GET", f"/api/tarefas/{data['tarefa']}")
            if task["estado"] != "rodando":
                break
            time.sleep(0.05)
        self.assertEqual(task["estado"], "erro")
        self.assertIn("recusou a chave", task["erro"])

    def test_empty_list_and_upload(self):
        status, doc = self.call("POST", "/api/tierlists", {"title": "Minha"})
        self.assertEqual(status, 200)
        self.assertEqual([t["label"] for t in doc["tiers"]], ["S", "A", "B", "C", "D", "F"])
        png = b"\x89PNG\r\n\x1a\n" + b"1" * 30
        status, data = self.call("POST", "/api/imagens/enviar", png, headers={"Content-Type": "image/png"})
        self.assertEqual(status, 200, data)
        status, raw = self.call("GET", f"/imagens/{data['image']}")
        self.assertEqual(raw, png)
        self.assertEqual(self.call("POST", "/api/imagens/enviar", b"<svg/>")[0], 400)

    def test_settings_clamp(self):
        _, data = self.call("POST", "/api/config", {"itens": 999, "esforco": "absurdo", "outra": 1})
        self.assertEqual(data["config"]["itens"], config.MAX_ITEMS)
        self.assertEqual(data["config"]["esforco"], "medium")
        self.assertNotIn("outra", data["config"])


if __name__ == "__main__":
    unittest.main()

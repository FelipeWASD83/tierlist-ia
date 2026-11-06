import unittest

import ia
from testes import falsos


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.api = falsos.FakeAPI()

    def tearDown(self):
        self.api.close()

    def client(self, model="claude-sonnet-5-5", **keys):
        keys = keys or {"claude_key": "sk-ant-teste"}
        return ia.AIClient(model, "medium", "auto", url_claude=self.api.claude_url,
                           url_openai=self.api.openai_url, timeout=10, **keys)

    def test_claude_request_shape_and_result(self):
        self.api.answers.append(falsos.claude_tool_answer())
        result = self.client().build_tierlist("doces brasileiros", 20)
        body = self.api.requests[0]["body"]
        headers = {k.lower(): v for k, v in self.api.requests[0]["headers"].items()}
        self.assertEqual(headers["x-api-key"], "sk-ant-teste")
        self.assertEqual(body["model"], "claude-sonnet-5-5")
        self.assertEqual(body["tool_choice"], {"type": "auto"})   # forced tool use is a 400 on Sonnet 5.5
        tools = {t["name"]: t for t in body["tools"]}
        self.assertTrue(tools["deliver_tierlist"]["strict"])
        self.assertEqual(tools["web_search"]["type"], "web_search_20260209")
        self.assertNotIn("temperature", body)
        self.assertIn("Exactly 20 items", body["system"][0]["text"])
        self.assertEqual(result["title"], "Doces brasileiros")
        # the AI never ranks: even if a model sends tiers, every item starts unranked
        self.assertEqual([i["tier"] for i in result["items"]], [-1, -1, -1])
        self.assertNotIn("tier", tools["deliver_tierlist"]["input_schema"]["properties"]["items"]["items"]["properties"])
        self.assertIn("you never rank", body["system"][0]["text"])
        self.assertEqual(result["searches"], 2)
        self.assertAlmostEqual(result["cost"], (1000 * 2 + 500 * 10) / 1e6 + 0.02)

    def test_haiku_uses_basic_web_search_and_no_web_when_off(self):
        self.api.answers += [falsos.claude_tool_answer(), falsos.claude_tool_answer()]
        self.client("claude-haiku-5-5").build_tierlist("x" * 5, 10)
        tools = {t["name"]: t for t in self.api.requests[0]["body"]["tools"]}
        self.assertEqual(tools["web_search"]["type"], "web_search_20250305")
        self.client().build_tierlist("x" * 5, 10, web=False)
        self.assertEqual([t["name"] for t in self.api.requests[1]["body"]["tools"]], ["deliver_tierlist"])

    def test_text_answer_gets_one_nudge(self):
        self.api.answers += [falsos.claude_text_answer(), falsos.claude_tool_answer()]
        result = self.client().build_tierlist("doces", 5)
        self.assertEqual(len(result["items"]), 3)
        second = self.api.requests[1]["body"]["messages"]
        self.assertEqual(second[1]["role"], "assistant")
        self.assertIn("deliver_tierlist", second[2]["content"][0]["text"])

    def test_pause_turn_continues_with_same_content(self):
        paused = (200, {"content": [{"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {}}],
                        "stop_reason": "pause_turn", "usage": {"input_tokens": 1, "output_tokens": 1}})
        self.api.answers += [paused, falsos.claude_tool_answer()]
        self.client().build_tierlist("doces", 5)
        messages = self.api.requests[1]["body"]["messages"]
        self.assertEqual(messages[-1]["role"], "assistant")
        self.assertEqual(messages[-1]["content"][0]["type"], "server_tool_use")

    def test_no_credit_moves_to_openai(self):
        self.api.answers += [falsos.CREDIT, falsos.openai_tool_answer()]
        client = self.client(claude_key="a", openai_key="b")
        result = client.build_tierlist("doces", 5)
        self.assertEqual(result["model"], "gpt-6.1-sol")
        self.assertTrue(result["replaced"])
        self.assertEqual(result["searches"], 1)
        self.assertTrue(client.breaker.aberto("claude"))

    def test_no_credit_without_other_key(self):
        self.api.answers.append(falsos.CREDIT)
        with self.assertRaises(ia.NoCreditError):
            self.client().build_tierlist("doces", 5)

    def test_missing_key(self):
        with self.assertRaises(ia.AIError):
            ia.AIClient("claude-sonnet-5-5").build_tierlist("doces", 5)

    def test_bad_key_message(self):
        self.api.answers.append((401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}}))
        with self.assertRaisesRegex(ia.AIError, "recusou a chave"):
            self.client().build_tierlist("doces", 5)


class TestNormalize(unittest.TestCase):
    def test_cut_dedupe_and_always_unranked(self):
        data = {"title": "", "tiers": [], "items": [
            {"name": "A", "tier": 0}, {"name": "a", "tier": 1}, {"name": "B", "tier": "x"}, {"name": "C", "tier": 2}]}
        out = ia.normalize(data, 2)
        self.assertEqual(out["tiers"], ia.DEFAULT_TIERS)
        self.assertEqual([i["name"] for i in out["items"]], ["A", "B"])
        self.assertTrue(all(i["tier"] == -1 for i in out["items"]))
        self.assertEqual(out["title"], "Tierlist")

    def test_fandom_address_becomes_subdomain(self):
        data = {"items": [{"name": "A", "fandom_wiki": "https://OnePiece.fandom.com/wiki/Kaidou", "tier": 0},
                          {"name": "B", "fandom_wiki": "naruto", "tier": 0}]}
        out = ia.normalize(data, 5)
        self.assertEqual([i["fandom_wiki"] for i in out["items"]], ["onepiece", "naruto"])

    def test_empty_is_an_error(self):
        with self.assertRaises(ia.AIError):
            ia.normalize({"items": []}, 5)


if __name__ == "__main__":
    unittest.main()

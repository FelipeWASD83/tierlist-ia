import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import armazem
import config
import imagens

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


class TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.patches = [mock.patch.object(config, "DATA", base), mock.patch.object(config, "IMAGES", base / "imagens"),
                        mock.patch.object(config, "LISTS", base / "tierlists")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class TestImages(TempData):
    def test_types(self):
        self.assertEqual(imagens.image_type(PNG), "png")
        self.assertEqual(imagens.image_type(b"\xff\xd8\xff\xe0abc"), "jpg")
        self.assertEqual(imagens.image_type(b"RIFF0000WEBPVP8 "), "webp")
        self.assertIsNone(imagens.image_type(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"))
        self.assertIsNone(imagens.image_type(b"<html>"))

    def test_store_is_by_hash_and_refuses_non_images(self):
        a = imagens.store(PNG)
        self.assertEqual(a, imagens.store(PNG))
        self.assertTrue(imagens.path_of(a))
        with self.assertRaises(imagens.ImageError):
            imagens.store(b"<svg/>")

    def test_path_of_refuses_anything_else(self):
        for name in ("../config.json", "x.png", "a" * 40 + ".svg", "", "..\\segredos.json"):
            self.assertIsNone(imagens.path_of(name))

    def test_check_url_refuses_local_and_odd(self):
        for url in ("http://127.0.0.1:4362/api/estado", "http://localhost/", "file:///C:/x.png",
                    "http://192.168.0.10/", "https://user:pw@example.com/a.png", "ftp://example.com/a.png"):
            with self.assertRaises(imagens.ImageError, msg=url):
                imagens.check_url(url)

    def test_wikipedia_follows_normalized_and_redirects(self):
        answer = {"query": {
            "normalized": [{"from": "monkey_D._Luffy", "to": "Monkey D. Luffy"}],
            "redirects": [{"from": "Monkey D. Luffy", "to": "Luffy (One Piece)"}],
            "pages": [{"title": "Luffy (One Piece)", "thumbnail": {"source": "https://upload.wikimedia.org/l.png"}},
                      {"title": "Nada", "missing": True}]}}
        with mock.patch.object(imagens, "_get_json", return_value=answer) as get:
            found = imagens.wikipedia_images(["monkey_D._Luffy", "Nada"], "en")
        self.assertEqual(found, {"monkey_D._Luffy": "https://upload.wikimedia.org/l.png"})
        self.assertIn("pilicense=any", get.call_args[0][0])
        with mock.patch.object(imagens, "_get_json", return_value={}) as get:
            imagens.wikipedia_images(["x"], "evil.com/")
        self.assertTrue(get.call_args[0][0].startswith("https://en.wikipedia.org/"))

    def test_picture_order_fandom_wikipedia_bing(self):
        bing = [{"thumb": "https://t/0", "full": "https://f/0", "title": "Trafalgar Square at night", "page": ""},
                {"thumb": "https://t/1", "full": "https://f/1", "title": "Law wallpaper", "page": ""}]
        with mock.patch.object(imagens, "download", side_effect=[imagens.ImageError("x"), imagens.ImageError("y"),
                                                                 "abc.png"]) as dl, \
                mock.patch.object(imagens, "bing_search", return_value=bing):
            name, source = imagens.picture_for({"name": "Trafalgar Law", "image_query": "x"},
                                               [("https://fandom/x.png", "fandom"), ("https://wiki/x.png", "wikipedia")])
        self.assertEqual((name, source), ("abc.png", "bing"))
        # "Trafalgar Square" shares "trafalgar", so it is tried first; both results mention the item
        self.assertEqual([c.args[0] for c in dl.call_args_list],
                         ["https://fandom/x.png", "https://wiki/x.png", "https://t/0"])
        with mock.patch.object(imagens, "download", return_value="ok.png"):
            self.assertEqual(imagens.picture_for({"name": "x"}, [("https://fandom/x.png", "fandom")]),
                             ("ok.png", "fandom"))

    def test_bing_result_must_mention_the_item(self):
        self.assertFalse(imagens.mentions({"title": "Boa Constrictor facts", "page": "https://zoo.example/boa"},
                                          "Hancock"))
        self.assertTrue(imagens.mentions({"title": "Pão de Queijo receita", "page": ""}, "pao de queijo"))
        self.assertTrue(imagens.mentions({"title": "", "page": "https://x.com/kaido-wallpaper"}, "Kaido"))
        with mock.patch.object(imagens, "bing_search", return_value=[
                {"thumb": "https://t/0", "full": "https://f/0", "title": "Unrelated", "page": ""}]), \
                mock.patch.object(imagens, "download") as dl:
            self.assertEqual(imagens.picture_for({"name": "Kaido"}), (None, ""))
        dl.assert_not_called()

    def test_section_redirect_is_not_the_item(self):
        answer = {"query": {
            "redirects": [{"from": "Trafalgar Law", "to": "List of One Piece characters", "tofragment": "Law"}],
            "pages": [{"title": "List of One Piece characters", "thumbnail": {"source": "https://u/group.png"}}]}}
        with mock.patch.object(imagens, "_get_json", return_value=answer):
            self.assertEqual(imagens.wikipedia_images(["Trafalgar Law"]), {})

    def test_fandom_host_and_bad_wiki(self):
        with mock.patch.object(imagens, "_get_json", return_value={}) as get:
            imagens.fandom_images(["Kaidou"], "onepiece")
            self.assertTrue(get.call_args[0][0].startswith("https://onepiece.fandom.com/api.php?"))
            self.assertEqual(imagens.fandom_images(["x"], "evil.com/"), {})
            self.assertEqual(get.call_count, 1)


class TestStore(TempData):
    def test_from_ai_and_clean(self):
        image = imagens.store(PNG)
        result = {"title": "T", "tiers": ["S", "A"], "items": [
            {"name": "um", "tier": 0, "image": image}, {"name": "dois", "tier": -1, "image": None}]}
        doc = armazem.save(armazem.from_ai(result, "pedido"))
        self.assertEqual(len(doc["tiers"][0]["items"]), 1)
        self.assertEqual(len(doc["pool"]), 1)
        loaded = armazem.load(doc["id"])
        one, two = doc["tiers"][0]["items"][0], doc["pool"][0]
        # the screen sends an item twice, a bad image name and forgets one item: each item ends in one place
        loaded["tiers"][1]["items"] = [one]
        loaded["pool"] = []
        loaded["items"][one]["image"] = "../segredos.json"
        cleaned = armazem.clean(loaded, doc["id"])
        self.assertEqual(cleaned["tiers"][0]["items"], [one])
        self.assertEqual(cleaned["tiers"][1]["items"], [])
        self.assertEqual(cleaned["pool"], [two])
        self.assertIsNone(cleaned["items"][one]["image"])
        self.assertEqual(cleaned["request"], "pedido")

    def test_summaries_and_delete(self):
        doc = armazem.save(armazem.from_ai({"title": "T", "tiers": ["S"], "items": [{"name": "a", "tier": 0}]}, "p"))
        self.assertEqual(armazem.summaries()[0]["count"], 1)
        armazem.delete(doc["id"])
        self.assertEqual(armazem.summaries(), [])
        with self.assertRaises(armazem.StoreError):
            armazem.load("../../x")


if __name__ == "__main__":
    unittest.main()

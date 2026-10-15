"""Space chatter (this fork: outrider/chatter.py, resources/chatter.json, GET /api/chatter): the lines the co-pilot
says unprompted. The timing is the page's (static/fork.js; tests/page_smoke.js)."""
import asyncio
import json
import os
import tempfile
import types
import unittest

from support import ed_outrider

import outrider.chatter as chatter


class Lines(unittest.TestCase):
    def test_the_shipped_lines(self):
        with open(chatter.CHATTER_FILE, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(chatter.check(doc), [])
        rocky = chatter.lines()["rocky"]
        self.assertGreaterEqual(len(rocky), 50)                               # enough that an evening does not repeat
        with open(os.path.join(os.path.dirname(chatter.CHATTER_FILE), "speech.json"), encoding="utf-8") as f:
            styles = json.load(f)["styles"]
        self.assertLessEqual(set(doc["lines"]), set(styles))                  # only personalities the voice has
        marked = sum(("question?" in x) or any(f"{w} {w} {w}" in x.lower() for w in x.lower().rstrip(".").split()) for x in rocky)
        self.assertGreater(marked, 15)                                        # his way of talking, often

    def test_check(self):
        self.assertEqual(chatter.check({"lines": {"rocky": ["One.", "Two."]}}), [])
        self.assertTrue(chatter.check([]))
        self.assertTrue(chatter.check({"lines": []}))
        self.assertIn("rocky: a list of sentences", chatter.check({"lines": {"rocky": ["One.", 2]}}))
        self.assertIn("rocky: a line is there twice", chatter.check({"lines": {"rocky": ["One.", "One."]}}))
        for wrong in ("Hello {name}.", "It's fine.", "x" * (chatter.MAX_CHARS + 1)):
            self.assertTrue(chatter.check({"lines": {"rocky": [wrong]}}), wrong)

    def test_a_missing_or_wrong_file_is_no_chatter(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(chatter.lines(os.path.join(d, "none.json")), {})
            path = os.path.join(d, "chatter.json")
            for text in ("not json", json.dumps({"lines": {"rocky": ["It's wrong."]}})):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                os.utime(path, (1, len(text)))                                # a new file time: read again
                self.assertEqual(chatter.lines(path), {})
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"lines": {"rocky": ["Good good good."], "sweet": []}}, f)
            os.utime(path, (1, 99))
            self.assertEqual(chatter.lines(path), {"rocky": ["Good good good."]})   # an empty list is no personality


class Server(unittest.TestCase):
    def test_the_route(self):
        from aiohttp.test_utils import TestClient, TestServer
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        state = ed_outrider.State(db, ed_outrider.Journals(db), types.SimpleNamespace(cached=lambda i: (None, None)), 25)

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(state))) as c:
                r = await c.get("/api/chatter")
                return r.status, await r.json()
        status, body = asyncio.run(go())
        self.assertEqual((status, body["lines"]["rocky"]), (200, chatter.lines()["rocky"]))


if __name__ == "__main__":
    unittest.main()

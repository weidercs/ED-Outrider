"""GalNet News (outrider/galnet.py, State.galnet_news / galnet_systems, GET /api/galnet). The articles here are made
up; nothing reaches Frontier's feed or Spansh (a fake session and a fake name search)."""
import asyncio
import types
import unittest

from support import ed_outrider

import outrider.galnet as galnet


def article(ident, title, text, date="08 OCT 3312", published="2026-10-08T12:00:46+00:00", **extra):
    return {"type": "node--galnet_article", "id": f"uuid-{ident}",
            "attributes": dict({"title": title, "published_at": published, "field_galnet_date": date,
                                "field_galnet_guid": ident, "body": {"value": text, "format": "plain_text"}}, **extra)}


FEED = {"jsonapi": {"version": "1.0"}, "data": [
    article("aaa111", "Older  News", "First line.\r\n\r\n  Second   line. ", date="01 OCT 3312", published="2026-10-01T10:00:00+00:00"),
    article("bbb222", "Prison Ship Found in Talvik Reach System",
            "Pilots protected the recovery in the Talvik Reach system.\r\nThe Imperial capital Ossia system and the "
            "Corvane and Hesperine systems sent aid, as did HIP 12345. The judicial system was praised."),
    article("bbb222", "A duplicate", "x"),
    {"id": "no-attributes"},
    article("ccc333", "", "no title"),
    article("bad id!", "Bad id", "text"),
], "links": {}}


class Resp:
    def __init__(self, status, body):
        self.status, self.body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise ed_outrider.ClientError(f"HTTP {self.status}")

    async def json(self, content_type=None):
        return self.body


class Session:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        got = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(got, Exception):
            raise got
        return Resp(*got)


class Parsing(unittest.TestCase):
    def test_parse(self):
        arts = galnet.parse(FEED)
        self.assertEqual([(a["id"], a["title"], a["date"]) for a in arts],
                         [("bbb222", "Prison Ship Found in Talvik Reach System", "08 OCT 3312"), ("aaa111", "Older News", "01 OCT 3312")])
        self.assertEqual(arts[1]["text"], "First line.\nSecond line.")   # Windows line ends, blank lines and runs of spaces
        self.assertEqual(galnet.parse({"data": []}), [])
        self.assertEqual(len(galnet.parse({"data": [article(f"id{i}", "T", "x", published=f"2026-10-{i + 1:02d}T00:00:00+00:00")
                                                    for i in range(40)]})), galnet.ARTICLES)
        for bad in ({"errors": [{"title": "down"}]}, [], None, {"data": "soon"}):
            with self.assertRaises(ValueError):
                galnet.parse(bad)
        self.assertEqual(galnet.query(), {"sort": "-published_at", "page[limit]": "30"})

    def test_candidates(self):
        got = galnet.candidates(galnet.parse(FEED)[0]["title"] + "\n" + galnet.parse(FEED)[0]["text"])
        # the capitalised words right before "system": a lower-case word ends the run ("in", "capital")
        self.assertEqual(got, [["Talvik Reach", "Reach"], ["Ossia"], ["Corvane"], ["Hesperine"], ["HIP 12345"]])
        # a headline capitalises every word: the whole run is tried first, then its last three words, two, one
        self.assertEqual(galnet.candidates("Fleet Attack On Outer Sol System"),
                         [["Fleet Attack On Outer Sol", "On Outer Sol", "Outer Sol", "Sol"]])
        # the same system named twice is one mention; a sentence's first word is no part of the name
        self.assertEqual(galnet.candidates("The Sol system. In the Sol system, and the LHS 20, Wolf 359 and Sol systems."),
                         [["Sol"], ["LHS 20"], ["Wolf 359"]])
        self.assertEqual(galnet.candidates("Seen near Col 285 Sector KM-V d2-106 and Blua Eaec WW-E c14-1293 today."),
                         [["Col 285 Sector KM-V d2-106"], ["Blua Eaec WW-E c14-1293"]])
        for none in ("The judicial system failed.", "A new Federal system of taxes.", "the 12 systems nearby", "", None):
            self.assertEqual(galnet.candidates(none), [], none)


class News(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.session = Session([(200, FEED)])
        self.asked = []

        async def system_record(name):
            self.asked.append(name)
            if isinstance(self.known.get(name.lower()), Exception):
                raise self.known[name.lower()]
            return self.known.get(name.lower())
        self.known = {"ossia": {"name": "Ossia", "id64": 3001}, "corvane": {"name": "Corvane", "id64": 3002},
                      "hip 12345": {"name": "HIP 12345", "id64": 3003}}
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(
            cached=lambda i: (None, None), session=self.session, system_record=system_record), 25)

    def test_news_kept_and_refreshed(self):
        async def go():
            first = await self.state.galnet_news()
            again = await self.state.galnet_news()             # within MAX_AGE_S: the copy, nobody asked
            calls = len(self.session.calls)
            self.session.answers = [ed_outrider.ClientError("down")]
            failed = await self.state.galnet_news(refresh=True)
            self.session.answers = [(200, {"errors": []})]
            odd = await self.state.galnet_news(refresh=True)
            self.session.answers = [(503, None)]
            busy = await self.state.galnet_news(refresh=True)
            return first, again, calls, failed, odd, busy
        first, again, calls, failed, odd, busy = asyncio.run(go())
        self.assertEqual(self.session.calls[0], (galnet.URL, {"sort": "-published_at", "page[limit]": "30"}))
        self.assertEqual(([a["id"] for a in first["articles"]], first["error"], calls), (["bbb222", "aaa111"], None, 1))
        self.assertEqual(again["articles"], first["articles"])
        for out, words in ((failed, "down"), (odd, "unexpected shape"), (busy, "HTTP 503")):
            self.assertEqual(out["articles"], first["articles"])   # a failed read keeps the copy
            self.assertIn(words, out["error"])
            self.assertEqual(out["checked"], first["checked"])
        self.state.spansh = types.SimpleNamespace(session=None)
        self.assertIn("no network session", asyncio.run(self.state.galnet_news(refresh=True))["error"])

    def test_systems_confirmed_before_named(self):
        """A system you know needs no request; another is named only when Spansh knows it by exactly that name; what
        was asked is remembered."""
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Talvik Reach",
                       "SystemAddress": 2001, "StarPos": [1, 2, 3]})

        async def go():
            await self.state.galnet_news()
            first = await self.state.galnet_systems("bbb222")
            asked = list(self.asked)
            again = await self.state.galnet_systems("bbb222")
            return first, asked, again, await self.state.galnet_systems("zzz"), await self.state.galnet_systems("aaa111")
        (first, status), asked, again, missing, plain = asyncio.run(go())
        self.assertEqual(status, 200)
        self.assertEqual(first["systems"], [{"text": "Talvik Reach", "name": "Talvik Reach"}, {"text": "Ossia", "name": "Ossia"},
                                            {"text": "Corvane", "name": "Corvane"}, {"text": "HIP 12345", "name": "HIP 12345"}])
        self.assertIsNone(first["error"])
        self.assertNotIn("Talvik Reach", asked)                    # yours: not asked about
        self.assertIn("Hesperine", asked)                          # asked, unknown to Spansh: not named
        self.assertEqual((again[0]["systems"], self.asked), (first["systems"], asked))   # remembered: nobody asked again
        self.assertEqual(missing, ({"error": "no such article"}, 404))
        self.assertEqual(plain[0]["systems"], [])

    def test_systems_when_spansh_is_down(self):
        self.known["ossia"] = asyncio.TimeoutError()

        async def go():
            await self.state.galnet_news()
            failed = await self.state.galnet_systems("bbb222")
            self.known["ossia"] = {"name": "Ossia", "id64": 3001}
            return failed, await self.state.galnet_systems("bbb222")
        (failed, _), (later, _) = asyncio.run(go())
        self.assertIn("Spansh could not be asked", failed["error"])
        self.assertNotIn("Ossia", [s["name"] for s in failed["systems"]])   # not known either way: not named, not forgotten
        self.assertEqual((later["error"], "Ossia" in [s["name"] for s in later["systems"]]), (None, True))

    def test_endpoints(self):
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                news = await (await c.get("/api/galnet")).json()
                systems = await (await c.get("/api/galnet/systems?id=bbb222")).json()
                bad = [(await c.get("/api/galnet/systems" + q)).status for q in ("", "?id=", "?id=a/b", "?id=" + "a" * 65, "?id=zzz")]
                cross = (await c.get("/api/galnet", headers={"Sec-Fetch-Site": "cross-site"})).status
                return news, systems, bad, cross
        news, systems, bad, cross = asyncio.run(go())
        self.assertEqual((len(news["articles"]), news["error"]), (2, None))
        self.assertEqual([s["name"] for s in systems["systems"]], ["Ossia", "Corvane", "HIP 12345"])
        self.assertEqual((bad, cross), ([400, 400, 400, 400, 404], 403))


if __name__ == "__main__":
    unittest.main()

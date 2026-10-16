"""The Game Route list (outrider/navroute.py, State.navroute_view, GET /api/navroute): the game's own route, jump by
jump. Made-up systems."""
import asyncio
import types
import unittest

from support import ed_outrider

import outrider.navroute as navroute

HERE = {"id64": 1, "name": "Start", "x": 0.0, "y": 0.0, "z": 0.0}
HOPS = [{"id64": 10 + i, "name": n, "star_class": c, "x": 40.0 * (i + 1), "y": 0.0, "z": 0.0}
        for i, (n, c) in enumerate((("First Hop", "K"), ("Dry Stop", "N"), ("Third", "M"), ("Far End", "DA")))]


class Rows(unittest.TestCase):
    def test_rows(self):
        self.assertEqual(navroute.rows(HOPS, HERE), [{"i": 0, "ly": 40.0, "total_ly": 40.0}, {"i": 1, "ly": 40.0, "total_ly": 80.0},
                                                     {"i": 2, "ly": 40.0, "total_ly": 120.0}, {"i": 3, "ly": 40.0, "total_ly": 160.0}])
        bent = [dict(HOPS[0], x=3.0, y=4.0), dict(HOPS[1], x=3.0, y=4.0, z=12.0)]
        self.assertEqual([(r["ly"], r["total_ly"]) for r in navroute.rows(bent, HERE)], [(5.0, 5.0), (12.0, 17.0)])
        self.assertEqual(navroute.rows([], HERE), [])


class View(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def plot(self, hops=HOPS):
        self.j.pos = dict(HERE)
        ed_outrider.meta_set(self.db, "route", {"ts": "2026-10-11T10:00:00Z", "hops": [dict(HERE, star_class="G")] + hops})

    def test_no_route(self):
        self.assertIsNone(self.state.navroute_view()["route"])
        self.j.pos = dict(HERE)
        self.assertIsNone(self.state.navroute_view()["route"])
        self.plot()
        self.j.pos = dict(HOPS[-1])                       # arrived: nothing ahead
        self.assertIsNone(self.state.navroute_view()["route"])

    def test_the_list(self):
        self.plot()
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Third", "SystemAddress": 12,
                       "StarPos": [120, 0, 0]})          # an old visit
        self.j.pos = dict(HERE)
        r = self.state.navroute_view()["route"]
        self.assertEqual((r["count"], r["ly"], r["to"], r["ts"]), (4, 160.0, "Far End", "2026-10-11T10:00:00Z"))
        self.assertEqual([(h["i"], h["name"], h["star_class"], h["scoopable"], h["ly"], h["total_ly"], h["visited"], h["known"])
                          for h in r["hops"]],
                         [(0, "First Hop", "K", True, 40.0, 40.0, False, None), (1, "Dry Stop", "N", False, 40.0, 80.0, False, None),
                          (2, "Third", "M", True, 40.0, 120.0, True, "visited"), (3, "Far End", "DA", False, 40.0, 160.0, False, None)])
        self.assertNotIn("fuel", r)                       # route information only
        self.assertEqual(set(r["hops"][0]), {"i", "id", "name", "star_class", "scoopable", "ly", "total_ly", "visited", "known", "x", "z", "discoverer"})
        self.assertEqual((r["from"], r["start"], [(h["x"], h["z"]) for h in r["hops"][:2]]), ("Start", [0.0, 0.0], [(40.0, 0.0), (80.0, 0.0)]))
        self.j.pos = dict(HOPS[1])                        # part way: only what is ahead
        self.assertEqual([h["name"] for h in self.state.navroute_view()["route"]["hops"]], ["Third", "Far End"])
        self.plot([dict(HOPS[0], star_class=None)])       # a hop whose star the game did not name
        self.assertEqual([(h["star_class"], h["scoopable"]) for h in self.state.navroute_view()["route"]["hops"]], [(None, None)])

    def test_endpoints(self):
        from aiohttp.test_utils import TestClient, TestServer
        self.plot()

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                view = await (await c.get("/api/navroute")).json()
                gone = (await c.get("/api/navroute/refuel")).status
                cross = (await c.get("/api/navroute", headers={"Sec-Fetch-Site": "cross-site"})).status
                payload = (await (await c.get("/api/nearby")).json())["route"]
                return view, gone, cross, payload
        view, gone, cross, payload = asyncio.run(go())
        self.assertEqual((view["route"]["count"], view["position"]["name"]), (4, "Start"))
        self.assertEqual((gone, cross), (404, 403))
        self.assertEqual(payload["known_v"], 0)            # the page reloads the list as the Known column comes in


class Layout(unittest.TestCase):
    def test_the_list_takes_the_highways_place(self):
        """In the window-filling layout Plot Route is a grid: the list on the left, the map filling the right. The
        game route's list must sit in the Highway list's cell and its switch outside the grid, or they land in cells of
        their own and the map is squeezed (seen 2026-10-12)."""
        import os
        import re
        static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
        with open(os.path.join(static, "page.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(static, "page.css"), encoding="utf-8") as f:
            css = f.read()
        view = html[html.index('<section id="hwyView"'):]
        view = view[:view.index("</section>")]
        panes = view[view.index('<div id="hwyPanes">'):]
        self.assertLess(view.index('id="hwyGame"'), view.index('id="hwyPanes"'))        # the switch: above the grid
        self.assertNotIn('id="hwyGame"', panes)
        self.assertIn('id="nrPane"', panes)                                              # the list: one of its panes
        place = lambda sel: re.search(r"body\.app %s \{ grid-column: (\d+); grid-row: (\d+); \}" % re.escape(sel), css)
        self.assertEqual(place("#nrPane").groups(), place("#hwyPane").groups())          # the Highway list's own cell
        self.assertEqual(place("#nrPane").groups(), place("#richPane").groups())
        self.assertRegex(css, r"(?m)^#nrPane \{ order: 5; \}")                           # and its place in the narrow layout


if __name__ == "__main__":
    unittest.main()

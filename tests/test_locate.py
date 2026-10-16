"""Locate (this fork: outrider/locate.py, GET /api/locate): the nearest places for a need, from Spansh's station and
body searches. No request leaves the tests: the session is a fake that records what it is asked."""
import asyncio
import types
import unittest

from support import ed_outrider

import outrider.locate as L

NOW = 1791806400   # 2026-10-12T12:00:00Z
POS = {"name": "Sol", "x": 0.0, "y": 0.0, "z": 0.0}


class Pure(unittest.TestCase):
    def test_station_bodies(self):
        b = L.station_body("guardian", POS)
        self.assertEqual(b["filters"]["technology_broker"], {"value": ["Guardian"]})
        self.assertEqual((b["sort"], b["reference_coords"], b["size"]), ([{"distance": {"direction": "asc"}}], {"x": 0.0, "y": 0.0, "z": 0.0}, L.SIZE))
        self.assertEqual(L.station_body("factors", POS)["filters"]["services"], [{"name": "Interstellar Factors Contact"}])
        self.assertEqual(L.station_body("raw", POS)["filters"]["material_trader"], {"value": ["Raw"]})
        self.assertEqual(L.station_body("black", POS, pad="L")["filters"]["has_large_pad"], {"value": True})
        self.assertNotIn("has_large_pad", L.station_body("black", POS)["filters"])
        self.assertEqual(set(L.STATIONS), {"factors", "raw", "encoded", "manufactured", "outfitting", "shipyard", "repair", "black", "guardian", "human"})

    def test_station_rows(self):
        rows = L.station_rows([
            {"name": "Magnus Gateway", "system_name": "EZ Aquarii", "system_id64": 5, "distance": 11.123, "distance_to_arrival": 351.7,
             "has_large_pad": True, "type": "Coriolis Starport", "updated_at": "2026-10-11T12:00:00Z", "technology_broker": "Guardian"},
            {"name": "Rescue Ship", "system_name": "Sol", "distance": 0, "has_large_pad": False, "type": "Mega ship", "updated_at": "junk"},
            {"name": "A depot", "system_name": "X", "type": "Space Construction Depot"},   # nowhere to land a ship
            {"system_name": "no name"}, "junk"], now=NOW)
        self.assertEqual(rows[0], {"name": "Magnus Gateway", "system": "EZ Aquarii", "id64": "5", "distance": 11.1, "ls": 352, "pad": "L",
                                   "type": "Coriolis Starport", "planetary": False, "age": 86400, "broker": "Guardian", "trader": None})
        self.assertEqual((rows[1]["pad"], rows[1]["age"], len(rows)), ("M", None, 2))

    def test_hotspot_rows(self):
        rows = L.hotspot_rows([{"name": "Barnard's Star 5", "system_name": "Barnard's Star", "system_id64": 7, "distance": 5.95, "distance_to_arrival": 3272.4,
                                "rings": [{"name": "A Ring", "type": "Metal Rich", "signals": [{"name": "Painite", "count": 2}, {"name": "Platinum", "count": 1}]},
                                          {"name": "B Ring", "type": "Icy", "signals": [{"name": "Bromellite", "count": 1}]}, "junk"]}], "Platinum")
        self.assertEqual(rows, [{"body": "Barnard's Star 5", "system": "Barnard's Star", "id64": "7", "distance": 6.0, "ls": 3272, "ring": "A Ring",
                                 "ring_type": "Metal Rich", "count": 1, "others": [["Painite", 2]]}])   # B Ring has none: left out
        b = L.hotspot_body("Painite", POS)
        self.assertEqual(b["filters"]["ring_signals"], [{"name": "Painite", "comparison": "<=>", "value": [1, 99]}])


class Server(unittest.TestCase):
    def setUp(self):
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        self.state = ed_outrider.State(db, ed_outrider.Journals(db), types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.state.journals.handle({"event": "FSDJump", "timestamp": "2026-10-15T10:00:00Z", "StarSystem": "Sol", "SystemAddress": 10477373803,
                                    "StarPos": [0.0, 0.0, 0.0]})
        self.posted, self.fail = [], None
        test = self

        class Resp:
            def __init__(self, doc):
                self.doc = doc

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def raise_for_status(self):
                if test.fail:
                    raise test.fail

            async def json(self):
                return self.doc

        def post(url, json=None):
            self.posted.append((url, json))
            if "bodies" in url:
                return Resp({"results": [{"name": "B 5", "system_name": "Bee", "distance": 9.0, "rings": [{"name": "B 5 A Ring", "type": "Icy",
                                                                                                          "signals": [{"name": "Tritium", "count": 3}]}]}]})
            return Resp({"results": [{"name": "Broker Port", "system_name": "Bee", "distance": 9.0, "has_large_pad": True, "type": "Orbis Starport"}]})
        self.state.spansh = types.SimpleNamespace(session=types.SimpleNamespace(post=post), sem_fast=asyncio.Semaphore(4),
                                                  cached=lambda i: (None, None))

    def get(self, *qs):
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                return [(r.status, await r.json()) for r in [await c.get("/api/locate", params=q) for q in qs]]
        return asyncio.run(go())

    def test_the_route(self):
        (s1, guardian), (s2, mining), *bad = self.get({"what": "guardian", "pad": "L"}, {"what": "mining", "mineral": "Tritium"},
                                                      {"what": "nope"}, {"what": "mining", "mineral": "Gravel"}, {"what": "raw", "pad": "XL"})
        self.assertEqual((s1, guardian["title"], guardian["from"], guardian["rows"][0]["name"]), (200, "Guardian technology broker", "Sol", "Broker Port"))
        self.assertEqual((s2, mining["title"], mining["rows"][0]["ring"], mining["rows"][0]["count"]), (200, "Tritium hotspots", "B 5 A Ring", 3))
        self.assertEqual([b[0] for b in bad], [400, 400, 400])
        self.assertEqual([u for u, _ in self.posted], [ed_outrider.SPANSH_STATION_SEARCH, ed_outrider.SPANSH_BODY_SEARCH])   # the server's own URLs
        self.assertEqual(self.posted[0][1]["filters"]["has_large_pad"], {"value": True})

    def test_spansh_down(self):
        self.fail = OSError("down")
        (status, out), = self.get({"what": "black"})
        self.assertEqual((status, out["error"]), (502, "Spansh could not be asked (OSError)"))


if __name__ == "__main__":
    unittest.main()

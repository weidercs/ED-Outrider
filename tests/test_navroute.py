"""The Game Route list (outrider/navroute.py, State.navroute_view / navroute_refuel, GET /api/navroute): the game's
own route with the fuel it takes, and where to refuel near where the tank runs dry. Made-up systems; the station
search is a stand-in (nothing reaches Spansh)."""
import asyncio
import time
import types
import unittest

from support import ed_outrider

import outrider.navroute as navroute
from outrider.fsd import hop_fuel

MODEL = {"unladen": 400.0, "r0": 50.0, "boost": 0.0, "max_fuel": 5.0, "power": 2.5, "fitted": False, "need": None}
HERE = {"id64": 1, "name": "Start", "x": 0.0, "y": 0.0, "z": 0.0}
HOPS = [{"id64": 10 + i, "name": n, "star_class": c, "x": 40.0 * (i + 1), "y": 0.0, "z": 0.0}
        for i, (n, c) in enumerate((("First Hop", "K"), ("Dry Stop", "N"), ("Third", "M"), ("Far End", "DA")))]


def station(name, system, x, kind="Coriolis Starport", services=("Refuel", "Repair"), large=True, **extra):
    return dict({"name": name, "type": kind, "system_name": system, "system_id64": abs(hash(system)) % 10 ** 9,
                 "system_x": x, "system_y": 0.0, "system_z": 0.0, "distance_to_arrival": 300.0,
                 "services": [{"name": s} for s in services], "has_large_pad": large, "medium_pads": 2,
                 "updated_at": ed_outrider.iso_ts(time.time() - 3600)}, **extra)


class Projection(unittest.TestCase):
    def test_fuel_jump_by_jump(self):
        """Each jump is worked out at the mass it is made at; the fuel lasts or says where it stops."""
        rows, f = navroute.project(HOPS, HERE, MODEL, 32.0, 8)
        first = hop_fuel(MODEL, 40.0, 400 + 32 + 8)
        second = hop_fuel(MODEL, 40.0, 400 + 32 - first + 8)
        self.assertEqual([(r["i"], r["ly"], r["total_ly"]) for r in rows], [(0, 40.0, 40.0), (1, 40.0, 80.0), (2, 40.0, 120.0), (3, 40.0, 160.0)])
        self.assertEqual((rows[0]["fuel_used"], rows[1]["fuel_used"]), (round(first, 2), round(second, 2)))
        self.assertLess(second, first)                                   # lighter, so cheaper
        self.assertAlmostEqual(rows[1]["fuel_left"], 32 - first - second, places=1)
        self.assertEqual((f["empty_at"], f["why"], f["last"], f["start"]), (None, None, 3, 32.0))
        self.assertEqual(f["end"], rows[3]["fuel_left"])

    def test_runs_dry(self):
        rows, f = navroute.project(HOPS, HERE, MODEL, 5.5, 0)
        self.assertEqual((f["empty_at"], f["why"], f["last"], f["end"]), (1, "fuel", 0, None))
        self.assertEqual(f["left"], rows[0]["fuel_left"])
        self.assertGreater(f["need"], f["left"])
        self.assertEqual([(r["fuel_used"], r["fuel_left"]) for r in rows[1:]], [(None, None)] * 3)   # nothing guessed past it
        _, none = navroute.project(HOPS, HERE, MODEL, 0.5, 0)
        self.assertEqual((none["empty_at"], none["last"]), (0, -1))      # not even the first jump

    def test_a_jump_past_the_range(self):
        """A jump the ship cannot make at that mass (plotted with a boost): said as such, not as an empty tank."""
        far = [dict(HOPS[0]), dict(HOPS[1], x=40.0 + 300.0)]
        rows, f = navroute.project(far, HERE, MODEL, 32.0, 0)
        self.assertEqual((f["empty_at"], f["why"], f["need"], f["last"]), (1, "range", None, 0))

    def test_without_a_model(self):
        for model, fuel, cargo in ((None, 10.0, 0), (MODEL, None, 0), (MODEL, 10.0, None), (None, None, None)):
            rows, f = navroute.project(HOPS, HERE, model, fuel, cargo)
            self.assertIsNone(f)
            self.assertEqual([(r["ly"], r["fuel_used"], r["fuel_left"]) for r in rows], [(40.0, None, None)] * 4)
        self.assertEqual(navroute.project([], HERE, MODEL, 5.0, 0), ([], dict(start=5.0, empty_at=None, why=None, last=-1,
                                                                             need=None, left=None, end=5.0)))

    def test_nearest_hops(self):
        places = [{"name": "A", "x": 42.0, "y": 0.0, "z": 0.0}, {"name": "B", "x": 1.0, "y": 0.0, "z": 0.0},
                  {"name": "C", "x": 200.0, "y": 0.0, "z": 0.0}]
        got = navroute.nearest_hops(places, HERE, HOPS, 1)                 # only the hops still reached count
        self.assertEqual([p["near"] for p in got], [{"i": 0, "name": "First Hop", "ly": 2.0}, {"i": -1, "name": "Start", "ly": 1.0},
                                                    {"i": 1, "name": "Dry Stop", "ly": 120.0}])
        self.assertEqual(navroute.nearest_hops(places[:1], HERE, HOPS, -1)[0]["near"]["i"], -1)


class View(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.searches = []

        async def dock_search(pos, need=()):
            self.searches.append((pos.get("name"), list(need)))
            if isinstance(self.found, Exception):
                raise self.found
            return self.found
        self.found = [station("Fuel Dock", "Pump System", 46.0), station("No Fuel", "Dry Stop", 80.0, services=("Repair",)),
                      station("Small Port", "First Hop", 40.0, kind="Outpost", large=False),
                      station("G0B-W2J", "First Hop", 40.0, kind="Drake-Class Carrier", carrier_name="Deep Relay",
                              carrier_docking_access="All"),
                      station("Old Dock", "Pump System", 47.0, updated_at="2020-01-01T00:00:00Z")]
        self.sp = types.SimpleNamespace(cached=lambda i: (None, None), dock_search=dock_search)
        self.state = ed_outrider.State(self.db, self.j, self.sp, 25)
        self.fuel = 5.5
        self.state.fuel_now = lambda: (MODEL, self.fuel, 0) if self.fuel is not None else None

    def plot(self, hops=HOPS):
        self.j.pos = dict(HERE)
        self.j.ship = {"type": "anaconda", "fuel_main": 32.0}
        ed_outrider.meta_set(self.db, "route", {"ts": "2026-10-11T10:00:00Z", "hops": [dict(HERE, star_class="G")] + hops})

    def test_no_route(self):
        self.assertIsNone(self.state.navroute_view()["route"])
        self.j.pos = dict(HERE)
        self.assertIsNone(self.state.navroute_view()["route"])
        self.assertEqual(asyncio.run(self.state.navroute_refuel()), ({"error": "no route is plotted in the game"}, 409))
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
        self.assertEqual([(h["i"], h["name"], h["star_class"], h["scoopable"], h["visited"], h["known"]) for h in r["hops"]],
                         [(0, "First Hop", "K", True, False, None), (1, "Dry Stop", "N", False, False, None),
                          (2, "Third", "M", True, True, "visited"), (3, "Far End", "DA", False, False, None)])
        f = r["fuel"]
        self.assertEqual((f["empty_at"], f["last"], f["last_name"], f["empty_name"], f["scoopable_before"], f["capacity"]),
                         (1, 0, "First Hop", "Dry Stop", 1, 32.0))
        self.assertIsNotNone(r["hops"][0]["fuel_left"])
        self.assertIsNone(r["hops"][1]["fuel_left"])
        self.fuel = 32.0
        full = self.state.navroute_view()["route"]["fuel"]
        self.assertEqual((full["empty_at"], full["last_name"], full["empty_name"], full["scoopable_before"]), (None, "Far End", None, 2))
        self.fuel = None                                  # no Loadout mass or no reading: listed without fuel
        bare = self.state.navroute_view()["route"]
        self.assertEqual((bare["fuel"], bare["hops"][0]["fuel_left"], bare["hops"][0]["ly"]), (None, None, 40.0))
        self.j.pos = dict(HOPS[1])                        # part way: only what is ahead
        self.assertEqual([h["name"] for h in self.state.navroute_view()["route"]["hops"]], ["Third", "Far End"])

    def test_refuel_near_where_it_runs_dry(self):
        """Stations your ship can land at and carriers, with Refuel and fresh data, nearest the last system the fuel
        reaches; each with the reachable route system it is closest to."""
        self.plot()
        out, status = asyncio.run(self.state.navroute_refuel())
        self.assertEqual((status, out["needed"], out["at"], out["pad"]), (200, True, {"name": "First Hop", "i": 0}, "L"))
        self.assertEqual(self.searches, [("First Hop", ["Refuel"])])       # asked around the last system reached
        self.assertEqual([(r["kind"], r["name"], r["system"], r["ly"]) for r in out["rows"]],
                         [("carrier", "Deep Relay", "First Hop", 0.0), ("station", "Fuel Dock", "Pump System", 6.0)])
        self.assertEqual([r["near"] for r in out["rows"]], [{"i": 0, "name": "First Hop", "ly": 0.0},
                                                            {"i": 0, "name": "First Hop", "ly": 6.0}])
        self.assertEqual((out["hidden"]["service"], out["hidden"]["pad"], out["hidden"]["old"]), (1, 1, 1))
        asyncio.run(self.state.navroute_refuel())
        self.assertEqual(len(self.searches), 1)                             # the same place again: the last answer
        self.fuel = 0.5                                                     # not even the first jump: around where you are
        out, _ = asyncio.run(self.state.navroute_refuel())
        self.assertEqual((out["at"], self.searches[-1][0]), ({"name": "Start", "i": -1}, "Start"))
        self.fuel = 32.0
        self.assertEqual(asyncio.run(self.state.navroute_refuel()), ({"needed": False, "rows": [], "errors": []}, 200))
        self.assertEqual(len(self.searches), 2)                             # the fuel lasts: nobody asked
        self.fuel = None
        self.assertEqual(asyncio.run(self.state.navroute_refuel())[1], 409)

    def test_refuel_when_spansh_is_down(self):
        self.plot()
        self.found = ed_outrider.ClientError("down")
        out, status = asyncio.run(self.state.navroute_refuel())
        self.assertEqual((status, out["needed"], out["rows"]), (200, True, []))
        self.assertIn("Spansh could not be reached (down)", out["errors"][0])

    def test_endpoints(self):
        from aiohttp.test_utils import TestClient, TestServer
        self.plot()

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                view = await (await c.get("/api/navroute")).json()
                refuel = await (await c.get("/api/navroute/refuel")).json()
                cross = (await c.get("/api/navroute", headers={"Sec-Fetch-Site": "cross-site"})).status
                payload = (await (await c.get("/api/nearby")).json())["route"]
                return view, refuel, cross, payload
        view, refuel, cross, payload = asyncio.run(go())
        self.assertEqual((view["route"]["count"], view["route"]["fuel"]["empty_at"], view["position"]["name"]), (4, 1, "Start"))
        self.assertEqual((refuel["needed"], len(refuel["rows"]), cross), (True, 2, 403))
        self.assertEqual(payload["known_v"], 0)            # the page reloads the list as the Known column comes in


if __name__ == "__main__":
    unittest.main()

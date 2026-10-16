"""The engineers' trip (this fork: outrider/engtour.py, POST /api/commander/engineer_tour): which engineers cover the
picks for the fewest light years, in which order, ending at the carrier when asked. Made-up engineers on a line."""
import asyncio
import itertools
import math
import types
import unittest

from support import ed_outrider

import outrider.engtour as T

PLACES = {"A": (10, 0, 0), "B": (20, 0, 0), "C": (100, 0, 0), "D": (-30, 0, 0), "M": (12, 0, 0), "Far": (5000, 0, 0)}
ALL = {k: {"progress": "Unlocked", "rank": 5} for k in PLACES}


def req(label, *engineers, grade=None):
    return {"label": label, "grade": grade, "engineers": list(engineers)}


class Plan(unittest.TestCase):
    def test_one_engineer_for_two_picks_beats_two(self):
        reqs = [req("FSD G5", "A", "M", grade=5), req("Power plant G5", "M", "B", grade=5)]
        out = T.plan(reqs, ALL, PLACES, (0, 0, 0))
        self.assertEqual([s["engineer"] for s in out["stops"]], ["M"])          # M does both: one stop (12 ly) ...
        reqs2 = [req("FSD G5", "A", grade=5), req("Power plant G5", "B", "C", grade=5)]
        out2 = T.plan(reqs2, ALL, PLACES, (0, 0, 0))
        self.assertEqual([s["engineer"] for s in out2["stops"]], ["A", "B"])    # ... but A then B (20 ly) beats A and C
        self.assertEqual((out2["total_ly"], [s["leg_ly"] for s in out2["stops"]]), (20.0, [10.0, 10.0]))
        self.assertEqual([s["covers"] for s in out2["stops"]], [["FSD G5"], ["Power plant G5"]])

    def test_the_order_is_the_shortest(self):
        reqs = [req(k, k) for k in ("C", "A", "D", "B")]
        out = T.plan(reqs, ALL, PLACES, (0, 0, 0))
        order = [s["engineer"] for s in out["stops"]]
        best = min(itertools.permutations("ABCD"), key=lambda o: sum(math.dist(a, b) for a, b in zip(
            [(0, 0, 0)] + [PLACES[x] for x in o], [PLACES[x] for x in o])))
        self.assertEqual(order, list(best))
        self.assertEqual(out["total_ly"], 30 + 40 + 10 + 80)                     # D first (30), back past A, B, out to C

    def test_ending_at_the_carrier(self):
        reqs = [req("x", "D"), req("y", "C")]
        out = T.plan(reqs, ALL, PLACES, (0, 0, 0), end=(100, 0, 0))
        self.assertEqual([s["engineer"] for s in out["stops"]], ["D", "C"])     # the carrier is past C: C last
        self.assertEqual((out["back_ly"], out["total_ly"]), (0.0, 30 + 130))
        alone = T.plan(reqs, ALL, PLACES, (0, 0, 0), end=(-40, 0, 0))
        self.assertEqual([s["engineer"] for s in alone["stops"]], ["C", "D"])   # the carrier the other way: D last
        self.assertEqual(alone["back_ly"], 10.0)

    def test_locked_engineers(self):
        st = {"A": {"progress": "Unlocked", "rank": 3}, "B": {"progress": "Invited"}, "C": {"progress": "Unlocked", "rank": 5}}
        reqs = [req("G5", "A", "B", "C", grade=5)]
        out = T.plan(reqs, st, PLACES, (0, 0, 0))
        self.assertEqual(([s["engineer"] for s in out["stops"]], out["stops"][0]["locked"]), (["C"], None))   # A's rank 3, B invited
        near = T.plan(reqs, st, PLACES, (0, 0, 0), include_locked=True)
        self.assertEqual(([s["engineer"] for s in near["stops"]], near["stops"][0]["locked"]), (["A"], "rank 3 of 5 needed"))
        none = T.plan([req("G4", "B", grade=4), req("other", "Nobody")], st, PLACES, (0, 0, 0))
        self.assertEqual(none["stops"], [])
        self.assertEqual([(u["label"], u["why"]) for u in none["uncovered"]],
                         [("G4", "no engineer you can use (not unlocked yet)"), ("other", "no engineer you can use (no workshop known)")])
        self.assertEqual(T.plan([req("x")], ALL, PLACES, (0, 0, 0))["uncovered"][0]["why"], "nobody listed for it")

    def test_names_are_matched_loosely(self):
        st = {"Tod 'The Blaster' McQuinn": {"progress": "Unlocked", "rank": 5}}
        places = {'Tod "The Blaster" McQuinn': (1, 0, 0)}
        out = T.plan([req("x", 'Tod "The Blaster" McQuinn', grade=5)], st, places, (0, 0, 0))
        self.assertEqual(out["stops"][0]["engineer"], 'Tod "The Blaster" McQuinn')

    def test_many_stops(self):
        places = {f"E{i}": (float(i * 10), float((i * 37) % 23), 0.0) for i in range(14)}
        st = {k: {"progress": "Unlocked", "rank": 5} for k in places}
        out = T.plan([req(k, k) for k in places], st, places, (0, 0, 0))
        self.assertEqual(len(out["stops"]), 14)                                   # past EXACT_STOPS: still every stop, once
        self.assertEqual(sorted(s["engineer"] for s in out["stops"]), sorted(places))
        straight = sum(math.dist(a, b) for a, b in zip([(0, 0, 0)] + [places[f"E{i}"] for i in range(14)], [places[f"E{i}"] for i in range(14)]))
        self.assertLessEqual(out["total_ly"], round(straight, 1) + 0.1)          # no worse than the obvious order here

    def test_nothing_picked(self):
        self.assertEqual(T.plan([], ALL, PLACES, (0, 0, 0)), {"stops": [], "total_ly": 0.0, "back_ly": None, "uncovered": [], "covers_tried": 1})


class Server(unittest.TestCase):
    def test_the_route(self):
        from aiohttp.test_utils import TestClient, TestServer
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        state = ed_outrider.State(db, ed_outrider.Journals(db), types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        j = state.journals
        j.handle({"event": "FSDJump", "timestamp": "2026-10-15T10:00:00Z", "StarSystem": "Sol", "SystemAddress": 10477373803,
                  "StarPos": [0.0, 0.0, 0.0]})
        import outrider.commander as C
        # every workshop placed (far away) but the three that matter: nothing is asked of Spansh
        places = {v[0]: [9000.0, 0.0, 0.0] for v in C.ENGINEER_SYSTEMS.values()}
        places.update({"Deciat": [122.6, -0.8, -47.3], "Sirius": [6.2, -1.3, -5.8], "Khun": [-171.6, 20.0, -57.0]})
        ed_outrider.meta_set(db, "engineer_places", places)
        real = C.engineer_progress
        C.engineer_progress = lambda dirs: {"Felicity Farseer": {"progress": "Unlocked", "rank": 5}, "Marco Qwent": {"progress": "Unlocked", "rank": 4}}
        self.addCleanup(setattr, C, "engineer_progress", real)

        async def record(name):
            return None
        state.spansh = types.SimpleNamespace(system_record=record, cached=lambda i: (None, None))

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(state))) as c:
                ok = await c.post("/api/commander/engineer_tour", json={"requirements": [
                    {"label": "FSD G5", "grade": 5, "engineers": ["Felicity Farseer", "Elvira Martuuk"]},
                    {"label": "Power plant G4", "grade": 4, "engineers": ["Marco Qwent", "Felicity Farseer"]}]})
                bad = [(await c.post("/api/commander/engineer_tour", json=b)).status for b in
                       ({}, {"requirements": "x"}, {"requirements": [{"label": "x", "engineers": "y"}]}, {"requirements": [], "include_locked": "yes"})]
                return ok.status, await ok.json(), bad
        status, out, bad = asyncio.run(go())
        self.assertEqual((status, [(s["engineer"], s["system"]) for s in out["stops"]]), (200, [("Felicity Farseer", "Deciat")]))
        self.assertEqual((out["from"], out["stops"][0]["covers"]), ("Sol", ["FSD G5", "Power plant G4"]))
        self.assertEqual(bad, [400, 400, 400, 400])


if __name__ == "__main__":
    unittest.main()

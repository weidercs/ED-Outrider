"""The Unscanned (bio) plotter (outrider/biohunt.py, State.unscanned_start_plot / _unscanned_plot,
Spansh.unscanned_near): a chain of systems with no scan data, picked by their mass code's odds of life, each hop as
close to the jump range as there is one. Made-up systems; Spansh is a stand-in."""
import asyncio
import types
import unittest
import unittest.mock

from support import _HwSession, ed_outrider

import outrider.biohunt as B
from outrider.highway import highway_text

START = {"id64": 1, "name": "Start", "x": 0.0, "y": 0.0, "z": 0.0}


def system(i, name, x, y=0.0, z=0.0):
    return {"id64": i, "name": name, "x": float(x), "y": float(y), "z": float(z)}


class Pure(unittest.TestCase):
    def test_mass_code(self):
        for name, want in (("Swoilz QK-O b26-2", "b"), ("Fine Ring Sector GG-Y d38", "d"), ("Col 285 Sector KM-V d2-106", "d"),
                           ("  Blua  Eaec WW-E  c14-1293 ", "c"), ("Eol Prou RS-T h3-6", "h"), ("Sol", None), ("HIP 12345", None),
                           ("Swoilz QK-O x26-2", None), ("Swoilz QK-O B26-2", None), ("", None), (None, None)):
            self.assertEqual(B.mass_code(name), want, name)

    def test_rates_blend_your_own_counts(self):
        self.assertEqual(B.rates(), {c: B.PRIOR[c] for c in B.MASS_CODES})          # nothing of your own: the guess
        r = B.rates({"d": (180, 18), "a": (0, 0), "c": (20, 20), "e": (5, 9)})
        self.assertEqual(r["d"], round((18 + 0.60 * 20) / 200, 3))                   # 180 of your own outweigh the guess
        self.assertLess(r["d"], B.PRIOR["d"])
        self.assertEqual(r["c"], round((20 + 0.45 * 20) / 40, 3))
        self.assertEqual(r["e"], round((5 + 0.50 * 20) / 25, 3))                     # more "with bio" than scanned: capped
        self.assertEqual((r["a"], r["h"]), (B.PRIOR["a"], B.PRIOR["h"]))
        self.assertEqual((B.odds("X AB-C d1", r), B.odds("Sol", r), B.odds("X AB-C d1", None)), (r["d"], B.OTHER, B.PRIOR["d"]))
        self.assertEqual(B.odds_text(None).split(", ")[:3], ["d 60%", "e 50%", "c 45%"])

    def test_pick_keeps_to_the_range(self):
        """Within one jump, the hop that uses most of the range wins among systems of one kind; a likelier kind wins
        over a little more distance; nothing beyond the range is taken while something is within it."""
        same = [system(2, "S AB-C d1", 20), system(3, "S AB-C d2", 48), system(4, "S AB-C d3", 35), system(5, "S AB-C d4", 60)]
        c, d, jumps = B.pick(same, START, 50.0)
        self.assertEqual((c["id64"], d, jumps), (3, 48.0, 1))                         # 60 ly is past the 50 ly range
        kinds = [system(2, "S AB-C a1", 49), system(3, "S AB-C d1", 40)]
        self.assertEqual(B.pick(kinds, START, 50.0)[0]["id64"], 3)                    # 0.60 x 0.8 beats 0.20 x 0.98
        self.assertEqual(B.pick(kinds, START, 50.0, {"a": 0.9, "d": 0.1})[0]["id64"], 2)   # your own counts decide
        far = B.pick([system(5, "S AB-C d4", 120)], START, 50.0)
        self.assertEqual((far[0]["id64"], far[1], far[2]), (5, 120.0, 3))             # nothing nearer: three jumps
        self.assertEqual(B.pick([system(6, "S AB-C d5", 100)], START, 50.0)[2], 2)    # exactly two ranges: two jumps
        self.assertIsNone(B.pick([], START, 50.0))
        self.assertIsNone(B.pick([system(2, "S AB-C d1", 0.2), {"id64": 9, "name": "No Place", "x": None, "y": 0, "z": 0}], START, 50.0))

    def test_pick_leads_on(self):
        here = system(2, "S AB-C d1", 50)
        cands = [system(3, "S AB-C d2", 5), system(4, "S AB-C d3", 95), system(5, "S AB-C d4", 50, 40)]
        self.assertEqual(B.pick(cands, here, 50.0, start=START)[0]["id64"], 4)        # outward: not back towards the start
        self.assertEqual(B.pick(cands, here, 50.0, start=START, taken={4})[0]["id64"], 5)   # never a system twice
        self.assertIsNone(B.pick(cands[:1], here, 50.0, start=START))
        toward = system(99, "Goal", 50, 500)
        self.assertEqual(B.pick(cands, here, 50.0, start=START, toward=toward)[0]["id64"], 5)   # the one nearer the goal
        self.assertEqual(B.pick(cands, START, 50.0, start=START)[0]["id64"], 5)       # the first hop: any direction (64 ly: two jumps)

    def test_species_lean(self):
        """Favouring one species: each mass code by how much commoner it is among the systems with the species than
        among scanned systems at large; a code nobody near you has scanned or found it in is left neutral; too few
        reports give no lean at all."""
        found = [f"S AB-C c{i}" for i in range(30)] + [f"S AB-C b{i}" for i in range(20)] + [f"S AB-C a{i}" for i in range(2)]
        scanned = [f"T AB-C c{i}" for i in range(20)] + [f"T AB-C b{i}" for i in range(30)] + [f"T AB-C a{i}" for i in range(50)]
        odds, lift = B.species_lean(found + found[:5] + ["Sol"], scanned + ["Achenar"])      # repeats and hand names: not counted
        self.assertEqual(lift, {"a": 0.23, "b": 1.24, "c": 2.58, "d": 1.0, "e": 1.0, "f": 1.0, "g": 1.0, "h": 1.0})
        self.assertEqual((odds["c"], odds["b"], odds["a"], odds["d"]), (1.0, 0.481, 0.089, 0.388))   # the best code is 1
        self.assertEqual(B.lift_text(lift), "c x2.58, b x1.24, d x1, e x1, f x1, g x1, h x1, a x0.23")
        self.assertEqual(B.species_lean(found[:B.LEAN_MIN_FOUND - 1], scanned), (None, None))
        self.assertEqual(B.species_lean(found, scanned[:B.LEAN_MIN_SCANNED - 1]), (None, None))
        self.assertEqual(B.code_counts(["S AB-C c1", "S AB-C c2", "S AB-C d1", "Sol", ""]), {"c": 2, "d": 1})
        only = B.species_lean([f"S AB-C h{i}" for i in range(25)], scanned)[1]              # found only where nothing was scanned
        self.assertGreater(only["h"], 5)
        # the lean decides the pick: the c system a little nearer beats the a system at the range
        cands = [system(2, "S AB-C a1", 49), system(3, "S AB-C c1", 40)]
        self.assertEqual(B.pick(cands, START, 50.0, odds)[0]["id64"], 3)

    def test_rows(self):
        chain = [dict(START), dict(system(2, "S AB-C d1", 40), hop_jumps=1), dict(system(3, "S AB-C d2", 40, 90), hop_jumps=2)]
        rows = B.rows(chain)
        self.assertEqual([(r["system"], r["id64"], r["distance"], r["jumps"], r["remaining"]) for r in rows],
                         [("Start", 1, 0.0, 0, 130.0), ("S AB-C d1", 2, 40.0, 1, 90.0), ("S AB-C d2", 3, 90.0, 2, 0.0)])
        self.assertEqual({(r["fuel_used"], r["fuel_left"], r["neutron"], r["refuel"]) for r in rows}, {(None, None, 0, 0)})
        self.assertEqual(highway_text(rows, 0, "unscanned"), "Next unscanned system: S AB-C d1.")
        self.assertEqual(highway_text(rows, 1, "unscanned"), "Next unscanned system: S AB-C d2, two jumps away.")
        self.assertTrue(highway_text(rows, 0).startswith("Next Neutron Highway Stop: S AB-C d1"))   # the Highway's own


class Search(unittest.TestCase):
    def test_unscanned_near(self):
        """Spansh is asked for systems with no scan value, the farthest first; what comes back with bodies, a permit
        or no place is left out."""
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        sp = ed_outrider.Spansh(db)

        class Session(_HwSession):
            def post(self, url, json=None):
                self.calls.append((url, json))
                return self.get.__self__.__class__.get(self, url)   # the scripted answer, as get() gives it
        answer = {"count": 6, "results": [
            {"id64": 2, "name": "S AB-C d1", "x": 1, "y": 2, "z": 3, "bodies": []},
            {"id64": 3, "name": "Scanned", "x": 1, "y": 2, "z": 3, "bodies": [{"name": "Scanned A"}]},
            {"id64": 4, "name": "Locked", "x": 1, "y": 2, "z": 3, "bodies": [], "needs_permit": True},
            {"id64": 5, "name": "Nowhere", "x": None, "y": 2, "z": 3}, {"id64": "6", "name": "Bad Id", "x": 1, "y": 2, "z": 3}, "junk"]}
        sp.session = Session([(200, answer)])
        got = asyncio.run(sp.unscanned_near({"x": 10.0, "y": 20.0, "z": 30.0}, 55.123))
        self.assertEqual(got, [{"id64": 2, "name": "S AB-C d1", "x": 1, "y": 2, "z": 3}])
        url, body = sp.session.calls[0]
        self.assertEqual(url, ed_outrider.SPANSH_SEARCH)
        self.assertEqual(body["filters"], {"distance": {"min": "0", "max": "55.12"},
                                           "estimated_scan_value": {"value": [0, 0], "comparison": "<=>"}})
        self.assertEqual((body["sort"], body["reference_coords"], body["size"]),
                         ([{"distance": {"direction": "desc"}}], {"x": 10.0, "y": 20.0, "z": 30.0}, 200))
        sp.session = None
        with self.assertRaises(ed_outrider.HighwayError):
            asyncio.run(sp.unscanned_near({"x": 0, "y": 0, "z": 0}, 50))


class Plot(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.j.handle({"event": "FSDJump", "timestamp": ed_outrider.iso_ts(1000), "StarSystem": "Start", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})
        # along x: one unscanned system every 10 ly, mass code d but for two; 150 ly holds a system you have been to
        self.field = [system(100 + k, f"Field AB-C {'a' if k in (4, 9) else 'd'}{k}", 10.0 * k) for k in range(1, 40)]
        self.db.execute("INSERT INTO visits (id64, name, x, y, z, first_ts, last_ts, count) VALUES (115, 'Field AB-C d15', 150, 0, 0, 't', 't', 1)")
        self.searches = []

        async def unscanned_near(pos, radius, size=200):
            self.searches.append((round(pos["x"], 1), radius))
            if isinstance(self.down, Exception):
                raise self.down
            return [dict(s) for s in self.field if B.ly(pos, s) <= radius]

        async def system_record(name):
            return {"goal": system(900, "Goal", 0, 400)}.get(name.lower())
        self.down = None
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(
            cached=lambda i: (None, None), unscanned_near=unscanned_near, system_record=system_record), 25)
        self.state.clipboard = None

    def run_plot(self, **body):
        async def go():
            with unittest.mock.patch.object(ed_outrider, "UNSCANNED_GAP_S", 0):
                out, status = self.state.highway_start_plot(dict({"plotter": "unscanned", "range": 50}, **body))
                if status == 202:
                    busy = self.state.highway_start_plot({"plotter": "unscanned", "range": 50})[1]
                    await self.state.highway_task
                    return out, status, busy
                return out, status, None
        return asyncio.run(go())

    def test_your_own_counts(self):
        for sid, name, bodies, bio in ((201, "Seen AB-C d1", 3, True), (202, "Seen AB-C d2", 2, False), (203, "Seen AB-C d3", 1, True),
                                       (204, "Seen AB-C c1", 4, True), (205, "Achenar", 9, True)):
            self.db.execute("INSERT INTO visits (id64, name, x, y, z, first_ts, last_ts, count) VALUES (?, ?, 0, 0, 0, 't', 't', 1)", (sid, name))
            for n in range(bodies):
                self.db.execute("INSERT INTO own_bodies (system, body_id, name, record, ts) VALUES (?, ?, ?, '{}', 't')", (sid, n, f"{name} {n}"))
            if bio:
                self.db.execute("INSERT INTO own_signals (system, name, bio, geo, ts) VALUES (?, ?, 2, 0, 't')", (sid, f"{name} 1"))
        # d3 was only passed through (the arrival star alone): not counted; Achenar has no mass code
        self.assertEqual(self.state.bio_mass_counts(), {"d": (2, 1), "c": (1, 1)})

    def test_a_route_a_jump_range_apart(self):
        out, status, busy = self.run_plot(stops=5)
        self.assertEqual((status, busy, out["plotting"]["plotter"], out["plotting"]["stops"]), (202, 409, "unscanned", 5))
        self.assertEqual(self.state.highway_plotting["state"], "done")
        r = self.state.highway_view()["route"]
        self.assertEqual((r["plotter"], r["from"], r["count"]), ("unscanned", "Start", 6))
        rows = r["done"] + r["ahead"]
        # 50 ly hops; 150 ly is visited (its neighbour stands in), then on from there, always outward
        self.assertEqual([(x["system"], x["distance"], x["jumps"]) for x in rows],
                         [("Start", 0.0, 0), ("Field AB-C d5", 50.0, 1), ("Field AB-C d10", 50.0, 1), ("Field AB-C d14", 40.0, 1),
                          ("Field AB-C d19", 50.0, 1), ("Field AB-C d24", 50.0, 1)])
        self.assertEqual((r["total_ly"], [x["remaining"] for x in rows][-2:]), (240.0, [50.0, 0.0]))
        o = r["options"]
        self.assertEqual((o["range"], o["stops"], o["found"], o["toward"], o["odds"]), (50.0, 5, 5, None, B.rates()))
        self.assertEqual(len(self.searches), 5)                                 # one search per hop
        self.assertEqual(self.state.highway_summary()["next"]["name"], "Field AB-C d5")   # followed like any Highway route

    def test_towards_a_system_and_longer_hops(self):
        self.field = [system(301, "Side AB-C d1", 0, 45), system(302, "Side AB-C d2", 45, 0), system(303, "Side AB-C d3", 0, 170)]
        out, status, _ = self.run_plot(stops=3, to="Goal")
        self.assertEqual(status, 202)
        r = self.state.highway_view()["route"]
        rows = r["done"] + r["ahead"]
        # the one towards Goal (y), not the one beside it; then nothing within one jump or two: three jump ranges out
        self.assertEqual([(x["system"], x["distance"], x["jumps"]) for x in rows],
                         [("Start", 0.0, 0), ("Side AB-C d1", 45.0, 1), ("Side AB-C d3", 125.0, 3)])
        self.assertEqual((r["options"]["toward"], r["options"]["found"], r["options"]["stops"]), ("Goal", 2, 3))   # it ran out
        # one jump range, then two, then four, for the hop that needed it and for the one that found nothing
        self.assertEqual([rad for _, rad in self.searches], [50, 50, 100, 200, 50, 100, 200])

    def test_favouring_a_species(self):
        """With a species named, the odds come from where players reported it: Spansh's bodies with that landmark
        against the scanned systems around; the route records what it leaned on. Too few reports, or no answer: the
        any-life odds, and the reason."""
        asked = []

        async def body_search(filters, pos, radius, max_pages):
            asked.append(("bodies", filters, radius, max_pages))
            if isinstance(self.down, Exception):
                raise self.down
            return [{"system_name": f"Rep AB-C {'a' if k % 10 == 0 else 'd'}{k}", "distance": 5.0 * k} for k in range(self.reports)], 123.4

        async def sphere(pos, radius, max_pages=10):
            asked.append(("sphere", radius, max_pages))
            return [{"name": f"Near AB-C {'d' if k % 4 == 0 else 'a'}{k}", "bodies": [{}] if k % 2 else []} for k in range(400)]
        self.reports = 60
        self.state.spansh.body_search, self.state.spansh.sphere = body_search, sphere
        # the field: an 'a' system at the range and a 'd' system a little nearer, every 50 ly
        self.field = [system(100 + k, f"Field AB-C a{k}", 50.0 * k) for k in range(1, 6)] + \
                     [system(200 + k, f"Field AB-C d{k}", 50.0 * k - 8) for k in range(1, 6)]
        out, status, _ = self.run_plot(stops=2, species="stratum tectonicas")
        self.assertEqual(status, 202)
        self.assertEqual(asked[0], ("bodies", {"landmarks": [{"type": "Stratum", "subtype": ["Stratum Tectonicas"]}]},
                                    ed_outrider.SPECIES_RADIUS, 1))
        self.assertEqual(asked[1], ("sphere", ed_outrider.SPECIES_BASE_RADIUS, ed_outrider.SPECIES_BASE_PAGES))
        r = self.state.highway_view()["route"]
        o = r["options"]
        self.assertEqual((o["species"], o["lean"]["found"], o["lean"]["scanned"], o["lean"]["radius"], o["lean"]["why"]),
                         ("Stratum Tectonicas", 60, 200, 123, None))
        self.assertGreater(o["lean"]["lift"]["d"], 1)                      # players found it in d systems, seldom in a
        self.assertLess(o["lean"]["lift"]["a"], 1)
        self.assertEqual((o["odds"]["d"], "odds" in o["lean"]), (1.0, False))
        self.assertEqual([x["system"] for x in r["ahead"]], ["Field AB-C d1", "Field AB-C d2"])   # the d systems, though nearer
        self.reports = 5                                                    # too few reports: any life, and why
        self.run_plot(stops=2, species="Stratum Tectonicas")
        o = self.state.highway_view()["route"]["options"]
        self.assertEqual((o["odds"], o["lean"]["found"]), (B.rates(), 5))
        self.assertIn("too few reports of Stratum Tectonicas near Start", o["lean"]["why"])
        self.down = ed_outrider.ClientError("down")                         # Spansh not answering the question: the same
        self.reports = 60
        self.state.spansh.unscanned_near = unittest.mock.AsyncMock(return_value=[dict(s) for s in self.field])
        self.run_plot(stops=2, species="Stratum Tectonicas")
        o = self.state.highway_view()["route"]["options"]
        self.assertIn("Spansh could not be asked where Stratum Tectonicas has been found (down)", o["lean"]["why"])
        out, status, _ = self.run_plot(species="Stratum Imaginarius")
        self.assertEqual((status, out["error"]), (400, "species: not a species the biology rules know"))
        names = self.state.highway_view()["bio_species"]
        self.assertIn("Stratum Tectonicas", names[:12])                     # the most valuable first
        self.assertGreater(len(names), 80)

    def test_nothing_to_find_and_failures(self):
        self.field = []
        self.run_plot(stops=3)
        p = self.state.highway_plotting
        self.assertEqual(p["state"], "failed")
        self.assertIn("Spansh knows no unscanned system within 200 ly of Start", p["error"])
        self.assertIsNone(self.state.highway_view()["route"])
        self.down = ed_outrider.ClientError("down")
        self.run_plot(stops=3)
        self.assertIn("Spansh's system search failed (down)", self.state.highway_plotting["error"])
        self.down = None
        self.run_plot(stops=3, to="Nowhere At All")
        self.assertIn("neither Outrider nor Spansh knows a system named Nowhere At All", self.state.highway_plotting["error"])

    def test_the_request_is_checked(self):
        for body, words in (({"stops": 1}, "stops is out of range"), ({"stops": 101}, "stops is out of range"),
                            ({"stops": "many"}, "stops is not a number"), ({"range": 0}, "range is out of range"),
                            ({"range": None}, "give the jump range")):
            out, status, _ = self.run_plot(**body)
            self.assertEqual(status, 400, body)
            self.assertIn(words, out["error"])
        self.j.pos = None
        out, status, _ = self.run_plot()
        self.assertEqual((status, "start system" in out["error"]), (400, True))
        self.assertEqual(self.state.highway_start_plot({"plotter": "sideways", "to": "x"}),
                         ({"error": "plotter must be exact, neutron or unscanned"}, 400))


if __name__ == "__main__":
    unittest.main()

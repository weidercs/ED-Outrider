"""Unit tests: the nearest place to dock (outrider/dock.py, State.nearest_dock / dssa_list, the voice's "nearest
station"...): real Spansh and DSSA data near the author (tests/fixtures/spansh_dock.json, dssa_carriers.json), fakes
for every request.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import asyncio
import calendar
import json
import os
import time
import types
import unittest

from support import ed_outrider  # also puts the repository root on sys.path
import outrider.ask as ask  # noqa: E402
import outrider.dock as dock  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
NOW = calendar.timegm(time.strptime("2026-10-08T15:30:00", "%Y-%m-%dT%H:%M:%S"))
HERE = {"id64": 1, "name": "Smojooe AR-E b25-8", "x": -4177.09, "y": -1.0, "z": 3324.53}


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def spansh():
    return dock.spansh_rows(fixture("spansh_dock.json")["results"])


def dssa():
    return dock.dssa_rows(fixture("dssa_carriers.json")["carriers"])


class Rows(unittest.TestCase):

    def test_dssa_list(self):
        rows = {r["callsign"]: r for r in dssa()}
        self.assertEqual(len(rows), 6)
        k = rows["K3K-L1N"]
        self.assertEqual((k["name"], k["access"], k["dssa"], k["until"]), ("[IGAU] Paradox Destiny", "All", True, "September 1, 2032"))
        self.assertEqual(k["services"], {"UC", "Vista", "Repair", "Refuel", "Shipyard", "Outfitting"})   # split words
        self.assertIn("UC", rows["TFF-34Z"]["services"])   # written "UC" there
        self.assertNotIn("Vista", rows["TFF-34Z"]["services"])
        self.assertEqual((rows["V8Z-06T"]["away"], rows["V8Z-06T"]["system"]), ("Procyon", "Preou Auscs PI-T C3-8"))
        self.assertEqual(dock.dssa_rows({"not": "a list"}), [])
        self.assertEqual(dock.dssa_rows([{"callsign": "X", "coords": {"x": "a"}}]), [])

    def test_spansh_answer(self):
        rows = spansh()
        st = [r for r in rows if r["kind"] == "station"]
        ca = {r["callsign"]: r for r in rows if r["kind"] == "carrier"}
        self.assertEqual(len(st) + len(ca), 24)
        may = next(r for r in st if r["name"] == "May Terminal")
        self.assertEqual((may["large"], may["services"] >= {"UC", "Vista"}, may["access"]), (True, True, "All"))
        self.assertFalse(next(r for r in st if r["name"] == "Skov Drilling Exploration")["large"])   # a settlement
        self.assertEqual(ca["KBT-B8Z"]["access"], "All")
        self.assertIsNone(ca["JBK-48M"]["access"])   # Spansh has none recorded
        self.assertEqual(ca["Q5B-2PZ"]["access"], "Squadron Friends")

    def test_merge_by_callsign(self):
        """A carrier in both: the DSSA badge, the fresher place, both lists of services."""
        sp = [{"kind": "carrier", "callsign": "K3K-L1N", "name": "", "system": "Old Place", "id64": 5, "x": 0.0, "y": 0.0,
               "z": 0.0, "ls": 12.0, "services": {"Shipyard"}, "pads": "L M", "large": True, "medium": True, "access": None,
               "seen": NOW - 400 * 86400, "source": "Spansh", "dssa": False, "until": "", "away": None}]
        rows = dock.merge(sp, dssa())
        k = next(r for r in rows if r["callsign"] == "K3K-L1N")
        self.assertEqual(len([r for r in rows if r["callsign"] == "K3K-L1N"]), 1)
        self.assertTrue(k["dssa"])
        self.assertEqual(k["system"], "Prai Hypoo TX-B d4")   # the DSSA sighting is fresher
        self.assertEqual((k["access"], k["source"]), ("All", "DSSA + Spansh"))
        own = dock.own_row({"id": 1, "callsign": "g0x-85z", "name": "OUT OF THE BLUE", "system": "Here", "x": 1, "y": 2, "z": 3,
                            "services": ["dock", "exploration", "vistagenomics", "refuel"]})
        self.assertEqual(own["services"], {"UC", "Vista", "Refuel"})   # what its last Docked listed
        rows = dock.merge(spansh(), [], own)
        self.assertEqual([r["access"] for r in rows if r["callsign"] == "G0X-85Z"], ["yours"])   # not Spansh's copy
        self.assertIsNone(dock.own_row({"id": 1, "x": 1, "y": 2, "z": 3, "decommission": {"done": True}}))


class Nearest(unittest.TestCase):

    def rows(self):
        own = dock.own_row({"id": 1, "callsign": "G0X-85Z", "name": "OUT OF THE BLUE", "system": "Smojooe AR-E b25-8",
                            "x": HERE["x"], "y": HERE["y"], "z": HERE["z"], "services": ["exploration", "vistagenomics"]})
        return dock.merge(spansh(), dssa(), own)

    def test_selling_data(self):
        out = dock.nearest(self.rows(), HERE, need={"UC", "Vista"}, pad="L", age_days=30, laden=76.2, now=NOW)
        r = out["rows"]
        self.assertEqual((r[0]["callsign"], r[0]["here"], r[0]["warn"]), ("G0X-85Z", True, []))   # yours, here
        names = [x["callsign"] or x["name"] for x in r]
        self.assertEqual(names[1:3], ["KBT-B8Z", "JBK-48M"])
        self.assertEqual(r[2]["warn"], ["docking not reported"])
        self.assertIn("May Terminal", names)
        self.assertIn("K3K-L1N", names)   # the DSSA list
        self.assertGreater(out["hidden"]["old"], 3)   # reports older than 30 days (carriers move)
        k = r[1]
        self.assertEqual((k["jumps"], k["ls"], k["services"][:2]), (10, 235, ["UC", "Vista"]))

    def test_filters_and_warnings(self):
        out = dock.nearest(self.rows(), HERE, need={"Repair"}, pad="L", age_days=120, now=NOW)
        q5b = next(x for x in out["rows"] if x["callsign"] == "Q5B-2PZ")
        self.assertEqual(q5b["warn"], ["squadron and friends only"])
        self.assertGreater(out["hidden"]["pad"], 0)   # settlements without a large pad
        self.assertEqual(dock.nearest(self.rows(), HERE, need={"Repair"}, pad=None, age_days=120, now=NOW)["hidden"]["pad"], 0)
        only = dock.nearest(self.rows(), HERE, stations=False, age_days=3650, now=NOW)["rows"]
        self.assertTrue(all(x["kind"] == "carrier" for x in only))
        st = dock.nearest(self.rows(), HERE, carriers=False, age_days=3650, now=NOW)["rows"]
        self.assertEqual([x["callsign"] for x in st if x["kind"] == "carrier"], ["G0X-85Z"])   # yours stays
        may = next(x for x in self.rows() if x["name"] == "May Terminal")
        out = dock.nearest(self.rows(), HERE, age_days=3650, permits={may["id64"]}, now=NOW)
        self.assertNotIn("May Terminal", [x["name"] for x in out["rows"]])
        self.assertGreater(out["hidden"]["permit"], 0)
        away = dock.nearest(self.rows(), HERE, age_days=3650, now=NOW, limit=200)["rows"]
        self.assertIn("last seen at Procyon", next(x for x in away if x["callsign"] == "V8Z-06T")["warn"])

    def test_spoken(self):
        out = dock.nearest(self.rows(), HERE, need={"Vista"}, pad="L", age_days=30, laden=76.2, now=NOW)
        self.assertEqual(dock.spoken(out, ["Vista"]), "Nearest place to dock with Vista Genomics: KBT-B8Z, a fleet carrier, "
                                                      "712 light years away, in Smojooe QI-T d3-37.")
        out = dock.nearest(self.rows(), HERE, carriers=False, need={"UC"}, age_days=30, now=NOW)
        self.assertTrue(dock.spoken(out, ["UC"], "station").startswith(
            "Nearest station with Universal Cartographics: May Terminal, a coriolis starport, 2,111 light years away"))
        self.assertEqual(dock.spoken({"rows": []}, [], "carrier"), "No carrier is known nearby with recent enough reports.")


class FakeSpansh:
    """dock_search / permit_ids / get_if_changed without a network: each call recorded."""

    def __init__(self, dssa_answers):
        self.dssa_answers, self.calls = list(dssa_answers), []

    async def dock_search(self, pos):
        self.calls.append("search")
        return fixture("spansh_dock.json")["results"]

    async def permit_ids(self, ids):
        self.calls.append("permits")
        return set()

    async def get_if_changed(self, url, etag=None, modified=None):
        self.calls.append(("dssa", etag))
        a = self.dssa_answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


class Endpoint(unittest.TestCase):

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.sp = FakeSpansh([(200, fixture("dssa_carriers.json")["carriers"], '"e1"', "Thu"),
                              (304, None, '"e1"', "Thu"), ed_outrider.ClientError("down")])
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.state.spansh = self.sp

    def ask(self, **q):
        return asyncio.run(self.state.nearest_dock({k: str(v) for k, v in q.items()}))

    def test_validation(self):
        self.assertEqual(self.ask()[1], 409)   # no position yet
        self.j.pos = dict(HERE)
        self.assertEqual(self.ask(age="soon")[1], 400)
        self.assertEqual(self.ask(age=0)[1], 400)

    def test_dssa_on_demand(self):
        """Fetched when asked, at most hourly, conditionally; an error keeps the copy; cached=1 never fetches."""
        self.j.pos = dict(HERE)
        out, status = self.ask(need="uc,vista", age=3650)
        self.assertEqual(status, 200)
        self.assertEqual(self.sp.calls.count(("dssa", None)), 1)
        self.assertTrue(any(r["callsign"] == "K3K-L1N" and r["dssa"] for r in out["rows"]))
        self.assertEqual(out["dssa"]["count"], 6)
        self.ask()   # within the hour: no request
        self.assertEqual(len([c for c in self.sp.calls if c[0] == "dssa"]), 1)
        d = ed_outrider.meta_get(self.db, "dssa")
        ed_outrider.meta_set(self.db, "dssa", dict(d, checked=time.time() - 7200))
        out, _ = self.ask(age=3650)   # an hour on: asked again with its etag, unchanged (304), the copy kept
        self.assertIn(("dssa", '"e1"'), self.sp.calls)
        self.assertEqual(out["dssa"]["count"], 6)
        ed_outrider.meta_set(self.db, "dssa", dict(ed_outrider.meta_get(self.db, "dssa"), checked=0))
        out, _ = self.ask(age=3650)   # EDAstro unreachable: the copy kept, the error said
        self.assertEqual(out["dssa"]["count"], 6)
        self.assertTrue(out["errors"])
        n = len(self.sp.calls)
        ed_outrider.meta_set(self.db, "dssa", dict(ed_outrider.meta_get(self.db, "dssa"), checked=0))
        self.ask(cached=1)   # the voice and the AI never fetch
        self.assertNotIn("dssa", [c[0] for c in self.sp.calls[n:]])


class Voice(unittest.TestCase):

    def test_phrases(self):
        phrases = ask.load_phrases()
        for text, cmd in (("nearest station", "nearest_dock"), ("Vespa, nearest vista", "nearest_dock"),
                          ("where can I dock", "nearest_dock"), ("nearest carrier with repair", "nearest_dock"),
                          ("nearest unvisited", "nearest_unvisited"), ("nearest", None)):
            self.assertEqual(ask.match(text, phrases), cmd, text)
        self.assertEqual(ask.nearest_query("nearest carrier with vista genomics and repair"), (["Vista", "Repair"], "carrier"))
        self.assertEqual(ask.nearest_query("nearest station"), ([], "station"))
        self.assertEqual(ask.nearest_query("nearest UC"), (["UC"], None))

    def test_answer(self):
        seen = []

        async def get(path, params=None):
            seen.append((path, dict(params or {})))
            return {"rows": [{"kind": "carrier", "name": "", "callsign": "KBT-B8Z", "system": "Smojooe QI-T d3-37", "ly": 711.5,
                              "ls": 235, "services": ["UC", "Vista"], "pads": "L M", "dssa": False, "own": False, "warn": [],
                              "age_s": 86400}], "hidden": {}, "pad": "L"}
        words = asyncio.run(ask.fixed_answer("nearest_dock", get, text="nearest carrier with vista"))
        self.assertEqual(words, "Nearest carrier with Vista Genomics: KBT-B8Z, a fleet carrier, 712 light years away, "
                                "in Smojooe QI-T d3-37.")
        self.assertEqual(seen[0][0], "/api/nearest")
        self.assertEqual((seen[0][1]["cached"], seen[0][1]["need"], seen[0][1]["stations"]), ("1", "Vista", "0"))


if __name__ == "__main__":
    unittest.main()

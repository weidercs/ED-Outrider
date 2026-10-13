"""Unit tests: the species other commanders reported on your system's bodies (S23): Spansh's body search answer read
(tests/fixtures/spansh_landmarks.json, a real one: its dumps carry no landmarks), when Outrider asks, and Here's facts.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import asyncio
import copy
import json
import os
import time
import unittest
import unittest.mock

from support import ed_outrider, _HwSession  # also puts the repository root on sys.path

with open(os.path.join(os.path.dirname(__file__), "fixtures", "spansh_landmarks.json"), encoding="utf-8") as f:
    FIX = json.load(f)
BODY = FIX["one_system_within_1ly"]["results"][0]   # Eol Prou LW-L c8-324 4 b: Bacterium Vesicula - Mulberry
SYS = BODY["system_id64"]


def answer():
    """The search out to 1 ly as Spansh could answer it: the body, a neighbour's body (left out), and on the body a
    second place of the same species and colour (kept once), another colour, and a landmark that is no biology."""
    b = copy.deepcopy(BODY)
    b["landmarks"] += [dict(b["landmarks"][0], latitude=1.0), dict(b["landmarks"][0], variant="Teal"),
                       {"subtype": "Water Ice Geyser", "type": "Geysers", "value": 0}]
    return {"count": 2, "results": [b, FIX["bio_search"]["results"][1]]}


class Parse(unittest.TestCase):
    def test_reported_life(self):
        self.assertEqual(FIX["dump"]["bodies"] and [k for b in FIX["dump"]["bodies"] for k in b if k == "landmarks"], [])   # dumps: none
        got = ed_outrider.reported_life(answer()["results"], SYS)
        self.assertEqual(got, {32: [{"genus": "Bacterium", "species": "Bacterium Vesicula", "variant": "Mulberry", "value": 1000000},
                                    {"genus": "Bacterium", "species": "Bacterium Vesicula", "variant": "Teal", "value": 1000000}]})
        self.assertEqual(ed_outrider.reported_life([{"system_id64": SYS, "body_id": 1, "landmarks": "x"}, None, "x"], SYS), {})
        self.assertEqual(ed_outrider.reported_life(None, SYS), {})


class Server(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.spansh = ed_outrider.Spansh(self.db)
        self.state = ed_outrider.State(self.db, self.j, self.spansh, 25)
        self.now = time.time()
        at = lambda s: ed_outrider.iso_ts(self.now - 60 + s)
        name = BODY["system_name"]
        self.j.handle({"event": "FSDJump", "timestamp": at(0), "StarSystem": name, "SystemAddress": SYS,
                       "StarPos": [BODY["system_x"], BODY["system_y"], BODY["system_z"]]})
        self.j.handle({"event": "Scan", "timestamp": at(5), "ScanType": "Detailed", "StarSystem": name, "SystemAddress": SYS, "BodyID": 32,
                       "BodyName": BODY["name"], "PlanetClass": "Icy body", "Landable": True, "AtmosphereType": "Argon",
                       "SurfaceGravity": 3.3, "SurfaceTemperature": 179.2, "DistanceFromArrivalLS": 1196.0,
                       "WasDiscovered": True, "WasMapped": False})
        self.db.commit()

    def run_once(self, now=None):
        async def go():
            self.state.maybe_reported(now)
            if self.state.reported_task:
                await self.state.reported_task
        asyncio.run(go())

    def signals(self):
        self.j.handle({"event": "FSSBodySignals", "timestamp": ed_outrider.iso_ts(self.now - 50), "BodyName": BODY["name"], "BodyID": 32,
                       "SystemAddress": SYS, "Signals": [{"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 1}]})
        self.db.commit()
        self.state.apply_own_changes()   # as the tick does after your scans (scan_version moves on)

    def test_asked_once_a_day_where_there_is_life(self):
        self.spansh.session = _HwSession([(200, answer())])
        self.run_once(self.now)
        self.assertEqual(self.spansh.session.calls, [])   # no biological signals known here: nothing to ask
        self.signals()
        before = self.state.scan_version
        self.run_once(self.now + 1)   # the FSS has found life: asked at once
        (method, url, body), = self.spansh.session.calls
        self.assertEqual((method, url), ("POST", ed_outrider.SPANSH_BODY_SEARCH))
        self.assertEqual((body["filters"]["distance"], body["reference_coords"]),
                         ({"min": "0", "max": "1"}, {"x": BODY["system_x"], "y": BODY["system_y"], "z": BODY["system_z"]}))
        self.assertEqual(self.state.scan_version, before + 1)   # Here asks again
        row = next(b for b in self.state.system_detail(SYS)["bodies"] if b["body_id"] == 32)
        self.assertEqual([(x["species"], x["variant"]) for x in row["reported"]], [("Bacterium Vesicula", "Mulberry"), ("Bacterium Vesicula", "Teal")])
        # fresh for a day: not asked again; after it, asked again
        self.run_once(self.now + 2 * ed_outrider.REPORTED_RETRY_S)
        self.assertEqual(len(self.spansh.session.calls), 1)
        self.run_once(self.now + ed_outrider.REPORTED_MAX_AGE + ed_outrider.REPORTED_RETRY_S)
        self.assertEqual(len(self.spansh.session.calls), 2)

    def test_spansh_down_is_tried_again_later(self):
        self.signals()
        self.spansh.session = _HwSession([ed_outrider.ClientError("down")])
        with unittest.mock.patch("sys.stderr"):
            self.run_once(self.now)
        self.assertIsNone(self.db.execute("SELECT 1 FROM spansh_reported").fetchone())
        self.assertEqual(self.state.reported_bodies(SYS), {})
        self.spansh.session = _HwSession([(200, answer())])
        self.run_once(self.now + 1)
        self.assertEqual(self.spansh.session.calls, [])
        self.run_once(self.now + ed_outrider.REPORTED_RETRY_S)
        self.assertEqual(sorted(self.state.reported_bodies(SYS)), [32])


if __name__ == "__main__":
    unittest.main()

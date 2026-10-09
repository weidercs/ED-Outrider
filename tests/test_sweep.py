"""Fixes from the full-codebase bug sweep of 2026-10-09 (each test fails without its fix).

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import asyncio
import inspect
import json
import os
import shutil
import tempfile
import types
import unittest
import unittest.mock

from support import ed_outrider  # also puts the repository root on sys.path


def journals():
    db = ed_outrider.open_db(":memory:")
    return db, ed_outrider.Journals(db)


def state(db, j):
    return ed_outrider.State(db, j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)


class JournalReader(unittest.TestCase):
    """Batch C: the journal reader."""

    def setUp(self):
        self.db, self.j = journals()
        self.addCleanup(self.db.close)

    def test_old_carrier_dock_still_tells_its_services_after_a_reread(self):
        """meta docked is kept through a re-read; an older Docked at your carrier still sets its services (the Nearest
        finder left your own carrier out after a re-read)."""
        lines = [{"timestamp": "2026-10-01T10:00:00Z", "event": "CarrierStats", "CarrierID": 42, "Callsign": "G0X-85Z",
                  "Name": "OUT OF THE BLUE", "FuelLevel": 800, "JumpRangeCurr": 500},
                 {"timestamp": "2026-10-01T11:00:00Z", "event": "Docked", "StationName": "G0X-85Z", "StationType": "FleetCarrier",
                  "MarketID": 42, "StarSystem": "Sol", "SystemAddress": 10477373803,
                  "StationServices": ["dock", "exploration", "vistagenomics"]},
                 {"timestamp": "2026-10-01T12:00:00Z", "event": "Undocked", "StationName": "G0X-85Z", "MarketID": 42},
                 {"timestamp": "2026-10-01T13:00:00Z", "event": "Docked", "StationName": "Abraham Lincoln", "StationType": "Orbis",
                  "MarketID": 128016640, "StarSystem": "Sol", "SystemAddress": 10477373803, "StationServices": ["dock"]}]
        for ev in lines:
            self.j.handle(ev)
        self.db.commit()
        self.db.executescript(ed_outrider.RESET_JOURNAL_DATA)
        j2 = ed_outrider.Journals(self.db)                       # meta docked survives: the Orbis dock
        for ev in lines:
            j2.handle(ev)
        self.assertEqual(j2.carrier.get("services"), ["dock", "exploration", "vistagenomics"])
        self.assertEqual(j2.docked["station"], "Abraham Lincoln")   # the docked state itself is the newest

    def test_journals_read_in_time_order(self):
        """Old-format names (Journal.YYMMDDhhmmss.NN.log) are read before newer files, not after every one of them."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        for name in ("Journal.2024-01-01T100000.01.log", "Journal.220315120000.01.log", "Journal.2026-10-08T173741.01.log"):
            with open(os.path.join(d, name), "w") as f:
                f.write(json.dumps({"timestamp": "2022-01-01T00:00:00Z", "event": "Music"}) + "\n")
        order = []
        with unittest.mock.patch.object(self.j, "read_file", lambda p: order.append(os.path.basename(p))):
            self.j.scan_dir(d)
        self.assertEqual(order, ["Journal.220315120000.01.log", "Journal.2024-01-01T100000.01.log",
                                 "Journal.2026-10-08T173741.01.log"])
        self.assertGreaterEqual(ed_outrider.PARSER_VERSION, 44)   # existing databases are read again in that order

    def test_an_apex_shuttle_is_not_your_ship(self):
        def loadout(ts, ship, ship_id, rng, hull):
            return {"timestamp": ts, "event": "Loadout", "Ship": ship, "ShipID": ship_id, "ShipName": "", "ShipIdent": "",
                    "HullHealth": hull, "UnladenMass": 400.0, "CargoCapacity": 8, "MaxJumpRange": rng,
                    "FuelCapacity": {"Main": 32.0, "Reserve": 0.63}, "Modules": []}
        self.j.handle(loadout("2026-10-01T10:00:00Z", "krait_light", 7, 60.0, 1.0))
        self.j.fuel_hist = [[40.0, 2.0, 150.5, 0], [42.0, 2.2, 148.3, 0]]
        before = (dict(self.j.ship or {}), self.j.jump_range, dict(self.j.hull or {}), list(self.j.fuel_hist))
        self.j.handle(loadout("2026-10-01T11:00:00Z", "adder_taxi", 99, 12.0, 0.5))
        self.assertEqual((dict(self.j.ship or {}), self.j.jump_range, dict(self.j.hull or {}), list(self.j.fuel_hist)), before)

    def test_a_stop_during_the_import_keeps_whole_files_only(self):
        """A SIGTERM during the start-up import drops the part of the file being read (it was committed without its
        offset, and the next start doubled it)."""
        src = inspect.getsource(ed_outrider.run)
        handler = src[src.index("def stop_during_start"):src.index("signal.signal(signal.SIGTERM, stop_during_start)")]
        self.assertIn("db.rollback()", handler)
        self.assertNotIn("db.commit()", handler)


class SpanshStandIns(unittest.TestCase):
    """Batch C: what Spansh knew, apart from stand-ins."""

    def setUp(self):
        self.db, self.j = journals()
        self.addCleanup(self.db.close)
        self.st = state(self.db, self.j)

    def test_an_edsm_stand_in_is_no_verdict(self):
        """Spansh unreachable (EDSM's sphere stood in): no 'partial' stored for the arrival for good."""
        self.st.bases[5] = ("edsm", {"name": "X", "body_count": None, "records": [{"type": "Star", "placeholder": True}],
                                     "edsm": True})
        self.assertIsNone(self.st.spansh_verdict(5))
        self.st.target_verdicts[6] = "spansh unreachable"
        self.assertIsNone(self.st.spansh_verdict(6))
        self.st.bases[7] = ("spansh", {"name": "Y", "body_count": 3, "records": [{"type": "Star"}]})
        self.assertEqual(self.st.spansh_verdict(7), "partial")      # a real Spansh answer still counts

    def test_a_stand_in_still_gets_spanshs_bodies(self):
        """A system past Spansh's sphere (an 'own' stand-in) gets its bodies fetched on demand when opened."""
        self.st.bases[8] = ("own", {"name": "Z", "body_count": None, "records": []})
        self.st.locate = lambda id64: ("Z", 1.0, 2.0, 3.0)
        calls = []

        async def full_records(id64, *a, **k):
            calls.append(id64)
        self.st.spansh = types.SimpleNamespace(cached=lambda i: (None, None), fetched_age=lambda i: None,
                                               full_records=full_records)
        asyncio.run(self.st.ensure_records(8))
        self.assertEqual(calls, [8])
        self.st.bases[9] = ("spansh", {"name": "S", "records": []})
        asyncio.run(self.st.ensure_records(9))
        self.assertEqual(calls, [8])                               # a Spansh entry: the refresh fetches it


if __name__ == "__main__":
    unittest.main()

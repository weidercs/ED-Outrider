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


class ServerAndDevices(unittest.TestCase):
    """Batch D: backups, the start-up checks, shutdown."""

    def test_a_damaged_zip_is_a_message_not_a_traceback(self):
        import zipfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "b.zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("ed_outrider.sqlite", os.urandom(20000) + b"x" * 200000)
        with zipfile.ZipFile(path) as z:
            info = z.infolist()[0]
            start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        with open(path, "r+b") as f:                           # damage the deflate stream itself
            f.seek(start)                                       # 0xff: a reserved block type, zlib.error
            f.write(b"\xff" * 64)
        problem = ed_outrider.check_zip(path)
        self.assertIsInstance(problem, str)

    def test_windows_bind_check_uses_exclusive_use(self):
        """On Windows the start-up check binds with exclusive use, never SO_REUSEADDR (which let it share the port of
        a running Outrider, so a second copy started the import against the live database)."""
        import socket
        opts = []

        class Sock:
            def __init__(self, *a):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def setsockopt(self, level, opt, val):
                opts.append(opt)

            def bind(self, addr):
                pass
        with unittest.mock.patch.object(ed_outrider.os, "name", "nt"), unittest.mock.patch.object(socket, "socket", Sock), \
                unittest.mock.patch.object(socket, "SO_EXCLUSIVEADDRUSE", 0x7FFF, create=True):
            self.assertIsNone(ed_outrider.listen_problem("127.0.0.1", 8025))
        self.assertEqual(opts, [0x7FFF])

    def test_restore_on_an_address_not_this_machines(self):
        """--restore with a [server] host that is no longer this machine's address does not say "stop ED Outrider
        first" (nothing can be running there): it goes on to check the zip."""
        with unittest.mock.patch.object(ed_outrider, "listen_problem",
                                        lambda h, p: f"cannot listen on {h}:{p}: Cannot assign requested address"):
            with self.assertRaises(RuntimeError) as e:
                ed_outrider.restore_backup("/nonexistent/backup.zip", "/nonexistent/db.sqlite", "10.9.9.9", 8025)
        self.assertNotIn("stop ED Outrider first", str(e.exception))
        with unittest.mock.patch.object(ed_outrider, "listen_problem", lambda h, p: "port 8025 is already in use: ..."):
            with self.assertRaises(RuntimeError) as e:
                ed_outrider.restore_backup("/nonexistent/backup.zip", "/nonexistent/db.sqlite", "127.0.0.1", 8025)
        self.assertIn("stop ED Outrider first", str(e.exception))

    def test_shutdown_lets_go_of_primary_fire(self):
        """Stopping Outrider: an auto honk holding Primary Fire lets go now, a press waiting for the keyboard is
        refused, and the honk task is one of the State's tasks (cancelled before the database closes)."""
        import outrider.honk as honk
        h = honk.Honker("KEY_RIGHTCTRL+KEY_K", hold=0.01)
        closed = []
        h.ui = types.SimpleNamespace(close=lambda: closed.append(1))
        h.owners = {"honk", "target"}
        h.lock.acquire()                                      # a hold under way
        h.shutdown()
        self.assertTrue(h.stop.is_set())
        self.assertEqual(h.owners, set())
        h.lock.release()
        h2 = honk.Honker("KEY_RIGHTCTRL+KEY_K", hold=0.01)
        h2.ui = types.SimpleNamespace(close=lambda: closed.append(2))
        h2.shutdown()                                         # idle: closed at once, and stays refusing
        self.assertEqual((closed, h2.ui, h2.stop.is_set(), h2.ready), ([2], None, True, False))
        src = inspect.getsource(ed_outrider.run)
        self.assertIn("state._honk_cancel.set()", src)
        self.assertIn("state.honker.shutdown()", src)
        db, j = journals()
        self.addCleanup(db.close)
        st = state(db, j)
        st.searcher = types.SimpleNamespace(task=None)       # made at start-up in the real server
        st.honk_run_task = "task"
        self.assertIn("task", st.background_tasks())


class VoiceTools(unittest.TestCase):
    """Batch E: the voice's and the AI bridge's tools, the fixed questions."""

    def test_tool_arguments(self):
        import outrider.tools as T
        self.assertEqual(T._int({"days": float("inf")}, "days", 30, 1, 3650), 30)   # 1e999 parses as inf
        got = []

        async def get(path, q=None):
            got.append(q)
            return {"rows": [], "errors": ["Spansh could not be reached (timeout)"]}
        out = asyncio.run(T.call("nearest_dock", {"need": "Vista"}, get, 10))
        self.assertEqual(got[0]["need"], "Vista")                  # not "V,i,s,t,a"
        self.assertEqual(out["errors"], ["Spansh could not be reached (timeout)"])

    def test_spansh_unreachable_is_said(self):
        import outrider.ask as A

        async def get(path, q=None):
            return {"rows": [], "errors": ["Spansh could not be reached (timeout)"]}
        said = asyncio.run(A.fixed_answer("nearest_dock", get, 10, "nearest station"))
        self.assertTrue(said.startswith("Spansh could not be reached"), said)

    def test_nearest_with_fuel_is_a_place_not_the_gauge(self):
        import outrider.ask as A
        ph = A.load_phrases()
        self.assertEqual(A.match("nearest station with fuel", ph), "nearest_dock")
        self.assertEqual(A.match("nearest vista to sell what im carrying", ph), "nearest_dock")
        self.assertEqual(A.match("how much fuel", ph), "fuel")
        self.assertEqual(A.match("what's left here", ph), "whats_left")
        self.assertEqual(A.nearest_query("nearest station with fuel")[0], ["Refuel"])

    def test_mcp_speaks_utf8(self):
        import outrider.mcp as M
        src = inspect.getsource(M.main)
        self.assertIn('stream.reconfigure(encoding="utf-8"', src)
        self.assertLess(src.index("reconfigure"), src.index("serve(sys.stdin"))


class DataModules(unittest.TestCase):
    """Batch F: the data modules."""

    def test_a_dssa_carrier_seen_elsewhere_drops_the_old_systems_id(self):
        import outrider.dock as D
        spansh = [{"kind": "carrier", "callsign": "ABC-123", "name": "C", "system": "Old", "id64": 11, "ls": 5000.0,
                   "x": 0, "y": 0, "z": 0, "seen": 100, "services": set(), "access": "All"}]
        dssa = [{"kind": "carrier", "callsign": "ABC-123", "name": "C", "system": "New", "x": 1, "y": 1, "z": 1, "seen": 200,
                 "services": set(), "until": None, "away": None, "dssa": True}]
        [row] = D.merge(spansh, dssa)
        self.assertEqual((row["system"], row["id64"], row["ls"]), ("New", None, None))

    def test_low_temperature_diamonds_one_name(self):
        odds = ed_outrider.load_mining_odds()
        names = {n for g in odds.values() for n, _ in g["materials"]}
        self.assertNotIn("Low Temp Diamonds", names)
        self.assertIn("Low Temperature Diamonds", names)

    def test_bio_rules_update_that_does_not_parse_is_not_written(self):
        import outrider.bio as B
        failed = []
        got = B._literals("X = 1\ncatalog = {'a': THIN}\n", failed)
        self.assertEqual((got, failed), ({"X": 1}, ["catalog"]))
        src = inspect.getsource(B.update_rules)
        self.assertIn('if "catalog" in failed:', src)               # that file fails the update: the old copy stays

    def test_a_species_missing_from_the_price_list_gets_the_rules_figure(self):
        import outrider.bio as B
        if not B.load_rules():
            self.skipTest("no bio rules file")
        self.assertTrue(B.species_value("Radicoida Unicus"))

    def test_calibrate_skips_an_old_sale(self):
        import outrider.unsold as U
        src = inspect.getsource(U.calibrate)
        self.assertIn("not isinstance(d, dict)", src)

    def test_since_still_counts_later_sales_and_deaths(self):
        import outrider.unsold as U
        src = inspect.getsource(U)
        self.assertNotIn("SELL_ORGANIC and not args.since", src)
        self.assertNotIn("not args.since and not args.ignore_deaths", src)


if __name__ == "__main__":
    unittest.main()

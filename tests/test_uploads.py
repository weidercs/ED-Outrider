"""Unit tests: the uploaders' foundation (outrider/uploads.py; PLAN-edmc-functionality part A): the session, the live
gate through the journal reader, priming a file met part way through, and the outbox. Nothing is sent anywhere.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import json
import os
import shutil
import tempfile
import time
import unittest

from support import ed_outrider  # also puts the repository root on sys.path
import outrider.uploads as U  # noqa: E402
from outrider.core import iso_ts  # noqa: E402


def now_ts(ago=0):
    return iso_ts(time.time() - ago)


def header(ts, version="4.2.0.100", build="r312345/r0 "):
    return {"timestamp": ts, "event": "Fileheader", "part": 1, "language": "English/UK", "Odyssey": True,
            "gameversion": version, "build": build}


def loadgame(ts, cmdr="Briadin", **kw):
    return dict({"timestamp": ts, "event": "LoadGame", "FID": "F123", "Commander": cmdr, "Horizons": True,
                 "Odyssey": True, "Ship": "Mandalay", "ShipID": 7}, **kw)


def location(ts, addr=10, name="Sol", pos=(0.0, 0.0, 0.0), **kw):
    return dict({"timestamp": ts, "event": "Location", "StarSystem": name, "SystemAddress": addr, "StarPos": list(pos)}, **kw)


class SessionTests(unittest.TestCase):

    def test_follows_the_journal(self):
        s = U.Session()
        s.feed(header("2026-10-08T10:00:00Z"), "Journal.2026-10-08T100000.01.log")
        self.assertEqual((s.gameversion, s.gamebuild, s.blocked()), ("4.2.0.100", "r312345/r0 ", "commander"))
        s.feed(loadgame("2026-10-08T10:00:01Z", Horizons=True))
        self.assertEqual((s.cmdr, s.fid, s.horizons, s.odyssey, s.ship_id, s.blocked()), ("Briadin", "F123", True, True, 7, None))
        s.feed(location("2026-10-08T10:00:02Z", Docked=True, MarketID=99, StationName="Abraham Lincoln", Body="Earth", BodyID=3, BodyType="Planet"))
        self.assertEqual((s.addr, s.system, s.pos, s.market_id, s.station, s.body_id), (10, "Sol", [0.0, 0.0, 0.0], 99, "Abraham Lincoln", 3))
        self.assertTrue(s.located(10) and not s.located(11))
        s.feed({"event": "Undocked", "timestamp": "2026-10-08T10:01:00Z"})
        s.feed({"event": "FSDJump", "timestamp": "2026-10-08T10:02:00Z", "StarSystem": "B", "SystemAddress": 11, "StarPos": [1, 2, 3]})
        self.assertEqual((s.addr, s.market_id, s.body), (11, None, None))
        s.feed({"event": "JoinACrew", "timestamp": "2026-10-08T10:03:00Z", "Captain": "Someone"})
        self.assertEqual((s.blocked(), s.addr), ("crew", None))
        s.feed({"event": "QuitACrew", "timestamp": "2026-10-08T10:04:00Z", "Captain": "Someone"})
        self.assertIsNone(s.blocked())

    def test_flags_left_out_and_blocked_sessions(self):
        s = U.Session()
        s.feed(header("2026-10-08T10:00:00Z", version="3.8.0.404"), "Journal.x.log")
        s.feed({"timestamp": "2026-10-08T10:00:01Z", "event": "LoadGame", "Commander": "B", "Horizons": True})
        self.assertEqual((s.horizons, s.odyssey, s.blocked()), (True, None, "legacy"))   # no Odyssey key: left out
        s.feed(header("2026-10-08T11:00:00Z", version="4.0.0.1500 beta"), "Journal.y.log")
        s.feed(loadgame("2026-10-08T11:00:01Z"))
        self.assertEqual(s.blocked(), "beta")
        s.feed(header("2026-10-08T12:00:00Z"), "JournalBeta.z.log")
        s.feed(loadgame("2026-10-08T12:00:01Z"))
        self.assertEqual(s.blocked(), "beta")
        s.feed(header("2026-10-08T13:00:00Z", version=""), "Journal.w.log")
        s.feed(loadgame("2026-10-08T13:00:01Z"))
        self.assertEqual(s.blocked(), "version")

    def test_live_gate(self):
        now = time.time()
        self.assertTrue(U.live_line(iso_ts(now - 10), now))
        self.assertFalse(U.live_line(iso_ts(now - U.MAX_AGE_S - 5), now))   # an old line (a catch-up through NFS...)
        self.assertTrue(U.live_line(iso_ts(now + 60), now))                 # the game PC's clock a minute ahead
        self.assertFalse(U.live_line("not a time", now))


class HubThroughTheReader(unittest.TestCase):
    """The hub sees lines only from the live folders, queues only from the running tail."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "Journal.2026-10-08T100000.01.log")
        echo = lambda ev, session: [("echo/1", {"event": ev["event"], "system": session.system})]
        self.on = True
        self.hub = U.UploadHub(self.db, {"test": echo}, enabled=lambda s: self.on)
        self.j.uploads = self.hub

    def write(self, *events):
        with open(self.path, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def rows(self):
        return [(r["schema"], json.loads(r["message"])["event"]) for r in self.db.execute("SELECT * FROM upload_queue ORDER BY id")]

    def test_catchup_then_live(self):
        self.write(header(now_ts(30)), loadgame(now_ts(29)), location(now_ts(28)))
        self.j.scan_dir(self.dir, upload="catchup")          # the start-up scan: state only
        self.assertEqual(self.rows(), [])
        self.assertEqual((self.hub.session.cmdr, self.hub.session.system), ("Briadin", "Sol"))
        self.write({"timestamp": now_ts(5), "event": "FSDJump", "StarSystem": "B", "SystemAddress": 11, "StarPos": [1, 2, 3]})
        self.j.scan_dir(self.dir, upload="live")
        self.assertEqual(self.rows(), [("echo/1", "FSDJump")])
        r = self.db.execute("SELECT cmdr, gameversion, gamebuild, source FROM upload_queue").fetchone()
        self.assertEqual(tuple(r)[:3], ("Briadin", "4.2.0.100", "r312345/r0 "))
        self.assertTrue(r["source"].startswith("Journal.2026-10-08T100000.01.log:"))

    def test_old_lines_legacy_folders_and_off(self):
        self.write(header(now_ts(3600)), loadgame(now_ts(3599)), location(now_ts(3598)))
        self.j.scan_dir(self.dir, upload="live")                # live, but an hour old: nothing
        self.assertEqual(self.rows(), [])
        self.write({"timestamp": now_ts(1), "event": "Music", "MusicTrack": "Exploration"})
        self.j.scan_dir(self.dir)                               # a legacy folder: the hub never sees it
        self.assertEqual(self.rows(), [])
        self.on = False
        self.write({"timestamp": now_ts(1), "event": "Music", "MusicTrack": "Combat"})
        self.j.scan_dir(self.dir, upload="live")                # uploads off: nothing either
        self.assertEqual(self.rows(), [])

    def test_restart_mid_file_primes_the_session(self):
        self.write(header(now_ts(60)), loadgame(now_ts(59)), location(now_ts(58), addr=42, name="Here"))
        size = os.path.getsize(self.path)
        self.db.execute("INSERT INTO journal_files (path, offset) VALUES (?, ?)", (self.path, size))
        self.j.reload()                                          # Outrider stopped here; a new start
        self.write({"timestamp": now_ts(2), "event": "Scan", "BodyName": "Here 1", "BodyID": 1, "SystemAddress": 42,
                    "StarSystem": "Here", "ScanType": "Detailed"})
        self.j.scan_dir(self.dir, upload="live")
        self.assertEqual(self.rows(), [("echo/1", "Scan")])
        self.assertEqual((self.hub.session.gameversion, self.hub.session.cmdr, self.hub.session.addr), ("4.2.0.100", "Briadin", 42))

    def test_once_per_line_and_rolled_back_with_the_tick(self):
        s = U.Session()
        s.feed(header(now_ts(9)), "J.log")
        s.feed(loadgame(now_ts(8)))
        self.assertTrue(U.enqueue(self.db, "test", "echo/1", "J.log:100", now_ts(5), s, {"a": 1}))
        self.assertFalse(U.enqueue(self.db, "test", "echo/1", "J.log:100", now_ts(5), s, {"a": 1}))   # the same line again
        self.assertTrue(U.enqueue(self.db, "other", "echo/1", "J.log:100", now_ts(5), s, {"a": 1}))   # another service
        self.db.commit()
        U.enqueue(self.db, "test", "echo/1", "J.log:200", now_ts(5), s, {"a": 2})
        self.db.rollback()                                        # a failed tick
        self.assertEqual(self.db.execute("SELECT count(*) FROM upload_queue").fetchone()[0], 2)

    def test_outbox_settle_and_prune(self):
        s = U.Session()
        s.feed(header(now_ts(9)), "J.log")
        s.feed(loadgame(now_ts(8)))
        for i in range(3):
            U.enqueue(self.db, "test", "x/1", f"J.log:{i}", now_ts(5), s, {"i": i})
        now = time.time()
        rows = U.due(self.db, "test", now)
        self.assertEqual([json.loads(r["message"])["i"] for r in rows], [0, 1, 2])
        U.settle(self.db, rows[0]["id"], "sent", "200 OK", now)
        U.settle(self.db, rows[1]["id"], "queued", "503", now, retry_in=60)       # back off
        U.settle(self.db, rows[2]["id"], "dropped", "400 FAIL: Schema Validation", now)
        self.assertEqual([json.loads(r["message"])["i"] for r in U.due(self.db, "test", now)], [])
        self.assertEqual([json.loads(r["message"])["i"] for r in U.due(self.db, "test", now + 61)], [1])
        c = U.counts(self.db, "test")
        self.assertEqual((c["queued"], c["sent_24h"], c["dropped_24h"]), (1, 1, 1))
        U.prune(self.db, now + 8 * 86400)
        self.assertEqual(self.db.execute("SELECT count(*) FROM upload_queue").fetchone()[0], 1)   # the queued one stays

    def test_a_reread_keeps_the_outbox(self):
        self.assertNotIn("upload_queue", ed_outrider.RESET_JOURNAL_DATA)

    def test_a_failed_tick_puts_the_session_back(self):
        self.write(header(now_ts(30)), loadgame(now_ts(29)), location(now_ts(28)))
        self.j.scan_dir(self.dir, upload="catchup")
        cp = self.j.checkpoint()
        self.hub.session.feed({"timestamp": now_ts(5), "event": "FSDJump", "StarSystem": "B", "SystemAddress": 11, "StarPos": [1, 2, 3]})
        self.j.restore(cp)                                       # the tick's lines will be handled again
        self.assertEqual(self.hub.session.system, "Sol")


class Settings(unittest.TestCase):

    def test_config(self):
        self.assertEqual(U.upload_settings({})["uploads"], {"eddn": {"enabled": False, "test": False}, "edsm": {"enabled": False}})
        got = U.upload_settings({"eddn": {"enabled": True, "test": "yes"}, "edsm": {"enabled": True}})["uploads"]
        self.assertEqual(got, {"eddn": {"enabled": True, "test": False}, "edsm": {"enabled": True}})   # a non-bool is the default


class StateSwitches(unittest.TestCase):
    """The config's [eddn]/[edsm] enabled, the page's switch over it, never in --simulate, held on a refused key."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def test_switches(self):
        st = self.state
        self.assertIs(self.j.uploads, st.uploads_hub)
        self.assertEqual((st.upload_on("eddn"), st.upload_on("edsm"), st.upload_on("inara")), (False, False, False))
        st.upload_cfg["eddn"]["enabled"] = True
        self.assertTrue(st.upload_on("eddn"))
        st.set_upload("eddn", False)                            # the page's switch wins over the config
        self.assertFalse(st.upload_on("eddn"))
        st.set_upload("edsm", True)
        self.assertTrue(st.upload_on("edsm"))
        st.upload_report("edsm", {"error": None, "at": 1, "results": [(1, "held", "203 Commander name/API Key not found", None)]})
        self.assertFalse(st.upload_on("edsm"))                   # waiting on the player
        self.assertEqual(st.uploads_summary()["edsm"]["held"], "203 Commander name/API Key not found")
        st.set_upload("edsm", True)                              # switching it on again clears the hold
        self.assertTrue(st.upload_on("edsm"))
        st.simulate = True
        self.assertFalse(st.upload_on("edsm"))

    def test_endpoint(self):
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                out = [(await c.post("/api/uploads", json={"service": "eddn", "on": True})).status]
                for bad in ({"service": "inara", "on": True}, {"service": "eddn", "on": "yes"}, ["eddn"]):
                    out.append((await c.post("/api/uploads", json=bad)).status)
                return out
        self.assertEqual(asyncio.run(go()), [200, 400, 400, 400])
        self.assertTrue(self.state.upload_on("eddn"))


class Loop(unittest.TestCase):
    """upload_loop: each row settled as the sender says; a network failure waits (at least a minute, growing)."""

    def test_rounds(self):
        import asyncio
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        s = U.Session()
        s.feed(header(now_ts(9)), "J.log")
        s.feed(loadgame(now_ts(8)))
        for i in range(3):
            U.enqueue(db, "eddn", "x/1", f"J.log:{i}", now_ts(5), s, {"i": i})
        db.commit()
        clock = [1000.0]
        calls, reports = [], []

        when = []

        async def send(rows):
            when.append(clock[0])
            calls.append([json.loads(r["message"])["i"] for r in rows])
            if len(calls) == 1:
                raise ConnectionError("unreachable")
            return [(rows[0]["id"], "sent", "200 OK", None), (rows[1]["id"], "dropped", "400 FAIL", None),
                    (rows[2]["id"], "queued", "503", 60)][:len(rows)]

        async def sleep(secs):
            clock[0] += max(secs, 1)
            if clock[0] > 1000 + 400:
                raise asyncio.CancelledError

        async def go():
            try:
                await U.upload_loop("eddn", db, send, lambda s: True, clock=lambda: clock[0], sleep=sleep,
                                    report=lambda s, o: reports.append(o["error"]))
            except asyncio.CancelledError:
                pass
        asyncio.run(go())
        self.assertEqual(calls[0], [0, 1, 2])                    # the first round: unreachable
        self.assertEqual(calls[1], [0, 1, 2])                    # again, a minute later (not at once)
        self.assertGreaterEqual(when[1] - when[0], 60)
        self.assertEqual(reports[0], "ConnectionError: unreachable")
        states = {json.loads(r["message"])["i"]: r["state"] for r in db.execute("SELECT * FROM upload_queue")}
        self.assertEqual(states, {0: "sent", 1: "dropped", 2: "queued"})

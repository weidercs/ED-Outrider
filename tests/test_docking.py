"""#3 (Kurbo26, GitHub discussion #3): docking help. The pad a station gives you (said every time, big on Now and in the
overlay's Target panel) and why one refused, only when that is not obvious. Live only: a re-read says and keeps nothing."""
import time
import types
import unittest

from support import ed_outrider  # also puts the repository root on sys.path

import outrider.overlay  # noqa: E402


def ts(offset=0.0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


class Docking(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def ev(self, name, offset=0.0, **kw):
        self.j.handle(dict({"timestamp": ts(offset), "event": name}, **kw))

    def moments(self):
        return [(m["what"], m.get("pad"), m.get("words")) for m in self.j.moments if m["kind"] == "docking"]

    def test_the_events_are_read(self):
        wanted = b"".join(ed_outrider.WANTED)
        for name in ed_outrider.DOCKING_EVENTS:
            self.assertIn(f'"event":"{name}"'.encode(), wanted)

    def test_granted_then_docked(self):
        self.ev("DockingGranted", -5, LandingPad=34, StationName="Jameson Memorial", StationType="Orbis", MarketID=128666762)
        d = self.state.docking_summary()
        self.assertEqual((d["pad"], d["station"], d["type"]), (34, "Jameson Memorial", "Orbis"))
        self.assertEqual(self.state.payload()["docking"]["pad"], 34)
        self.assertEqual(self.moments(), [("granted", 34, None)])
        self.ev("Docked", -1, StationName="Jameson Memorial", StationType="Orbis", MarketID=128666762)
        self.assertIsNone(self.state.docking_summary())
        self.assertEqual(self.moments()[-1][0], "clear")

    def test_a_carrier_pad_too_and_the_end_of_it(self):
        """Every grant is said, your own carrier's included (the author); a cancel, a timeout or leaving ends it."""
        for end in ("DockingCancelled", "DockingTimeout", "SupercruiseEntry", "FSDJump"):
            self.ev("DockingGranted", -5, LandingPad=7, StationName="G0X-85Z", StationType="FleetCarrier")
            self.assertEqual(self.state.docking_summary()["pad"], 7)
            self.ev(end, -1, StationName="G0X-85Z")
            self.assertIsNone(self.state.docking_summary(), end)
        self.assertEqual([m[0] for m in self.moments()], ["granted", "clear"] * 4)

    def test_denied_only_when_not_obvious(self):
        self.ev("DockingDenied", -3, Reason="NoSpace", StationName="Jameson Memorial", StationType="Orbis")
        d = self.state.docking_summary()
        self.assertEqual((d["denied"], d["words"]), ("NoSpace", "no pad free for your ship: try again shortly"))
        self.assertEqual(self.moments(), [("denied", None, "no pad free for your ship: try again shortly")])
        # too far: you can see it, the game says so: nothing said, the refusal before it cleared
        self.ev("DockingDenied", -2, Reason="Distance", StationName="Jameson Memorial")
        self.assertIsNone(self.state.docking_summary())
        self.assertEqual([m[0] for m in self.moments()], ["denied", "clear"])
        for reason in ("TooLarge", "RestrictedAccess", "Hostile", "Offences", "ActiveFighter"):
            self.assertIn(reason, ed_outrider.DENIED_WORDS)

    def test_how_long_it_shows(self):
        self.ev("DockingDenied", -3, Reason="TooLarge", StationName="Outpost")
        now = time.time()
        self.assertIsNotNone(self.state.docking_summary(now))
        self.assertIsNone(self.state.docking_summary(now + ed_outrider.DOCK_DENIED_KEEP_S + 5))
        self.ev("DockingGranted", -2, LandingPad=2, StationName="Outpost")
        self.assertIsNotNone(self.state.docking_summary(now + ed_outrider.DOCK_DENIED_KEEP_S + 5))
        self.assertIsNone(self.state.docking_summary(now + ed_outrider.DOCK_GRANT_KEEP_S + 5))
        self.j.status_json = {"flags": ed_outrider.FLAG_DOCKED, "live": True}   # docked: gone whatever the journal said
        self.assertIsNone(self.state.docking_summary(now))

    def test_old_lines_say_and_keep_nothing(self):
        """A re-read, a late legacy folder: no pad said, nothing kept."""
        self.ev("DockingGranted", -86400, LandingPad=12, StationName="Old Station")
        self.ev("DockingDenied", -86000, Reason="NoSpace", StationName="Old Station")
        self.assertIsNone(self.state.docking_summary())
        self.assertEqual(self.moments(), [])
        self.assertIsNone(ed_outrider.meta_get(self.db, "docking"))

    def test_live_only(self):
        self.assertNotIn("docking", ed_outrider.RESET_JOURNAL_DATA)   # a re-read would drop a grant in progress

    def test_the_overlay_target_panel(self):
        pal = outrider.overlay.palette("default")
        p = outrider.overlay.pad_panel({"pad": 34, "station": "Jameson Memorial"}, pal)
        texts = [r[0] for it in p["items"] if it["t"] == "runs" for r in it["runs"]]
        self.assertEqual(p["id"], "body")   # the Target panel: its place, size, its switch and hide-when-docked
        self.assertIn("PAD 34", texts)
        big = next(it for it in p["items"] if it["t"] == "runs" and it["runs"][0][0] == "PAD 34")
        self.assertEqual((big["runs"][0][2], big.get("align")), ("huge", "center"))
        self.assertGreater(outrider.overlay.FONT_PX["huge"], outrider.overlay.FONT_PX["large"] * 2)
        self.assertTrue(any("Jameson Memorial" in t for t in texts))
        no = outrider.overlay.pad_panel({"denied": "NoSpace", "words": "no pad free for your ship: try again shortly",
                                         "station": "Jameson Memorial"}, pal)
        words = " ".join(" ".join(r[0] for it in no["items"] if it["t"] == "runs" for r in it["runs"]).split())
        self.assertIn("Docking denied", words)
        self.assertIn("no pad free", words)
        self.assertIn("try again shortly", words)   # wrapped, never cut with …
        self.assertNotIn("…", words)
        for size in ("small", "normal", "large"):   # the longest reason wraps at every text size
            long = outrider.overlay.pad_panel({"denied": "RestrictedAccess", "station": "X",
                                               "words": ed_outrider.DENIED_WORDS["RestrictedAccess"]}, pal, size)
            said = " ".join(r[0] for it in long["items"] if it["t"] == "runs" for r in it["runs"])
            self.assertNotIn("…", said, size)
        self.assertIsNone(outrider.overlay.pad_panel(None, pal))

    def test_the_target_panel_shows_the_pad_while_docking(self):
        """overlay_target_panel: the pad in place of the target while a grant holds, never over the galaxy map."""
        self.j.pos = {"id64": 1, "name": "Shinrarta Dezhra", "x": 0, "y": 0, "z": 0, "ts": ts(-60)}
        self.ev("DockingGranted", -5, LandingPad=34, StationName="Jameson Memorial")
        pal, now = outrider.overlay.palette("default"), time.time()
        p = self.state.overlay_target_panel({}, self.j.pos, now, pal, "normal", galaxy=False)
        self.assertIn("PAD 34", [r[0] for it in p["items"] if it["t"] == "runs" for r in it["runs"]])
        self.assertIsNone(self.state.overlay_target_panel({}, self.j.pos, now, pal, "normal", galaxy=True))   # no FSD target


if __name__ == "__main__":
    unittest.main()

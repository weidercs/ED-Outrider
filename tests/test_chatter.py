"""Space chatter (#15, the author 2026-10-16): where you are for it and what keeps it quiet (outrider/chatter.py), its
keys and topics, the settings in meta chatter (POST /api/voice/chatter) and the payload's chatter. The page talks
(tests/page_smoke.js)."""
import asyncio
import types
import unittest

from support import ed_outrider  # also puts the repository root on sys.path

import outrider.chatter as C  # noqa: E402
import outrider.speech as S  # noqa: E402

SC = C.F_SUPERCRUISE | C.F_IN_MAIN_SHIP


class Where(unittest.TestCase):
    def test_places(self):
        self.assertEqual(C.where(SC), ("space", None))
        self.assertEqual(C.where(0, C.F2_ON_FOOT | C.F2_ON_FOOT_ON_PLANET), ("planet", None))
        self.assertEqual(C.where(C.F_IN_SRV | C.F_HAS_LAT_LONG), ("planet", None))
        for flags, flags2 in ((C.F_IN_MAIN_SHIP, 0), (C.F_DOCKED | C.F_IN_MAIN_SHIP, 0), (C.F_LANDED | C.F_IN_MAIN_SHIP, 0),
                              (0, C.F2_ON_FOOT | C.F2_ON_FOOT_IN_STATION), (SC, C.F2_IN_TAXI), (SC, C.F2_IN_MULTICREW),
                              # a planetary port's hangar and concourse set on-foot-on-planet too: docked, not the surface
                              (0, C.F2_ON_FOOT | C.F2_ON_FOOT_ON_PLANET | C.F2_ON_FOOT_IN_HANGAR),
                              (0, C.F2_ON_FOOT | C.F2_ON_FOOT_ON_PLANET | C.F2_ON_FOOT_SOCIAL_SPACE),
                              (0, 0), (None, None)):
            self.assertEqual(C.where(flags, flags2), (None, None), (flags, flags2))

    def test_what_keeps_it_quiet(self):
        """Danger, heat, low fuel, the FSD, the suit, a screen the game has open; never the data you carry."""
        cases = {C.F_IN_DANGER: "danger", C.F_INTERDICTED: "danger", C.F_OVERHEATING: "heat", C.F_LOW_FUEL: "low fuel",
                 C.F_FSD_CHARGING: "the FSD", C.F_FSD_JUMP: "the FSD"}
        for bit, why in cases.items():
            self.assertEqual(C.where(SC | bit), ("space", why), why)
        foot = C.F2_ON_FOOT | C.F2_ON_FOOT_ON_PLANET
        for bit in (C.F2_LOW_OXYGEN, C.F2_LOW_HEALTH):
            self.assertEqual(C.where(0, foot | bit), ("planet", "your suit"))
        for bit in (C.F2_VERY_COLD, C.F2_VERY_HOT):   # common on the worlds you sample: the temperature alone never
            self.assertEqual(C.where(0, foot | bit), ("planet", None))
        self.assertEqual(C.where(SC, C.F2_HYPERDRIVE_CHARGING), ("space", "the FSD"))
        for gui, words in C.GUI_BUSY.items():
            self.assertEqual(C.where(SC, 0, gui), ("space", words))
        self.assertEqual(C.where(SC, 0, 0), ("space", None))   # the cockpit


class Keys(unittest.TestCase):
    def test_keys_and_topics(self):
        """Every topic's ask and answer is a speech key with {to}; the monologues have their context; the topics name
        real stations; the page gets them with the lines."""
        for tid, kind, ask, answer in C.TOPICS:
            self.assertIn(kind, (C.STATION, C.PERSONAL))
            self.assertTrue(ask and answer and set(ask) | set(answer) <= set(S.CREW_IDS), tid)
            for w in ("ask", "answer"):
                key = f"chat_{tid}_{w}"
                self.assertIn(key, S.KEYS)
                self.assertIn("to", S.fills(key))
                self.assertIn(key, S.SAMPLES)
        self.assertLessEqual({"system", "minutes", "jumps", "firsts"}, S.fills("chatter_space"))
        self.assertLessEqual({"body", "ship_dist"}, S.fills("chatter_planet_orbit") & S.fills("chatter_planet_landed"))
        self.assertEqual(set(S.CHATTER_KEYS), set(C.KEYS))
        stations = sum(1 for t in C.TOPICS if t[1] == C.STATION)
        self.assertGreater(stations, 2 * sum(1 for t in C.TOPICS if t[1] == C.PERSONAL) - 1)   # mostly stations
        info = C.page_info()
        self.assertEqual([t["id"] for t in info["topics"]], [t[0] for t in C.TOPICS])
        self.assertEqual((info["levels"], info["written"]), (C.LEVELS, C.LINES_WRITTEN))
        self.assertTrue(all(3 <= m <= 30 for m in C.LEVELS.values()))


class Settings(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def test_settings(self):
        """Off by default; on, a chattiness, a station left out or back in; anything else refused; kept by a re-read."""
        st = self.state
        self.assertEqual(st.chatter_raw(), {"on": False, "level": "normal", "off": []})
        for body in ({"on": True}, {"level": "chatty"}, {"role": "tactical", "takes_part": False},
                     {"role": "comms", "takes_part": False}, {"role": "tactical", "takes_part": True}):
            self.assertEqual(st.set_chatter(body)[1], 200, body)
        self.assertEqual(st.chatter_raw(), {"on": True, "level": "chatty", "off": ["comms"]})
        for bad in ({}, None, {"on": "yes"}, {"level": "loud"}, {"role": "chef", "takes_part": True},
                    {"role": "comms"}, {"volume": 3}):
            self.assertEqual(st.set_chatter(bad)[1], 400, bad)
        self.db.executescript(ed_outrider.RESET_JOURNAL_DATA)
        self.assertEqual(st.chatter_raw()["level"], "chatty")
        self.assertEqual(st.payload()["chatter"]["on"], True)

    def test_where_and_since(self):
        """chatter_watch follows Status.json: since is when you entered supercruise (a blocker coming and going keeps
        it), None out of it; it says when anything changed, so the payload moves."""
        st = self.state
        self.j.status_json = {"live": True, "flags": SC, "flags2": 0, "gui_focus": 0}
        self.assertTrue(st.chatter_watch(now=100))
        self.assertEqual({k: st.chatter_summary()[k] for k in ("where", "why_not", "since")}, {"where": "space", "why_not": None, "since": 100})
        self.assertFalse(st.chatter_watch(now=110))
        self.j.status_json = dict(self.j.status_json, gui_focus=9)
        self.assertTrue(st.chatter_watch(now=120))
        self.assertEqual((st.chatter_summary()["why_not"], st.chatter_summary()["since"]), ("the FSS", 100))
        self.j.status_json = dict(self.j.status_json, flags=C.F_IN_MAIN_SHIP, gui_focus=0)
        self.assertTrue(st.chatter_watch(now=130))
        self.assertEqual((st.chatter_summary()["where"], st.chatter_summary()["since"]), (None, None))
        self.j.status_json = dict(self.j.status_json, live=False, flags=SC)
        self.assertFalse(st.chatter_watch(now=140))   # an old Status.json (the game not running): nowhere

    def test_route(self):
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                r1 = await c.post("/api/voice/chatter", json={"on": True})
                r2 = await c.post("/api/voice/chatter", json={"level": "nope"})
                r3 = await c.post("/api/voice/chatter", data="not json")
                return r1.status, (await r1.json())["chatter"]["on"], r2.status, r3.status
        self.assertEqual(asyncio.run(go()), (200, True, 400, 400))


if __name__ == "__main__":
    unittest.main()

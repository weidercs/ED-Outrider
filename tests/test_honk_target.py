"""Auto honk's "then target the next route system" (this fork): after an auto honk the journal confirms, the next
system of the route you follow is targeted a set number of seconds later, when switched on. Nothing here presses a
key: the honker is a fake and the target run is recorded, not started."""
import argparse
import asyncio
import contextlib
import datetime as dt
import io
import tomllib
import types
import unittest
import unittest.mock

from support import ed_outrider

ARGS = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)


def now(s=0):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Settings(unittest.TestCase):
    def settings(self, cfg):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            return ed_outrider.settings_from(cfg, ARGS, None, ([], [])), err.getvalue()

    def test_config(self):
        st, _ = self.settings({})
        self.assertEqual((st["autohonk"]["target_next"], st["autohonk"]["target_delay"]), (False, 3.0))   # off by default
        st, _ = self.settings({"autohonk": {"target_next": True, "target_delay": 7.5}})
        self.assertEqual((st["autohonk"]["target_next"], st["autohonk"]["target_delay"]), (True, 7.5))
        back = tomllib.loads(ed_outrider.config_text(st))["autohonk"]
        self.assertEqual((back["target_next"], back["target_delay"]), (True, 7.5))
        for given, want in ((500, 60.0), (-4, 0.0)):
            st, _ = self.settings({"autohonk": {"target_delay": given}})
            self.assertEqual(st["autohonk"]["target_delay"], want)
        st, err = self.settings({"autohonk": {"target_next": "yes", "target_delay": "soon"}})
        self.assertEqual((st["autohonk"]["target_next"], st["autohonk"]["target_delay"]), (False, 3.0))
        self.assertIn("target_next", err)


class Target(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.runs = []
        self.answer = ({"system": "Next Stop", "in": 4.0, "seq": 1, "dry_run": False, "kind": "next"}, 200)

        def start(kind="test", countdown=None, aim=None):
            self.runs.append((kind, countdown, aim))
            return self.answer
        self.state.start_autotarget_run = start
        self.j.handle({"event": "FSDJump", "timestamp": now(), "StarSystem": "S1", "SystemAddress": 1, "StarPos": [0, 0, 0]})
        self.arrival = self.j.jump_arrival

    def test_only_when_switched_on(self):
        self.assertIsNone(self.state.honk_then_target(self.arrival))
        self.assertEqual(self.runs, [])                                        # off by default: nothing
        self.state.autohonk.update(target_next=True, target_delay=4.0)
        out = self.state.honk_then_target(self.arrival)
        self.assertEqual((self.runs, out["system"]), ([("next", 4.0, None)], "Next Stop"))   # Target next, 4 s from now
        self.assertEqual((self.state.honk_target_pending, self.state.honk_target_note), (True, None))
        self.j.handle({"event": "FSDJump", "timestamp": now(), "StarSystem": "S2", "SystemAddress": 2, "StarPos": [9, 0, 0]})
        self.assertIsNone(self.state.honk_then_target(self.arrival))           # you jumped on meanwhile: not for the old system
        self.assertEqual(len(self.runs), 1)

    def test_no_route_says_nothing_and_a_refusal_is_kept(self):
        self.state.autohonk.update(target_next=True)
        self.answer = ({"error": "no route is plotted"}, 400)
        self.assertIsNone(self.state.honk_then_target(self.arrival))
        self.assertEqual((self.state.honk_target_note, self.state.honk_target_pending), (None, False))   # most honks: no route
        self.state.highway_summary = lambda: {"id": "r1", "next": {"name": "Next Stop"}}
        self.answer = ({"error": "no keyboard binding for Galaxy map (GalaxyMapOpen)"}, 400)
        self.state.honk_then_target(self.arrival)
        self.assertEqual(self.state.honk_target_note, "no keyboard binding for Galaxy map (GalaxyMapOpen)")
        self.assertEqual(self.state.autohonk_info()["target_note"], "no keyboard binding for Galaxy map (GalaxyMapOpen)")
        self.answer = ({"system": "Next Stop", "in": 3.0, "seq": 2, "dry_run": False, "kind": "next"}, 200)
        self.state.honk_then_target(self.arrival)
        self.assertIsNone(self.state.honk_target_note)                          # it worked: the old reason goes

    def test_the_switch_is_remembered_and_stops_a_run(self):
        self.state.set_honk_target(True, 12)
        info = self.state.autohonk_info()
        self.assertEqual((info["target_next"], info["target_delay"]), (True, 12.0))
        self.assertEqual(ed_outrider.meta_get(self.db, "autohonk_target"), {"enabled": True, "delay": 12.0})
        self.state.set_honk_target(delay=999)
        self.assertEqual(self.state.autohonk["target_delay"], 60.0)             # at most a minute
        self.state.set_honk_target(delay=-1)
        self.assertEqual((self.state.autohonk["target_delay"], self.state.autohonk["target_next"]), (0.0, True))
        stopped = []
        self.state.cancel_autotarget = lambda route=False: stopped.append(route)
        self.state.honk_then_target(self.arrival)
        self.state.set_honk_target(False)
        self.assertEqual((stopped, self.state.autohonk["target_next"]), (["highway"], False))   # the run it started stops

    def test_after_a_confirmed_honk_only(self):
        """The whole auto honk: a press the journal answers with a discovery scan is followed by the target run; a
        press nothing follows is not."""
        j = self.j

        class FakeHonker:
            ready, available, status = True, True, "ready"

            def __init__(self, answers):
                self.answers = answers

            def press(self, check=None, cancel=None):
                if self.answers:
                    j.last_honk = {"id64": j.jump_arrival["id64"], "ts": now(), "bodies": 5, "progress": 0.2}
                return True

        def arrive(id64, answers):
            self.state.honker = FakeHonker(answers)
            self.state.autohonk = dict(ed_outrider.AUTOHONK, enabled=True, delay=0, target_next=True, target_delay=2.5)
            self.state.honk_confirm = 0.3
            j.handle({"event": "FSDJump", "timestamp": now(), "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [id64, 0, 0]})

            async def go():
                self.state.maybe_honk()
                await asyncio.sleep(0.6)
            asyncio.run(go())
        arrive(31, answers=True)
        self.assertEqual(self.runs, [("next", 2.5, None)])
        arrive(32, answers=False)
        self.assertEqual(len(self.runs), 1)                                     # no discovery scan: no targeting

    def test_endpoint(self):
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                post = lambda body: c.post("/api/autohonk", json=body)
                ok = await (await post({"target_next": True, "target_delay": 5})).json()
                only_delay = await (await post({"target_delay": 8.5})).json()
                bad = [(await post(b)).status for b in ({"target_next": "yes"}, {"target_delay": 61}, {"target_delay": -1},
                                                        {"target_delay": True}, {"target_delay": "3"}, {})]
                both = await (await post({"enabled": False, "target_next": False})).json()
                return ok, only_delay, bad, both
        ok, only_delay, bad, both = asyncio.run(go())
        self.assertEqual((ok["target_next"], ok["target_delay"]), (True, 5))
        self.assertEqual((only_delay["target_next"], only_delay["target_delay"]), (True, 8.5))
        self.assertEqual(bad, [400] * 6)
        self.assertEqual((both["target_next"], both["wanted"]), (False, False))


if __name__ == "__main__":
    unittest.main()

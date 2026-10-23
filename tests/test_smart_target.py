"""Smart targeting: on a route plotted here, the next system is targeted after the supercharge where the
route expects one (as "Auto-target after a supercharge" would), and everywhere else after auto honk's honk (as "Then
target the next route system" would), with neither switch ticked. Nothing here presses a key: the runs are recorded."""
import argparse
import asyncio
import contextlib
import io
import time
import tomllib
import types
import unittest

from support import HWY_EXACT, ed_outrider, hwy_jump, hwy_plot_exact, hwy_ts

ARGS = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)


class Settings(unittest.TestCase):
    def settings(self, cfg):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            return ed_outrider.settings_from(cfg, ARGS, None, ([], [])), err.getvalue()

    def test_config(self):
        st, _ = self.settings({})
        self.assertIs(st["highway"]["smart_target"], False)                     # off by default
        st, _ = self.settings({"highway": {"smart_target": True}})
        self.assertIs(st["highway"]["smart_target"], True)
        self.assertIs(tomllib.loads(ed_outrider.config_text(st))["highway"]["smart_target"], True)
        st, err = self.settings({"highway": {"smart_target": "yes"}})
        self.assertIs(st["highway"]["smart_target"], False)
        self.assertIn("smart_target", err)


class Smart(unittest.TestCase):
    EXACT = HWY_EXACT
    jump = hwy_jump
    ts = hwy_ts

    def setUp(self):
        self.now = time.time()
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.state.highway_cfg.update(autotarget=False, smart_target=True)
        self.runs, self.auto = [], []

        def start(kind="test", countdown=None, aim=None):   # the honk's Target next run
            self.runs.append((kind, countdown))
            return {"system": "x", "in": countdown, "seq": 1, "dry_run": False, "kind": kind}, 200
        self.state.start_autotarget_run = start

        async def run(tgt, test=None, cancel=None):         # the supercharge's run
            self.auto.append(tgt["name"])
        self.state._autotarget = run
        hwy_plot_exact(self)   # at Start (a neutron row): Start, Neu A, Bridge B, Scoop C, Neu D, End

    def at(self, id64, name, x, s=1):
        self.jump(s, id64, name, x)
        return self.j.jump_arrival

    def supercharge(self, s=2):
        """A live supercharge here, and whether maybe_autotarget started a run for it."""
        async def go():
            self.j.handle({"event": "JetConeBoost", "timestamp": self.ts(s), "BoostValue": 4})
            started = self.state.maybe_autotarget()
            if started:
                await self.state.autotarget_task
            return started
        return asyncio.run(go())

    def test_supercharge_expected_by_the_route_row(self):
        self.assertTrue(self.state.supercharge_expected())                      # Start: has_neutron
        self.at(101, "Neu A", 50)
        self.assertTrue(self.state.supercharge_expected())
        self.at(102, "Bridge B", 80)
        self.assertFalse(self.state.supercharge_expected())                     # a plain jump from here
        self.at(999, "Elsewhere", 85)
        self.assertFalse(self.state.supercharge_expected())                     # off the route
        self.state.highway_clear()
        self.assertFalse(self.state.supercharge_expected())                     # no Spansh route: the game's own never counts

    def test_no_neutron_boost_plot_expects_none(self):
        hw = ed_outrider.meta_get(self.db, "highway")
        hw["options"] = dict(hw.get("options") or {}, no_neutrons=True)
        ed_outrider.meta_set(self.db, "highway", hw)
        self.at(101, "Neu A", 50)
        self.assertFalse(self.state.supercharge_expected())

    def test_neutron_row_targets_after_the_supercharge_not_the_honk(self):
        self.state.autohonk["target_next"] = True                               # overridden: ticked or not
        a = self.at(101, "Neu A", 50)
        self.assertIsNone(self.state.honk_then_target(a))
        self.assertEqual(self.runs, [])                                         # the honk leaves it to the supercharge
        self.assertTrue(self.supercharge())                                     # with "after a supercharge" unticked
        self.assertEqual(self.auto, ["Bridge B"])

    def test_plain_row_targets_after_the_honk_not_a_supercharge(self):
        self.state.autohonk.update(target_next=False, target_delay=2.5)
        self.state.highway_cfg["autotarget"] = True                             # overridden: ticked or not
        a = self.at(102, "Bridge B", 80)
        self.state.honk_then_target(a)
        self.assertEqual(self.runs, [("next", 2.5)])                            # "then target" unticked: its seconds
        self.assertFalse(self.supercharge())                                    # a white dwarf boost here: not Smart's
        self.assertEqual(self.auto, [])

    def test_off_means_the_old_switches_alone(self):
        self.state.highway_cfg["smart_target"] = False
        a = self.at(102, "Bridge B", 80)
        self.assertIsNone(self.state.honk_then_target(a))
        self.at(103, "Scoop C", 100)
        a = self.at(104, "Neu D", 150)
        self.assertFalse(self.supercharge())
        self.assertEqual((self.runs, self.auto), ([], []))
        self.state.autohonk["target_next"] = True                               # the honk's own switch still works as before,
        self.state.honk_then_target(a)                                          # neutron row or not
        self.assertEqual(len(self.runs), 1)

    def test_the_automatic_run_is_not_stale_with_smart_alone(self):
        tgt = {"name": "Bridge B", "route": ed_outrider.meta_get(self.db, "highway")["id"]}
        self.assertIsNone(self.state._autotarget_stale(tgt, None, None))
        self.state.highway_cfg["smart_target"] = False
        self.assertEqual(self.state._autotarget_stale(tgt, None, None), "switched off")

    def test_switch_remembered_and_stops_a_run(self):
        stopped = []
        self.state.cancel_autotarget = lambda route=False: stopped.append(route)
        self.state.set_autotarget(smart=False)
        self.assertEqual(ed_outrider.meta_get(self.db, "autotarget"), {"enabled": False, "delay": 5.0, "smart": False})
        self.assertEqual(stopped, [False])                                      # a pending supercharge run stops
        self.state.set_autotarget(smart=True)
        info = self.state.autotarget_info()
        self.assertEqual((info["smart"], info["smart_note"]), (True, "auto honk is off: only after a supercharge"))
        self.state.autohonk["enabled"] = True
        self.assertIsNone(self.state.autotarget_info()["smart_note"])

    def test_endpoint(self):
        from aiohttp.test_utils import TestClient, TestServer
        self.state.game_pc = True

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                post = lambda body: c.post("/api/highway/autotarget", json=body)
                off = await (await post({"smart": False})).json()
                bad = [(await post(b)).status for b in ({"smart": "yes"}, {"smart": 1})]
                on = await (await post({"smart": True})).json()
                return off, bad, on
        off, bad, on = asyncio.run(go())
        self.assertEqual((off["smart"], on["smart"], bad), (False, True, [400, 400]))


if __name__ == "__main__":
    unittest.main()

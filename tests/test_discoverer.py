"""Discoverer names in the route lists (this fork): EDSM's first discoverer of each listed system somebody has been
to, asked in the background, a few at a time. No request leaves the tests: the session and Spansh are fakes."""
import asyncio
import contextlib
import io
import types
import unittest
import unittest.mock

from support import ed_outrider


class FakeResponse:
    def __init__(self, doc):
        self.doc = doc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    async def json(self):
        return self.doc


class Edsm(unittest.TestCase):
    def ask(self, doc):
        asked = []

        def get(url, params=None):
            asked.append((url, params))
            return FakeResponse(doc)
        sp = ed_outrider.Spansh.__new__(ed_outrider.Spansh)
        sp.session, sp.sem_fast = types.SimpleNamespace(get=get), asyncio.Semaphore(1)
        return asyncio.run(sp.edsm_discoverer("Test Sector AB-C d1-2")), asked

    def test_who_found_it(self):
        body = lambda name, who, date, main=False: {"name": name, "isMainStar": main, "discovery": {"commander": who, "date": date}}
        got, asked = self.ask({"name": "Test Sector AB-C d1-2", "bodies": [
            body("2", "Late Comer", "2020-01-01 00:00:00"), body("A", "First In", "2021-05-05 00:00:00", main=True), {"name": "3"}, "junk"]})
        self.assertEqual(got, "First In")                                       # the main star's, whenever the planets were found
        self.assertEqual(asked, [(ed_outrider.EDSM_BODIES, {"systemName": "Test Sector AB-C d1-2"})])
        self.assertEqual(self.ask({"name": "X", "bodies": [body("2", "Second", "2021-01-01"), body("1", " Early ", "2019-01-01")]})[0], "Early")
        self.assertEqual(self.ask({"name": "X", "bodies": [{"name": "A", "discovery": None}, {"name": "B", "discovery": {"commander": ""}}]})[0], "")
        self.assertIsNone(self.ask({})[0])                                      # EDSM does not know the system
        self.assertIsNone(self.ask([])[0])


class RouteList(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.state = ed_outrider.State(self.db, ed_outrider.Journals(self.db), types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        j = self.state.journals
        j.handle({"event": "FSDJump", "timestamp": ed_outrider.iso_ts(1000), "StarSystem": "Start", "SystemAddress": 1, "StarPos": [0, 0, 0]})
        row = lambda i, name: {"system": name, "id64": i, "x": 50.0 * (i - 1), "y": 0.0, "z": 0.0, "distance": 50.0 if i > 1 else 0.0,
                               "fuel_used": None, "fuel_left": None, "neutron": 0, "refuel": 0, "jumps": 1 if i > 1 else 0,
                               "remaining": 50.0 * (5 - i)}
        self.state.highway_store([row(1, "Start"), row(2, "Known B"), row(3, "Empty C"), row(4, "Known D"), row(5, "Unasked E")],
                                 {"plotter": "exact", "options": {}, "ship": None})
        self.state.route_known.update({2: "explored", 3: "no bodies", 4: "partial"})   # what Spansh said; 5: not looked up yet
        self.asked = []
        self.names = {"Start": "You", "Known B": "First In", "Known D": None}

        async def edsm_discoverer(name):
            self.asked.append(name)
            if isinstance(self.names[name], Exception):
                raise self.names[name]
            return self.names[name]
        async def lookup(id64, interactive=True):   # Spansh's own check of a system not looked up yet: nothing known
            return None
        self.state.spansh = types.SimpleNamespace(cached=lambda i: (None, None), session=object(), edsm_discoverer=edsm_discoverer,
                                                  lookup=lookup)

    def names_shown(self):
        r = self.state.highway_view()["route"]
        return [x["discoverer"] for x in r["done"] + r["ahead"]]

    def test_asked_for_systems_somebody_has_been_to(self):
        async def go():
            self.state.highway_view()
            off = self.state.route_discoverer_task          # the lookups are not switched on: nobody is asked
            self.state.route_known_on = True
            v0 = self.state.highway_summary()["known_v"]
            self.state.highway_view()
            task = self.state.route_discoverer_task
            self.state.highway_view()                        # asked again while it runs: the same task
            same = self.state.route_discoverer_task is task
            await task
            self.state.highway_view()
            return off, same, v0, self.state.route_discoverer_task is task
        with unittest.mock.patch.object(ed_outrider, "ROUTE_DISCOVERER_GAP_S", 0):
            off, same, v0, done = asyncio.run(go())
        self.assertEqual((off, same, done), (None, True, True))                  # nothing left to ask: no new task
        self.assertEqual(self.asked, ["Known B", "Known D"])   # the systems ahead: not the empty one, nor the one not looked up
        self.assertEqual(self.names_shown(), [None, "First In", None, "", None])   # "": EDSM credits nobody
        self.assertGreater(self.state.highway_summary()["known_v"], v0)         # the page reloads the list

    def test_the_games_route_too(self):
        ed_outrider.meta_set(self.state.db, "route", {"ts": ed_outrider.iso_ts(1001), "hops": [
            {"id64": 1, "name": "Start", "star_class": "G", "x": 0.0, "y": 0.0, "z": 0.0},
            {"id64": 2, "name": "Known B", "star_class": "K", "x": 50.0, "y": 0.0, "z": 0.0}]})
        self.state.route_known_on = True

        async def go():
            self.state.navroute_view()
            await self.state.route_discoverer_task
        asyncio.run(go())
        self.assertEqual(self.asked, ["Known B"])
        self.assertEqual([h["discoverer"] for h in self.state.navroute_view()["route"]["hops"]], ["First In"])

    def test_edsm_down(self):
        self.names["Known B"] = OSError("no route to host")
        self.state.route_known_on = True

        async def go():
            self.state.highway_view()
            await self.state.route_discoverer_task
            self.state.highway_view()                        # nothing more for a minute
            await self.state.route_discoverer_task
        with contextlib.redirect_stderr(io.StringIO()) as err:
            asyncio.run(go())
        self.assertEqual(self.asked, ["Known B"])
        self.assertIn("route systems: EDSM discoverer lookup failed", err.getvalue())
        self.assertEqual(self.names_shown(), [None] * 5)

    def test_a_pass_is_limited(self):
        self.state.route_known_on = True
        self.names.update({f"S{i}": "X" for i in range(60)})
        self.state.route_known.update({100 + i: "explored" for i in range(60)})

        async def go():
            with unittest.mock.patch.object(ed_outrider, "ROUTE_DISCOVERER_GAP_S", 0):
                self.state.route_discoverer_check([{"id64": 100 + i, "name": f"S{i}"} for i in range(60)])
                await self.state.route_discoverer_task
        asyncio.run(go())
        self.assertEqual(len(self.asked), ed_outrider.ROUTE_DISCOVERER_MAX)


if __name__ == "__main__":
    unittest.main()

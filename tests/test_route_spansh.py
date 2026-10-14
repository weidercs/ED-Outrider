"""Unit tests: what the In-Game Route's chips say about Spansh (Kurbo26, GitHub discussion #3, 2026-10-13: Sol's chip
said "not reported to Spansh"). A hop is known (Spansh has a record), unreported (Spansh was asked and has none: the
✦) or not looked up (no claim either way). Outrider asks Spansh about the route's hops in one search when it is
plotted (State.maybe_route_lookup), and an empty cache is never read as "Spansh has none" (State.spansh_knows), here
or in the Nearby rows, the arrival briefing and the overlay's strip.

The search's answer is tests/fixtures/spansh_ids.json (probed 2026-10-14, trimmed). Nothing here touches the network.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import asyncio
import contextlib
import io
import json
import os
import time
import types
import unittest

from support import _HwSession, ed_outrider  # also puts the repository root on sys.path

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "spansh_ids.json")


def spansh_base(name, x):
    return {"v": ed_outrider.CACHE_VERSION, "name": name, "x": x, "y": 0, "z": 0, "body_count": 3, "records": []}


class RecordsById(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.sp = ed_outrider.Spansh(self.db)

    def test_one_search_and_the_absent_ones(self):
        with open(FIXTURE, encoding="utf-8") as f:
            answer = json.load(f)
        self.sp.session = _HwSession([(200, answer)])
        ids = [10477373803, 3238296097059, 123456789012345]
        got = asyncio.run(self.sp.records_by_id(ids))
        self.assertEqual({r["id64"] for r in got}, {10477373803, 3238296097059})   # the third: no record, not in it
        self.assertEqual(self.sp.session.calls, [("POST", ed_outrider.SPANSH_SEARCH,
                                                  {"filters": {"id64": {"value": ids}}, "size": 3, "page": 0})])
        # permit_ids reads the same search
        self.sp.session = _HwSession([(200, dict(answer, results=[dict(answer["results"][0], needs_permit=True)]))])
        self.assertEqual(asyncio.run(self.sp.permit_ids(ids)), {answer["results"][0]["id64"]})

    def test_a_failure_is_never_an_answer(self):
        self.sp.session = None
        with self.assertRaises(ed_outrider.ClientError):
            asyncio.run(self.sp.records_by_id([1]))
        for bad in ((200, {"error": "Invalid request"}), (500, {})):
            self.sp.session = _HwSession([bad])
            with self.assertRaises(ed_outrider.ClientError):
                asyncio.run(self.sp.records_by_id([1]))


class RouteBase(unittest.TestCase):
    """You in S1 (at 0, 0, 0), a Spansh with its cache only (no session: nothing is asked)."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.sp = ed_outrider.Spansh(self.db)
        self.state = ed_outrider.State(self.db, self.j, self.sp, 25)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "S1", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})

    def route(self, n):
        hops = [{"id64": i, "name": f"S{i}", "star_class": "K", "x": i * 10.0, "y": 0, "z": 0} for i in range(1, n + 1)]
        ed_outrider.meta_set(self.db, "route", {"ts": "2026-01-01T00:00:30Z", "hops": hops})

    def known(self):
        return {int(h["id"]): h["known"] for h in self.state.route_summary()["hops"]}


class RouteChips(RouteBase):
    def test_three_states(self):
        """Never asked: None (the page shows no ✦ and claims nothing); in Spansh's cache: True; asked and absent: False.
        An EDSM stand-in in the cache is not Spansh's answer."""
        self.route(7)
        self.assertEqual(set(self.known().values()), {None})   # nothing asked yet: no claim (it said "not reported")
        self.sp.store(2, "u", spansh_base("S2", 20))
        self.sp.store(3, None, ed_outrider.base_from_edsm({"name": "S3", "coords": {"x": 30, "y": 0, "z": 0}}))
        self.state.route_spansh[4] = (time.time(), False)                     # the hop lookup: no record
        self.state.route_spansh[5] = (time.time() - ed_outrider.ROUTE_LOOKUP_KEEP_S - 1, False)   # too old to trust
        self.state.target_verdicts[6] = "unreported"                          # the target's lookup found nothing
        self.state.target_verdicts[7] = "lookup failed"
        self.assertEqual(self.known(), {2: True, 3: None, 4: False, 5: None, 6: False, 7: None})

    def test_the_nearby_search_answers_for_its_sphere(self):
        """A stand-in from your route plots inside the search Spansh answered is unreported; one it could not cover
        (Spansh down, or past a busy region's sphere_cut) is not looked up, in the chip and in the Nearby row."""
        self.route(3)
        self.state.bases = {2: ("route", {"name": "S2", "x": 20, "y": 0, "z": 0, "records": []}),
                            3: ("route", {"name": "S3", "x": 30, "y": 0, "z": 0, "records": [], "unasked": True})}
        self.assertEqual(self.known(), {2: False, 3: None})
        rows = {i: self.state.row(i) for i in (2, 3)}
        self.assertEqual([(rows[i]["status"], rows[i]["in_spansh"]) for i in (2, 3)], [("unreported", False), ("unasked", None)])


class RouteLookup(RouteBase):
    def setUp(self):
        super().setUp()
        self.calls, self.fail = [], {}
        test = self

        class Fake(ed_outrider.Spansh):
            async def records_by_id(self, ids):
                test.calls.append(list(ids))
                if test.fail.get("down"):
                    raise ed_outrider.ClientError("down")
                return [{"id64": i, "name": f"S{i}"} for i in ids if i % 2 == 0]   # Spansh has the even ones

        self.sp = Fake(self.db)
        self.sp.session = object()   # "started": records_by_id is the fake's, nothing goes out
        self.state.spansh = self.sp

    def run_lookup(self, now=None):
        async def go():
            self.state.maybe_route_lookup(now=now)
            if self.state.route_task:
                await self.state.route_task
        with contextlib.redirect_stderr(io.StringIO()):
            asyncio.run(go())

    def test_one_search_for_the_hops_shown(self):
        self.route(31)                       # 30 hops ahead of you; the strip shows 24
        self.sp.store(2, "u", spansh_base("S2", 20))   # already answered: not asked
        self.run_lookup()
        self.assertEqual(self.calls, [[i for i in range(3, 26)]])   # one search, the first 24 hops less the cached one
        k = self.known()
        self.assertEqual([k[i] for i in (2, 3, 4, 25, 26)], [True, False, True, False, None])
        self.state.route_task = None
        self.run_lookup()                    # all 24 answered: nothing more is asked
        self.assertEqual(len(self.calls), 1)

    def test_a_failed_search_claims_nothing_and_waits(self):
        self.route(3)
        self.fail["down"] = True
        self.run_lookup(now=1000)
        self.assertEqual(set(self.known().values()), {None})
        self.fail["down"] = False
        self.run_lookup(now=1000 + ed_outrider.ROUTE_LOOKUP_RETRY_S - 1)   # paced: not again so soon
        self.assertEqual(len(self.calls), 1)
        self.state.route_retry_at = 0
        self.run_lookup()
        self.assertEqual((len(self.calls), self.known()), (2, {2: True, 3: False}))

    def test_without_the_lookup_nothing_is_asked(self):
        self.route(3)
        self.sp.session = None                 # no network session (not started, or none in this mode)
        self.run_lookup()
        self.state.spansh = types.SimpleNamespace(cached=lambda i: (None, None))   # a fake Spansh without the search
        self.run_lookup()
        self.assertEqual((self.calls, self.state.route_task), ([], None))


class ArrivalAndStrip(RouteBase):
    def test_never_asked_is_not_not_in_spansh(self):
        """The arrival briefing and the overlay's strip read the same three states: a system the Nearby list does not
        have yet and Spansh was never asked about is None (the briefing says "Known.", the strip says nothing), not
        False ("Known, not in Spansh.", "Spansh ✗")."""
        self.state.system_detail = lambda id64: {}
        self.assertIsNone(self.state.arrival_facts(1)["in_spansh"])
        self.assertIsNone(self.state.overlay_strip_info(self.j.pos)["in_spansh"])
        self.state.target_verdicts[1] = "unreported"
        self.assertIs(self.state.arrival_facts(1)["in_spansh"], False)
        self.assertIs(self.state.overlay_strip_info(self.j.pos)["in_spansh"], False)


class NearbyStandIns(unittest.TestCase):
    """The refresh marks the stand-ins (your visits and route plots Spansh's answer did not list) "unasked" when that
    answer could not speak for them: the search failed, or a busy region's answer stopped at sphere_cut."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "S1", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})
        self.db.execute("INSERT INTO route_systems VALUES (8, 'S8', 3, 0, 0, 'K', 't')")
        self.fail = {}
        test = self

        class Fake(ed_outrider.Spansh):
            async def sphere(self, pos, r):
                if test.fail.get("sphere"):
                    raise ed_outrider.ClientError("down")
                return test.fail.get("results", [])

            async def edsm_sphere(self, pos, r):
                return []
        self.state = ed_outrider.State(self.db, self.j, Fake(self.db), 25)
        self.state.center = self.j.pos

    def refresh(self):
        with contextlib.redirect_stderr(io.StringIO()):
            asyncio.run(self.state._refresh(self.j.pos))
        row = self.state.systems[8]
        return row["status"], row["in_spansh"], self.state.spansh_knows(8)

    def test_answered_failed_and_cut(self):
        self.assertEqual(self.refresh(), ("unreported", False, False))   # Spansh answered, without it
        self.fail["sphere"] = True
        self.assertEqual(self.refresh(), ("unasked", None, None))        # Spansh down: no claim
        # a busy region: the answer is SPANSH_PAGE * SPANSH_MAX_PAGES systems long and stops at 2 ly, S8 is at 3
        self.fail = {"results": [{"id64": 1000 + i, "name": f"F{i}", "x": 0, "y": 0, "z": 0, "distance": 2.0, "bodies": []}
                                 for i in range(ed_outrider.SPANSH_PAGE * ed_outrider.SPANSH_MAX_PAGES)]}
        self.assertEqual(self.refresh(), ("unasked", None, None))


if __name__ == "__main__":
    unittest.main()

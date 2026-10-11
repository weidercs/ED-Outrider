"""The fork's Inara upload (outrider/inara.py). Nothing here reaches a network: the sender gets a fake session."""
import argparse
import asyncio
import contextlib
import io
import json
import os
import unittest

from support import ed_outrider, temp_dir

import outrider
import outrider.inara as up
from outrider.core import iso_ts

NOW = 1791400000.0   # the wall clock the tests run at
ARGS = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
TS = iso_ts(NOW)

# Journal lines as the game writes them (made up: no real commander or system)
POS = [12.5, -3.25, 40.0]
FILEHEADER = {"timestamp": TS, "event": "Fileheader", "part": 1, "language": "English/UK", "Odyssey": True,
              "gameversion": "4.2.0.100", "build": "r312744/r0 "}
LOADGAME = {"timestamp": TS, "event": "LoadGame", "FID": "F1234567", "Commander": "Sample Pilot", "Horizons": True,
            "Odyssey": True, "Ship": "krait_light", "ShipID": 7, "Credits": 1500000, "Loan": 0,
            "gameversion": "4.2.0.100", "build": "r312744/r0 "}
FACTION = {"Name": "Talvik Free", "FactionState": "Boom", "Government": "Democracy", "Influence": 0.4,
           "Allegiance": "Independent", "MyReputation": 42.5}
LOCATION = {"timestamp": TS, "event": "Location", "Docked": False, "StarSystem": "Talvik Reach", "SystemAddress": 2001,
            "StarPos": POS, "Body": "Talvik Reach A 1", "BodyID": 4, "BodyType": "Planet"}
FSDJUMP = {"timestamp": TS, "event": "FSDJump", "Taxi": False, "Multicrew": False, "StarSystem": "Ossia",
           "SystemAddress": 3001, "StarPos": [20.0, 1.0, 44.5], "JumpDist": 8.6, "FuelUsed": 1.2, "FuelLevel": 30.5,
           "Factions": [FACTION]}
DOCKED = {"timestamp": TS, "event": "Docked", "StationName": "Hesper Dock", "StationType": "Coriolis", "Taxi": False,
          "StarSystem": "Talvik Reach", "SystemAddress": 2001, "MarketID": 3200001}


def tracker(*events):
    tr = up.Tracker()
    for ev in events or (FILEHEADER, LOADGAME, LOCATION):
        tr.apply(ev)
    return tr


def line(ev):
    """A journal line with the game's own spacing: "event":"Name" (what the start-up prefilter looks for)."""
    return json.dumps(ev, separators=(", ", ":"))


def at(ev, ts=TS, **kw):
    return dict(ev, timestamp=ts, **kw)


class Reply:
    def __init__(self, status, body):
        self.status, self.body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self, content_type=None):
        return self.body


class FakeSession:
    """Records every request; `answer(url, kw)` gives (status, body) or an exception to raise."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        got = self.answer(url, kw)
        if isinstance(got, Exception):
            raise got
        return Reply(*got)


class Game:
    """A journal folder the test writes to as the game would."""

    def __init__(self, test, name="Journal.2026-10-07T100000.01.log"):
        self.dir = temp_dir(test)
        self.path = os.path.join(self.dir, name)

    def write(self, *events, path=None):
        with open(path or self.path, "a", encoding="utf-8", newline="\n") as f:
            for ev in events:
                f.write(line(ev) + "\n")


def sync(game, **settings):
    log = []
    u = up.InaraSync(dict({"enabled": True, "api_key": "KEY"}, **settings), [game.dir], log=lambda *a, **k: log.append(a[0]))
    u.logged = log
    return u


def names(u):
    return [e["eventName"] for e in u.queue]


class LiveOnly(unittest.TestCase):
    def test_only_what_is_written_from_now_on(self):
        """What the journal held at start is read for the state and never sent; a line written after is."""
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION, FSDJUMP)
        u = sync(g)
        u.poll(NOW)
        self.assertEqual(names(u), [])
        self.assertEqual((u.tracker.cmdr, u.tracker.system["name"]), ("Sample Pilot", "Ossia"))
        g.write(DOCKED)
        with open(g.path, "a", encoding="utf-8") as f:
            f.write(line(LOCATION)[:40])     # the game is mid-line
        u.poll(NOW + 1)
        self.assertEqual(names(u), ["addCommanderTravelDock"])
        with open(g.path, "a", encoding="utf-8") as f:
            f.write(line(LOCATION)[40:] + "\n")
        u.poll(NOW + 2)
        self.assertEqual(names(u), ["addCommanderTravelDock", "setCommanderTravelLocation"])

    def test_an_old_line_is_history(self):
        """A journal copied into the folder, or one being caught up on: its events are not news, and they do not
        move the commander either."""
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION)
        u = sync(g)
        u.poll(NOW)
        old = iso_ts(NOW - up.LIVE_S - 5)
        g.write(at(FSDJUMP, old), at({"event": "garbage"}, None))
        g.write(at(FILEHEADER, old), at(LOADGAME, old, Commander="Somebody Else"), at(FSDJUMP, old),
                path=os.path.join(g.dir, "Journal.2020-01-01T000000.01.log"))
        u.poll(NOW)
        self.assertEqual(names(u), [])
        self.assertEqual((u.tracker.cmdr, u.tracker.system["name"]), ("Sample Pilot", "Talvik Reach"))
        g.write(at(FSDJUMP, iso_ts(NOW - up.LIVE_S + 5)))
        u.poll(NOW)
        self.assertEqual(names(u)[0], "addCommanderTravelFSDJump")

    def test_a_new_journal_is_followed(self):
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION)
        u = sync(g)
        u.poll(NOW)
        nxt = os.path.join(g.dir, "Journal.2026-10-07T120000.01.log")
        g.write(FILEHEADER, dict(LOADGAME, Commander="Second Pilot"), LOCATION, path=nxt)
        u.poll(NOW)
        self.assertEqual((names(u), u.tracker.cmdr), (["setCommanderCredits", "setCommanderTravelLocation"], "Second Pilot"))

    def test_no_commander_no_upload(self):
        g = Game(self)
        g.write(FILEHEADER)
        u = sync(g)
        u.poll(NOW)
        g.write(LOCATION)        # before LoadGame named the commander
        u.poll(NOW + 1)
        self.assertEqual(names(u), [])

    def test_only_your_own_live_galaxy_log(self):
        """Nothing from the Legacy galaxy, a beta, or another commander's ship."""
        for header, extra in ((dict(FILEHEADER, gameversion="3.8.0.1400"), ()),
                              (dict(FILEHEADER, gameversion="4.3.0.0 (Beta 1)"), ()),
                              (FILEHEADER, ({"timestamp": TS, "event": "JoinACrew", "Captain": "Someone"},))):
            g = Game(self)
            g.write(header, LOADGAME, LOCATION, *extra)
            u = sync(g)
            u.poll(NOW)
            g.write(FSDJUMP)
            u.poll(NOW + 1)
            self.assertEqual(names(u), [], header["gameversion"])

    def test_off_means_off(self):
        """The default: not switched on, so no task, no request, nothing queued. The same with --simulate or while
        EDMC sends to Inara, whatever the config says."""
        st = ed_outrider.settings_from({}, ARGS, None, ([], []))["inara"]
        self.assertEqual(st, {"enabled": False, "api_key": ""})
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION)
        made = []
        for u, words in ((up.InaraSync(st, [g.dir]), "off ([inara] enabled)"),
                         (up.InaraSync({"enabled": True, "api_key": "k"}, [g.dir], off="--simulate"), "off (--simulate)")):
            self.assertFalse(u.active)
            asyncio.run(u.run(session_factory=lambda: made.append(1)))   # returns at once, makes no session
            self.assertEqual(u.status_line(), words)
            u.poll(NOW)
            g.write(FSDJUMP)
            u.poll(NOW + 1)
            self.assertEqual(len(u.queue), 0)
            asyncio.run(u.send(FakeSession(lambda url, kw: made.append(2) or (200, {})), 99))
        self.assertEqual(made, [])
        self.assertEqual(up.InaraSync({"enabled": True, "api_key": "k"}, [g.dir], off="--simulate").info()["off"], "--simulate")
        self.assertEqual(up.InaraSync({"enabled": True, "api_key": "k"}, [g.dir]).status_line(), "on (live play only)")


class Sending(unittest.TestCase):
    def game(self, **settings):
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION)
        u = sync(g, **settings)
        u.poll(NOW)
        return g, u

    def test_inara(self):
        g, u = self.game()
        g.write(dict(LOADGAME, Credits=10), dict(LOADGAME, Credits=2500000, Loan=5), FSDJUMP)
        u.poll(NOW + 1)
        reply = {"header": {"eventStatus": 200}, "events": [{"eventStatus": 200}, {"eventStatus": 400,
                                                                                  "eventStatusText": "no such ship"},
                                                           {"eventStatus": 200}]}
        s = FakeSession(lambda url, kw: (200, reply))
        asyncio.run(u.send(s, 1))
        sent = s.calls[0][1]["json"]
        self.assertEqual((s.calls[0][0], sent["header"]), (up.INARA_URL, {
            "appName": "ED Outrider", "appVersion": outrider.__version__, "APIkey": "KEY",
            "commanderName": "Sample Pilot", "commanderFrontierID": "F1234567"}))
        self.assertEqual([e["eventName"] for e in sent["events"]],
                         ["setCommanderCredits", "addCommanderTravelFSDJump", "setCommanderReputationMinorFaction"])
        self.assertEqual(sent["events"][0], {"eventName": "setCommanderCredits", "eventTimestamp": TS,
                                             "eventData": {"commanderCredits": 2500000, "commanderLoan": 5}})
        self.assertEqual(sent["events"][1]["eventData"], {"starsystemName": "Ossia", "starsystemCoords": [20.0, 1.0, 44.5],
                                                          "jumpDistance": 8.6, "shipType": "krait_light", "shipGameID": 7})
        self.assertEqual((u.sent, u.dropped), (2, 1))
        self.assertIn("no such ship", u.info()["error"])
        g.write(DOCKED)
        u.poll(NOW + 2)
        asyncio.run(u.send(s, 2))
        self.assertEqual(len(s.calls), 1)                                  # one request per INARA_GAP_S
        s.answer = lambda url, kw: (200, {"header": {"eventStatus": 400, "eventStatusText": "Invalid API key."}})
        asyncio.run(u.send(s, 1 + up.INARA_GAP_S))
        self.assertIn("Invalid API key.", u.info()["error"])
        self.assertTrue(any("Inara refused the upload" in words for words in u.logged))
        g.write(FSDJUMP)
        u.poll(NOW + 3)
        asyncio.run(u.send(s, 200))
        self.assertEqual((len(s.calls), len(u.queue)), (2, 0))             # refused: not asked again

    def test_inara_waits_out_a_failure(self):
        """Inara unreachable: the events are kept and nothing more is tried for a minute."""
        g, u = self.game()
        g.write(FSDJUMP)
        u.poll(NOW + 1)
        s = FakeSession(lambda url, kw: asyncio.TimeoutError())
        asyncio.run(u.send(s, 1))
        asyncio.run(u.send(s, 30))
        self.assertEqual((len(s.calls), len(u.queue), u.info()["error"]), (1, 2, "Inara could not be reached (timed out)"))
        s.answer = lambda url, kw: (503, None)
        asyncio.run(u.send(s, 1 + up.RETRY_S))
        self.assertEqual((len(u.queue), u.info()["error"]), (2, "Inara answered 503"))
        s.answer = lambda url, kw: (200, {"header": {"eventStatus": 200}, "events": []})
        asyncio.run(u.send(s, 1 + 2 * up.RETRY_S))
        self.assertEqual((u.sent, len(u.queue), u.info()["error"]), (2, 0, None))

    def test_queue_bounded(self):
        g, u = self.game()
        g.write(*[{"timestamp": TS, "event": "MaterialCollected", "Category": "Raw", "Name": "iron", "Count": 1}
                  for _ in range(up.QUEUE_MAX + 5)])
        u.poll(NOW + 1)
        self.assertEqual((len(u.queue), u.dropped), (up.QUEUE_MAX, 5))

    def test_inara_events(self):
        tr, memo = tracker(), {}
        made = lambda ev: (tr.apply(ev), up.inara_events(ev, tr, memo))[1]
        self.assertEqual(made({"event": "Rank", "Combat": 3, "Trade": 5, "Explore": 8}), [])
        self.assertEqual(made({"event": "Progress", "Combat": 50, "Trade": 0, "Explore": 100}), [("setCommanderRankPilot", [
            {"rankName": "combat", "rankValue": 3, "rankProgress": 0.5}, {"rankName": "trade", "rankValue": 5, "rankProgress": 0.0},
            {"rankName": "explore", "rankValue": 8, "rankProgress": 1.0}])])
        self.assertEqual(made({"event": "Reputation", "Empire": 75.5, "Federation": -10}), [(
            "setCommanderReputationMajorFaction", [{"majorfactionName": "empire", "majorfactionReputation": 0.755},
                                                   {"majorfactionName": "federation", "majorfactionReputation": -0.1}])])
        self.assertEqual(made({"event": "Materials", "Raw": [{"Name": "iron", "Count": 10}],
                               "Encoded": [{"Name": "shieldcyclerecordings", "Name_Localised": "x", "Count": 3}]}),
                         [("setCommanderInventoryMaterials", [{"itemName": "iron", "itemCount": 10},
                                                              {"itemName": "shieldcyclerecordings", "itemCount": 3}])])
        self.assertEqual(made(LOCATION), [("setCommanderTravelLocation", {"starsystemName": "Talvik Reach",
                                                                           "starsystemCoords": POS})])
        self.assertEqual(made(DOCKED), [("addCommanderTravelDock", {
            "starsystemName": "Talvik Reach", "starsystemCoords": POS, "stationName": "Hesper Dock", "shipType": "krait_light",
            "shipGameID": 7, "marketID": 3200001})])
        made({"event": "Undocked", "StationName": "Hesper Dock"})
        self.assertEqual(made(DOCKED), [])                       # back to the pad without leaving: no new visit
        made({"event": "Undocked"})
        made({"event": "SupercruiseEntry"})
        self.assertEqual(len(made(DOCKED)), 1)
        taxi = made(dict(FSDJUMP, Taxi=True))[0]
        self.assertEqual(taxi[1], {"starsystemName": "Ossia", "starsystemCoords": [20.0, 1.0, 44.5], "jumpDistance": 8.6,
                                   "isTaxiShuttle": True})
        self.assertEqual(made({"event": "Loadout", "Ship": "anaconda", "ShipID": 9, "ShipName": "Far Out", "ShipIdent": "SP-01",
                               "HullValue": 100, "ModulesValue": 200, "Rebuy": 15, "MaxJumpRange": 60.5, "CargoCapacity": 64}),
                         [("setCommanderShip", {"shipType": "anaconda", "shipGameID": 9, "isCurrentShip": True,
                                                "shipName": "Far Out", "shipIdent": "SP-01", "shipHullValue": 100,
                                                "shipModulesValue": 200, "shipRebuyCost": 15, "shipMaxJumpRange": 60.5,
                                                "shipCargoCapacity": 64})])
        self.assertEqual(made({"event": "MissionAccepted", "Name": "Mission_Courier", "MissionID": 55, "Faction": "Talvik Free",
                               "DestinationSystem": "Ossia", "Expiry": "2026-10-09T00:00:00Z", "Influence": "++",
                               "Reputation": "+"}),
                         [("addCommanderMission", {"missionName": "Mission_Courier", "missionGameID": 55,
                                                   "missionExpiry": "2026-10-09T00:00:00Z", "influenceGain": "++",
                                                   "reputationGain": "+", "minorfactionNameOrigin": "Talvik Free",
                                                   "starsystemNameTarget": "Ossia", "starsystemNameOrigin": "Ossia"})])
        self.assertEqual(made({"event": "MissionCompleted", "MissionID": 55, "Reward": 9000}),
                         [("setCommanderMissionCompleted", {"missionGameID": 55, "rewardCredits": 9000})])
        self.assertEqual(made({"event": "Died", "KillerName": "Someone"}),
                         [("addCommanderCombatDeath", {"starsystemName": "Ossia", "opponentName": "Someone"})])
        self.assertEqual(made({"event": "Interdicted", "Submitted": True, "Interdictor": "Pirate", "IsPlayer": False}),
                         [("addCommanderCombatInterdicted", {"starsystemName": "Ossia", "opponentName": "Pirate",
                                                             "isPlayer": False, "isSubmit": True})])
        self.assertEqual(made({"event": "Music"}), [])
        shipless = up.inara_events(FSDJUMP, tracker(FILEHEADER, dict(LOADGAME, ShipID=None), FSDJUMP), {})
        self.assertEqual([e[0] for e in shipless], ["setCommanderReputationMinorFaction"])   # no ship known: no jump


class Settings(unittest.TestCase):
    def test_inara_settings(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(up.inara_settings({"inara": {"enabled": "yes", "api_key": " abc "}}),
                             {"enabled": False, "api_key": "abc"})
            self.assertEqual(up.inara_settings({"inara": {"enabled": True}}), {"enabled": False, "api_key": ""})
            self.assertEqual(up.inara_settings({"inara": {"enabled": True, "api_key": 5}}), {"enabled": False, "api_key": ""})
        for words in ("enabled = 'yes' must be true or false", "enabled = true needs api_key", "api_key must be text"):
            self.assertIn(words, err.getvalue())
        self.assertEqual(up.inara_settings({"inara": "x"}), up.DEFAULTS)
        self.assertEqual(up.inara_settings({"inara": {"enabled": True, "api_key": "k"}}), {"enabled": True, "api_key": "k"})

    def test_config_round_trip(self):
        import tomllib
        st = ed_outrider.settings_from({"inara": {"enabled": True, "api_key": 'k"ey'}}, ARGS, None, ([], []))
        self.assertEqual(tomllib.loads(ed_outrider.config_text(st))["inara"], {"enabled": True, "api_key": 'k"ey'})
        off = tomllib.loads(ed_outrider.config_text(ed_outrider.settings_from({}, ARGS, None, ([], []))))["inara"]
        self.assertEqual(off, {"enabled": False, "api_key": ""})


if __name__ == "__main__":
    unittest.main()

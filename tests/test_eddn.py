"""Unit tests: EDDN messages (outrider/eddn.py) checked against EDDN's own schemas (tests/fixtures/eddn, its live branch),
the sender against a fake session, and a journal line all the way to the outbox. Nothing is sent anywhere.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import asyncio
import gzip
import json
import os
import shutil
import tempfile
import time
import types
import unittest

from support import ed_outrider  # also puts the repository root on sys.path
import outrider.eddn as E  # noqa: E402
import outrider.uploads as U  # noqa: E402
from outrider.core import iso_ts  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "eddn")
try:
    import jsonschema
except ImportError:   # requirements-dev.txt has it; without it only the schema checks are skipped
    jsonschema = None


def valid(envelope, schema_file):
    """Raise unless `envelope` passes EDDN's schema (draft-04, as EDDN's gateway validates)."""
    with open(os.path.join(FIX, schema_file), encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.Draft4Validator(schema).validate(envelope)


def session(horizons=True, odyssey=True):
    s = U.Session()
    s.feed({"event": "Fileheader", "timestamp": "2026-10-08T10:00:00Z", "gameversion": "4.2.0.100", "build": "r312345/r0 "},
           "Journal.2026-10-08T100000.01.log")
    lg = {"event": "LoadGame", "timestamp": "2026-10-08T10:00:01Z", "Commander": "Briadin", "FID": "F1"}
    if horizons is not None:
        lg["Horizons"] = horizons
    if odyssey is not None:
        lg["Odyssey"] = odyssey
    s.feed(lg)
    return s


FSDJUMP = {"timestamp": "2026-10-08T10:05:00Z", "event": "FSDJump", "Taxi": False, "Multicrew": False,
           "StarSystem": "Smojooe AR-E b25-8", "SystemAddress": 18264118102193, "StarPos": [-4177.09, -1.0, 3324.53],
           "SystemAllegiance": "", "SystemEconomy": "$economy_None;", "SystemEconomy_Localised": "None",
           "SystemSecondEconomy": "$economy_None;", "SystemSecondEconomy_Localised": "None", "SystemGovernment": "$government_None;",
           "SystemGovernment_Localised": "None", "SystemSecurity": "$GAlAXY_MAP_INFO_state_anarchy;",
           "SystemSecurity_Localised": "Anarchy", "Population": 0, "Body": "Smojooe AR-E b25-8", "BodyID": 0, "BodyType": "Star",
           "JumpDist": 43.12, "FuelUsed": 3.2, "FuelLevel": 28.1, "BoostUsed": 4, "Wanted": False,
           "Factions": [{"Name": "Some Faction", "FactionState": "None", "Government": "Democracy", "Influence": 0.5,
                         "Allegiance": "Independent", "Happiness": "$Faction_HappinessBand2;", "Happiness_Localised": "Happy",
                         "MyReputation": 12.5, "HomeSystem": True, "SquadronFaction": False, "HappiestSystem": False}]}

SCAN = {"timestamp": "2026-10-08T10:06:00Z", "event": "Scan", "ScanType": "Detailed", "BodyName": "Smojooe AR-E b25-8 A 1",
        "BodyID": 5, "Parents": [{"Star": 1}, {"Null": 0}], "StarSystem": "Smojooe AR-E b25-8", "SystemAddress": 18264118102193,
        "DistanceFromArrivalLS": 450.2, "TidalLock": False, "TerraformState": "", "PlanetClass": "Rocky body",
        "Atmosphere": "", "AtmosphereType": "None", "Volcanism": "", "MassEM": 0.02, "Radius": 1500000.0,
        "SurfaceGravity": 1.2, "SurfaceTemperature": 180.0, "SurfacePressure": 0.0, "Landable": True,
        "Materials": [{"Name": "iron", "Name_Localised": "Iron", "Percent": 20.1}, {"Name": "nickel", "Percent": 15.2}],
        "Composition": {"Ice": 0.0, "Rock": 0.9, "Metal": 0.1}, "SemiMajorAxis": 1.0e10, "Eccentricity": 0.01,
        "OrbitalInclination": 0.1, "Periapsis": 10.0, "OrbitalPeriod": 1.0e6, "AscendingNode": 1.0, "MeanAnomaly": 2.0,
        "RotationPeriod": 1.0e5, "AxialTilt": 0.1, "WasDiscovered": False, "WasMapped": False, "WasFootfalled": False}


@unittest.skipUnless(jsonschema, "jsonschema is not installed (requirements-dev.txt)")
class JournalSchema(unittest.TestCase):
    """journal/1: the personal fields gone, the cross-check, the flags, every message valid for EDDN."""

    def test_fsdjump(self):
        s = session()
        s.feed(FSDJUMP)
        [(name, env)] = E.build(FSDJUMP, s, "2026.10.18")
        valid(env, "journal-v1.0.json")
        m = env["message"]
        self.assertEqual(name, "journal")
        self.assertEqual(env["$schemaRef"], "https://eddn.edcd.io/schemas/journal/1")
        self.assertEqual(env["header"], {"uploaderID": "Briadin", "softwareName": "ED Outrider", "softwareVersion": "2026.10.18",
                                         "gameversion": "4.2.0.100", "gamebuild": "r312345/r0 "})
        for k in ("JumpDist", "FuelUsed", "FuelLevel", "BoostUsed", "Wanted", "SystemEconomy_Localised"):
            self.assertNotIn(k, m)
        self.assertEqual(set(m["Factions"][0]) & {"MyReputation", "HomeSystem", "SquadronFaction", "HappiestSystem", "Happiness_Localised"}, set())
        self.assertEqual((m["horizons"], m["odyssey"]), (True, True))
        self.assertEqual(E.build(FSDJUMP, s, "2026.10.18", test=True)[0][1]["$schemaRef"], "https://eddn.edcd.io/schemas/journal/1/test")

    def test_scan_cross_check(self):
        s = session(odyssey=None)                                # LoadGame without an Odyssey key: left out
        s.feed(FSDJUMP)
        [(_, env)] = E.build(SCAN, s, "v")
        valid(env, "journal-v1.0.json")
        m = env["message"]
        self.assertEqual(m["StarPos"], [-4177.09, -1.0, 3324.53])               # added from the jump
        self.assertEqual(m["Materials"][0], {"Name": "iron", "Percent": 20.1})  # _Localised gone, inside lists too
        self.assertNotIn("odyssey", m)
        self.assertEqual(E.build(dict(SCAN, SystemAddress=999), s, "v"), [])  # another system: never sent
        s2 = session()
        self.assertEqual(E.build(SCAN, s2, "v"), [])                          # no position yet

    def test_saa_signals_and_docked_and_location(self):
        s = session()
        s.feed(FSDJUMP)
        saa = {"timestamp": "2026-10-08T10:07:00Z", "event": "SAASignalsFound", "BodyName": "Smojooe AR-E b25-8 A 1",
               "SystemAddress": 18264118102193, "BodyID": 5,
               "Signals": [{"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 2}],
               "Genuses": [{"Genus": "$Codex_Ent_Bacterial_Genus_Name;", "Genus_Localised": "Bacterium"}]}
        [(_, env)] = E.build(saa, s, "v")
        valid(env, "journal-v1.0.json")
        self.assertEqual(env["message"]["StarSystem"], "Smojooe AR-E b25-8")
        loc = {"timestamp": "2026-10-08T11:00:00Z", "event": "Location", "Docked": True, "StationName": "OUT OF THE BLUE",
               "StationType": "FleetCarrier", "MarketID": 3700251648, "StarSystem": "Smojooe AR-E b25-8",
               "SystemAddress": 18264118102193, "StarPos": [-4177.09, -1.0, 3324.53], "Latitude": 1.0, "Longitude": 2.0,
               "Body": "Smojooe AR-E b25-8", "BodyID": 0, "BodyType": "Star", "Population": 0}
        s.feed(loc)
        [(_, env)] = E.build(loc, s, "v")
        valid(env, "journal-v1.0.json")
        self.assertNotIn("Latitude", env["message"])
        docked = {"timestamp": "2026-10-08T11:05:00Z", "event": "Docked", "StationName": "OUT OF THE BLUE",
                  "StationType": "FleetCarrier", "StarSystem": "Smojooe AR-E b25-8", "SystemAddress": 18264118102193,
                  "MarketID": 3700251648, "StationFaction": {"Name": "FleetCarrier"}, "StationGovernment": "$government_Carrier;",
                  "StationGovernment_Localised": "Private Ownership", "StationServices": ["dock", "autodock"],
                  "StationEconomy": "$economy_Carrier;", "StationEconomy_Localised": "Private Enterprise",
                  "StationEconomies": [{"Name": "$economy_Carrier;", "Name_Localised": "Private Enterprise", "Proportion": 1.0}],
                  "DistFromStarLS": 0.0, "LandingPads": {"Small": 4, "Medium": 4, "Large": 8}, "Wanted": False,
                  "ActiveFine": False, "CockpitBreach": False}
        [(_, env)] = E.build(docked, s, "v")
        valid(env, "journal-v1.0.json")
        self.assertEqual(set(env["message"]) & {"Wanted", "ActiveFine", "CockpitBreach"}, set())

    def test_other_events_make_nothing(self):
        s = session()
        s.feed(FSDJUMP)
        self.assertEqual(E.build({"event": "Music", "timestamp": "2026-10-08T10:00:00Z", "MusicTrack": "x"}, s, "v"), [])


class Answers(unittest.TestCase):

    def test_outcome(self):
        self.assertEqual(E.outcome(200), ("sent", None))
        for st in (400, 413, 426):
            self.assertEqual(E.outcome(st), ("dropped", None))   # never retried (EDDN's MUST NOT)
        self.assertEqual(E.outcome(503)[0], "queued")
        self.assertGreaterEqual(E.outcome(408)[1], 60)           # at least a minute
        h = E.SchemaHold()
        for t in (0, 10, 20):
            self.assertIsNone(h.is_held("journal"))
            h.refused("journal", t, "400 FAIL")
        self.assertEqual(h.is_held("journal"), "400 FAIL")
        h2 = E.SchemaHold()
        for t in (0, 2000, 4000):                                 # spread over more than an hour: not held
            h2.refused("journal", t, "400")
        self.assertIsNone(h2.is_held("journal"))


class _Resp:
    def __init__(self, status, text):
        self.status, self._text = status, text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    def __init__(self, answers):
        self.answers, self.posts = list(answers), []

    def post(self, url, data=None, headers=None):
        self.posts.append((url, json.loads(gzip.decompress(data)), headers))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return _Resp(*a)


class SenderAndPipeline(unittest.TestCase):

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def rows(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM upload_queue ORDER BY id")]

    def test_journal_line_to_eddn(self):
        """A live jump goes through the reader, the hub and the EDDN builder into the outbox, then out as gzip JSON."""
        self.state.set_upload("eddn", True)
        path = os.path.join(self.dir, "Journal.2026-10-08T100000.01.log")
        now = lambda ago: iso_ts(time.time() - ago)
        with open(path, "w", encoding="utf-8") as f:
            for e in ({"timestamp": now(30), "event": "Fileheader", "gameversion": "4.2.0.100", "build": "r1 "},
                      {"timestamp": now(29), "event": "LoadGame", "Commander": "Briadin", "Horizons": True, "Odyssey": True},
                      dict(FSDJUMP, timestamp=now(5))):
                f.write(json.dumps(e) + "\n")
        self.j.scan_dir(self.dir, upload="live")
        [row] = self.rows()
        self.assertEqual((row["service"], row["schema"], row["state"]), ("eddn", "journal", "queued"))
        self.state.upload_session = _Session([(200, "OK")])
        out = asyncio.run(self.state.eddn_send([row]))
        self.assertEqual(out, [(row["id"], "sent", "200 OK", None)])
        url, sent, headers = self.state.upload_session.posts[0]
        self.assertEqual((url, headers["Content-Encoding"]), (E.UPLOAD_URL, "gzip"))
        self.assertEqual(sent["message"]["StarSystem"], "Smojooe AR-E b25-8")
        if jsonschema:
            valid(sent, "journal-v1.0.json")

    def test_refusals_hold_the_schema(self):
        s = session()
        for i in range(4):
            U.enqueue(self.db, "eddn", "journal", f"J:{i}", "2026-10-08T10:00:00Z", s, {"$schemaRef": "x", "message": {}})
        rows = self.rows()
        self.state.upload_session = _Session([(400, "FAIL: Schema Validation: [...]")] * 3)
        got = [asyncio.run(self.state.eddn_send([r]))[0][1] for r in rows[:3]]
        self.assertEqual(got, ["dropped"] * 3)
        out = asyncio.run(self.state.eddn_send([rows[3]]))      # held now: not even sent
        self.assertEqual((out[0][1], len(self.state.upload_session.posts)), ("dropped", 3))
        self.state.upload_session = _Session([ConnectionError("unreachable")])
        with self.assertRaises(ConnectionError):                 # the loop backs off
            asyncio.run(self.state.eddn_send([dict(rows[0], schema="fsssignaldiscovered")]))

    def test_available_in_the_summary(self):
        self.assertTrue(self.state.uploads_summary()["eddn"]["available"])
        self.assertFalse(self.state.uploads_summary()["edsm"]["available"])

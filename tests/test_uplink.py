"""The uploads (outrider/uplink.py): EDDN, EDSM and Inara. Nothing here reaches a network: the senders get a fake
session, and every EDDN message is checked against EDDN's own schemas (tests/fixtures/eddn, copied from EDCD/EDDN's
live branch; BSD 3-Clause, see LICENSE-EDDN.txt there)."""
import argparse
import asyncio
import contextlib
import io
import json
import os
import re
import unittest

from support import ed_outrider, temp_dir

import outrider
import outrider.uplink as up
from outrider.core import iso_ts

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "eddn")
NOW = 1791400000.0   # the wall clock the tests run at
ARGS = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
TS = iso_ts(NOW)


# ---------------------------------------------------------------------------
# JSON Schema (draft 4), the part EDDN's schemas use; an unknown keyword fails the test rather than being skipped
# ---------------------------------------------------------------------------

IGNORED = {"$schema", "id", "description", "renamed", "definitions", "format", "title", "$comment"}
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def is_type(v, t):
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, TYPES[t])


def check(v, schema, root, path="$"):
    """The ways `v` breaks `schema`, as a list of words (empty: valid)."""
    bad = []
    for key, rule in schema.items():
        if key in IGNORED:
            continue
        if key == "$ref":
            target = root
            for part in rule.lstrip("#/").split("/"):
                target = target[part]
            bad += check(v, target, root, path)
        elif key == "type":
            if not any(is_type(v, t) for t in (rule if isinstance(rule, list) else [rule])):
                bad.append(f"{path}: not {rule}")
        elif key == "enum":
            if v not in rule:
                bad.append(f"{path}: {v!r} not in {rule}")
        elif key == "not":
            if not check(v, rule, root, path):
                bad.append(f"{path}: not allowed")
        elif key == "required":
            if isinstance(v, dict):
                bad += [f"{path}: {k} missing" for k in rule if k not in v]
        elif key in ("properties", "patternProperties", "additionalProperties"):
            if not isinstance(v, dict) or key != "properties":
                continue   # the three are checked together, at "properties" (or below when there is none)
        elif key == "items":
            if isinstance(v, list):
                for i, item in enumerate(v):
                    bad += check(item, rule, root, f"{path}[{i}]")
        elif key == "minItems":
            if isinstance(v, list) and len(v) < rule:
                bad.append(f"{path}: fewer than {rule} items")
        elif key == "maxItems":
            if isinstance(v, list) and len(v) > rule:
                bad.append(f"{path}: more than {rule} items")
        elif key == "uniqueItems":
            if rule and isinstance(v, list) and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
                bad.append(f"{path}: items repeat")
        elif key == "minLength":
            if isinstance(v, str) and len(v) < rule:
                bad.append(f"{path}: shorter than {rule}")
        elif key == "pattern":
            if isinstance(v, str) and not re.search(rule, v):
                bad.append(f"{path}: does not match {rule}")
        else:
            raise AssertionError(f"schema keyword {key!r} is not handled by this checker")
    if isinstance(v, dict) and any(k in schema for k in ("properties", "patternProperties", "additionalProperties")):
        props, patterns = schema.get("properties", {}), schema.get("patternProperties", {})
        extra = schema.get("additionalProperties", True)
        for k, x in v.items():
            known = False
            if k in props:
                known = True
                bad += check(x, props[k], root, f"{path}.{k}")
            for pattern, rule in patterns.items():
                if re.search(pattern, k):
                    known = True
                    bad += check(x, rule, root, f"{path}.{k}")
            if not known and extra is False:
                bad.append(f"{path}: {k} is not allowed")
            elif not known and isinstance(extra, dict):
                bad += check(x, extra, root, f"{path}.{k}")
    return bad


_schemas = {}


def problems(envelope):
    """What EDDN's own schema says is wrong with a whole message (empty: it would be accepted)."""
    ref = envelope["$schemaRef"]
    assert ref.startswith(up.EDDN_SCHEMAS), ref
    name, version = ref[len(up.EDDN_SCHEMAS):].removesuffix("/test").split("/")
    if name not in _schemas:
        with open(os.path.join(FIXTURES, f"{name}-v{version}.0.json"), encoding="utf-8") as f:
            _schemas[name] = json.load(f)
    return check(envelope, _schemas[name], _schemas[name])


# ---------------------------------------------------------------------------
# Journal lines as the game writes them (made up: no real commander or system)
# ---------------------------------------------------------------------------

POS = [12.5, -3.25, 40.0]
FILEHEADER = {"timestamp": TS, "event": "Fileheader", "part": 1, "language": "English/UK", "Odyssey": True,
              "gameversion": "4.2.0.100", "build": "r312744/r0 "}
LOADGAME = {"timestamp": TS, "event": "LoadGame", "FID": "F1234567", "Commander": "Sample Pilot", "Horizons": True,
            "Odyssey": True, "Ship": "krait_light", "ShipID": 7, "Credits": 1500000, "Loan": 0,
            "gameversion": "4.2.0.100", "build": "r312744/r0 "}
FACTION = {"Name": "Talvik Free", "FactionState": "Boom", "Government": "Democracy", "Influence": 0.4,
           "Allegiance": "Independent", "Happiness": "$Faction_HappinessBand2;", "Happiness_Localised": "Happy",
           "MyReputation": 42.5, "SquadronFaction": True, "HappiestSystem": True, "HomeSystem": True}
LOCATION = {"timestamp": TS, "event": "Location", "Docked": False, "StarSystem": "Talvik Reach", "SystemAddress": 2001,
            "StarPos": POS, "SystemAllegiance": "", "Body": "Talvik Reach A 1", "BodyID": 4, "BodyType": "Planet",
            "Latitude": 12.5, "Longitude": -40.25, "Wanted": True, "Factions": [FACTION]}
FSDJUMP = {"timestamp": TS, "event": "FSDJump", "Taxi": False, "Multicrew": False, "StarSystem": "Ossia",
           "SystemAddress": 3001, "StarPos": [20.0, 1.0, 44.5], "SystemEconomy": "$economy_None;",
           "SystemEconomy_Localised": "None", "Population": 0, "Body": "Ossia A", "BodyID": 1, "BodyType": "Star",
           "JumpDist": 8.6, "FuelUsed": 1.2, "FuelLevel": 30.5, "BoostUsed": 4, "Wanted": False, "Factions": [FACTION]}
DOCKED = {"timestamp": TS, "event": "Docked", "StationName": "Hesper Dock", "StationType": "Coriolis", "Taxi": False,
          "StarSystem": "Talvik Reach", "SystemAddress": 2001, "MarketID": 3200001, "StationFaction": {"Name": "Talvik Free"},
          "StationGovernment": "$government_Democracy;", "StationGovernment_Localised": "Democracy",
          "StationServices": ["dock", "commodities"], "StationEconomy": "$economy_Refinery;",
          "StationEconomies": [{"Name": "$economy_Refinery;", "Name_Localised": "Refinery", "Proportion": 1.0}],
          "DistFromStarLS": 310.5, "Wanted": True, "ActiveFine": True, "CockpitBreach": True,
          "LandingPads": {"Small": 4, "Medium": 8, "Large": 2}}
SCAN = {"timestamp": TS, "event": "Scan", "ScanType": "Detailed", "BodyName": "Talvik Reach A 1", "BodyID": 4,
        "StarSystem": "Talvik Reach", "SystemAddress": 2001, "DistanceFromArrivalLS": 120.5, "PlanetClass": "Icy body",
        "Materials": [{"Name": "sulphur", "Name_Localised": "Sulphur", "Percent": 20.5}], "WasDiscovered": False,
        "WasMapped": False, "Landable": True}
SAA = {"timestamp": TS, "event": "SAASignalsFound", "BodyName": "Talvik Reach A 1", "SystemAddress": 2001, "BodyID": 4,
       "Signals": [{"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 2}],
       "Genuses": [{"Genus": "$Codex_Ent_Bacterial_Genus_Name;", "Genus_Localised": "Bacterium"}]}
HONK = {"timestamp": TS, "event": "FSSDiscoveryScan", "Progress": 0.25, "BodyCount": 12, "NonBodyCount": 3,
        "SystemName": "Talvik Reach", "SystemAddress": 2001}
ALL_FOUND = {"timestamp": TS, "event": "FSSAllBodiesFound", "SystemName": "Talvik Reach", "SystemAddress": 2001, "Count": 12}
BODY_SIGNALS = {"timestamp": TS, "event": "FSSBodySignals", "BodyName": "Talvik Reach A 1", "BodyID": 4,
                "SystemAddress": 2001, "Signals": [{"Type": "$SAA_SignalType_Biological;",
                                                    "Type_Localised": "Biological", "Count": 2}]}
NAV_BEACON = {"timestamp": TS, "event": "NavBeaconScan", "SystemAddress": 2001, "NumBodies": 12}
BARYCENTRE = {"timestamp": TS, "event": "ScanBaryCentre", "StarSystem": "Talvik Reach", "SystemAddress": 2001, "BodyID": 2,
              "SemiMajorAxis": 1.5e9, "Eccentricity": 0.1, "OrbitalInclination": 3.5, "Periapsis": 80.25,
              "OrbitalPeriod": 9000000.5, "AscendingNode": 12.5, "MeanAnomaly": 200.5}
SETTLEMENT = {"timestamp": TS, "event": "ApproachSettlement", "Name": "$Ancient:#index=1;", "Name_Localised": "Ruins (1)",
              "MarketID": 3900001, "SystemAddress": 2001, "BodyID": 4, "BodyName": "Talvik Reach A 1", "Latitude": -46.5,
              "Longitude": 133.25, "StationEconomies": [{"Name": "$economy_Colony;", "Name_Localised": "Colony",
                                                         "Proportion": 1.0}],
              "StationFaction": {"Name": "Talvik Free"}, "StationServices": ["dock"], "StationEconomy": "$economy_Colony;",
              "StationEconomy_Localised": "Colony"}
CODEX = {"timestamp": TS, "event": "CodexEntry", "EntryID": 2100301, "Name": "$Codex_Ent_Bacterial_01_Name;",
         "Name_Localised": "Bacterium Aurasus", "SubCategory": "$Codex_SubCategory_Organic_Structures;",
         "SubCategory_Localised": "Organic structures", "Category": "$Codex_Category_Biology;",
         "Category_Localised": "Biological", "Region": "$Codex_RegionName_18;", "Region_Localised": "Inner Orion Spur",
         "System": "Talvik Reach", "SystemAddress": 2001, "BodyID": 4, "Latitude": 12.5, "Longitude": -40.25,
         "IsNewEntry": True, "NewTraitsDiscovered": True, "VoucherAmount": 2500}
GRANTED = {"timestamp": TS, "event": "DockingGranted", "LandingPad": 12, "MarketID": 3200001, "StationName": "Hesper Dock",
           "StationType": "Coriolis"}
DENIED = {"timestamp": TS, "event": "DockingDenied", "Reason": "Distance", "MarketID": 3200001,
          "StationName": "Hesper Dock", "StationType": "Coriolis"}
SIGNAL = {"timestamp": TS, "event": "FSSSignalDiscovered", "SystemAddress": 2001, "SignalName": "$USS;",
          "SignalName_Localised": "Unidentified signal source", "SignalType": "USS", "USSType": "$USS_Type_Salvage;",
          "USSType_Localised": "Degraded emissions", "SpawningState": "$FactionState_None;", "SpawningFaction": "$faction_none;",
          "ThreatLevel": 0, "TimeRemaining": 900.5}
MARKET = {"timestamp": TS, "event": "Market", "MarketID": 3200001, "StationName": "Hesper Dock", "StationType": "Coriolis",
          "StarSystem": "Talvik Reach", "Items": [
              {"id": 128049154, "Name": "$gold_name;", "Name_Localised": "Gold", "Category": "$MARKET_category_metals;",
               "Category_Localised": "Metals", "BuyPrice": 0, "SellPrice": 47000, "MeanPrice": 47609, "StockBracket": 0,
               "DemandBracket": 2, "Stock": 0, "Demand": 1500, "Consumer": True, "Producer": False, "Rare": False},
              {"id": 128049202, "Name": "$HydrogenFuel_name;", "Name_Localised": "Hydrogen Fuel",
               "Category": "$MARKET_category_chemicals;", "Category_Localised": "Chemicals", "BuyPrice": 90,
               "SellPrice": 85, "MeanPrice": 113, "StockBracket": 3, "DemandBracket": 0, "Stock": 20000, "Demand": 1,
               "Consumer": False, "Producer": True, "Rare": False}]}
OUTFITTING = {"timestamp": TS, "event": "Outfitting", "MarketID": 3200001, "StationName": "Hesper Dock",
              "StarSystem": "Talvik Reach", "Horizons": True, "Items": [
                  {"id": 128049382, "Name": "hpt_pulselaser_fixed_small", "BuyPrice": 2200},
                  {"id": 128064033, "Name": "int_powerplant_size2_class1", "BuyPrice": 1978},
                  {"id": 128049250, "Name": "sidewinder_armour_grade1", "BuyPrice": 0},
                  {"id": 128672317, "Name": "int_planetapproachsuite", "BuyPrice": 500},
                  {"id": 128667727, "Name": "paintjob_sidewinder_default_02", "BuyPrice": 0}]}
SHIPYARD = {"timestamp": TS, "event": "Shipyard", "MarketID": 3200001, "StationName": "Hesper Dock",
            "StarSystem": "Talvik Reach", "Horizons": True, "AllowCobraMkIV": False, "PriceList": [
                {"id": 128049249, "ShipType": "sidewinder", "ShipPrice": 32000},
                {"id": 128049255, "ShipType": "eagle", "ShipType_Localised": "Eagle", "ShipPrice": 44800}]}
NAVROUTE = {"timestamp": TS, "event": "NavRoute", "Route": [
    {"StarSystem": "Talvik Reach", "SystemAddress": 2001, "StarPos": POS, "StarClass": "K"},
    {"StarSystem": "Ossia", "SystemAddress": 3001, "StarPos": [20.0, 1.0, 44.5], "StarClass": "N"}]}
FCMATERIALS = {"timestamp": TS, "event": "FCMaterials", "MarketID": 3700001, "CarrierName": "SAMPLE CARRIER",
               "CarrierID": "X1A-B2C", "Items": [{"id": 128961524, "Name": "$tacticalplans_name;",
                                                   "Name_Localised": "Tactical Plans", "Price": 5000, "Stock": 0,
                                                   "Demand": 10}]}


def tracker(*events):
    tr = up.Tracker()
    for ev in events or (FILEHEADER, LOADGAME, LOCATION):
        tr.apply(ev)
    return tr


def envelopes(ev, tr=None, **kw):
    tr = tr or tracker()
    if ev.get("event") not in ("Location", "FSDJump", "CarrierJump"):
        tr.apply(ev)
    return [up.eddn_envelope(schema, msg, tr) for schema, msg in up.eddn_messages(ev, tr, **kw)]


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

    async def text(self):
        return self.body if isinstance(self.body, str) else json.dumps(self.body)

    async def json(self, content_type=None):
        return self.body


class FakeSession:
    """Records every request; `answer(method, url, kw)` gives (status, body) or raises."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def _ask(self, method, url, kw):
        self.calls.append((method, url, kw))
        got = self.answer(method, url, kw)
        if isinstance(got, Exception):
            raise got
        return Reply(*got)

    def post(self, url, **kw):
        return self._ask("POST", url, kw)

    def get(self, url, **kw):
        return self._ask("GET", url, kw)


class Game:
    """A journal folder the test writes to as the game would."""

    def __init__(self, test, name="Journal.2026-10-07T100000.01.log"):
        self.dir = temp_dir(test)
        self.path = os.path.join(self.dir, name)

    def write(self, *events, path=None):
        with open(path or self.path, "a", encoding="utf-8", newline="\n") as f:
            for ev in events:
                f.write(line(ev) + "\n")

    def file(self, name, content):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            json.dump(content, f)


def uplink(game, **settings):
    log = []
    u = up.Uplink(dict({"eddn": True}, **settings), [game.dir], log=lambda *a, **k: log.append(a[0]))
    u.logged = log
    return u


def bodies(u):
    return [item["body"] for item in u.eddn.queue]


class EddnMessages(unittest.TestCase):
    def test_every_message_passes_its_schema(self):
        """Each event EDDN takes, as the game writes it with the commander's own fields and the player's language
        in it, comes out as a message EDDN's schema accepts."""
        for ev, schema in ((LOCATION, "journal/1"), (FSDJUMP, "journal/1"), (DOCKED, "journal/1"), (SCAN, "journal/1"),
                           (SAA, "journal/1"), (HONK, "fssdiscoveryscan/1"), (ALL_FOUND, "fssallbodiesfound/1"),
                           (BODY_SIGNALS, "fssbodysignals/1"), (NAV_BEACON, "navbeaconscan/1"),
                           (BARYCENTRE, "scanbarycentre/1"), (SETTLEMENT, "approachsettlement/1"),
                           (CODEX, "codexentry/1"), (GRANTED, "dockinggranted/1"), (DENIED, "dockingdenied/1")):
            with self.subTest(event=ev["event"]):
                tr = tracker()
                if ev is FSDJUMP:
                    tr.apply(ev)
                made = envelopes(ev, tr)
                self.assertEqual([m["$schemaRef"] for m in made], [up.EDDN_SCHEMAS + schema])
                self.assertEqual(problems(made[0]), [])
                self.assertEqual(made[0]["header"], {"uploaderID": "Sample Pilot", "softwareName": "ED Outrider CWeed14 Edition",
                                                     "softwareVersion": outrider.__version__,
                                                     "gameversion": "4.2.0.100", "gamebuild": "r312744/r0 "})
                self.assertEqual((made[0]["message"]["horizons"], made[0]["message"]["odyssey"]), (True, True))
                self.assertNotIn("_Localised", json.dumps(made[0]))

    def test_the_checker_has_teeth(self):
        """The same events sent as the game wrote them are refused: the stripping is what makes them pass."""
        tr = tracker()
        for ev, schema in ((LOCATION, "journal/1"), (DOCKED, "journal/1"), (HONK, "fssdiscoveryscan/1"),
                           (CODEX, "codexentry/1")):
            raw = up.eddn_envelope(schema, dict(ev, StarSystem="Talvik Reach", StarPos=POS), tr)
            self.assertTrue(problems(raw), ev["event"])
        self.assertTrue(problems(up.eddn_envelope("journal/1", {"timestamp": TS, "event": "Scan"}, tr)))

    def test_nothing_personal_goes_out(self):
        loc = envelopes(LOCATION)[0]["message"]
        for k in ("Latitude", "Longitude", "Wanted"):
            self.assertNotIn(k, loc)
        self.assertEqual(loc["Factions"], [{"Name": "Talvik Free", "FactionState": "Boom", "Government": "Democracy",
                                            "Influence": 0.4, "Allegiance": "Independent",
                                            "Happiness": "$Faction_HappinessBand2;"}])
        tr = tracker()
        tr.apply(FSDJUMP)
        jump = envelopes(FSDJUMP, tr)[0]["message"]
        for k in ("JumpDist", "FuelUsed", "FuelLevel", "BoostUsed", "Wanted"):
            self.assertNotIn(k, jump)
        docked = envelopes(DOCKED)[0]["message"]
        for k in ("Wanted", "ActiveFine", "CockpitBreach"):
            self.assertNotIn(k, docked)
        self.assertEqual(docked["StationEconomies"], [{"Name": "$economy_Refinery;", "Proportion": 1.0}])
        self.assertNotIn("Progress", envelopes(HONK)[0]["message"])
        codex = envelopes(CODEX)[0]["message"]
        for k in ("IsNewEntry", "NewTraitsDiscovered", "BodyID", "BodyName"):
            self.assertNotIn(k, codex)
        self.assertNotIn("FID", json.dumps(envelopes(LOCATION)))

    def test_place_added_only_when_the_event_agrees(self):
        """A system's name and position come from the last arrival, and only for an event of that system."""
        scan = envelopes(SCAN)[0]["message"]
        self.assertEqual((scan["StarSystem"], scan["StarPos"], scan["SystemAddress"]), ("Talvik Reach", POS, 2001))
        saa = envelopes(SAA)[0]["message"]
        self.assertEqual((saa["StarSystem"], saa["StarPos"]), ("Talvik Reach", POS))
        self.assertEqual(envelopes(dict(SCAN, SystemAddress=9999)), [])        # another system's id
        self.assertEqual(envelopes(dict(SCAN, StarSystem="Elsewhere")), [])    # another system's name
        self.assertEqual(envelopes(dict(HONK, SystemName="Elsewhere")), [])
        self.assertEqual(envelopes(dict(NAV_BEACON, SystemAddress=9999)), [])
        self.assertEqual(envelopes({"timestamp": TS, "event": "Scan", "BodyName": "X", "BodyID": 1}), [])   # neither
        nowhere = tracker(FILEHEADER, LOADGAME)                                 # no arrival seen yet
        self.assertEqual(envelopes(SCAN, nowhere), [])
        self.assertEqual(envelopes(DOCKED, nowhere), [])
        bad = tracker(FILEHEADER, LOADGAME, dict(LOCATION, StarPos=[1, 2]))     # an arrival without a usable position
        self.assertIsNone(bad.system)
        self.assertEqual(envelopes(dict(LOCATION, StarPos=[1, 2]), bad), [])

    def test_codex_body(self):
        """A codex entry names its body only when the HUD names one, and numbers it only when the journal agrees."""
        tr = tracker()   # Location on Talvik Reach A 1, BodyID 4
        named = envelopes(CODEX, tr, status_body="Talvik Reach A 1")[0]
        self.assertEqual((named["message"]["BodyName"], named["message"]["BodyID"]), ("Talvik Reach A 1", 4))
        self.assertEqual(problems(named), [])
        other = envelopes(CODEX, tracker(), status_body="Talvik Reach A 2")[0]["message"]
        self.assertEqual(other["BodyName"], "Talvik Reach A 2")
        self.assertNotIn("BodyID", other)
        left = tracker(FILEHEADER, LOADGAME, LOCATION, {"timestamp": TS, "event": "LeaveBody"})
        self.assertNotIn("BodyID", envelopes(CODEX, left, status_body="Talvik Reach A 1")[0]["message"])

    def test_flags_and_test_schemas(self):
        old = tracker(dict(FILEHEADER, gameversion="3.8.0.1400"), {k: v for k, v in LOADGAME.items()
                                                                     if k not in ("Odyssey", "gameversion", "build")}, LOCATION)
        msg = envelopes(HONK, old)[0]
        self.assertEqual(msg["message"]["horizons"], True)
        self.assertNotIn("odyssey", msg["message"])    # LoadGame did not say: left out, never false
        self.assertEqual(msg["header"]["gameversion"], "3.8.0.1400")
        beta = tracker(dict(FILEHEADER, gameversion="4.3.0.0 (Beta 2)"), LOADGAME, LOCATION)
        self.assertEqual(envelopes(HONK, beta)[0]["$schemaRef"], up.EDDN_SCHEMAS + "fssdiscoveryscan/1/test")
        tr = tracker()
        self.assertEqual(up.eddn_envelope("journal/1", {}, tr, test=True)["$schemaRef"], up.EDDN_SCHEMAS + "journal/1/test")
        self.assertEqual(envelopes({"timestamp": TS, "event": "Music", "MusicTrack": "Exploration"}), [])

    def test_signals_batched(self):
        tr = tracker()
        events = [SIGNAL, dict(SIGNAL, SignalName="Hesper Dock", IsStation=True, SignalType="StationCoriolis"),
                  dict(SIGNAL, USSType="$USS_Type_MissionTarget;"), dict(SIGNAL, SystemAddress=9999)]
        schema, msg = up.fss_message(events, tr)
        env = up.eddn_envelope(schema, msg, tr)
        self.assertEqual(problems(env), [])
        self.assertEqual([s["SignalName"] for s in msg["signals"]], ["$USS;", "Hesper Dock"])
        self.assertNotIn("TimeRemaining", json.dumps(msg))
        self.assertNotIn("SystemAddress", msg["signals"][0])
        self.assertEqual((msg["StarSystem"], msg["StarPos"], msg["SystemAddress"]), ("Talvik Reach", POS, 2001))
        self.assertIsNone(up.fss_message([dict(SIGNAL, SystemAddress=9999)], tr))
        self.assertIsNone(up.fss_message([SIGNAL], tracker(FILEHEADER, LOADGAME)))

    def test_station_files(self):
        tr = tracker()
        schema, msg = up.market_message(MARKET, tr)
        self.assertEqual(problems(up.eddn_envelope(schema, msg, tr)), [])
        self.assertEqual(msg["commodities"][0], {"name": "gold", "meanPrice": 47609, "buyPrice": 0, "stock": 0,
                                                 "stockBracket": 0, "sellPrice": 47000, "demand": 1500, "demandBracket": 2})
        self.assertEqual((msg["commodities"][1]["name"], msg["systemName"], msg["stationName"], msg["marketId"],
                          msg["stationType"]), ("hydrogenfuel", "Talvik Reach", "Hesper Dock", 3200001, "Coriolis"))
        self.assertIsNone(up.market_message(dict(MARKET, Items=[]), tr))
        self.assertIsNone(up.market_message(dict(MARKET, Items=[{"Name": "$gold_name;"}]), tr))
        self.assertIsNone(up.market_message({k: v for k, v in MARKET.items() if k != "StarSystem"}, tr))
        schema, msg = up.outfitting_message(OUTFITTING, tr)
        self.assertEqual(problems(up.eddn_envelope(schema, msg, tr)), [])
        self.assertEqual(msg["modules"], ["hpt_pulselaser_fixed_small", "int_powerplant_size2_class1",
                                          "sidewinder_armour_grade1"])
        self.assertIsNone(up.outfitting_message(dict(OUTFITTING, Items=[OUTFITTING["Items"][4]]), tr))
        schema, msg = up.shipyard_message(SHIPYARD, tr)
        self.assertEqual(problems(up.eddn_envelope(schema, msg, tr)), [])
        self.assertEqual((msg["ships"], msg["allowCobraMkIV"]), (["eagle", "sidewinder"], False))
        self.assertIsNone(up.shipyard_message(dict(SHIPYARD, PriceList=[]), tr))
        schema, msg = up.navroute_message(NAVROUTE, tr)
        self.assertEqual(problems(up.eddn_envelope(schema, msg, tr)), [])
        self.assertEqual(len(msg["Route"]), 2)
        self.assertIsNone(up.navroute_message(dict(NAVROUTE, Route=[]), tr))
        schema, msg = up.fcmaterials_message(FCMATERIALS, tr)
        self.assertEqual(problems(up.eddn_envelope(schema, msg, tr)), [])
        self.assertEqual(msg["Items"], [{"id": 128961524, "Name": "$tacticalplans_name;", "Price": 5000, "Stock": 0,
                                         "Demand": 10}])


class LiveOnly(unittest.TestCase):
    def test_only_what_is_written_from_now_on(self):
        """What the journal held at start is read for the state and never sent; a line written after is."""
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION, HONK)
        u = uplink(g)
        u.poll(NOW, 0)
        self.assertEqual(bodies(u), [])
        self.assertEqual((u.tracker.cmdr, u.tracker.system["name"]), ("Sample Pilot", "Talvik Reach"))
        g.write(SCAN)
        with open(g.path, "a", encoding="utf-8") as f:
            f.write(line(ALL_FOUND)[:40])     # the game is mid-line
        u.poll(NOW + 1, 1)
        self.assertEqual([b["message"]["event"] for b in bodies(u)], ["Scan"])
        self.assertEqual(problems(bodies(u)[0]), [])
        with open(g.path, "a", encoding="utf-8") as f:
            f.write(line(ALL_FOUND)[40:] + "\n")
        u.poll(NOW + 2, 2)
        self.assertEqual([b["message"]["event"] for b in bodies(u)], ["Scan", "FSSAllBodiesFound"])

    def test_an_old_line_is_history(self):
        """A journal copied into the folder, or one being caught up on: its events are not news."""
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION)
        u = uplink(g)
        u.poll(NOW, 0)
        old = iso_ts(NOW - up.LIVE_S - 5)
        g.write(at(SCAN, old), at({"event": "garbage"}, None))
        g.write(at(FILEHEADER, old), at(LOADGAME, old), at(LOCATION, old), at(HONK, old),
                path=os.path.join(g.dir, "Journal.2020-01-01T000000.01.log"))
        u.poll(NOW, 1)
        self.assertEqual(bodies(u), [])
        g.write(at(SCAN, iso_ts(NOW - up.LIVE_S + 5)))
        u.poll(NOW, 2)
        self.assertEqual(len(bodies(u)), 1)

    def test_a_new_journal_is_followed(self):
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION)
        u = uplink(g)
        u.poll(NOW, 0)
        nxt = os.path.join(g.dir, "Journal.2026-10-07T120000.01.log")
        g.write(FILEHEADER, dict(LOADGAME, Commander="Second Pilot"), LOCATION, HONK, path=nxt)
        u.poll(NOW, 1)
        self.assertEqual([b["header"]["uploaderID"] for b in bodies(u)], ["Second Pilot", "Second Pilot"])
        g.write(SCAN, path=nxt)
        u.poll(NOW, 2)
        self.assertEqual(len(bodies(u)), 3)

    def test_no_commander_no_upload(self):
        g = Game(self)
        g.write(FILEHEADER)
        u = uplink(g)
        u.poll(NOW, 0)
        g.write(LOCATION)        # before LoadGame named the commander
        u.poll(NOW, 1)
        self.assertEqual(bodies(u), [])

    def test_signals_follow_the_arrival(self):
        """Odyssey writes a system's signals before the jump that arrived there: they go out as one message, with
        the new system's name; a run seen while idle goes out after a moment."""
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION)
        u = uplink(g)
        u.poll(NOW, 0)
        there = dict(SIGNAL, SystemAddress=3001)
        g.write(there, dict(there, SignalName="Beacon"), FSDJUMP)
        u.poll(NOW, 1)
        made = [b for b in bodies(u) if b["message"]["event"] == "FSSSignalDiscovered"]
        self.assertEqual(len(made), 1)
        self.assertEqual((made[0]["message"]["StarSystem"], len(made[0]["message"]["signals"])), ("Ossia", 2))
        self.assertEqual(problems(made[0]), [])
        g.write(dict(there, SignalName="Later"))
        u.poll(NOW, 2)
        self.assertEqual(len(bodies(u)), 2)      # the jump and its signals; the new run waits
        u.poll(NOW, 2 + up.FSS_IDLE_S)
        self.assertEqual(bodies(u)[-1]["message"]["signals"][0]["SignalName"], "Later")
        g.write(SIGNAL, at({"event": "Music", "MusicTrack": "x"}))   # another system's signal, then anything else
        u.poll(NOW, 9)
        self.assertEqual(len(bodies(u)), 3)      # dropped: it is not this system's

    def test_station_files_follow_their_event(self):
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION, DOCKED)
        g.file("Market.json", at(MARKET, iso_ts(NOW - 900)))     # the last station's, still on disk
        u = uplink(g)
        u.poll(NOW, 0)
        g.write({"timestamp": TS, "event": "Market", "MarketID": 3200001, "StationName": "Hesper Dock",
                 "StarSystem": "Talvik Reach"})
        u.poll(NOW, 1)
        self.assertEqual(bodies(u), [])          # the file is not this event's yet
        g.file("Market.json", MARKET)
        u.poll(NOW, 2)
        self.assertEqual([b["$schemaRef"] for b in bodies(u)], [up.EDDN_SCHEMAS + "commodity/3"])
        self.assertEqual(problems(bodies(u)[0]), [])
        later = iso_ts(NOW + 30)
        g.write(at({"event": "Market", "MarketID": 3200001}, later))
        g.file("Market.json", at(MARKET, later))
        u.poll(NOW + 30, 3)
        self.assertEqual(len(bodies(u)), 1)      # the same prices: nothing new to tell
        for name, content in (("Outfitting", OUTFITTING), ("Shipyard", SHIPYARD), ("NavRoute", NAVROUTE)):
            g.write({k: v for k, v in content.items() if k in ("timestamp", "event", "MarketID")})
            g.file(name + ".json", content)
        u.poll(NOW, 4)
        self.assertEqual([b["$schemaRef"].rsplit("/", 2)[-2] for b in bodies(u)],
                         ["commodity", "outfitting", "shipyard", "navroute"])
        g.write(at({"event": "Shipyard", "MarketID": 1}, iso_ts(NOW + 60)))   # a file that never comes
        u.poll(NOW + 60, 5)
        self.assertEqual(len(u.files), 1)
        u.poll(NOW + 60, 5 + up.FILE_WAIT_S + 1)
        self.assertEqual((u.files, len(bodies(u))), ([], 4))

    def test_off_means_off(self):
        """The default: nothing switched on, so no task, no request, nothing queued."""
        st = ed_outrider.settings_from({}, ARGS, None, ([], []))["uploads"]
        self.assertEqual(st, {"eddn": False, "eddn_test": False, "edsm": False, "edsm_commander": "", "edsm_api_key": "",
                              "inara": False, "inara_api_key": ""})
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION)
        made = []
        u = up.Uplink(st, [g.dir])
        self.assertFalse(u.active)
        asyncio.run(u.run(session_factory=lambda: made.append(1)))   # returns at once, makes no session
        self.assertEqual(made, [])
        self.assertEqual(u.status_line(), "off ([uploads]): nothing is sent anywhere")
        sim = up.Uplink({"eddn": True, "edsm": True, "edsm_api_key": "k", "inara": True, "inara_api_key": "k"}, [g.dir],
                        off="--simulate")
        self.assertFalse(sim.active)
        self.assertEqual((sim.status_line(), sim.info()["off"]), ("off (--simulate)", "--simulate"))
        sim.poll(NOW, 0)
        g.write(SCAN)
        sim.poll(NOW, 1)
        self.assertEqual((len(sim.eddn.queue), len(sim.edsm.queue), len(sim.inara.queue)), (0, 0, 0))


class Sending(unittest.TestCase):
    def game(self, **settings):
        g = Game(self)
        g.write(FILEHEADER, LOADGAME, LOCATION)
        u = uplink(g, **settings)
        u.poll(NOW, 0)
        return g, u

    def test_eddn_answers(self):
        """200: sent. 400: the message is wrong, dropped and never sent again. No answer or a 503: kept, and nothing
        more is tried for a minute; dropped after EDDN_TRIES."""
        g, u = self.game()
        g.write(SCAN, HONK, ALL_FOUND)
        u.poll(NOW, 1)
        answers = [(200, "OK"), (400, "FAIL: Schema Validation: x"), (503, "busy")]
        s = FakeSession(lambda m, url, kw: answers.pop(0))
        asyncio.run(u.send(s, 1))
        self.assertEqual([c[:2] for c in s.calls], [("POST", up.EDDN_URL)] * 3)
        self.assertEqual(s.calls[0][2]["headers"], {"Content-Type": "application/json"})
        self.assertEqual(json.loads(s.calls[0][2]["data"])["message"]["event"], "Scan")
        self.assertEqual((u.eddn.sent, u.eddn.dropped, len(u.eddn.queue)), (1, 1, 1))
        self.assertIn("could not be reached (503)", u.eddn.info()["error"])
        self.assertTrue(any("refused a fssdiscoveryscan/1 message (400)" in line for line in u.logged))
        asyncio.run(u.send(s, 1 + up.RETRY_S - 1))
        self.assertEqual(len(s.calls), 3)                    # not within the minute
        s.answer = lambda m, url, kw: asyncio.TimeoutError()
        for i in range(up.EDDN_TRIES):
            asyncio.run(u.send(s, 1 + up.RETRY_S * (i + 1)))
        self.assertEqual((len(u.eddn.queue), u.eddn.dropped), (0, 2))
        g.write(NAV_BEACON)
        u.poll(NOW, 2000)
        s.answer = lambda m, url, kw: (200, "OK")
        asyncio.run(u.send(s, 2000))
        self.assertEqual((u.eddn.sent, u.eddn.info()["error"], u.eddn.info()["waiting"]), (2, None, 0))

    def test_eddn_test_switch(self):
        g, u = self.game(eddn_test=True)
        g.write(SCAN)
        u.poll(NOW, 1)
        self.assertEqual(bodies(u)[0]["$schemaRef"], up.EDDN_SCHEMAS + "journal/1/test")
        self.assertTrue(u.info()["eddn"]["test"])
        self.assertEqual(u.status_line(), "to EDDN (test schemas) (live play only)")

    def test_queue_bounded(self):
        g, u = self.game()
        g.write(*[dict(SCAN, BodyID=i) for i in range(up.QUEUE_MAX + 5)])
        u.poll(NOW, 1)
        self.assertEqual((len(u.eddn.queue), u.eddn.dropped), (up.QUEUE_MAX, 5))

    def test_edsm(self):
        g, u = self.game(eddn=False, edsm=True, edsm_api_key="KEY", edsm_commander="")
        music = {"timestamp": TS, "event": "Music", "MusicTrack": "Exploration"}
        g.write(music, SCAN)
        u.poll(NOW, 1)
        self.assertEqual(len(u.eddn.queue), 0)
        answers = {up.EDSM_DISCARD_URL: (200, ["Music", "Fileheader"]), up.EDSM_URL: (200, {"msgnum": 100, "msg": "OK"})}
        s = FakeSession(lambda m, url, kw: answers[url])
        asyncio.run(u.send(s, 1))
        self.assertEqual([c[:2] for c in s.calls], [("GET", up.EDSM_DISCARD_URL)])   # a scan waits for a jump to ride with
        g.write(DOCKED)
        u.poll(NOW, 2)
        asyncio.run(u.send(s, 2))
        form = s.calls[-1][2]["data"]
        self.assertEqual({k: v for k, v in form.items() if k != "message"},
                         {"commanderName": "Sample Pilot", "apiKey": "KEY", "fromSoftware": "ED Outrider CWeed14 Edition",
                          "fromSoftwareVersion": outrider.__version__, "fromGameVersion": "4.2.0.100",
                          "fromGameBuild": "r312744/r0 "})
        sent = json.loads(form["message"])
        self.assertEqual([e["event"] for e in sent], ["Scan", "Docked"])             # Music: EDSM does not want it
        self.assertEqual({k: v for k, v in sent[0].items() if k.startswith("_")},
                         {"_systemName": "Talvik Reach", "_systemAddress": 2001, "_systemCoordinates": POS, "_shipId": 7})
        self.assertEqual((sent[1]["_stationName"], sent[1]["_marketId"]), ("Hesper Dock", 3200001))
        self.assertEqual((u.edsm.sent, len(u.edsm.queue)), (2, 0))
        g.write(FSDJUMP)
        u.poll(NOW, 3)
        asyncio.run(u.send(s, 3))
        self.assertEqual(len(s.calls), 2)                                             # not within EDSM_GAP_S
        answers[up.EDSM_URL] = (200, {"msgnum": 203, "msg": "Commander name/API Key not found"})
        asyncio.run(u.send(s, 3 + up.EDSM_GAP_S))
        self.assertIn("Commander name/API Key not found", u.edsm.info()["error"])
        g.write(DOCKED)
        u.poll(NOW, 100)
        asyncio.run(u.send(s, 100))
        self.assertEqual((len(s.calls), len(u.edsm.queue)), (3, 0))                   # refused: not asked again

    def test_edsm_waits_out_a_failure(self):
        g, u = self.game(eddn=False, edsm=True, edsm_api_key="KEY", edsm_commander="Other Name")
        g.write(FSDJUMP)
        u.poll(NOW, 1)
        s = FakeSession(lambda m, url, kw: OSError("no route"))
        asyncio.run(u.send(s, 1))
        asyncio.run(u.send(s, 30))
        self.assertEqual((len(s.calls), len(u.edsm.queue)), (1, 1))
        s.answer = lambda m, url, kw: (200, []) if m == "GET" else (200, {"msgnum": 100})
        asyncio.run(u.send(s, 1 + up.RETRY_S))
        self.assertEqual((s.calls[-1][2]["data"]["commanderName"], u.edsm.sent, u.edsm.info()["error"]),
                         ("Other Name", 1, None))

    def test_only_your_own_live_galaxy_log(self):
        """EDSM and Inara get nothing from the legacy galaxy, a beta, or another commander's ship."""
        both = dict(eddn=False, edsm=True, edsm_api_key="K", inara=True, inara_api_key="K")
        for header, extra in ((dict(FILEHEADER, gameversion="3.8.0.1400"), ()),
                              (dict(FILEHEADER, gameversion="4.3.0.0 (Beta 1)"), ()),
                              (FILEHEADER, ({"timestamp": TS, "event": "JoinACrew", "Captain": "Someone"},))):
            g = Game(self)
            g.write(header, LOADGAME, LOCATION, *extra)
            u = uplink(g, **both)
            u.poll(NOW, 0)
            g.write(FSDJUMP)
            u.poll(NOW, 1)
            self.assertEqual((len(u.edsm.queue), len(u.inara.queue)), (0, 0), header["gameversion"])

    def test_inara(self):
        g, u = self.game(eddn=False, inara=True, inara_api_key="KEY")
        g.write(dict(LOADGAME, Credits=10), dict(LOADGAME, Credits=2500000, Loan=5), FSDJUMP)
        u.poll(NOW, 1)
        reply = {"header": {"eventStatus": 200}, "events": [{"eventStatus": 200}, {"eventStatus": 400,
                                                                                  "eventStatusText": "no such ship"},
                                                           {"eventStatus": 200}]}
        s = FakeSession(lambda m, url, kw: (200, reply))
        asyncio.run(u.send(s, 1))
        sent = s.calls[0][2]["json"]
        self.assertEqual((s.calls[0][1], sent["header"]), (up.INARA_URL, {
            "appName": "ED Outrider CWeed14 Edition", "appVersion": outrider.__version__, "APIkey": "KEY",
            "commanderName": "Sample Pilot", "commanderFrontierID": "F1234567"}))
        self.assertEqual([e["eventName"] for e in sent["events"]],
                         ["setCommanderCredits", "addCommanderTravelFSDJump", "setCommanderReputationMinorFaction"])
        self.assertEqual(sent["events"][0], {"eventName": "setCommanderCredits", "eventTimestamp": TS,
                                             "eventData": {"commanderCredits": 2500000, "commanderLoan": 5}})
        self.assertEqual(sent["events"][1]["eventData"], {"starsystemName": "Ossia", "starsystemCoords": [20.0, 1.0, 44.5],
                                                          "jumpDistance": 8.6, "shipType": "krait_light", "shipGameID": 7})
        self.assertEqual((u.inara.sent, u.inara.dropped), (2, 1))
        self.assertIn("no such ship", u.inara.info()["error"])
        g.write(DOCKED)
        u.poll(NOW, 2)
        asyncio.run(u.send(s, 2))
        self.assertEqual(len(s.calls), 1)                                  # one request per INARA_GAP_S
        s.answer = lambda m, url, kw: (200, {"header": {"eventStatus": 400, "eventStatusText": "Invalid API key."}})
        asyncio.run(u.send(s, 1 + up.INARA_GAP_S))
        self.assertIn("Invalid API key.", u.inara.info()["error"])
        g.write(FSDJUMP)
        u.poll(NOW, 200)
        asyncio.run(u.send(s, 200))
        self.assertEqual((len(s.calls), len(u.inara.queue)), (2, 0))       # refused: not asked again

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
    def test_uploads_settings(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            st = up.uploads_settings({"uploads": {"eddn": "yes", "edsm": True, "inara": True, "inara_api_key": " abc ",
                                                  "edsm_commander": 5}})
        self.assertEqual(st, {"eddn": False, "eddn_test": False, "edsm": False, "edsm_commander": "", "edsm_api_key": "",
                              "inara": True, "inara_api_key": "abc"})
        for words in ("eddn = 'yes' must be true or false", "edsm = true needs edsm_api_key", "edsm_commander must be text"):
            self.assertIn(words, err.getvalue())
        self.assertEqual(up.uploads_settings({"uploads": "x"}), up.DEFAULTS)

    def test_config_round_trip(self):
        import tomllib
        cfg = {"uploads": {"eddn": True, "edsm": True, "edsm_api_key": 'k"ey', "edsm_commander": "Sample Pilot"}}
        st = ed_outrider.settings_from(cfg, ARGS, None, ([], []))
        back = tomllib.loads(ed_outrider.config_text(st))["uploads"]
        self.assertEqual(back, {"eddn": True, "eddn_test": False, "edsm": True, "edsm_commander": "Sample Pilot",
                                "edsm_api_key": 'k"ey', "inara": False, "inara_api_key": ""})

    def test_fixture_copy(self):
        """The schema copies are what the messages cite, and carry their licence."""
        self.assertTrue(os.path.exists(os.path.join(FIXTURES, "LICENSE-EDDN.txt")))
        for name in sorted(os.listdir(FIXTURES)):
            if name.endswith(".json"):
                with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
                    schema = json.load(f)
                base, version = name[:-len(".json")].split("-v")
                self.assertEqual(schema["id"].rstrip("#"), f"{up.EDDN_SCHEMAS}{base}/{version.split('.')[0]}")


if __name__ == "__main__":
    unittest.main()

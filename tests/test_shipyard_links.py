"""A ship's build as EDSY and Coriolis links (outrider/shipyard_links.py, EDMC's format), each ship's latest Loadout kept
whole in fleet_loadouts (Journals.note_fleet) and the links on the CMDR tab's ships (commander.ships)."""
import base64
import gzip
import json
import os
import sqlite3
import tempfile
import types
import unittest

from support import ed_outrider

import outrider.shipyard_links as S

# A real Loadout (2026-09-26, copied as the game wrote it): a blank ShipName, two pulse lasers with no ammo fields,
# Health and Value on most modules, the core slots after the optional ones
REAL = ('{ "timestamp":"2026-09-26T14:35:17Z", "event":"Loadout", "Ship":"explorer_nx", "ShipID":50, "ShipName":"", "ShipIdent":"BR-26E", '
        '"HullValue":160132759, "ModulesValue":10858023, "HullHealth":1.000000, "UnladenMass":1654.000000, "CargoCapacity":96, '
        '"MaxJumpRange":21.828001, "FuelCapacity":{ "Main":128.000000, "Reserve":1.140000 }, '
        '"Rebuy":8549541, "Modules":[ { "Slot":"MediumHardpoint1", "Item":"hpt_pulselaser_fixed_small", "On":true, "Priority":2, "Health":1.000000, "Value":1930 }, '
        '{ "Slot":"MediumHardpoint2", "Item":"hpt_pulselaser_fixed_small", "On":true, "Priority":2, "Health":1.000000, "Value":1930 }, '
        '{ "Slot":"Armour", "Item":"explorer_nx_armour_grade1_default", "On":true, "Priority":1, "Health":1.000000 }, '
        '{ "Slot":"PowerPlant", "Item":"int_powerplant_size8_class1", "On":true, "Priority":1, "Health":1.000000, "Value":1264681 }, '
        '{ "Slot":"MainEngines", "Item":"int_engine_size7_class1", "On":true, "Priority":2, "Health":1.000000, "Value":555632 }, '
        '{ "Slot":"FrameShiftDrive", "Item":"int_hyperdrive_overcharge_size8_class1", "On":true, "Priority":2, "Health":1.000000, "Value":6000825 }, '
        '{ "Slot":"LifeSupport", "Item":"int_lifesupport_size5_class1", "On":true, "Priority":2, "Health":1.000000, "Value":27885 }, '
        '{ "Slot":"PowerDistributor", "Item":"int_powerdistributor_size7_class1", "On":true, "Priority":2, "Health":1.000000, "Value":218617 }, '
        '{ "Slot":"Radar", "Item":"int_sensors_size8_class1", "On":true, "Priority":2, "Health":1.000000, "Value":612129 }, '
        '{ "Slot":"FuelTank", "Item":"int_fueltank_size7_class3", "On":true, "Priority":1, "Health":1.000000, "Value":1562752 }, '
        '{ "Slot":"Slot01_Size7", "Item":"int_cargorack_size6_class1", "On":true, "Priority":1, "Health":1.000000, "Value":318173 }, '
        '{ "Slot":"Slot02_Size6", "Item":"int_shieldgenerator_size6_class1", "On":true, "Priority":2, "Health":1.000000, "Value":175277 }, '
        '{ "Slot":"Slot03_Size6", "Item":"int_cargorack_size5_class1", "On":true, "Priority":1, "Health":1.000000, "Value":97899 }, '
        '{ "Slot":"Slot13_Size1", "Item":"int_supercruiseassist", "On":true, "Priority":2, "Health":1.000000, "Value":8003 }, '
        '{ "Slot":"Slot14_Size1", "Item":"int_dockingcomputer_advanced", "On":true, "Priority":2, "Health":1.000000, "Value":11852 }, '
        '{ "Slot":"PlanetaryApproachSuite", "Item":"int_planetapproachsuite_advanced", "On":true, "Priority":1, "Health":1.000000, "Value":438 }, '
        '{ "Slot":"VesselVoice", "Item":"voicepack_verity", "On":true, "Priority":1, "Health":1.000000 }, '
        '{ "Slot":"ShipCockpit", "Item":"explorer_nx_cockpit", "On":true, "Priority":1, "Health":1.000000 }, '
        '{ "Slot":"CargoHatch", "Item":"modularcargobaydoor", "On":true, "Priority":2, "Health":1.000000 } ] }')
# EDMC's order: hardpoints, the core slots in its order, the optional slots by name, then the rest by name
ORDER = ["MediumHardpoint1", "MediumHardpoint2", "ShipCockpit", "CargoHatch", "Armour", "PowerPlant", "MainEngines", "FrameShiftDrive",
         "LifeSupport", "PowerDistributor", "Radar", "FuelTank", "Slot01_Size7", "Slot02_Size6", "Slot03_Size6", "Slot13_Size1",
         "Slot14_Size1", "PlanetaryApproachSuite", "VesselVoice"]


def data_of(url, base):
    assert url.startswith(base), url
    return url[len(base):]


def expected(line):
    """What EDMC hands its plugins for this line, worked out here apart from the code under test."""
    ev = json.loads(line)
    mods = {m["Slot"]: {k: v for k, v in m.items() if k not in ("Health", "Value")} for m in ev["Modules"]}
    out = {"timestamp": ev["timestamp"], "event": "Loadout", "Ship": ev["Ship"].lower(), "ShipID": ev["ShipID"],
           "Modules": [mods[s] for s in ORDER]}
    if ev.get("ShipName", "").strip():
        out["ShipName"] = ev["ShipName"]
    if ev.get("ShipIdent"):
        out["ShipIdent"] = ev["ShipIdent"]
    return out


def setup(test, events=()):
    db = ed_outrider.open_db(":memory:")
    test.addCleanup(db.close)
    j = ed_outrider.Journals(db)
    for e in events:
        j.handle(e)
    return j, ed_outrider.State(db, j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)


class Links(unittest.TestCase):
    def test_a_real_loadout_decodes_back(self):
        """Both links carry the same data: URL-safe base64 of gzipped JSON, which decodes to the Loadout as EDMC shapes
        it (no Health, Value or hull figures; the empty ShipName left out; EDMC's slot order)."""
        got = S.links(json.loads(REAL))
        edsy, cor = data_of(got["edsy"], "https://edsy.org/#/I="), data_of(got["coriolis"], "https://coriolis.io/import?data=")
        self.assertEqual(edsy, cor)
        self.assertRegex(edsy, r"^[A-Za-z0-9_-]+(%3D)*$")                    # '=' written %3D, nothing else to escape
        build = S.decode(edsy)
        self.assertEqual(build, expected(REAL))
        self.assertEqual([m["Slot"] for m in build["Modules"]], ORDER)
        self.assertEqual((build["ShipIdent"], "ShipName" in build, "HullValue" in build), ("BR-26E", False, False))
        # gunzipped by hand too: compact JSON with sorted keys, as EDMC writes it
        raw = base64.urlsafe_b64decode(edsy.replace("%3D", "="))
        self.assertEqual(gzip.decompress(raw).decode("utf-8"), json.dumps(expected(REAL), ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    def test_the_same_build_the_same_link(self):
        """The gzip header's time is 0 (EDMC's is the click's), so a build always gives the same text."""
        a = S.links(json.loads(REAL))
        self.assertEqual(a, S.links(json.loads(REAL)))
        raw = base64.urlsafe_b64decode(data_of(a["edsy"], S.EDSY_URL).replace("%3D", "="))
        self.assertEqual(raw[:10].hex(), "1f8b08000000000002ff")              # gzip, deflate, no name, mtime 0, level 9

    def test_edmc_reshaping(self):
        """A laser's AmmoInClip/AmmoInHopper of 1 and 1 dropped (not on a tiny hardpoint, not other counts); "$..._name;"
        symbols and capitals canonical; a " " ShipName left out, a real one kept; a duplicate slot the later one."""
        ev = {"timestamp": "2026-10-14T10:00:00Z", "event": "Loadout", "Ship": "Krait_Light", "ShipID": 7, "ShipName": " ", "ShipIdent": "",
              "Modules": [{"Slot": "LargeHardpoint1", "Item": "$Hpt_BeamLaser_Gimbal_Large_name;", "AmmoInClip": 1, "AmmoInHopper": 1},
                          {"Slot": "TinyHardpoint1", "Item": "hpt_heatsinklauncher_turret_tiny", "AmmoInClip": 1, "AmmoInHopper": 1},
                          {"Slot": "MediumHardpoint1", "Item": "hpt_multicannon_fixed_medium", "AmmoInClip": 100, "AmmoInHopper": 2100},
                          {"Slot": "Armour", "Item": "a"}, {"Slot": "Armour", "Item": "krait_light_armour_grade3"}, "junk", {"Item": "no slot"}]}
        b = S.loadout(ev)
        self.assertEqual(b, {"timestamp": "2026-10-14T10:00:00Z", "event": "Loadout", "Ship": "krait_light", "ShipID": 7, "Modules": [
            {"Slot": "LargeHardpoint1", "Item": "hpt_beamlaser_gimbal_large"},
            {"Slot": "MediumHardpoint1", "Item": "hpt_multicannon_fixed_medium", "AmmoInClip": 100, "AmmoInHopper": 2100},
            {"Slot": "TinyHardpoint1", "Item": "hpt_heatsinklauncher_turret_tiny", "AmmoInClip": 1, "AmmoInHopper": 1},
            {"Slot": "Armour", "Item": "krait_light_armour_grade3"}]})
        self.assertEqual(S.loadout(dict(ev, ShipName="Sample Ship"))["ShipName"], "Sample Ship")
        self.assertEqual(ev["Modules"][0]["AmmoInClip"], 1)                  # the line itself untouched
        self.assertIsNone(S.links({"event": "Loadout", "Ship": "sidewinder"}))   # no module list: no link
        self.assertIsNone(S.links(None))


class Kept(unittest.TestCase):
    def test_the_latest_loadout_kept_whole_and_linked(self):
        """fleet_loadouts keeps each ship's latest Loadout line whole; the CMDR tab's ships carry its links (the one you
        fly and a stored one), a ship never boarded none; an older Loadout read later (a legacy folder) changes nothing."""
        real = json.loads(REAL)
        older = dict(real, timestamp="2026-09-20T10:00:00Z", Modules=real["Modules"][:3])
        stored = {"timestamp": "2026-09-26T15:00:00Z", "event": "StoredShips", "StationName": "Port", "StarSystem": "Sol",
                  "ShipsHere": [{"ShipID": 51, "ShipType": "asp", "Value": 1000}], "ShipsRemote": []}
        swap = {"timestamp": "2026-09-26T15:01:00Z", "event": "ShipyardSwap", "ShipType": "asp", "ShipID": 51,
                "StoreOldShip": "Explorer_NX", "StoreShipID": 50, "MarketID": 1}
        login = {"timestamp": "2026-09-26T14:30:00Z", "event": "LoadGame", "Commander": "Tester", "Ship": "explorer_nx", "ShipID": 50}
        j, state = setup(self, [login, real, older, stored])
        kept = state.db.execute("SELECT loadout FROM fleet_loadouts WHERE ship_id=50").fetchone()[0]
        self.assertEqual(json.loads(kept), real)
        rows = {s["id"]: s for s in state.commander_fleet()["ships"]}
        self.assertEqual(S.decode(data_of(rows[50]["links"]["edsy"], S.EDSY_URL)), expected(REAL))
        self.assertEqual(S.decode(data_of(rows[50]["links"]["coriolis"], S.CORIOLIS_URL)), expected(REAL))
        self.assertIsNone(rows[51]["links"])                                 # listed, never boarded
        j.handle(swap)
        j.handle({"timestamp": "2026-09-26T15:01:05Z", "event": "Loadout", "Ship": "asp", "ShipID": 51, "ShipName": "", "ShipIdent": "",
                  "Modules": [{"Slot": "Armour", "Item": "asp_armour_grade1", "Health": 1.0}]})
        rows = {s["id"]: s for s in state.commander_fleet()["ships"]}
        self.assertTrue(rows[51]["current"])
        self.assertEqual(S.decode(data_of(rows[51]["links"]["edsy"], S.EDSY_URL))["Modules"], [{"Slot": "Armour", "Item": "asp_armour_grade1"}])
        self.assertEqual(S.decode(data_of(rows[50]["links"]["edsy"], S.EDSY_URL)), expected(REAL))   # stored now, still linked
        prof = {s["id"]: s for s in state.commander_profile()["profile"]["fleet"]}
        self.assertEqual(prof[50]["links"], rows[50]["links"])               # the CMDR tab's Fleet list has them too
        # journal-derived: a re-read's reset clears it with the rest of the row
        self.assertIn("DELETE FROM fleet_loadouts", ed_outrider.RESET_JOURNAL_DATA)

    def test_an_older_database_gets_the_column(self):
        """A database from before: open_db adds fleet_loadouts.loadout (filled by the release's one re-read)."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.sqlite")
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE fleet_loadouts (ship_id INTEGER PRIMARY KEY, name TEXT, ship_type TEXT, ident TEXT, ts TEXT, "
                       "figures TEXT, value INTEGER)")
            db.commit()
            db.close()
            db = ed_outrider.open_db(path)
            try:
                self.assertIn("loadout", {r["name"] for r in db.execute("PRAGMA table_info(fleet_loadouts)")})
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()

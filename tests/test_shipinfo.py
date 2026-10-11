"""The Ship view (outrider/shipinfo.py, State.ship_summary, GET /api/ship): the Loadout as figures and modules with
their engineering. A made-up ship; the journals are written to a temporary folder."""
import asyncio
import base64
import gzip
import json
import os
import types
import unittest

from support import ed_outrider, temp_dir

import outrider.shipinfo as shipinfo

FSD = {"Slot": "FrameShiftDrive", "Item": "Int_Hyperdrive_Overcharge_Size5_Class5", "On": True, "Priority": 0, "Health": 0.75,
       "Value": 5103953, "Engineering": {
           "Engineer": "Felicity Farseer", "EngineerID": 300100, "BlueprintID": 128673694, "BlueprintName": "FSD_LongRange",
           "Level": 5, "Quality": 0.87, "ExperimentalEffect": "special_fsd_heavy", "ExperimentalEffect_Localised": "Mass Manager",
           "Modifiers": [{"Label": "Mass", "Value": 26.0, "OriginalValue": 20.0, "LessIsGood": 1},
                         {"Label": "FSDOptimalMass", "Value": 1692.6, "OriginalValue": 1050.0, "LessIsGood": 0},
                         {"Label": "PowerDraw", "Value": 0.5, "OriginalValue": 0.5, "LessIsGood": 1},
                         {"Label": "Integrity", "Value": 96.0, "OriginalValue": 0, "LessIsGood": 0},
                         {"Label": "DamageType", "ValueStr": "$Thermic;", "ValueStr_Localised": "Thermal"},
                         {"Value": 1}, "junk"]}}
LOADOUT = {"timestamp": "2026-10-11T12:00:00Z", "event": "Loadout", "Ship": "krait_light", "ShipID": 7, "ShipName": "Sample Ship",
           "ShipIdent": "SP-01", "HullValue": 40000000, "ModulesValue": 60000000, "HullHealth": 0.98, "UnladenMass": 410.5,
           "CargoCapacity": 8, "MaxJumpRange": 58.4, "FuelCapacity": {"Main": 32.0, "Reserve": 0.63}, "Rebuy": 5000000, "Hot": True,
           "Modules": [
               {"Slot": "MediumHardpoint1", "Item": "hpt_pulselaser_gimbal_medium", "On": False, "Priority": 2, "Health": 1.0},
               {"Slot": "LargeHardpoint1", "Item": "hpt_multicannon_turret_large", "On": True, "Priority": 0, "Health": 1.0, "AmmoInHopper": 90},
               {"Slot": "TinyHardpoint2", "Item": "hpt_shieldbooster_size0_class5", "On": True, "Priority": 1, "Health": 1.0},
               {"Slot": "Armour", "Item": "krait_light_armour_grade1", "On": True, "Priority": 1, "Health": 1.0},
               FSD,
               {"Slot": "PowerPlant", "Item": "int_powerplant_size6_class2", "On": True, "Priority": 0, "Health": 1.0},
               {"Slot": "Slot01_Size6", "Item": "int_fuelscoop_size6_class5", "On": True, "Priority": 0, "Health": 1.0},
               {"Slot": "Military01", "Item": "int_hullreinforcement_size4_class2", "On": True, "Priority": 0, "Health": 1.0},
               {"Slot": "Slot04_Size3", "Item": "int_newgadget_size3_class1", "On": True, "Priority": 0, "Health": 1.0},
               {"Slot": "PaintJob", "Item": "paintjob_krait_light_blackfriday_01"}, {"Slot": "Decal1", "Item": "decal_explorer_elite"},
               {"Slot": "ShipCockpit", "Item": "krait_light_cockpit"}, {"Slot": "CargoHatch", "Item": "modularcargobaydoor"},
               {"Slot": "PlanetaryApproachSuite", "Item": "int_planetapproachsuite_advanced"}, {"Slot": "VesselVoice", "Item": "voicepack_verity"},
               {"Slot": "Slot09_Size1"}, "junk"]}


def write(folder, name, *events):
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
        for ev in events:
            f.write(json.dumps(ev, separators=(", ", ":")) + "\n")


class Summary(unittest.TestCase):
    def test_names(self):
        for item, want in (("hpt_pulselaser_gimbal_medium", ("Pulse Laser", 2, None, "Gimballed")),
                           ("Hpt_MultiCannon_Turret_Large", ("Multi-Cannon", 3, None, "Turreted")),
                           ("hpt_beamlaser_fixed_huge", ("Beam Laser", 4, None, "Fixed")),
                           ("hpt_shieldbooster_size0_class5", ("Shield Booster", 0, "A", None)),
                           ("int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii", ("Frame Shift Drive (SCO)", 8, "A", None)),
                           ("int_hyperdrive_size5_class5", ("Frame Shift Drive", 5, "A", None)),
                           ("int_shieldgenerator_size5_class3_fast", ("Bi-Weave Shield Generator", 5, "C", None)),
                           ("int_shieldgenerator_size6_class5_strong", ("Prismatic Shield Generator", 6, "A", None)),
                           ("int_shieldgenerator_size4_class2", ("Shield Generator", 4, "D", None)),
                           ("int_dronecontrol_collection_size3_class4", ("Collector Limpet Controller", 3, "B", None)),
                           ("int_guardianfsdbooster_size5", ("Guardian FSD Booster", 5, None, None)),
                           ("krait_light_armour_grade1", ("Lightweight Alloy", None, None, None)),
                           ("anaconda_armour_reactive", ("Reactive Surface Composite", None, None, None)),
                           ("int_newgadget_size3_class1", ("Newgadget", 3, "E", None)), ("", ("?", None, None, None))):
            self.assertEqual(shipinfo.module_name(item), want, item)
        self.assertEqual([shipinfo.words(x) for x in ("FSDOptimalMass", "DamagePerSecond", "FSD_LongRange", "Mass", None)],
                         ["FSD Optimal Mass", "Damage Per Second", "FSD Long Range", "Mass", ""])
        self.assertEqual([shipinfo.slot_group(s) for s in ("PowerPlant", "TinyHardpoint3", "HugeHardpoint1", "Slot03_Size5", "Military02",
                                                           "PaintJob", "Decal2", "ShipCockpit", "CargoHatch", "WeaponColour", "", None)],
                         [("Core internals", "Power Plant"), ("Utility mounts", "Utility 3"), ("Hardpoints", "Huge 1"),
                          ("Optional internals", "Size 5"), ("Optional internals", "Military"), None, None, None, None, None, None, None])

    def test_engineering(self):
        e = shipinfo.engineering(FSD["Engineering"])
        self.assertEqual((e["blueprint"], e["level"], e["quality"], e["experimental"], e["engineer"]),
                         ("Long Range", 5, 0.87, "Mass Manager", "Felicity Farseer"))
        self.assertEqual(e["mods"], [
            {"label": "Mass", "value": 26.0, "original": 20.0, "pct": 30.0, "good": False},             # heavier: worse
            {"label": "FSD Optimal Mass", "value": 1692.6, "original": 1050.0, "pct": 61.2, "good": True},
            {"label": "Power Draw", "value": 0.5, "original": 0.5, "pct": 0.0, "good": None},           # unchanged
            {"label": "Integrity", "value": 96.0, "original": 0, "pct": None, "good": True},            # no stock value to compare
            {"label": "Damage Type", "text": "Thermal", "value": None, "original": None, "pct": None, "good": None}])
        self.assertIsNone(shipinfo.engineering(None))
        bare = shipinfo.engineering({"BlueprintName": "Weapon_Overcharged", "ExperimentalEffect": "special_auto_loader"})
        self.assertEqual((bare["blueprint"], bare["experimental"], bare["level"], bare["mods"]), ("Overcharged", "auto loader", None, []))

    def test_summary(self):
        s = shipinfo.summary(LOADOUT)
        self.assertEqual({k: s[k] for k in ("ship_id", "type", "name", "ident", "hull_value", "modules_value", "rebuy", "hull_health",
                                            "unladen", "cargo", "max_range", "fuel_main", "fuel_reserve", "hot", "engineered", "count", "ts")},
                         {"ship_id": 7, "type": "krait_light", "name": "Sample Ship", "ident": "SP-01", "hull_value": 40000000,
                          "modules_value": 60000000, "rebuy": 5000000, "hull_health": 0.98, "unladen": 410.5, "cargo": 8,
                          "max_range": 58.4, "fuel_main": 32.0, "fuel_reserve": 0.63, "hot": True, "engineered": 1, "count": 9,
                          "ts": "2026-10-11T12:00:00Z"})
        self.assertEqual([(g["name"], [(m["slot_label"], m["name"]) for m in g["modules"]]) for g in s["groups"]], [
            ("Hardpoints", [("Large 1", "Multi-Cannon"), ("Medium 1", "Pulse Laser")]),               # the largest first
            ("Utility mounts", [("Utility 2", "Shield Booster")]),
            ("Core internals", [("Power Plant", "Power Plant"), ("Frame Shift Drive", "Frame Shift Drive (SCO)"),
                                ("Bulkheads", "Lightweight Alloy")]),                                    # the game's own order
            ("Optional internals", [("Size 6", "Fuel Scoop"), ("Size 3", "Newgadget"), ("Military", "Hull Reinforcement Package")])])
        laser = s["groups"][0]["modules"][1]
        self.assertEqual((laser["on"], laser["priority"], laser["mount"], laser["size"], laser["engineering"]), (False, 3, "Gimballed", 2, None))
        fsd = s["groups"][2]["modules"][1]
        self.assertEqual((fsd["health"], fsd["rating"], fsd["value"], fsd["engineering"]["level"]), (0.75, "A", 5103953, 5))
        self.assertEqual(s["groups"][0]["modules"][0]["ammo"], 90)
        empty = shipinfo.summary({"event": "Loadout", "Ship": "sidewinder", "ShipID": 1})
        self.assertEqual((empty["groups"], empty["count"], empty["name"], empty["max_range"]), ([], 0, None, None))

    def test_links_carry_the_loadout(self):
        """EDSY and Coriolis take the Loadout event itself in the address: gzipped, URL-safe base64."""
        ln = shipinfo.links(LOADOUT)
        self.assertTrue(ln["edsy"].startswith("https://edsy.org/#/I="))
        self.assertTrue(ln["coriolis"].startswith("https://coriolis.io/import?data="))
        data = ln["edsy"].split("#/I=", 1)[1]
        self.assertEqual(data, ln["coriolis"].split("data=", 1)[1])
        self.assertNotIn("=", data)                                    # padding is written %3D
        back = json.loads(gzip.decompress(base64.urlsafe_b64decode(data.replace("%3D", "="))))
        self.assertEqual(back, LOADOUT)
        self.assertEqual(shipinfo.links(LOADOUT), ln)                   # the same ship, the same address


class Journals(unittest.TestCase):
    def test_latest_loadout(self):
        d = temp_dir(self)
        other = dict(LOADOUT, ShipID=9, Ship="mandalay", timestamp="2026-10-11T13:00:00Z")
        older = dict(LOADOUT, timestamp="2026-10-10T09:00:00Z", ShipName="Old Name")
        write(d, "Journal.2026-10-10T090000.01.log", {"event": "Fileheader"}, older)
        os.utime(os.path.join(d, "Journal.2026-10-10T090000.01.log"), (1000, 1000))
        write(d, "Journal.2026-10-11T120000.01.log", {"event": "Fileheader"}, LOADOUT, {"event": "Music"}, other,
              {"event": "Loadout", "ShipID": 7, "Modules": "none"})
        with open(os.path.join(d, "Journal.2026-10-11T120000.01.log"), "a", encoding="utf-8") as f:
            f.write('{ "timestamp":"x", "event":"Loadout", "ShipID":7, "Modu')      # the game is mid-line
        self.assertEqual(shipinfo.latest_loadout([d])["ShipID"], 9)                 # the newest of any ship
        self.assertEqual(shipinfo.latest_loadout([d], 7)["ShipName"], "Sample Ship")   # this ship's newest, not the older file's
        self.assertIsNone(shipinfo.latest_loadout([d], 99))
        self.assertIsNone(shipinfo.latest_loadout([os.path.join(d, "missing")]))
        self.assertEqual(shipinfo.latest_loadout([d, d], 7)["timestamp"], "2026-10-11T12:00:00Z")

    def test_state_and_endpoint(self):
        from aiohttp.test_utils import TestClient, TestServer
        d = temp_dir(self)
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        j = ed_outrider.Journals(db)
        state = ed_outrider.State(db, j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.assertEqual(state.ship_summary([d]), {"ship": None})
        write(d, "Journal.2026-10-11T120000.01.log", LOADOUT, dict(LOADOUT, ShipID=9, Ship="mandalay", ShipName="Other"))
        self.assertEqual(state.ship_summary([d])["ship"]["name"], "Other")           # no current ship known: the newest
        j.ship = {"ship_id": 7}
        self.assertEqual(state.ship_summary([d])["ship"]["name"], "Sample Ship")     # the ship you are in
        j.ship = {"ship_id": 55}
        self.assertEqual(state.ship_summary([d])["ship"]["name"], "Other")           # no Loadout of it yet: the newest

        async def go():
            with unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", [d]):
                async with TestClient(TestServer(ed_outrider.make_app(state))) as c:
                    r = await c.get("/api/ship")
                    cross = (await c.get("/api/ship", headers={"Sec-Fetch-Site": "cross-site"})).status
                    return r.status, await r.json(), cross
        import unittest.mock
        status, out, cross = asyncio.run(go())
        self.assertEqual((status, out["ship"]["type"], len(out["ship"]["groups"]), cross), (200, "mandalay", 4, 403))


if __name__ == "__main__":
    unittest.main()

"""This fork's engineers beside upstream's CMDR tab (outrider/engineers.py, GET /api/engineers, /api/engineers/ship,
POST /api/engineers/tour): where each works and how far, the ship you fly as the Engineering tab's picks, the trip.
No request leaves the tests: Spansh, the position and the journals are fakes."""
import asyncio
import json
import types
import unittest

from support import ed_outrider

import outrider.commander as commander
import outrider.engineers as E


class Where(unittest.TestCase):
    def test_where_the_engineers_are(self):
        """Every engineer with the system of their workshop, by any spelling the journal uses; one the table does not
        know is still listed, with no system."""
        self.assertEqual(E.engineer_system("Tod 'The Blaster' McQuinn"), ("Wolf 397", "ship", "bubble"))
        self.assertEqual(E.engineer_system("felicity farseer")[0], "Deciat")
        self.assertIsNone(E.engineer_system("Nobody"))
        rows = E.engineer_list({"Felicity Farseer": {"progress": "Unlocked", "rank": 5}, "Domino Green": {"progress": "Invited", "rank": None},
                                "New Engineer": {"progress": "Known", "rank": None}})
        by = {r["name"]: r for r in rows}
        self.assertEqual(len(rows), len(E.ENGINEER_SYSTEMS) + 1)
        self.assertEqual((by["Felicity Farseer"]["system"], by["Felicity Farseer"]["progress"], by["Felicity Farseer"]["rank"]), ("Deciat", "Unlocked", 5))
        self.assertEqual((by["Domino Green"]["kind"], by["Domino Green"]["progress"]), ("suit & weapon", "Invited"))
        self.assertEqual((by["New Engineer"]["system"], by["Petra Olmanova"]["region"], by["Bill Turner"]["progress"]), (None, "Colonia", None))
        kinds = [r["kind"] for r in rows]
        self.assertEqual(kinds[:kinds.index("suit & weapon")], ["ship"] * len([k for k in kinds if k == "ship"]))   # the ship engineers first
        self.assertEqual(len({v[0] for v in E.ENGINEER_SYSTEMS.values()}), len(E.ENGINEER_SYSTEMS))                 # one workshop a system

    def test_every_engineer_in_upstreams_table_has_a_workshop(self):
        for b in commander.load_blueprints() or []:
            for g in b["grades"].values():
                for e in g["engineers"]:
                    self.assertIsNotNone(E.engineer_system(e), e)


class Distances(unittest.TestCase):
    """How far each engineer's system is: known here (find_local), else asked of Spansh once and kept."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.asked, self.down = [], None

        async def system_record(name):
            self.asked.append(name)
            if self.down:
                raise self.down
            return {"name": name, "id64": 1, "x": 100.0, "y": 0.0, "z": 0.0} if name != "Wyrd" else None
        here = {"Sol": (10, "Sol", 0.0, 0.0, 0.0, "visited"), "Deciat": (11, "Deciat", 3.0, 4.0, 0.0, "visited")}
        self.state = types.SimpleNamespace(db=self.db, find_local=lambda n: here.get(n),
                                           spansh=types.SimpleNamespace(system_record=system_record),
                                           journals=types.SimpleNamespace(pos={"name": "Sol", "x": 0.0, "y": 0.0, "z": 0.0}))

    def test_distances(self):
        out = asyncio.run(E.engineer_distances(self.state, gap=0))
        systems = {v[0] for v in E.ENGINEER_SYSTEMS.values()}
        self.assertEqual((out["from"], out["error"], out["missing"]), ("Sol", None, ["Wyrd"]))
        self.assertEqual((out["distances"]["Sol"], out["distances"]["Deciat"], out["distances"]["Khun"]), (0.0, 5.0, 100.0))
        self.assertEqual(set(self.asked), systems - {"Sol", "Deciat"})              # the ones known here are not asked
        self.asked.clear()
        self.state.journals.pos = {"name": "Far", "x": 100.0, "y": 0.0, "z": 0.0}
        again = asyncio.run(E.engineer_distances(self.state, gap=0))
        self.assertEqual((self.asked, again["distances"]["Khun"], again["distances"]["Sol"]), (["Wyrd"], 0.0, 100.0))   # kept
        self.state.journals.pos = None
        self.assertEqual(asyncio.run(E.engineer_distances(self.state, gap=0))["distances"], {})

    def test_spansh_down(self):
        self.down = OSError("no route to host")
        out = asyncio.run(E.engineer_distances(self.state, gap=0))
        self.assertIn("Spansh could not be asked", out["error"])
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(set(out["distances"]), {"Sol", "Deciat"})


class LoadMyShip(unittest.TestCase):
    LOADOUT = {"event": "Loadout", "Ship": "krait_mkii", "ShipName": "Sample", "Modules": [
        {"Slot": "PowerPlant", "Item": "int_powerplant_size7_class5", "Engineering": {"BlueprintName": "PowerPlant_Boosted", "Level": 5,
                                                                                   "Quality": 0.9, "ExperimentalEffect_Localised": "Thermal Spread"}},
        {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size5_class5", "Engineering": {"BlueprintName": "FSD_LongRange", "Level": 4}},
        {"Slot": "ShieldGenerator", "Item": "int_shieldgenerator_size6_class3_fast"},
        {"Slot": "MediumHardpoint1", "Item": "hpt_basicmissilerack_fixed_medium", "Engineering": {"BlueprintName": "Weapon_HighCapacity", "Level": 3}},
        {"Slot": "MediumHardpoint2", "Item": "hpt_pulselaserburst_gimbal_medium"},
        {"Slot": "LargeHardpoint1", "Item": "hpt_multicannon_gimbal_large_advanced"},
        {"Slot": "Armour", "Item": "krait_mkii_armour_grade3", "Engineering": {"BlueprintName": "Armour_HeavyDuty", "Level": 5}},
        {"Slot": "Slot01_Size6", "Item": "int_cargorack_size6_class1"}, {"Slot": "PaintJob", "Item": "paintjob_x"}, "junk"]}

    def test_the_picks(self):
        out = E.ship_parts(self.LOADOUT)
        self.assertEqual(out["parts"], ["Power plant", "Frame shift drive", "Bi-weave shield generator", "Missile rack", "Burst laser",
                                        "Advanced multi-cannon", "Bulkheads"])   # the cargo rack and paint job: none
        self.assertEqual(out["grades"], ["Power plant|PowerPlant_Boosted|5", "Frame shift drive|FSD_LongRange|4",
                                         "Missile rack|Weapon_HighCapacity|3", "Bulkheads|Armour_HeavyDuty|5"])
        pp = out["modules"][0]
        self.assertEqual((pp["level"], pp["experimental"], pp["blueprint"]), (5, "Thermal Spread", "Boosted"))
        self.assertEqual(out["ship"], {"name": "Sample", "type": "krait_mkii"})
        self.assertEqual(E.ship_parts(None), {"ship": None, "modules": [], "parts": [], "grades": []})

    def test_every_part_and_grade_is_in_upstreams_table(self):
        rows = commander.load_blueprints() or []
        modules = {b["module"] for b in rows}
        for _, part in E.SHIP_PARTS:
            self.assertIn(part, modules)
        for item in ("int_shieldgenerator_size5_class3", "int_shieldgenerator_size5_class3_fast", "int_shieldgenerator_size5_class3_strong",
                     "anaconda_armour_grade1", "hpt_dumbfiremissilerack_fixed_medium_advanced"):
            self.assertIn(E.ship_part(item), modules, item)
        keys = {f"{b['module']}|{b['id']}|{g}" for b in rows for g in b["grades"]}
        for k in E.ship_parts(self.LOADOUT)["grades"]:
            self.assertIn(k, keys)


class Server(unittest.TestCase):
    def setUp(self):
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        self.state = ed_outrider.State(db, ed_outrider.Journals(db), types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        j = self.state.journals
        j.handle({"event": "FSDJump", "timestamp": "2026-10-15T10:00:00Z", "StarSystem": "Sol", "SystemAddress": 10477373803,
                  "StarPos": [0.0, 0.0, 0.0]})
        j.cmdr_view["engineers"] = {"Felicity Farseer": {"progress": "Unlocked", "rank": 5}, "Marco Qwent": {"progress": "Unlocked", "rank": 4}}
        places = {v[0]: [9000.0, 0.0, 0.0] for v in E.ENGINEER_SYSTEMS.values()}   # every workshop placed: nothing asked
        places.update({"Deciat": [122.6, -0.8, -47.3], "Sirius": [6.2, -1.3, -5.8], "Khun": [-171.6, 20.0, -57.0]})
        ed_outrider.meta_set(db, "engineer_places", places)

        async def record(name):
            return None
        self.state.spansh = types.SimpleNamespace(system_record=record, cached=lambda i: (None, None), session=None)

    def call(self, *calls):
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                out = []
                for method, path, body in calls:
                    r = await (c.post(path, json=body) if method == "POST" else c.get(path))
                    out.append((r.status, await r.json()))
                return out
        return asyncio.run(go())

    def test_the_list(self):
        (status, out), = self.call(("GET", "/api/engineers", None))
        ff = next(e for e in out["engineers"] if e["name"] == "Felicity Farseer")
        self.assertEqual((status, ff["system"], ff["progress"], out["from"], out["distances"]["Deciat"]), (200, "Deciat", "Unlocked", "Sol", 131.4))

    def test_the_tour(self):
        (status, out), *bad = self.call(
            ("POST", "/api/engineers/tour", {"requirements": [
                {"label": "FSD G5", "grade": 5, "engineers": ["Felicity Farseer", "Elvira Martuuk"]},
                {"label": "Power plant G4", "grade": 4, "engineers": ["Marco Qwent", "Felicity Farseer"]}]}),
            *[("POST", "/api/engineers/tour", b) for b in ({}, {"requirements": "x"}, {"requirements": [{"label": "x", "engineers": "y"}]},
                                                             {"requirements": [], "include_locked": "yes"})],
            ("POST", "/api/engineers/tour", {"requirements": [], "return_carrier": True}))
        self.assertEqual((status, [(s["engineer"], s["system"]) for s in out["stops"]]), (200, [("Felicity Farseer", "Deciat")]))
        self.assertEqual((out["from"], out["stops"][0]["covers"]), ("Sol", ["FSD G5", "Power plant G4"]))
        self.assertEqual([b[0] for b in bad], [400, 400, 400, 400, 409])               # no carrier on record: said so
        self.assertIn("fleet carrier", bad[-1][1]["error"])

    def test_the_ship(self):
        real = E.shipinfo.latest_loadout
        E.shipinfo.latest_loadout = lambda dirs, sid=None: json.loads(json.dumps(LoadMyShip.LOADOUT))
        self.addCleanup(setattr, E.shipinfo, "latest_loadout", real)
        (status, out), = self.call(("GET", "/api/engineers/ship", None))
        self.assertEqual((status, out["parts"][0], out["grades"][0]), (200, "Power plant", "Power plant|PowerPlant_Boosted|5"))


if __name__ == "__main__":
    unittest.main()

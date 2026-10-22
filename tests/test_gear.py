"""This fork's suit and weapon engineering (outrider/gear.py, GET /api/engineers/gear; the page side is static/fork.js,
forkGearHtml): the table, the ship locker against it, the suits and weapons you own, the route. The journals are fakes."""
import asyncio
import types
import unittest

from support import ed_outrider

import outrider.engineers as E
import outrider.gear as G


def ev(ts, name, **kw):
    return dict({"timestamp": f"2026-10-18T{ts}Z", "event": name}, **kw)


LOCKER = ev("09:00:00", "ShipLocker",
            Items=[{"Name": "suitschematic", "Name_Localised": "Suit Schematic", "OwnerID": 0, "Count": 6},
                   {"Name": "suitschematic", "Name_Localised": "Suit Schematic", "OwnerID": 0, "MissionID": 9, "Count": 4},
                   {"Name": "largecapacitypowerregulator", "Name_Localised": "Power Regulator", "OwnerID": 0, "Count": 1}],
            Components=[{"Name": "graphene", "OwnerID": 0, "Count": 12}, {"Name": "weaponcomponent", "OwnerID": 0, "Count": 5}],
            Consumables=[{"Name": "healthpack", "Name_Localised": "Medkit", "Count": 2}],
            Data=[{"Name": "$surveilleancelogs_name;", "Name_Localised": "Surveillance Logs", "OwnerID": 0, "Count": 5}])
SUITS = [ev("09:01:00", "SuitLoadout", SuitID=1, SuitName="utilitysuit_class3", SuitName_Localised="Maverick Suit",
            SuitMods=["suit_backpackcapacity", "suit_somethingnew"], LoadoutID=4293000001, LoadoutName="Grab", Modules=[
                {"SlotName": "PrimaryWeapon1", "SuitModuleID": 11, "ModuleName": "wpn_m_assaultrifle_kinetic_fauto",
                 "ModuleName_Localised": "Karma AR-50", "Class": 2, "WeaponMods": ["weapon_stability"]}]),
         # the same suit and rifle in a second loadout: owned once
         ev("09:02:00", "CreateSuitLoadout", SuitID=1, SuitName="utilitysuit_class3", SuitName_Localised="Maverick Suit",
            SuitMods=["suit_backpackcapacity", "suit_somethingnew"], LoadoutID=4293000002, LoadoutName="Spare", Modules=[
                {"SlotName": "PrimaryWeapon1", "SuitModuleID": 11, "ModuleName": "wpn_m_assaultrifle_kinetic_fauto",
                 "ModuleName_Localised": "Karma AR-50", "Class": 2, "WeaponMods": ["weapon_stability"]},
                {"SlotName": "SecondaryWeapon", "SuitModuleID": 12, "ModuleName": "wpn_s_pistol_laser_sauto",
                 "ModuleName_Localised": "TK Zenith", "Class": 1, "WeaponMods": []}])]


class Table(unittest.TestCase):
    def test_every_suit_and_weapon_and_mod(self):
        """Three suits and eleven weapons, each upgraded G2 to G5; each mod offered by engineers whose workshops the
        fork knows (the on-foot ones), the Colonia four among them; a weapon mod whose cost differs by family once per
        family; the hip fire accuracy mod once, not under its second name."""
        doc = G.load()
        self.assertIsNotNone(doc)
        self.assertEqual(sorted(i["kind"] for i in doc["items"]).count("suit"), 3)
        self.assertEqual(len(doc["items"]), 14)
        for it in doc["items"]:
            self.assertEqual(sorted(it["upgrades"]), ["2", "3", "4", "5"], it["name"])
            for mats in it["upgrades"].values():
                self.assertTrue(set(mats) <= set(doc["materials"]), it["name"])
        offered = set()
        for m in doc["mods"]:
            self.assertTrue(m["engineers"] and set(m["materials"]) <= set(doc["materials"]), m["name"])
            for e in m["engineers"]:
                self.assertEqual(E.engineer_system(e)[1], "suit & weapon", e)
                offered.add(e)
        self.assertEqual(offered, {k for k, v in E.ENGINEER_SYSTEMS.items() if v[1] == "suit & weapon"})
        names = [(m["name"], m["family"]) for m in doc["mods"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(sorted(f for n, f in names if n == "Greater range"), ["kinetic", "laser", "plasma"])
        self.assertNotIn("Higher accuracy", {n for n, _ in names})
        yi = sorted(m["name"] for m in doc["mods"] if "Yi Shen" in m["engineers"] and m["family"] in (None, "kinetic"))
        self.assertEqual(yi, ["Audio masking", "Headshot damage", "Night vision", "Quieter footsteps"])
        self.assertEqual({m["symbol"] for m in doc["mods"] if m["name"] == "Stability"}, {"weapon_stability"})
        self.assertEqual(doc["materials"]["surveilleancelogs"], {"name": "Surveillance Logs", "kind": "Data"})


class Locker(unittest.TestCase):
    def test_counts(self):
        """By the journal's name, else the English one; a mission's own is not yours to use; consumables are no
        material."""
        doc = G.load()
        snap = ed_outrider.outrider.commander.locker_apply(None, LOCKER)
        got = G.locker_counts(snap, doc["materials"])
        self.assertEqual((got["suitschematic"], got["largecapacitypowerregulator"], got["graphene"], got["surveilleancelogs"]), (6, 1, 12, 5))
        self.assertNotIn("healthpack", got)

    def test_owned(self):
        """Each suit and weapon once (the same one in two loadouts), its grade, its mods by the table's names (one it
        does not know in words)."""
        st = None
        for e in SUITS:
            st = ed_outrider.outrider.commander.suit_apply(st, e)
        got = G.owned(st, G.load())
        self.assertEqual(got["Maverick"], [{"loadout": "Spare", "class": 3, "mods": ["Extra backpack capacity", "Somethingnew"]}])
        self.assertEqual(got["Karma AR-50"], [{"loadout": "Spare", "class": 2, "mods": ["Stability"]}])
        self.assertEqual(got["TK Zenith"][0]["class"], 1)
        self.assertEqual(G.item_of("explorationsuit_class5", G.load()["items"])["name"], "Artemis")
        self.assertIsNone(G.item_of("flightsuit", G.load()["items"]))


class Server(unittest.TestCase):
    def setUp(self):
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        self.state = ed_outrider.State(db, ed_outrider.Journals(db), types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        j = self.state.journals
        for e in [LOCKER, *SUITS, ev("09:03:00", "EngineerProgress", Engineers=[
                {"Engineer": "Domino Green", "EngineerID": 400002, "Progress": "Unlocked"},
                {"Engineer": "Oden Geiger", "EngineerID": 400010, "Progress": "Invited"}])]:
            j.handle(e)

    def call(self, path):
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                r = await c.get(path)
                return r.status, await r.json()
        return asyncio.run(go())

    def test_the_gear(self):
        """From the journals as read: the locker against each upgrade, the suit mods on a suit and the kinetic ones on a
        Karma, each engineer's standing, what you own."""
        status, out = self.call("/api/engineers/gear")
        self.assertEqual((status, out["unreadable"]), (200, False))
        by = {i["name"]: i for i in out["items"]}
        mav, ar = by["Maverick"], by["Karma AR-50"]
        g2 = mav["upgrades"][0]
        self.assertEqual(g2["grade"], 2)
        self.assertEqual({m["id"]: (m["have"], m["need"]) for m in g2["materials"]}["suitschematic"], (6, 1))
        self.assertEqual(g2["rolls"], 0)                                   # no Health Monitor
        self.assertTrue(all(m["name"] != "Stability" for m in mav["mods"]))
        rng = [m for m in ar["mods"] if m["name"] == "Greater range"]
        self.assertEqual(len(rng), 1)
        self.assertIn("Weapon Component", [x["name"] for x in rng[0]["materials"]])   # the kinetic one
        stab = next(m for m in ar["mods"] if m["name"] == "Stability")
        self.assertEqual({e["name"]: (e["progress"], e["ready"]) for e in stab["engineers"]},
                         {"Domino Green": ("Unlocked", True), "Oden Geiger": ("Invited", False), "Rosa Dayette": (None, False)})
        self.assertEqual((mav["owned"][0]["class"], ar["owned"][0]["mods"], by["Artemis"]["owned"]), (3, ["Stability"], []))

    def test_no_table(self):
        real = G.load
        G.load = lambda path=None: None
        self.addCleanup(setattr, G, "load", real)
        self.assertEqual(self.call("/api/engineers/gear")[1], {"items": [], "unreadable": True})


if __name__ == "__main__":
    unittest.main()

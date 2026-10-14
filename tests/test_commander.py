"""The Commander view (outrider/commander.py, Journals.handle_commander, GET /api/commander/*): the commander,
inventory, engineering, missions and the combat and mining sessions, folded from made-up journal lines fed to
Journals.handle on a scratch database."""
import asyncio
import json
import os
import tempfile
import types
import unittest

from support import ed_outrider

import outrider.commander as C

NOW = 1791806400   # 2026-10-12T12:00:00Z
T = lambda hms, day="2026-10-12": f"{day}T{hms}Z"


def temp_dir(test):
    d = tempfile.TemporaryDirectory()
    test.addCleanup(d.cleanup)
    return d.name


def ev(ts, name, **kw):
    return dict({"timestamp": ts, "event": name}, **kw)


def write(folder, name, events):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, separators=(", ", ":")) + "\n")   # as the game writes: "event":"X"


def setup(test, events=()):
    """A scratch database, its Journals fed `events` and a State over it."""
    db = ed_outrider.open_db(":memory:")
    test.addCleanup(db.close)
    j = ed_outrider.Journals(db)
    for e in events:
        j.handle(e)
    return j, ed_outrider.State(db, j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)


LOGIN = ev(T("08:00:00"), "LoadGame", Commander="Tester", FID="F1", Credits=1234567890, Loan=5000, Ship="krait_light",
           Ship_Localised="Krait Phantom")
INVENTORY = [
    LOGIN,
    ev(T("09:00:00"), "Loadout", Ship="krait_light", ShipID=7, ShipName="Sample Ship", ShipIdent="SP-01", HullValue=40, ModulesValue=60,
       Modules=[]),
    ev(T("09:01:00"), "StoredShips", StationName="Old Port", StarSystem="Sol", ShipsHere=[
        {"ShipID": 7, "ShipType": "krait_light", "Value": 100},
        {"ShipID": 3, "ShipType": "asp", "ShipType_Localised": "Asp Explorer", "Name": "Scout", "Value": 9000000, "Hot": False}],
       ShipsRemote=[{"ShipID": 5, "ShipType": "anaconda", "StarSystem": "Colonia", "TransferPrice": 1234567, "TransferTime": 7200,
                     "Value": 150000000, "Hot": True}, {"ShipID": 6, "ShipType": "sidewinder", "InTransit": True, "Value": 32000}, "junk"]),
    ev(T("09:02:00"), "StoredModules", StationName="Old Port", StarSystem="Sol", Items=[
        {"Name": "$int_hyperdrive_size5_class5_name;", "Name_Localised": "FSD", "StorageSlot": 1, "StarSystem": "Sol", "TransferCost": 0,
         "TransferTime": 0, "BuyPrice": 5103953, "Hot": False, "EngineerModifications": "FSD_LongRange", "Level": 5, "Quality": 0.87},
        {"Name": "$hpt_pulselaser_gimbal_medium_name;", "Name_Localised": "Pulse Laser", "StorageSlot": 2, "StarSystem": "Colonia", "TransferCost": 4100, "TransferTime": 6000,
         "BuyPrice": 35400, "Hot": False}, {"Name": "$int_fuelscoop_size6_class5_name;", "StorageSlot": 3, "InTransit": True}]),
    ev(T("09:03:00"), "ShipLocker", Items=[{"Name": "weaponschematic", "Name_Localised": "Weapon Schematic", "OwnerID": 0, "Count": 3},
                                           {"Name": "weaponschematic", "Name_Localised": "Weapon Schematic", "OwnerID": 0, "MissionID": 9, "Count": 1}],
       Components=[{"Name": "graphene", "OwnerID": 0, "Count": 12}], Consumables=[{"Name": "healthpack", "Name_Localised": "Medkit", "Count": 2}],
       Data=[]),
    ev(T("09:04:00"), "ShipLocker"),                                           # the stub the game writes later: not a list
    ev(T("09:05:00"), "SuitLoadout", SuitID=1, SuitName="explorationsuit_class3", SuitName_Localised="Artemis Suit",
       SuitMods=["suit_increasedsprintduration"], LoadoutID=4293000001, LoadoutName="Bio", Modules=[
           {"SlotName": "PrimaryWeapon1", "SuitModuleID": 11, "ModuleName": "wpn_m_assaultrifle_laser_fauto", "ModuleName_Localised": "TK Aphelion",
            "Class": 2, "WeaponMods": ["weapon_stability"]}]),
]


class Inventory(unittest.TestCase):
    def test_ships(self):
        _, state = setup(self, INVENTORY)
        s = state.commander_inventory()["ships"]
        self.assertEqual((s["ts"], s["here"]), (T("09:01:00"), {"system": "Sol", "station": "Old Port"}))
        rows = {r["id"]: r for r in s["ships"]}
        self.assertEqual(list(rows), [7, 3, 5, 6])                             # the one you fly first, and only once
        self.assertEqual((rows[7]["current"], rows[7]["name"], rows[7]["ident"], rows[7]["value"]), (True, "Sample Ship", "SP-01", 100))
        self.assertEqual((rows[3]["system"], rows[3]["station"], rows[3]["type_name"], rows[3]["transfer_cost"]), ("Sol", "Old Port", "Asp Explorer", None))
        self.assertEqual((rows[5]["system"], rows[5]["transfer_cost"], rows[5]["transfer_s"], rows[5]["hot"]), ("Colonia", 1234567, 7200, True))
        self.assertTrue(rows[6]["in_transit"])
        self.assertEqual(C.ships(None), {"ts": None, "ships": [], "here": None})

    def test_the_fleet_after_the_list(self):
        """Should 1: a ship sold, swapped, sent for or renamed after the last StoredShips (as inara._fleet reads them);
        a Loadout newer than the list gives the value."""
        j, state = setup(self, INVENTORY + [
            ev(T("09:10:00"), "Location", StarSystem="Lave", SystemAddress=1, StarPos=[1.0, 2.0, 3.0], Docked=True,
               StationName="Lave Station", StationType="Orbis", MarketID=55),
            ev(T("09:11:00"), "ShipyardSell", ShipType="asp", SellShipID=3, ShipPrice=8000000, MarketID=55),
            ev(T("09:12:00"), "ShipyardSwap", ShipType="anaconda", ShipID=5, StoreOldShip="krait_light", StoreShipID=7, MarketID=55),
            ev(T("09:12:05"), "Loadout", Ship="anaconda", ShipID=5, ShipName="Big", ShipIdent="BG-01", HullValue=140000000,
               ModulesValue=20000000, Modules=[]),
            ev(T("09:13:00"), "SetUserShipName", Ship="krait_light", ShipID=7, UserShipName="Old Faithful", UserShipId="OF-01"),
            ev(T("09:14:00"), "ShipyardTransfer", ShipType="sidewinder", ShipID=6, System="Sol", ShipMarketID=1, Distance=99.0,
               TransferPrice=1000, TransferTime=600, MarketID=55),
            ev(T("09:15:00"), "SellShipOnRebuy", ShipType="cobramkiii", System="Lave", SellShipId=4, ShipPrice=1)])
        rows = {r["id"]: r for r in state.commander_inventory()["ships"]["ships"]}
        self.assertEqual(list(rows), [5, 7, 6])                                # the Asp sold; the Anaconda flown now
        self.assertEqual((rows[5]["current"], rows[5]["name"], rows[5]["value"]), (True, "Big", 160000000))
        self.assertEqual((rows[7]["system"], rows[7]["station"], rows[7]["name"], rows[7]["ident"], rows[7]["value"]),
                         ("Lave", "Lave Station", "Old Faithful", "OF-01", 100))
        self.assertEqual((rows[6]["system"], rows[6]["station"], rows[6]["in_transit"]), ("Lave", "Lave Station", False))   # long arrived
        moving = C.ships(j.cmdr_view["stored_ships"], now=ed_outrider.ts_seconds(T("09:15:00")))["ships"]
        self.assertEqual([s["in_transit"] for s in moving if s["id"] == 6], [True])   # ten minutes on its way
        p = state.commander_profile()["profile"]
        self.assertEqual((p["assets"]["ships"], p["assets"]["fleet"]), (3, 160000000 + 100 + 32000))

    def test_modules_locker_and_suits(self):
        _, state = setup(self, INVENTORY)
        inv = state.commander_inventory()
        m = inv["modules"]["modules"]
        self.assertEqual([(r["name"], r["size"], r["rating"], r["blueprint"], r["level"]) for r in m],
                         [("FSD", 5, "A", "Long range", 5), ("Fuelscoop", 6, "A", None, None), ("Pulse Laser", 2, None, None, None)])   # the game's name, else the symbol's words
        self.assertEqual(C.module_label("Hpt_MultiCannon_Turret_Huge"), ("Multicannon", 4, None, "Turreted"))
        self.assertEqual(C.module_label("$int_shieldgenerator_size6_class3_fast_name;", " Bi-Weave Shield "), ("Bi-Weave Shield", 6, "C", None))
        self.assertEqual(C.module_label(None), ("?", None, None, None))
        self.assertEqual((m[2]["mount"], m[2]["system"], m[2]["transfer_cost"], m[1]["in_transit"]), ("Gimballed", "Colonia", 4100, True))
        lk = inv["locker"]
        self.assertEqual(lk["ts"], T("09:03:00"))                              # the whole list, not the later stub
        self.assertEqual([(k["name"], [(i["name"], i["count"], i["mission"]) for i in k["items"]]) for k in lk["kinds"]], [
            ("Goods", [("Weapon Schematic", 3, False), ("Weapon Schematic", 1, True)]), ("Assets", [("graphene", 12, False)]),
            ("Data", []), ("Consumables", [("Medkit", 2, False)])])
        su = inv["suits"]
        self.assertEqual((su[0]["loadout"], su[0]["suit"], su[0]["class"], su[0]["mods"]), ("Bio", "Artemis Suit", 3, ["Increased sprint duration"]))
        self.assertEqual(su[0]["weapons"], [{"name": "TK Aphelion", "class": 2, "slot": "PrimaryWeapon1", "mods": ["Stability"]}])

    def test_suit_loadouts_fold(self):
        """Should 2: created, equipped, upgraded, renamed and deleted loadouts (as inara._suits reads them)."""
        _, state = setup(self, INVENTORY + [
            ev(T("09:20:00"), "CreateSuitLoadout", SuitID=2, SuitName="utilitysuit_class1", SuitName_Localised="Maverick Suit", SuitMods=[],
               LoadoutID=4293000002, LoadoutName="Spare", Modules=[]),
            ev(T("09:21:00"), "LoadoutEquipModule", LoadoutName="Bio", SuitID=1, SuitName="explorationsuit_class3", LoadoutID=4293000001,
               SlotName="SecondaryWeapon", ModuleName="wpn_s_pistol_kinetic_sauto", ModuleName_Localised="Karma P-15", Class=1,
               WeaponMods=[], SuitModuleID=12),
            ev(T("09:22:00"), "UpgradeWeapon", Name="wpn_m_assaultrifle_laser_fauto", SuitModuleID=11, Class=3, Cost=1, Resources=[]),
            ev(T("09:23:00"), "UpgradeSuit", Name="explorationsuit_class3", SuitID=1, Class=4, Cost=1, Resources=[]),
            ev(T("09:24:00"), "RenameSuitLoadout", SuitID=1, SuitName="explorationsuit_class3", LoadoutID=4293000001, LoadoutName="Bio 2"),
            ev(T("09:25:00"), "DeleteSuitLoadout", SuitID=2, SuitName="utilitysuit_class1", LoadoutID=4293000002, LoadoutName="Spare"),
            ev(T("09:26:00"), "LoadoutRemoveModule", LoadoutName="Bio 2", SuitID=1, LoadoutID=4293000001, SlotName="PrimaryWeapon1",
               ModuleName="wpn_m_assaultrifle_laser_fauto", SuitModuleID=11),
            ev(T("09:27:00"), "RenameSuitLoadout", LoadoutID=99, LoadoutName="never seen whole")])
        su = state.commander_inventory()["suits"]
        self.assertEqual([(s["loadout"], s["class"], [(w["name"], w["class"]) for w in s["weapons"]]) for s in su],
                         [("Bio 2", 4, [("Karma P-15", 1)])])                  # the deleted one gone; the rifle removed after its upgrade

    def test_the_ship_locker_file(self):
        """Should 3: the login line, then ShipLocker.json when it is newer (the later lines carry no contents)."""
        j, state = setup(self, INVENTORY)
        d = temp_dir(self)
        path = os.path.join(d, "ShipLocker.json")

        def file(ts, count):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(ev(ts, "ShipLocker", Items=[{"Name": "weaponschematic", "Name_Localised": "Weapon Schematic", "Count": count}],
                             Components=[], Data=[], Consumables=[]), f)
        v = j.commander_version
        file(T("09:30:00"), 5)
        self.assertTrue(j.read_locker_file(d))
        lk = state.commander_inventory()["locker"]
        self.assertEqual((lk["ts"], lk["kinds"][0]["items"], lk["kinds"][1]["items"]),
                         (T("09:30:00"), [{"name": "Weapon Schematic", "count": 5, "mission": False}], []))
        self.assertGreater(j.commander_version, v)
        self.assertFalse(j.read_locker_file(d))                                # the same file: nothing new
        file(T("09:00:00"), 1)
        self.assertFalse(j.read_locker_file(d))                                # older than what is kept (another folder's)
        self.assertEqual(state.commander_inventory()["locker"]["ts"], T("09:30:00"))
        self.assertFalse(j.read_locker_file(os.path.join(d, "none")))


class Engineering(unittest.TestCase):
    ROWS = [{"id": "FSD_LongRange", "module": "Frame shift drive", "name": "Increased range", "grades": {
        "1": {"materials": {"atypicaldisruptedwakeechoes": 1}, "engineers": ["Felicity Farseer", "Elvira Martuuk"]},
        "5": {"materials": {"arsenic": 1, "chemicalmanipulators": 1, "dataminedwake": 2}, "engineers": ["Felicity Farseer", 'Tod "The Blaster" McQuinn']}}}]

    def test_engineers(self):
        j, state = setup(self, [
            ev(T("08:00:00"), "EngineerProgress", Engineers=[{"Engineer": "Felicity Farseer", "EngineerID": 300100, "Progress": "Unlocked", "Rank": 4},
                                                              {"Engineer": "Elvira Martuuk", "EngineerID": 300160, "Progress": "Invited"}, "junk"]),
            ev(T("09:00:00"), "EngineerProgress", Engineer="Elvira Martuuk", EngineerID=300160, Progress="Unlocked"),
            ev(T("09:30:00"), "EngineerProgress", Engineer="Elvira Martuuk", EngineerID=300160, Rank=2)])
        self.assertEqual(j.cmdr_view["engineers"], {"Felicity Farseer": {"progress": "Unlocked", "rank": 4}, "Elvira Martuuk": {"progress": "Unlocked", "rank": 2}})
        j.materials = {"counts": {"arsenic": 4}, "names": {}}
        eng = state.commander_engineering()
        self.assertEqual(eng["engineers"][0], {"name": "Elvira Martuuk", "progress": "Unlocked", "rank": 2})
        fsd = next(b for b in eng["blueprints"] if b["id"] == "FSD_LongRange")
        self.assertEqual([m["have"] for m in fsd["grades"][-1]["materials"] if m["id"] == "arsenic"], [4])   # the materials held now

    def test_blueprints_against_your_materials(self):
        known = {"Felicity Farseer": {"progress": "Unlocked", "rank": 4}, "Elvira Martuuk": {"progress": "Invited", "rank": None},
                 "Tod 'The Blaster' McQuinn": {"progress": "Unlocked", "rank": 3}}
        counts = {"atypicaldisruptedwakeechoes": 7, "arsenic": 9, "chemicalmanipulators": 3, "dataminedwake": 5}
        b = C.blueprints(counts, known, lambda mid: mid.upper(), rows=self.ROWS)[0]
        self.assertEqual((b["module"], b["name"], [g["grade"] for g in b["grades"]]), ("Frame shift drive", "Increased range", [1, 5]))
        g1, g5 = b["grades"]
        self.assertEqual((g1["rolls"], g5["rolls"]), (7, 2))                    # 5 wake data at 2 a roll: twice
        self.assertEqual(g5["materials"][2], {"id": "dataminedwake", "name": "DATAMINEDWAKE", "need": 2, "have": 5})
        self.assertEqual([(e["name"], e["ready"]) for e in g1["engineers"]], [("Felicity Farseer", True), ("Elvira Martuuk", False)])
        # Rank is the highest grade an engineer crafts for you (the author's journals: no craft above it): rank 4, no G5
        self.assertEqual([(e["progress"], e["rank"], e["ready"]) for e in g5["engineers"]], [("Unlocked", 4, False), ("Unlocked", 3, False)])
        known["Felicity Farseer"]["rank"] = 5
        g5 = C.blueprints(counts, known, lambda mid: mid.upper(), rows=self.ROWS)[0]["grades"][1]
        self.assertEqual([e["ready"] for e in g5["engineers"]], [True, False])
        known["Felicity Farseer"].update(progress="Unlocked", rank=None)                 # unlocked, no rank said yet
        self.assertFalse(C.blueprints(counts, known, rows=self.ROWS)[0]["grades"][0]["engineers"][0]["ready"])
        self.assertEqual(C.blueprints({}, rows=self.ROWS)[0]["grades"][1]["rolls"], 0)

    def test_the_shipped_table(self):
        import outrider.materials as M
        rows = C.load_blueprints()
        self.assertGreater(len(rows), 70)
        for b in rows:
            self.assertTrue(b["module"] and b["name"] and b["grades"], b["id"])
            for g, v in b["grades"].items():
                self.assertIn(int(g), range(1, 6))
                self.assertTrue(v["materials"] and v["engineers"], f"{b['id']} G{g}")
                for mid, n in v["materials"].items():
                    self.assertIn(mid, M.MATERIALS, f"{b['id']} G{g}")           # the journal's own names: they meet your counts
                    self.assertGreater(n, 0)
        self.assertEqual(C.load_blueprints(os.path.join(temp_dir(self), "none.json")), [])


class Missions(unittest.TestCase):
    def test_what_you_hold(self):
        j, _ = setup(self, [
            ev(T("08:00:00"), "MissionAccepted", MissionID=1, Name="Mission_Delivery_name", LocalisedName="Deliver 20 units of Gold", Faction="Sol Workers",
               Commodity="$Gold_Name;", Commodity_Localised="Gold", Count=20, DestinationSystem="Alpha Centauri", DestinationStation="Hutton Orbital",
               Expiry=T("12:20:00"), Wing=False, Influence="++", Reputation="+", Reward=2500000),
            ev(T("08:05:00"), "MissionAccepted", MissionID=2, Name="Mission_Massacre", Faction="Sol Workers", TargetFaction="Bad Lot", KillCount=12,
               DestinationSystem="Wolf 359", Expiry=T("09:00:00", "2026-10-14"), Wing=True, Reward=9000000),
            ev(T("08:06:00"), "MissionAccepted", MissionID=3, Name="Mission_Courier", LocalisedName="Courier job", Faction="X", Expiry=T("09:00:00")),
            ev(T("08:07:00"), "MissionAccepted", MissionID=4, Name="Mission_Sightseeing", LocalisedName="Tour", PassengerCount=4, Expiry=T("09:00:00", "2026-10-20")),
            ev(T("08:30:00"), "CargoDepot", MissionID=1, ItemsDelivered=8, TotalItemsToDeliver=20),
            ev(T("08:40:00"), "MissionRedirected", MissionID=2, NewDestinationSystem="Sol", NewDestinationStation="Old Port"),
            ev(T("08:50:00"), "MissionCompleted", MissionID=4), ev(T("08:51:00"), "MissionFailed", MissionID=99)])
        m = C.missions(j.cmdr_view["missions"], now=NOW)
        self.assertEqual([r["id"] for r in m], [3, 1, 2])                       # the soonest first: the expired one leads
        self.assertEqual((m[0]["expired"], m[0]["soon"], m[1]["soon"], m[1]["expires_in"], m[2]["soon"]), (True, False, True, 1200, False))
        self.assertEqual((m[1]["name"], m[1]["commodity"], m[1]["count"], m[1]["delivered"], m[1]["station"], m[1]["reward"]),
                         ("Deliver 20 units of Gold", "Gold", 20, 8, "Hutton Orbital", 2500000))
        self.assertEqual((m[2]["name"], m[2]["target"], m[2]["count"], m[2]["wing"], m[2]["redirected"], m[2]["system"], m[2]["station"]),
                         ("Massacre", "Bad Lot", 12, True, True, "Sol", "Old Port"))

    def test_the_login_list_decides(self):
        missions = [ev(T("08:00:00"), "MissionAccepted", MissionID=1, Name="Mission_A", Expiry=T("20:00:00")),
                    ev(T("08:01:00"), "MissionAccepted", MissionID=2, Name="Mission_B"),
                    ev(T("10:00:00"), "Missions", Active=[{"MissionID": 2, "Name": "Mission_B", "PassengerMission": False, "Expires": 0},
                                                           {"MissionID": 7, "Name": "Mission_Old_name", "PassengerMission": True, "Expires": 7200}],
                       Failed=[], Complete=[])]
        j, state = setup(self, missions)
        m = C.missions(j.cmdr_view["missions"], now=NOW)
        self.assertEqual([(r["id"], r["name"], r["expiry"], r["passengers"]) for r in m],
                         [(7, "Old", T("12:00:00"), True), (2, "B", None, False)])   # 1 is gone; 7 was accepted before these journals
        self.assertEqual(C.missions(None, now=NOW), [])
        # a legacy folder read late: its lines are older than the login's list, which already says what is held
        j.handle(ev(T("07:00:00"), "MissionAccepted", MissionID=8, Name="Mission_Long_gone"))
        j.handle(ev(T("09:00:00"), "MissionCompleted", MissionID=2))
        self.assertEqual([r["id"] for r in state.commander_missions()["missions"]], [7, 2])


class Sessions(unittest.TestCase):
    EVENTS = [
        ev(T("08:00:00"), "LoadGame", Commander="Tester", Ship="krait_mkii", Ship_Localised="Krait Mk II"),
        ev(T("08:10:00"), "Bounty", Rewards=[{"Faction": "A", "Reward": 100000}, {"Faction": "B", "Reward": 50000}], Target="anaconda",
           Target_Localised="Anaconda", TotalReward=150000, VictimFaction="Bad Lot"),
        ev(T("08:20:00"), "Bounty", Target="anaconda", Target_Localised="Anaconda", TotalReward=250000),
        ev(T("08:40:00"), "FactionKillBond", Reward=60000, AwardingFaction="A", VictimFaction="B"),
        ev(T("08:41:00"), "Interdicted", Submitted=False), ev(T("08:45:00"), "Died"),
        ev(T("08:50:00"), "RedeemVoucher", Type="bounty", Amount=400000), ev(T("08:51:00"), "RedeemVoucher", Type="trade", Amount=5),
        ev(T("09:00:00"), "Shutdown"),
        ev(T("10:00:00"), "LoadGame", Commander="Tester", Ship="python"),
        ev(T("10:01:00"), "Scan"),
        ev(T("10:30:00"), "Shutdown"),                                          # nothing fought or mined: not listed
        ev(T("11:00:00"), "LoadGame", Commander="Tester", Ship="type9", Ship_Localised="Type-9 Heavy"),
        ev(T("11:00:30"), "LaunchDrone", Type="Prospector"), ev(T("11:00:40"), "LaunchDrone", Type="Collection"),
        ev(T("11:01:00"), "ProspectedAsteroid", Content="$AsteroidMaterialContent_High;", MotherlodeMaterial="Opal", Remaining=100.0),
        ev(T("11:02:00"), "ProspectedAsteroid", Content="$AsteroidMaterialContent_Low;", Remaining=100.0),
        ev(T("11:03:00"), "AsteroidCracked", Body="Ring A"),
    ] + [ev(T(f"11:{10 + i}:00"), "MiningRefined", Type="$platinum_name;", Type_Localised="Platinum") for i in range(5)] + [
        ev(T("11:31:00"), "MiningRefined", Type="$osmium_name;"),
        ev(T("11:50:00"), "MarketSell", Type="platinum", Type_Localised="Platinum", Count=5, TotalSale=1500000, MarketID=1),
        ev(T("11:51:00"), "MarketSell", Type="gold", Count=5, TotalSale=99, MarketID=1),
    ]

    def test_combat_and_mining(self):
        _, state = setup(self, self.EVENTS)
        got = state.commander_sessions()
        rows = got["sessions"]
        self.assertEqual([(r["start"], r["ship"], bool(r["combat"]), bool(r["mining"])) for r in rows],
                         [(T("11:00:00"), "Type-9 Heavy", False, True), (T("08:00:00"), "Krait Mk II", True, False)])   # newest first
        c = rows[1]["combat"]
        self.assertEqual((c["kills"], c["bounties"], c["bonds"], c["deaths"], c["interdicted"], c["redeemed"], c["by_ship"]),
                         (3, 400000, 60000, 1, 1, 400000, {"Anaconda": 2}))
        self.assertEqual((c["seconds"], c["per_hour"]), (1800, 6.0))            # three kills over half an hour
        m = rows[0]["mining"]
        self.assertEqual((m["tons"], m["refined"], m["prospected"], m["content"], m["motherlodes"], m["cracked"], m["srv_tons"]),
                         (6, {"Platinum": 5, "osmium": 1}, 2, {"High": 1, "Low": 1}, 1, 1, 0))
        self.assertEqual((m["prospectors"], m["collectors"], m["sold"], m["seconds"], m["per_hour"]), (1, 1, 1500000, 1800, 12.0))
        self.assertEqual((rows[0]["end"], rows[1]["end"]), (T("11:50:00"), T("08:50:00")))   # the last line that counted
        self.assertEqual((got["totals"]["combat"], got["totals"]["mining"], got["max"]),
                         ({"sessions": 1, "kills": 3, "bounties": 400000, "bonds": 60000, "deaths": 1},
                          {"sessions": 1, "tons": 6, "srv_tons": 0, "prospected": 2, "sold": 1500000}, C.SESSIONS_MAX))

    def test_the_srv_refinery_apart(self):
        """Should 4: the Rhino's refinery is not the ship's mining (the reader knows the vehicle you are in)."""
        _, state = setup(self, [
            ev(T("11:00:00"), "LoadGame", Commander="Tester", Ship="python"),
            ev(T("11:05:00"), "MiningRefined", Type="$painite_name;", Type_Localised="Painite"),
            ev(T("11:20:00"), "LaunchSRV", SRVType="mev_rhino", SRVType_Localised="Rhino", Loadout="default", ID=1, PlayerControlled=True),
            ev(T("11:21:00"), "MiningRefined", Type="$gold_name;", Type_Localised="Gold"),
            ev(T("11:31:00"), "MiningRefined", Type="$gold_name;", Type_Localised="Gold"),
            ev(T("11:40:00"), "DockSRV", SRVType="mev_rhino", ID=1),
            ev(T("11:45:00"), "MiningRefined", Type="$painite_name;", Type_Localised="Painite"),
            ev(T("11:50:00"), "MarketSell", Type="gold", Type_Localised="Gold", Count=2, TotalSale=100000, MarketID=1)])
        m = state.commander_sessions()["sessions"][0]["mining"]
        self.assertEqual((m["tons"], m["refined"], m["srv_tons"], m["srv_refined"], m["seconds"], m["srv_seconds"], m["sold"]),
                         (2, {"Painite": 2}, 2, {"Gold": 2}, 2400, 600, 100000))

    def test_before_any_login(self):
        _, state = setup(self, self.EVENTS[1:3])                               # no login on record: no session to count in
        self.assertEqual(state.commander_sessions()["sessions"], [])

    def test_a_reread_doubles_nothing(self):
        """Everything is journal-derived: a re-read (RESET_JOURNAL_DATA, then the files again) gives the same, and a
        file read twice counts once."""
        d = temp_dir(self)
        write(d, "Journal.2026-10-12T080000.01.log", INVENTORY + Sessions.EVENTS[1:9] + [
            ev(T("08:01:00"), "MissionAccepted", MissionID=1, Name="Mission_A"),
            ev(T("08:02:00"), "EngineerProgress", Engineers=[{"Engineer": "Felicity Farseer", "Progress": "Unlocked", "Rank": 5}])])
        j, state = setup(self)
        reads = lambda: [state.commander_profile(), state.commander_inventory(), state.commander_missions(), state.commander_sessions(),
                         state.commander_engineering()]
        j.scan_dir(d)
        first = reads()
        self.assertEqual(first[3]["sessions"][0]["combat"]["kills"], 3)
        j.scan_dir(d)
        self.assertEqual(reads(), first)
        ed_outrider.reset_journal_data(j.db)
        for key in C.COMMANDER_META:
            self.assertIsNone(ed_outrider.meta_get(j.db, key), key)
        self.assertEqual(j.db.execute("SELECT count(*) FROM play_activity").fetchone()[0], 0)
        j.reload()
        self.assertIsNone(state.commander_profile()["profile"])
        j.scan_dir(d)
        self.assertEqual(reads(), first)


class Profile(unittest.TestCase):
    EVENTS = [
        ev(T("07:00:00", "2026-10-10"), "LoadGame", Commander="Old Login", Credits=1, Loan=0),
        ev(T("07:59:58"), "Rank", Combat=3, Trade=7, Explore=8, Soldier=0, Exobiologist=4, Empire=2, Federation=14, CQC=0),
        ev(T("07:59:59"), "Progress", Combat=41, Trade=50, Explore=100, Soldier=0, Exobiologist=25, Empire=80, Federation=0, CQC=0),
        ev(T("07:59:59"), "Reputation", Empire=76.5, Federation=-40.0, Alliance=12.25),
        ev(T("07:59:59"), "SquadronStartup", SquadronName="Sample Wing", CurrentRank=1),
        LOGIN,
        ev(T("08:00:04"), "Powerplay", Power="Aisling Duval", Rank=3, Merits=4500),
        ev(T("08:00:06"), "Statistics", Bank_Account={"Current_Wealth": 9000000000, "Spent_On_Ships": 500000000, "Insurance_Claims": 3},
           Exploration={"Systems_Visited": 12345, "Total_Hyperspace_Distance": 987654, "Time_Played": 7200000, "Exploration_Profits": 0},
           Combat={"Bounties_Claimed": 40}),
        ev(T("08:00:07"), "CarrierStats", CarrierID=1, Callsign="X1X-X1X", Name="SAMPLE CARRIER", FuelLevel=800, Finance={"CarrierBalance": 250000000}),
        ev(T("08:30:00"), "Promotion", Combat=4),
        ev(T("08:40:00"), "PowerplayMerits", Power="Aisling Duval", MeritsGained=100, TotalMerits=4600),
    ] + INVENTORY[1:]

    def test_ranks_and_what_the_next_takes(self):
        _, state = setup(self, self.EVENTS)
        p = state.commander_profile()["profile"]
        r = {x["key"]: x for x in p["ranks"]}
        self.assertEqual([x["title"] for x in p["ranks"]], ["Combat", "Trade", "Exploration", "Exobiology", "Mercenary", "CQC", "Federal Navy", "Imperial Navy"])
        self.assertEqual((r["Combat"]["name"], r["Combat"]["progress"], r["Combat"]["next"], r["Combat"]["to_next"]), ("Expert", 0, "Master", None))   # promoted since
        # trade and exploration: their percentage only (no figures that could be checked against the game's own)
        self.assertEqual((r["Trade"]["name"], r["Trade"]["next"], r["Trade"]["progress"], r["Trade"]["to_next"], r["Trade"]["earned_by"]),
                         ("Tycoon", "Elite", 50, None, None))
        self.assertEqual((r["Explore"]["name"], r["Explore"]["next"], r["Explore"]["to_next"]), ("Elite", "Elite I", None))
        self.assertEqual((r["Exobiologist"]["name"], r["Exobiologist"]["to_next"], r["Exobiologist"]["earned_by"], r["Exobiologist"]["uncertain"]),
                         ("Cataloguer", 458_400_000, "exobiology data sold", False))   # 75% of the 611.2M step
        self.assertEqual((r["Federation"]["name"], r["Federation"]["progress"], r["Federation"]["next"]), ("Admiral", None, None))   # the top
        self.assertEqual((r["Empire"]["name"], r["Empire"]["next"], r["Empire"]["progress"]), ("Serf", "Master", 80))
        self.assertEqual(C.rank_rows({"Trade": 99, "Explore": "x"}, {})[0]["name"], "99")

    def test_the_exobiology_table(self):
        """The post-Update-14 thresholds (the Frontier forum, 2 Jan 2023), pinned; what is left is the step times the
        game's own share still to go. The author's journals: Geneticist 64% at the 2026-10-12 login."""
        self.assertEqual(C.RANK_CREDITS["Exobiologist"], (0, 22_500_000, 83_475_000, 210_560_000, 532_800_000, 1_144_000_000, 2_262_600_000,
                                                          3_996_000_000, 8_425_000_000, 12_969_000_000, 17_425_000_000, 21_925_000_000,
                                                          26_320_000_000, 30_917_860_900))
        self.assertEqual(set(C.RANK_CREDITS), {"Exobiologist"})
        row = lambda n, pct: C.rank_rows({"Exobiologist": n}, {"Exobiologist": pct})[0]
        g = row(7, 64)
        self.assertEqual((g["name"], g["next"], g["to_next"], g["uncertain"]), ("Geneticist", "Elite", 1_594_440_000, False))   # 36% of 4.429B
        self.assertEqual((row(8, 50)["to_next"], row(8, 50)["uncertain"]), (2_272_000_000, False))
        self.assertEqual([row(n, 0)["uncertain"] for n in (10, 11, 12)], [False, True, True])   # Elite IV and V are estimates
        top = row(13, 40)
        self.assertEqual((top["name"], top["next"], top["to_next"], top["progress"]), ("Elite V", None, None, None))

    def test_money_fleet_and_career(self):
        _, state = setup(self, self.EVENTS)
        p = state.commander_profile()["profile"]
        self.assertEqual((p["commander"], p["ts"], p["squadron"]), ("Tester", T("08:00:00"), "Sample Wing"))
        # credits and the carrier have one owner each: the payload's commander and carrier (the tiles'), not this
        self.assertFalse({"credits", "loan", "carrier"} & set(p))
        self.assertEqual(p["assets"], {"wealth": 9000000000, "ships": 4, "fleet": 100 + 9000000 + 150000000 + 32000, "modules": 5103953 + 35400})
        self.assertEqual([s["id"] for s in p["fleet"]], [7, 5, 3, 6])                    # the one you fly, then by value
        self.assertEqual(p["reputation"], {"Federation": -40.0, "Empire": 76.5, "Alliance": 12.2})
        self.assertEqual(p["power"], {"name": "Aisling Duval", "rank": 3, "merits": 4600})   # merits gained since the login
        self.assertEqual([(c["label"], c["value"], c["kind"]) for c in p["career"]], [
            ("Time played", 7200000, "time"), ("Systems visited", 12345, "n"), ("Distance jumped", 987654, "ly"), ("Bounties claimed", 40, "n"),
            ("Insurance claims", 3, "n"), ("Spent on ships", 500000000, "cr")])          # a zero is left out
        _, bare = setup(self, INVENTORY[1:])
        self.assertIsNone(bare.commander_profile()["profile"])                          # no login on record
        _, bare = setup(self, [ev(T("08:00:00"), "LoadGame", Commander="New")])
        p = bare.commander_profile()["profile"]
        self.assertEqual((p["ranks"], p["fleet"], p["career"], p["power"]), ([], [], [], None))

    def test_powerplay_and_squadron_changes(self):
        _, state = setup(self, self.EVENTS + [
            ev(T("09:00:00"), "PowerplayDefect", FromPower="Aisling Duval", ToPower="Edmund Mahon"),
            ev(T("09:01:00"), "PowerplayRank", Power="Edmund Mahon", Rank=1),
            ev(T("09:02:00"), "LeftSquadron", SquadronName="Sample Wing")])
        p = state.commander_profile()["profile"]
        self.assertEqual((p["power"], p["squadron"]), ({"name": "Edmund Mahon", "rank": 1, "merits": None}, None))
        _, state = setup(self, self.EVENTS + [ev(T("09:00:00"), "PowerplayLeave", Power="Aisling Duval")])
        self.assertIsNone(state.commander_profile()["profile"]["power"])


class Reader(unittest.TestCase):
    def test_login_snapshots_leave_the_session_end(self):
        """The trap: the snapshots the game writes as you log in (missions, reputation, engineers, Powerplay, squadron,
        the ship locker) are not play, so they must not move last_play_ts (History's session end, the "away" greeting)."""
        j, _ = setup(self, [ev(T("08:00:00"), "LoadGame", Commander="Tester"), ev(T("08:10:00"), "Bounty", TotalReward=5)])
        self.assertEqual(j.last_play_ts, T("08:10:00"))
        for name, kw in (("Missions", {"Active": [], "Failed": [], "Complete": []}), ("Reputation", {"Empire": 1.0}),
                         ("EngineerProgress", {"Engineers": []}), ("Powerplay", {"Power": "X", "Rank": 1}),
                         ("SquadronStartup", {"SquadronName": "S"}), ("ShipLocker", {"Items": []})):
            j.handle(ev(T("12:00:00"), name, **kw))
            self.assertEqual(j.last_play_ts, T("08:10:00"), name)
            self.assertIn(name, ed_outrider.LOGIN_EVENTS)
        j.handle(ev(T("12:05:00"), "MissionAccepted", MissionID=1, Name="Mission_A"))   # accepting one is play
        self.assertEqual(j.last_play_ts, T("12:05:00"))

    def test_everything_kept_is_journal_derived(self):
        """Every fold's meta key and play_activity are cleared by a re-read (none of it is live-only), and the reader's
        filter lets their lines through."""
        reset = ed_outrider.RESET_JOURNAL_DATA
        for key in C.COMMANDER_META:
            self.assertIn(f"'{key}'", reset)
        self.assertIn("DELETE FROM play_activity", reset)
        for name in C.EVENTS:
            self.assertIn(f'"event":"{name}"'.encode(), ed_outrider.WANTED, name)
        self.assertIn(51, ed_outrider.PARSER_CHANGES)
        self.assertGreaterEqual(ed_outrider.PARSER_VERSION, 51)

    def test_other_handlers_still_see_shared_lines(self):
        """A line both the Commander view and another handler read (a MissionCompleted's materials, a Died) still
        reaches the other."""
        j, _ = setup(self, [ev(T("08:00:00"), "LoadGame", Commander="Tester"),
                            ev(T("08:10:00"), "Died")])
        self.assertEqual(j.db.execute("SELECT count(*) FROM deaths").fetchone()[0], 1)
        self.assertEqual(j.cmdr_view["missions"], None)


class Version(unittest.TestCase):
    def test_a_line_the_view_reads_moves_it(self):
        """The payload's commander_version: the page asks for the open tab again when it moves (as Materials on its
        version), not on a timer; State wakes the page for it."""
        j, state = setup(self)
        d = temp_dir(self)
        write(d, "Journal.2026-10-12T080000.01.log", [ev(T("08:00:00"), "Music", MusicTrack="Exploration"),
                                                      ev(T("08:01:00"), "MissionAccepted", MissionID=1, Name="Mission_A"),
                                                      ev(T("08:02:00"), "ReceiveText", Message="MissionAccepted"),
                                                      ev(T("08:03:00"), "Bounty", TotalReward=5)])
        v0 = j.commander_version
        j.read_file(os.path.join(d, "Journal.2026-10-12T080000.01.log"))
        self.assertEqual(j.commander_version, v0 + 2)              # the mission and the bounty, not a text naming one
        self.assertEqual(state.payload()["commander_version"], v0 + 2)
        v = state.version
        state.apply_own_changes()
        self.assertEqual(state.version, v + 1)                      # the page is woken for it
        state.apply_own_changes()
        self.assertEqual(state.version, v + 1)                      # once
        j.reload()                                                  # a rolled-back tick: what was read may differ
        self.assertGreater(j.commander_version, v0 + 2)


class Server(unittest.TestCase):
    def _get(self, state, parts):
        from aiohttp.test_utils import TestClient, TestServer
        app = ed_outrider.make_app(state)

        async def go():
            async with TestClient(TestServer(app)) as c:
                out = []
                for p in parts:
                    r = await c.get(f"/api/commander/{p}")
                    out.append((r.status, await r.json()))
                return out
        return asyncio.run(go())

    def test_routes(self):
        j, state = setup(self, INVENTORY + Sessions.EVENTS[1:5] + [
            ev(T("08:00:00"), "EngineerProgress", Engineers=[{"Engineer": "Felicity Farseer", "Progress": "Unlocked", "Rank": 5}]),
            ev(T("08:01:00"), "MissionAccepted", MissionID=1, Name="Mission_A", LocalisedName="A job")])
        j.materials = {"counts": {"arsenic": 4}, "names": {}}
        (_, pro), (_, inv), (_, eng), (_, mis), (_, ses) = self._get(state, ("profile", "inventory", "engineering", "missions", "sessions"))
        self.assertEqual((pro["profile"]["commander"], len(pro["profile"]["fleet"])), ("Tester", 4))
        self.assertEqual((len(inv["ships"]["ships"]), len(inv["modules"]["modules"]), len(inv["suits"])), (4, 3, 1))
        fsd = next(b for b in eng["blueprints"] if b["id"] == "FSD_LongRange")
        self.assertEqual([m["have"] for m in fsd["grades"][-1]["materials"] if m["id"] == "arsenic"], [4])
        self.assertEqual(eng["engineers"], [{"name": "Felicity Farseer", "progress": "Unlocked", "rank": 5}])
        self.assertTrue(all(e["ready"] for g in fsd["grades"] for e in g["engineers"] if e["name"] == "Felicity Farseer"))
        self.assertEqual([m["name"] for m in mis["missions"]], ["A job"])
        self.assertEqual((ses["sessions"][0]["combat"]["kills"], ses["totals"]["combat"]["sessions"]), (3, 1))

    def test_an_error_is_the_servers_to_log(self):
        """No local 500: json_errors answers {error, code: server_error} and prints the traceback for Show log."""
        import contextlib
        import io
        _, state = setup(self)
        state.commander_inventory = lambda: (_ for _ in ()).throw(ValueError("a line nobody expected"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            [(status, body)] = self._get(state, ("inventory",))
        self.assertEqual((status, body["code"]), (500, "server_error"))
        self.assertIn("a line nobody expected", body["error"])
        self.assertIn("Traceback", err.getvalue())

    def test_the_real_server_has_them(self):
        _, state = setup(self)
        paths = {r.resource.canonical for r in ed_outrider.make_app(state).router.routes()}
        for part in ("profile", "inventory", "engineering", "missions", "sessions"):
            self.assertIn(f"/api/commander/{part}", paths)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(C.__file__), "jscan.py")))   # no file scanning left


if __name__ == "__main__":
    unittest.main()

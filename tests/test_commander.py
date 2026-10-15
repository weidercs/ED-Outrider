"""The Commander view (outrider/commander.py, outrider/jscan.py, GET /api/commander/*): the commander, inventory,
engineering, missions and the combat and mining sessions, from made-up journals written to a temporary folder."""
import asyncio
import json
import os
import tempfile
import types
import unittest

from support import ed_outrider

import outrider.commander as C
import outrider.jscan as jscan

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
        f.write("not json\n")


class Scan(unittest.TestCase):
    def test_events_by_name_in_order_and_cached(self):
        d = temp_dir(self)
        write(d, "Journal.2026-10-11T100000.01.log", [ev(T("10:00:00", "2026-10-11"), "LoadGame"), ev(T("10:05:00", "2026-10-11"), "Bounty", TotalReward=5)])
        write(d, "Journal.2026-10-12T100000.01.log", [ev(T("10:00:00"), "Bounty", TotalReward=7), ev(T("10:01:00"), "Scan"),
                                                      {"event": "Bounty"}, ev(T("10:02:00"), "Docked", note='"event":"Bounty"')])
        write(d, "Journal.2026-08-01T100000.01.log", [ev("2026-08-01T10:00:00Z", "Bounty", TotalReward=1)])
        got = jscan.events([d], ("Bounty",), days=5, now=NOW)
        self.assertEqual([e["TotalReward"] for e in got], [5, 7])            # oldest first; no stamp, another event: left out
        self.assertEqual(len(jscan.events([d], ("Bounty",), days=120, now=NOW)), 3)
        self.assertIs(jscan.events([d], ("Bounty",), days=5, now=NOW)[0], got[0])   # an unchanged file is not read again
        with open(os.path.join(d, "Journal.2026-10-12T100000.01.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps(ev(T("10:09:00"), "Bounty", TotalReward=9)) + "\n")
        self.assertEqual([e["TotalReward"] for e in jscan.events([d], ("Bounty",), days=5, now=NOW)], [5, 7, 9])   # it grew
        self.assertEqual(jscan.events([os.path.join(d, "none")], ("Bounty",), now=NOW), [])


class Inventory(unittest.TestCase):
    EVENTS = [
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
        ev(T("09:04:00"), "ShipLocker"),                                       # the stub the game writes later: not a list
        ev(T("09:05:00"), "SuitLoadout", SuitID=1, SuitName="explorationsuit_class3", SuitName_Localised="Artemis Suit",
           SuitMods=["suit_increasedsprintduration"], LoadoutID=4293000001, LoadoutName="Bio", Modules=[
               {"SlotName": "PrimaryWeapon1", "ModuleName": "wpn_m_assaultrifle_laser_fauto", "ModuleName_Localised": "TK Aphelion",
                "Class": 2, "WeaponMods": ["weapon_stability"]}]),
    ]

    def test_ships(self):
        s = C.ships(self.EVENTS)
        self.assertEqual((s["ts"], s["here"]), (T("09:01:00"), {"system": "Sol", "station": "Old Port"}))
        rows = {r["id"]: r for r in s["ships"]}
        self.assertEqual(list(rows), [7, 3, 5, 6])                             # the one you fly first, and only once
        self.assertEqual((rows[7]["current"], rows[7]["name"], rows[7]["ident"], rows[7]["value"]), (True, "Sample Ship", "SP-01", 100))
        self.assertEqual((rows[3]["system"], rows[3]["station"], rows[3]["type_name"], rows[3]["transfer_cost"]), ("Sol", "Old Port", "Asp Explorer", None))
        self.assertEqual((rows[5]["system"], rows[5]["transfer_cost"], rows[5]["transfer_s"], rows[5]["hot"]), ("Colonia", 1234567, 7200, True))
        self.assertTrue(rows[6]["in_transit"])
        self.assertEqual(C.ships([]), {"ts": None, "ships": [], "here": None})

    def test_modules_locker_and_suits(self):
        m = C.stored_modules(self.EVENTS)["modules"]
        self.assertEqual([(r["name"], r["size"], r["rating"], r["blueprint"], r["level"]) for r in m],
                         [("FSD", 5, "A", "Long range", 5), ("Fuelscoop", 6, "A", None, None), ("Pulse Laser", 2, None, None, None)])   # the game's name, else the symbol's words
        self.assertEqual(C.module_label("Hpt_MultiCannon_Turret_Huge"), ("Multicannon", 4, None, "Turreted"))
        self.assertEqual(C.module_label("$int_shieldgenerator_size6_class3_fast_name;", " Bi-Weave Shield "), ("Bi-Weave Shield", 6, "C", None))
        self.assertEqual(C.module_label(None), ("?", None, None, None))
        self.assertEqual((m[2]["mount"], m[2]["system"], m[2]["transfer_cost"], m[1]["in_transit"]), ("Gimballed", "Colonia", 4100, True))
        lk = C.locker(self.EVENTS)
        self.assertEqual(lk["ts"], T("09:03:00"))                              # the whole list, not the later stub
        self.assertEqual([(k["name"], [(i["name"], i["count"], i["mission"]) for i in k["items"]]) for k in lk["kinds"]], [
            ("Goods", [("Weapon Schematic", 3, False), ("Weapon Schematic", 1, True)]), ("Assets", [("graphene", 12, False)]),
            ("Data", []), ("Consumables", [("Medkit", 2, False)])])
        su = C.suits(self.EVENTS)
        self.assertEqual((su[0]["loadout"], su[0]["suit"], su[0]["class"], su[0]["mods"]), ("Bio", "Artemis Suit", 3, ["Increased sprint duration"]))
        self.assertEqual(su[0]["weapons"], [{"name": "TK Aphelion", "class": 2, "slot": "PrimaryWeapon1", "mods": ["Stability"]}])


class Engineering(unittest.TestCase):
    ROWS = [{"id": "FSD_LongRange", "module": "Frame shift drive", "name": "Increased range", "grades": {
        "1": {"materials": {"atypicaldisruptedwakeechoes": 1}, "engineers": ["Felicity Farseer", "Elvira Martuuk"]},
        "5": {"materials": {"arsenic": 1, "chemicalmanipulators": 1, "dataminedwake": 2}, "engineers": ["Felicity Farseer", 'Tod "The Blaster" McQuinn']}}}]

    def test_engineers(self):
        known = C.engineers([
            ev(T("08:00:00"), "EngineerProgress", Engineers=[{"Engineer": "Felicity Farseer", "EngineerID": 300100, "Progress": "Unlocked", "Rank": 4},
                                                              {"Engineer": "Elvira Martuuk", "EngineerID": 300160, "Progress": "Invited"}, "junk"]),
            ev(T("09:00:00"), "EngineerProgress", Engineer="Elvira Martuuk", EngineerID=300160, Progress="Unlocked"),
            ev(T("09:30:00"), "EngineerProgress", Engineer="Elvira Martuuk", EngineerID=300160, Rank=2)])
        self.assertEqual(known, {"Felicity Farseer": {"progress": "Unlocked", "rank": 4}, "Elvira Martuuk": {"progress": "Unlocked", "rank": 2}})

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
        self.assertEqual([(e["progress"], e["rank"], e["ready"]) for e in g5["engineers"]], [("Unlocked", 4, True), ("Unlocked", 3, False)])
        self.assertEqual(C.blueprints({}, rows=self.ROWS)[0]["grades"][1]["rolls"], 0)

    def test_where_the_engineers_are(self):
        """Every engineer with the system of their workshop, by any spelling the journal uses; one the table does not
        know is still listed, with no system."""
        self.assertEqual(C.engineer_system("Tod 'The Blaster' McQuinn"), ("Wolf 397", "ship", "bubble"))
        self.assertEqual(C.engineer_system("felicity farseer")[0], "Deciat")
        self.assertIsNone(C.engineer_system("Nobody"))
        rows = C.engineer_list({"Felicity Farseer": {"progress": "Unlocked", "rank": 5}, "Domino Green": {"progress": "Invited", "rank": None},
                                "New Engineer": {"progress": "Known", "rank": None}})
        by = {r["name"]: r for r in rows}
        self.assertEqual(len(rows), len(C.ENGINEER_SYSTEMS) + 1)
        self.assertEqual((by["Felicity Farseer"]["system"], by["Felicity Farseer"]["progress"], by["Felicity Farseer"]["rank"]), ("Deciat", "Unlocked", 5))
        self.assertEqual((by["Domino Green"]["kind"], by["Domino Green"]["progress"]), ("suit & weapon", "Invited"))
        self.assertEqual((by["New Engineer"]["system"], by["Petra Olmanova"]["region"], by["Bill Turner"]["progress"]), (None, "Colonia", None))
        kinds = [r["kind"] for r in rows]
        self.assertEqual(kinds[:kinds.index("suit & weapon")], ["ship"] * len([k for k in kinds if k == "ship"]))   # the ship engineers first
        self.assertEqual(len({v[0] for v in C.ENGINEER_SYSTEMS.values()}), len(C.ENGINEER_SYSTEMS))                 # one workshop a system
        for b in C.load_blueprints():                                    # every engineer a blueprint names has a system
            for g in b["grades"].values():
                for e in g["engineers"]:
                    self.assertIsNotNone(C.engineer_system(e), e)

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
        events = [
            ev(T("08:00:00"), "MissionAccepted", MissionID=1, Name="Mission_Delivery_name", LocalisedName="Deliver 20 units of Gold", Faction="Sol Workers",
               Commodity="$Gold_Name;", Commodity_Localised="Gold", Count=20, DestinationSystem="Alpha Centauri", DestinationStation="Hutton Orbital",
               Expiry=T("12:20:00"), Wing=False, Influence="++", Reputation="+", Reward=2500000),
            ev(T("08:05:00"), "MissionAccepted", MissionID=2, Name="Mission_Massacre", Faction="Sol Workers", TargetFaction="Bad Lot", KillCount=12,
               DestinationSystem="Wolf 359", Expiry=T("09:00:00", "2026-10-14"), Wing=True, Reward=9000000),
            ev(T("08:06:00"), "MissionAccepted", MissionID=3, Name="Mission_Courier", LocalisedName="Courier job", Faction="X", Expiry=T("09:00:00")),
            ev(T("08:07:00"), "MissionAccepted", MissionID=4, Name="Mission_Sightseeing", LocalisedName="Tour", PassengerCount=4, Expiry=T("09:00:00", "2026-10-20")),
            ev(T("08:30:00"), "CargoDepot", MissionID=1, ItemsDelivered=8, TotalItemsToDeliver=20),
            ev(T("08:40:00"), "MissionRedirected", MissionID=2, NewDestinationSystem="Sol", NewDestinationStation="Old Port"),
            ev(T("08:50:00"), "MissionCompleted", MissionID=4), ev(T("08:51:00"), "MissionFailed", MissionID=99),
        ]
        m = C.missions(events, now=NOW)
        self.assertEqual([r["id"] for r in m], [3, 1, 2])                       # the soonest first: the expired one leads
        self.assertEqual((m[0]["expired"], m[0]["soon"], m[1]["soon"], m[1]["expires_in"], m[2]["soon"]), (True, False, True, 1200, False))
        self.assertEqual((m[1]["name"], m[1]["commodity"], m[1]["count"], m[1]["delivered"], m[1]["station"], m[1]["reward"]),
                         ("Deliver 20 units of Gold", "Gold", 20, 8, "Hutton Orbital", 2500000))
        self.assertEqual((m[2]["name"], m[2]["target"], m[2]["count"], m[2]["wing"], m[2]["redirected"], m[2]["system"], m[2]["station"]),
                         ("Massacre", "Bad Lot", 12, True, True, "Sol", "Old Port"))

    def test_the_login_list_decides(self):
        events = [ev(T("08:00:00"), "MissionAccepted", MissionID=1, Name="Mission_A", Expiry=T("20:00:00")),
                  ev(T("08:01:00"), "MissionAccepted", MissionID=2, Name="Mission_B"),
                  ev(T("10:00:00"), "Missions", Active=[{"MissionID": 2, "Name": "Mission_B", "PassengerMission": False, "Expires": 0},
                                                         {"MissionID": 7, "Name": "Mission_Old_name", "PassengerMission": True, "Expires": 7200}],
                     Failed=[], Complete=[])]
        m = C.missions(events, now=NOW)
        self.assertEqual([(r["id"], r["name"], r["expiry"], r["passengers"]) for r in m],
                         [(7, "Old", T("12:00:00"), True), (2, "B", None, False)])   # 1 is gone; 7 was accepted before these journals
        self.assertEqual(C.missions([], now=NOW), [])


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
        ev(T("11:50:00"), "MarketSell", Type="platinum", Type_Localised="Platinum", Count=5, TotalSale=1500000),
        ev(T("11:51:00"), "MarketSell", Type="gold", Count=5, TotalSale=99),
    ]

    def test_combat_and_mining(self):
        rows = C.sessions(self.EVENTS)
        self.assertEqual([(r["start"], r["ship"], bool(r["combat"]), bool(r["mining"])) for r in rows],
                         [(T("11:00:00"), "Type-9 Heavy", False, True), (T("08:00:00"), "Krait Mk II", True, False)])   # newest first
        c = rows[1]["combat"]
        self.assertEqual((c["kills"], c["bounties"], c["bonds"], c["deaths"], c["interdicted"], c["redeemed"], c["by_ship"]),
                         (3, 400000, 60000, 1, 1, 400000, {"Anaconda": 2}))
        self.assertEqual((c["seconds"], c["per_hour"]), (1800, 6.0))            # three kills over half an hour
        m = rows[0]["mining"]
        self.assertEqual((m["tons"], m["refined"], m["prospected"], m["content"], m["motherlodes"], m["cracked"]),
                         (6, {"Platinum": 5, "osmium": 1}, 2, {"High": 1, "Low": 1}, 1, 1))
        self.assertEqual((m["prospectors"], m["collectors"], m["sold"], m["seconds"], m["per_hour"]), (1, 1, 1500000, 1800, 12.0))
        self.assertEqual(rows[0]["end"], T("11:51:00"))
        t = C.totals(rows)
        self.assertEqual((t["combat"], t["mining"]), ({"sessions": 1, "kills": 3, "bounties": 400000, "bonds": 60000, "deaths": 1},
                                                      {"sessions": 1, "tons": 6, "prospected": 2, "sold": 1500000}))

    def test_without_a_login_line(self):
        rows = C.sessions(self.EVENTS[1:3])                                     # the window began mid-session
        self.assertEqual((len(rows), rows[0]["combat"]["kills"], rows[0]["commander"]), (1, 2, None))
        self.assertEqual(C.sessions([]), [])


class Profile(unittest.TestCase):
    EVENTS = [
        ev(T("07:00:00", "2026-10-10"), "LoadGame", Commander="Old Login", Credits=1, Loan=0),
        ev(T("08:00:00"), "LoadGame", Commander="Tester", FID="F1", Credits=1234567890, Loan=5000, Ship="krait_light"),
        ev(T("08:00:01"), "Rank", Combat=3, Trade=7, Explore=8, Soldier=0, Exobiologist=4, Empire=2, Federation=14, CQC=0),
        ev(T("08:00:02"), "Progress", Combat=41, Trade=50, Explore=100, Soldier=0, Exobiologist=25, Empire=80, Federation=0, CQC=0),
        ev(T("08:00:03"), "Reputation", Empire=76.5, Federation=-40.0, Alliance=12.25),
        ev(T("08:00:04"), "Powerplay", Power="Aisling Duval", Rank=3, Merits=4500),
        ev(T("08:00:05"), "SquadronStartup", SquadronName="Sample Wing", CurrentRank=1),
        ev(T("08:00:06"), "Statistics", Bank_Account={"Current_Wealth": 9000000000, "Spent_On_Ships": 500000000, "Insurance_Claims": 3},
           Exploration={"Systems_Visited": 12345, "Total_Hyperspace_Distance": 987654, "Time_Played": 7200000, "Exploration_Profits": 0},
           Combat={"Bounties_Claimed": 40}),
        ev(T("08:00:07"), "CarrierStats", CarrierID=1, Callsign="X1X-X1X", Name="SAMPLE CARRIER", FuelLevel=800, Finance={"CarrierBalance": 250000000}),
        ev(T("08:30:00"), "Promotion", Combat=4),
    ] + Inventory.EVENTS

    def test_ranks_and_what_the_next_takes(self):
        p = C.profile(self.EVENTS)
        r = {x["key"]: x for x in p["ranks"]}
        self.assertEqual([x["title"] for x in p["ranks"]], ["Combat", "Trade", "Exploration", "Exobiology", "Mercenary", "CQC", "Federal Navy", "Imperial Navy"])
        self.assertEqual((r["Combat"]["name"], r["Combat"]["progress"], r["Combat"]["next"], r["Combat"]["to_next"]), ("Expert", 0, "Master", None))   # promoted since
        self.assertEqual((r["Trade"]["name"], r["Trade"]["next"], r["Trade"]["to_next"], r["Trade"]["earned_by"]),
                         ("Tycoon", "Elite", 330000000, "trade profit"))                 # half of the 660M step left
        self.assertEqual((r["Explore"]["name"], r["Explore"]["next"], r["Explore"]["to_next"]), ("Elite", "Elite I", None))   # past the known steps
        self.assertEqual((r["Exobiologist"]["name"], r["Exobiologist"]["to_next"]), ("Cataloguer", 3000000))   # 75% of 4M
        self.assertEqual((r["Federation"]["name"], r["Federation"]["progress"], r["Federation"]["next"]), ("Admiral", None, None))   # the top
        self.assertEqual((r["Empire"]["name"], r["Empire"]["next"], r["Empire"]["progress"]), ("Serf", "Master", 80))
        self.assertEqual(C.rank_rows({"Trade": 99, "Explore": "x"}, {})[0]["name"], "99")

    def test_money_fleet_and_career(self):
        p = C.profile(self.EVENTS)
        self.assertEqual((p["commander"], p["ts"], p["credits"], p["loan"], p["squadron"]), ("Tester", T("08:00:00"), 1234567890, 5000, "Sample Wing"))
        self.assertEqual(p["assets"], {"wealth": 9000000000, "ships": 4, "fleet": 100 + 9000000 + 150000000 + 32000, "modules": 5103953 + 35400,
                                       "carrier": 250000000})
        self.assertEqual([s["id"] for s in p["fleet"]], [7, 5, 3, 6])                    # the one you fly, then by value
        self.assertEqual(p["reputation"], {"Federation": -40.0, "Empire": 76.5, "Alliance": 12.2})
        self.assertEqual(p["power"], {"name": "Aisling Duval", "rank": 3, "merits": 4500})
        self.assertEqual(p["carrier"], {"name": "SAMPLE CARRIER", "callsign": "X1X-X1X", "balance": 250000000, "fuel": 800})
        self.assertEqual([(c["label"], c["value"], c["kind"]) for c in p["career"]], [
            ("Time played", 7200000, "time"), ("Systems visited", 12345, "n"), ("Distance jumped", 987654, "ly"), ("Bounties claimed", 40, "n"),
            ("Insurance claims", 3, "n"), ("Spent on ships", 500000000, "cr")])          # a zero is left out
        self.assertIsNone(C.profile(Inventory.EVENTS))                                  # no login on record
        bare = C.profile([ev(T("08:00:00"), "LoadGame", Commander="New")])
        self.assertEqual((bare["ranks"], bare["fleet"], bare["career"], bare["power"], bare["carrier"]), ([], [], [], None, None))


class Distances(unittest.TestCase):
    """How far each engineer's system is: known here (find_local), else asked of Spansh once and kept."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.asked = []
        self.down = None

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
        out = asyncio.run(C.engineer_distances(self.state, gap=0))
        systems = {v[0] for v in C.ENGINEER_SYSTEMS.values()}
        self.assertEqual((out["from"], out["error"], out["missing"]), ("Sol", None, ["Wyrd"]))   # Spansh has no such system here
        self.assertEqual((out["distances"]["Sol"], out["distances"]["Deciat"], out["distances"]["Khun"]), (0.0, 5.0, 100.0))
        self.assertEqual(set(self.asked), systems - {"Sol", "Deciat"})              # the ones known here are not asked
        self.asked.clear()
        self.state.journals.pos = {"name": "Far", "x": 100.0, "y": 0.0, "z": 0.0}
        again = asyncio.run(C.engineer_distances(self.state, gap=0))
        self.assertEqual((self.asked, again["distances"]["Khun"], again["distances"]["Sol"]), (["Wyrd"], 0.0, 100.0))   # kept: only the missing one again
        self.state.journals.pos = None
        self.assertEqual(asyncio.run(C.engineer_distances(self.state, gap=0))["distances"], {})   # no position yet

    def test_spansh_down(self):
        self.down = OSError("no route to host")
        out = asyncio.run(C.engineer_distances(self.state, gap=0))
        self.assertIn("Spansh could not be asked", out["error"])
        self.assertEqual(len(self.asked), 1)                                          # stopped at the first failure
        self.assertEqual(set(out["distances"]), {"Sol", "Deciat"})


class Server(unittest.TestCase):
    def test_routes(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        d = temp_dir(self)
        write(d, "Journal.2026-10-12T080000.01.log", Inventory.EVENTS + Sessions.EVENTS[:5] + [
            ev(T("08:00:00"), "EngineerProgress", Engineers=[{"Engineer": "Felicity Farseer", "Progress": "Unlocked", "Rank": 5}]),
            ev(T("08:01:00"), "MissionAccepted", MissionID=1, Name="Mission_A", LocalisedName="A job")])
        state = types.SimpleNamespace(journals=types.SimpleNamespace(materials={"counts": {"arsenic": 4}, "names": {}}))
        app = web.Application()
        C.add_routes(app, state, lambda: [d])
        real = C.jscan.events
        C.jscan.events = lambda dirs, names, days=30, now=None: real(dirs, names, 3650, now)   # whenever the test runs
        self.addCleanup(setattr, C.jscan, "events", real)

        async def go():
            async with TestClient(TestServer(app)) as c:
                return [await (await c.get(f"/api/commander/{p}")).json() for p in ("inventory", "engineering", "missions", "sessions", "profile")]
        inv, eng, mis, ses, pro = asyncio.run(go())
        self.assertEqual((pro["profile"]["commander"], len(pro["profile"]["fleet"])), ("Tester", 4))
        self.assertEqual((len(inv["ships"]["ships"]), len(inv["modules"]["modules"]), len(inv["suits"])), (4, 3, 1))
        fsd = next(b for b in eng["blueprints"] if b["id"] == "FSD_LongRange")
        self.assertEqual([m["have"] for m in fsd["grades"][-1]["materials"] if m["id"] == "arsenic"], [4])
        ff = next(e for e in eng["engineers"] if e["name"] == "Felicity Farseer")
        self.assertEqual((ff["progress"], ff["rank"], ff["system"]), ("Unlocked", 5, "Deciat"))
        self.assertEqual(len(eng["engineers"]), len(C.ENGINEER_SYSTEMS))
        self.assertEqual({e["system"] for g in fsd["grades"] for e in g["engineers"] if e["name"] == "Felicity Farseer"}, {"Deciat"})
        self.assertTrue(all(e["ready"] for g in fsd["grades"] for e in g["engineers"] if e["name"] == "Felicity Farseer"))
        self.assertEqual([m["name"] for m in mis["missions"]], ["A job"])
        self.assertEqual((ses["sessions"][0]["combat"]["kills"], ses["totals"]["combat"]["sessions"]), (3, 1))

    def test_the_real_server_has_them(self):
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        state = ed_outrider.State(db, ed_outrider.Journals(db), types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        paths = {r.resource.canonical for r in ed_outrider.make_app(state).router.routes()}
        for part in ("profile", "inventory", "engineering", "missions", "sessions", "engineer_distances"):
            self.assertIn(f"/api/commander/{part}", paths)


if __name__ == "__main__":
    unittest.main()

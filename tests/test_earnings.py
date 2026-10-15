"""The CMDR tab's Earnings, its summary (outrider/earnings.py, State.commander_earnings, GET /api/commander/earnings and
/api/export?what=earnings): the totals, the period, the months, the sales, the species, the stations, the ships, the
mining and the estimates, from made-up journal lines fed to Journals.handle on a scratch database."""
import asyncio
import csv
import io
import json
import types
import unittest

from support import ed_outrider

import outrider.earnings as E
import outrider.unsold

T = lambda day, hms: f"{day}T{hms}Z"
AUG, OCT, OCT13 = "2026-08-10", "2026-10-12", "2026-10-13"
CARRIER = 3700000099   # your carrier (made up)
STATION = 3228000001   # a station's market (made up)
AURASUS = "$Codex_Ent_Bacterial_01_Name;"


def ev(ts, name, **kw):
    return dict({"timestamp": ts, "event": name}, **kw)


def loadout(ts, ship_id, ship, name):
    return ev(ts, "Loadout", Ship=ship, ShipID=ship_id, ShipName=name, HullValue=1, ModulesValue=1, MaxJumpRange=50.0,
              FuelCapacity={"Main": 32, "Reserve": 0.6}, Modules=[])


def jump(ts, id64, pos, star):
    """The FSD's charge (the arrival's star class) and the jump."""
    return [ev(ts[:-3] + "00Z", "StartJump", JumpType="Hyperspace", StarSystem=f"S{id64}", SystemAddress=id64, StarClass=star),
            ev(ts, "FSDJump", StarSystem=f"S{id64}", SystemAddress=id64, StarPos=pos, JumpDist=5.0, FuelUsed=1.0, FuelLevel=20.0)]


def scan(ts, system, body_id, planet, mass):
    return ev(ts, "Scan", ScanType="Detailed", BodyName=f"S{system} {body_id}", BodyID=body_id, StarSystem=f"S{system}",
              SystemAddress=system, DistanceFromArrivalLS=10.0, PlanetClass=planet, MassEM=mass, Radius=1000000.0,
              SurfaceGravity=1.0, SurfaceTemperature=100.0, Landable=False, WasDiscovered=False, WasMapped=False)


def organic(ts, kind):
    return ev(ts, "ScanOrganic", ScanType=kind, Genus="$Codex_Ent_Bacterial_Genus_Name;", Genus_Localised="Bacterium",
              Species=AURASUS, Species_Localised="Bacterium Aurasus", SystemAddress=101, Body=2)


def docked(ts, name="Keller Relay", market=STATION, kind="Coriolis"):
    return ev(ts, "Docked", StationName=name, StationType=kind, MarketID=market, StarSystem="S101", SystemAddress=101,
              StationServices=["dock", "exploration", "vistagenomics", "commodities"])


def undocked(ts, name="Keller Relay", market=STATION):
    return ev(ts, "Undocked", StationName=name, MarketID=market)


def refined(ts, what):
    return ev(ts, "MiningRefined", Type=f"${what}_name;", Type_Localised=what.title())


def sell(ts, what, count, total, market=STATION):
    return ev(ts, "MarketSell", MarketID=market, Type=what, Type_Localised=what.title(), Count=count,
              SellPrice=total // count, TotalSale=total, AvgPricePaid=0)


def carto(ts, system, base, bonus):
    return ev(ts, "MultiSellExplorationData", Discovered=[{"SystemName": system, "NumBodies": 1}], BaseValue=base, Bonus=bonus,
              TotalEarnings=base + bonus)


# A year of play in one list: a sale before any ship was known (2025), an exploration trip in August (two jumps, a first
# scan, a sample run, a cartographic and a Vista Genomics sale at a station), nothing in September, and October's mining
# (3 t of painite refined by the ship and sold with 2 t bought, 1 t of gold by the SRV sold to your own carrier), then a
# jump, a scan and a death that loses it
EVENTS = [
    carto(T("2025-12-31", "23:00:00"), "Far Away", 900, 100),
    loadout(T(AUG, "08:00:00"), 7, "krait_light", "Seeker"),
    *jump(T(AUG, "08:01:00"), 100, [0, 0, 0], "K"),
    *jump(T(AUG, "08:02:00"), 101, [3, 4, 0], "K"),
    scan(T(AUG, "08:03:00"), 101, 1, "Icy body", 0.1),
    organic(T(AUG, "08:10:00"), "Log"), organic(T(AUG, "08:12:00"), "Sample"), organic(T(AUG, "08:14:00"), "Analyse"),
    docked(T(AUG, "10:00:00")),
    carto(T(AUG, "10:01:00"), "S101", 500, 100),
    ev(T(AUG, "10:02:00"), "SellOrganicData", MarketID=STATION, BioData=[
        {"Genus": "$Codex_Ent_Bacterial_Genus_Name;", "Species": AURASUS, "Species_Localised": "Bacterium Aurasus",
         "Value": 1000000, "Bonus": 4000000},
        {"Genus": "$Codex_Ent_Stratum_Genus_Name;", "Species": "$Codex_Ent_Stratum_02_Name;",
         "Species_Localised": "Stratum Paleas", "Value": 500000, "Bonus": 0}]),
    undocked(T(AUG, "10:05:00")),
    ev(T(OCT, "08:00:00"), "LoadGame", Commander="Tester", Ship="python"),
    loadout(T(OCT, "08:00:05"), 9, "python", "Digger"),
    ev(T(OCT, "08:00:10"), "CarrierStats", CarrierID=CARRIER, Callsign="ABC-123", Name="TEST CARRIER", FuelLevel=500,
       JumpRangeCurr=500.0, CarrierType="FleetCarrier"),
    refined(T(OCT, "08:10:00"), "painite"), refined(T(OCT, "08:11:00"), "painite"), refined(T(OCT, "08:12:00"), "painite"),
    ev(T(OCT, "08:20:00"), "LaunchSRV", SRVType="mev_rhino", ID=1, PlayerControlled=True),
    refined(T(OCT, "08:21:00"), "gold"),
    ev(T(OCT, "08:22:00"), "DockSRV", SRVType="mev_rhino", ID=1),
    docked(T(OCT, "09:00:00")),
    sell(T(OCT, "09:01:00"), "painite", 5, 1000000),       # 3 t mined, 2 t bought: 600,000 is mining
    undocked(T(OCT, "09:05:00")),
    docked(T(OCT, "09:30:00"), "ABC-123", CARRIER, "FleetCarrier"),
    sell(T(OCT, "09:31:00"), "gold", 1, 50000, CARRIER),   # your own carrier: left out
    undocked(T(OCT, "09:35:00"), "ABC-123", CARRIER),
    *jump(T(OCT13, "08:01:00"), 102, [3, 4, 12], "F"),
    scan(T(OCT13, "08:02:00"), 102, 1, "Water world", 0.5),
    ev(T(OCT13, "08:30:00"), "Died"),
    ev(T(OCT13, "08:31:00"), "Resurrect", Option="rebuy", Cost=100, Bankrupt=False),
]


def setup(test, events=EVENTS):
    """A scratch database, its Journals fed `events` and a State over it."""
    db = ed_outrider.open_db(":memory:")
    test.addCleanup(db.close)
    j = ed_outrider.Journals(db)
    for e in events:
        j.handle(e)
    return j, ed_outrider.State(db, j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)


def value(planet, mass):
    """Outrider's own estimate of one first-discovered, unmapped planet (outrider.unsold, as the Ledger values it)."""
    return outrider.unsold.body_value({"PlanetClass": planet, "MassEM": mass, "first_discovered": True}, False, False, True)


class Summary(unittest.TestCase):
    def setUp(self):
        self.j, self.state = setup(self)

    def test_totals(self):
        t = self.state.commander_earnings()["totals"]
        self.assertEqual(t["carto"], {"base": 1400, "bonus": 200, "total": 1600, "sales": 2, "systems": 2})
        self.assertEqual(t["bio"], {"base": 1500000, "bonus": 4000000, "total": 5500000, "sales": 1, "species": 2})
        self.assertEqual(t["mining"], {"total": 600000, "tons": 3, "sales": 1})   # the mined part; your carrier's left out
        self.assertEqual((t["total"], t["sales"]), (1600 + 5500000 + 600000, 4))

    def test_the_period(self):
        got = lambda *a: self.state.commander_earnings(*a)
        self.assertEqual(got()["period"], {"kind": "all", "label": "All time", "year": None, "month": None})
        y25 = got("2025")
        self.assertEqual((y25["period"]["label"], y25["totals"]["total"], [s["ts"][:4] for s in y25["sales"]]),
                         ("2025", 1000, ["2025"]))
        aug = got("2026", "8")
        self.assertEqual(aug["period"], {"kind": "month", "label": "August 2026", "year": 2026, "month": 8})
        self.assertEqual((aug["totals"]["carto"]["total"], aug["totals"]["bio"]["total"], aug["totals"]["mining"]["total"]),
                         (600, 5500000, 0))
        self.assertEqual(got("2026", "10")["totals"]["total"], 600000)
        self.assertEqual(got("2026", "9")["totals"]["sales"], 0)
        self.assertEqual(got("2026", "8")["months"], got()["months"])   # the chart is all time, whatever the period

    def test_the_months_and_years(self):
        out = self.state.commander_earnings()
        months = out["months"]
        self.assertEqual([m["month"] for m in months], ["2025-12"] + [f"2026-{m:02d}" for m in range(1, 11)])   # no gaps
        by = {m["month"]: m for m in months}
        self.assertEqual(by["2025-12"], {"month": "2025-12", "carto": 1000, "bio": 0, "mining": 0})
        self.assertEqual(by["2026-08"], {"month": "2026-08", "carto": 600, "bio": 5500000, "mining": 0})
        self.assertEqual(by["2026-09"], {"month": "2026-09", "carto": 0, "bio": 0, "mining": 0})   # the gap month
        self.assertEqual(by["2026-10"]["mining"], 600000)
        self.assertEqual(out["years"], [2025, 2026])
        self.assertEqual(E.month_series([]), [])

    def test_the_sales(self):
        sales = self.state.commander_earnings()["sales"]
        self.assertEqual([(s["kind"], s["ts"]) for s in sales], [("mining", T(OCT, "09:01:00")), ("bio", T(AUG, "10:02:00")),
                                                                 ("carto", T(AUG, "10:01:00")), ("carto", T("2025-12-31", "23:00:00"))])
        mine, bio, carto, old = sales
        self.assertEqual(mine, {"ts": T(OCT, "09:01:00"), "kind": "mining", "station": "Keller Relay", "station_type": "Coriolis",
                                "market_id": STATION, "ship": {"id": 9, "name": "Digger", "type": "python", "type_name": None},
                                "what": {"commodity": "Painite", "tons": 3, "of": 5}, "base": None, "bonus": None, "total": 600000})
        self.assertEqual((bio["what"], bio["base"], bio["bonus"], bio["total"], bio["ship"]["name"]),
                         ({"species": 2}, 1500000, 4000000, 5500000, "Seeker"))
        self.assertEqual((carto["what"], carto["station"]), ({"systems": 1}, "Keller Relay"))
        self.assertEqual((old["ship"], old["station"]), (None, None))   # before any ship or dock was known
        self.assertEqual(self.state.commander_earnings()["more"], 0)

    def test_the_list_is_capped(self):
        p = E.period()
        out = E.summary(p, E.read(self.j.db, p), limit=2)
        self.assertEqual(([s["kind"] for s in out["sales"]], out["more"]), (["mining", "bio"], 2))
        self.assertEqual(out["totals"]["sales"], 4)   # the totals are the period's, whatever is listed

    def test_species_exact_from_each_sale(self):
        self.assertEqual(self.state.commander_earnings()["species"], [
            {"name": "Bacterium Aurasus", "count": 1, "value": 1000000, "bonus": 4000000, "total": 5000000},
            {"name": "Stratum Paleas", "count": 1, "value": 500000, "bonus": 0, "total": 500000}])
        self.assertEqual(self.state.commander_earnings("2026", "10")["species"], [])

    def test_stations(self):
        self.assertEqual(self.state.commander_earnings()["stations"],
                         [{"name": "Keller Relay", "type": "Coriolis", "sales": 3, "total": 600 + 5500000 + 600000}])

    def test_per_ship(self):
        ships = {s["id"]: s for s in self.state.commander_earnings()["ships"]}
        self.assertEqual(ships[7], {"id": 7, "name": "Seeker", "type": "krait_light", "type_name": None, "jumps": 2, "ly": 5.0,
                                    "bodies": 1, "species": 1, "earnings": 600 + 5500000, "days": 1})
        self.assertEqual(ships[9], {"id": 9, "name": "Digger", "type": "python", "type_name": None, "jumps": 1, "ly": 12.0,
                                    "bodies": 1, "species": 0, "earnings": 600000, "days": 2})
        self.assertEqual([s["id"] for s in self.state.commander_earnings()["ships"]], [7, 9])   # the most earned first
        # October alone: the jump starts where August's last one ended (the arrival before the period)
        self.assertEqual([(s["id"], s["ly"]) for s in self.state.commander_earnings("2026", "10")["ships"]], [(9, 12.0)])

    def test_mining(self):
        m = self.state.commander_earnings()["mining"]
        self.assertEqual((m["earned"], m["tons"], m["sales"]), (600000, 3, 1))
        self.assertEqual(m["commodities"], [
            {"name": "Painite", "refined": 3, "refined_srv": 0, "sold": 3, "earned": 600000, "per_ton": 200000},
            {"name": "Gold", "refined": 0, "refined_srv": 1, "sold": 0, "earned": 0, "per_ton": None}])
        self.assertEqual(m["stations"], [{"name": "Keller Relay", "type": "Coriolis", "sales": 1, "tons": 3, "earned": 600000,
                                          "per_ton": 200000}])
        self.assertEqual(m["best"], [{"ts": T(OCT, "09:01:00"), "commodity": "Painite", "tons": 3, "earned": 600000,
                                      "per_ton": 200000, "station": "Keller Relay"}])
        self.assertEqual(m["own_carrier"], {"sales": 1, "tons": 1, "total": 50000})   # the "left out" line
        notes = self.state.commander_earnings()["notes"]
        self.assertTrue(any("own carrier" in n and "50,000 cr" in n for n in notes))

    def test_most_common(self):
        c = self.state.commander_earnings()["common"]
        self.assertEqual(c["stars"], [{"class": "K", "name": "K (Yellow-Orange) Star", "count": 2},
                                      {"class": "F", "name": "F (White) Star", "count": 1}])
        self.assertEqual(c["bodies"], [{"type": "Icy body", "count": 1}, {"type": "Water world", "count": 1}])
        self.assertEqual(c["species"], [{"name": "Bacterium Aurasus", "count": 1}])
        self.assertEqual(self.state.commander_earnings("2026", "10")["common"]["bodies"], [{"type": "Water world", "count": 1}])

    def test_the_estimates_are_labelled_and_the_losses_the_ledgers(self):
        est = self.state.commander_earnings()["estimates"]
        self.assertEqual(est["label"], "estimate")
        # the system sold, valued by Outrider from your scan of it; "Far Away" was never scanned here: no estimate
        self.assertEqual(est["top_systems"], [{"name": "S101", "id": "101", "value": value("Icy body", 0.1), "bodies": 1,
                                               "sold": T(AUG, "10:01:00")}])
        self.assertEqual(est["systems"], 2)
        lost = self.state.ledger()["losses"]
        self.assertEqual(len(lost), 1)
        self.assertEqual(est["lost"], {"deaths": 1, "ships": 1, "value": round(lost[0]["value"] + lost[0]["bio_value"]),
                                       "carto": round(lost[0]["value"]), "bio": 0})
        self.assertEqual(est["lost"]["value"], value("Water world", 0.5))   # the scan that died with the ship
        self.assertEqual(self.state.commander_earnings("2026", "8")["estimates"]["lost"]["deaths"], 0)
        self.assertTrue(any("estimate" in n.lower() for n in self.state.commander_earnings()["notes"]))

    def test_kept_until_the_data_moves(self):
        first = self.state.commander_earnings()
        self.assertIs(self.state.commander_earnings(), first)
        self.j.handle(docked(T(OCT13, "10:00:00")))
        self.j.handle(carto(T(OCT13, "10:01:00"), "S102", 1000, 0))
        self.assertEqual(self.state.commander_earnings()["totals"]["carto"]["sales"], 3)

    def test_a_sale_stored_before_53_counts_without_its_pay(self):
        """bio_sales rows from before PARSER_VERSION 53 named their species only: counted, at 0 cr, named from your runs."""
        self.j.db.execute("UPDATE bio_sales SET bio_data = ?", (json.dumps([[AURASUS.lower(), True]]),))
        self.j.data_seq += 1
        self.assertEqual(self.state.commander_earnings()["species"],
                         [{"name": "Bacterium Aurasus", "count": 1, "value": 0, "bonus": 0, "total": 0}])


class Period(unittest.TestCase):
    def test_good_and_bad(self):
        self.assertEqual(E.period("", "")["kind"], "all")
        self.assertEqual(E.period("2026")["label"], "2026")
        self.assertEqual((E.period("2026", "12")["start"], E.period("2026", "12")["end"]),
                         ("2026-12-01T00:00:00Z", "2027-01-01T00:00:00Z"))
        self.assertEqual(E.period("2026", "03")["label"], "March 2026")
        for year, month in (("26", None), ("abcd", None), ("20266", None), ("２０２６", None), (None, "8"), ("2026", "13"),
                            ("2026", "0"), ("2026", "x"), ("2026", "123")):
            with self.assertRaises(ValueError, msg=(year, month)):
                E.period(year, month)


class Server(unittest.TestCase):
    def client(self, state, go):
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            async with TestClient(TestServer(ed_outrider.make_app(state))) as c:
                return await go(c)
        return asyncio.run(run())

    def test_the_route(self):
        _, state = setup(self)

        async def go(c):
            out = []
            for q in ("", "?year=2026", "?year=2026&month=8", "?year=&month=", "?year=26", "?month=8", "?year=2026&month=13",
                      "?year=2026&month=x"):
                r = await c.get("/api/commander/earnings" + q)
                out.append((r.status, await r.json()))
            return out
        got = self.client(state, go)
        self.assertEqual([s for s, _ in got], [200, 200, 200, 200, 400, 400, 400, 400])
        self.assertEqual([b["period"]["label"] for _, b in got[:4]], ["All time", "2026", "August 2026", "All time"])
        self.assertEqual({b["code"] for _, b in got[4:]}, {"bad_request"})
        self.assertEqual(got[5][1]["error"], "month: only with a year")
        self.assertEqual(set(got[0][1]), {"period", "totals", "months", "years", "sales", "more", "species", "stations",
                                          "ships", "mining", "common", "estimates", "notes"})

    def test_not_an_ai_tool_yet(self):
        import outrider.tools
        self.assertFalse(outrider.tools.allowed("/api/commander/earnings"))

    def test_the_csv(self):
        _, state = setup(self)

        async def go(c):
            r = await c.get("/api/export?what=earnings")
            return r.status, r.headers.get("Content-Disposition"), await r.text()
        status, disp, text = self.client(state, go)
        self.assertEqual(status, 200)
        self.assertIn('filename="earnings-', disp)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], ["ts", "kind", "station", "station_type", "ship", "what", "base", "bonus", "total"])
        self.assertEqual(rows[1], [T(OCT, "09:01:00"), "mining", "Keller Relay", "Coriolis", "Digger (python)",
                                   "3 t Painite (of 5 t sold)", "", "", "600000"])
        self.assertEqual(rows[2], [T(AUG, "10:02:00"), "bio", "Keller Relay", "Coriolis", "Seeker (krait_light)", "2 species",
                                   "1500000", "4000000", "5500000"])
        self.assertEqual(rows[-1], [T("2025-12-31", "23:00:00"), "carto", "", "", "", "1 system", "900", "100", "1000"])
        self.assertEqual(len(rows), 5)   # every sale, your own carrier's left out


if __name__ == "__main__":
    unittest.main()

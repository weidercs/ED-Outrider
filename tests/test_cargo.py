"""Unit tests: cargo: the ship's hold (exact, with what you paid) and your fleet carrier's (tracked: sell orders confirm,
the journal tracks the rest, Recount fills gaps), the carrier's tritium (outrider/cargo.py, State.cargo_summary).

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import json
import os
import shutil
import tempfile
import types
import unittest

from support import ed_outrider  # also puts the repository root on sys.path
import outrider.cargo as cargo  # noqa: E402

CARRIER = 3700251648
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "carrier_market.json")


def real():
    """The author's carrier on 2026-10-07 (tests/fixtures/carrier_market.json): its journal events and Market.json."""
    with open(FIXTURE, encoding="utf-8") as f:
        fx = json.load(f)
    at, events = None, []
    for ev in fx["events"]:   # the docks give a CargoTransfer its market, as Journals.handle_cargo does
        if ev["event"] == "Docked":
            at = None if ev.get("Taxi") or ev.get("Multicrew") else ev.get("MarketID")
        elif ev["event"] == "Undocked":
            at = None
        else:
            events.append((ev["timestamp"], dict(ev, _at=at) if ev["event"] == "CargoTransfer" else ev))
    return fx, events, [(fx["market"]["timestamp"], fx["market"]["Items"])]


def ev(ts, name, **kw):
    return dict({"timestamp": ts, "event": name}, **kw)


def stats(ts, cargo_t, fuel=500, used=None):
    return ev(ts, "CarrierStats", CarrierID=CARRIER, CarrierType="FleetCarrier", FuelLevel=fuel,
              SpaceUsage={"TotalCapacity": 25000, "Cargo": cargo_t, "FreeSpace": 25000 - (used or cargo_t + 1000)})


def item(name, stock=0, demand=0, buy=0, sell=0):
    return {"Name": f"${name}_name;", "Name_Localised": name.title(), "Stock": stock, "Demand": demand,
            "BuyPrice": buy, "SellPrice": sell}


class CarrierFold(unittest.TestCase):
    """carrier_fold: pure."""

    def test_real_carrier(self):
        """The author's carrier: the market's sell orders confirm 15,746 t; the sell orders set earlier that day and
        cancelled (an order means at least that much there) and a transfer of water are tracked; with the two lines
        no order ever showed entered, the total is CarrierStats' 16,085 t, in sync."""
        fx, events, markets = real()
        st = cargo.carrier_fold(CARRIER, events, markets)
        lines = st["lines"]
        self.assertEqual(sum(x["count"] for x in lines.values() if x["state"] == "confirmed"), 15746)
        self.assertEqual((lines["tritium"]["count"], lines["tritium"]["state"]), (13531, "confirmed"))
        self.assertEqual((lines["personalweapons"]["count"], lines["personalweapons"]["state"]), (182, "seen"))
        self.assertEqual(lines["water"]["state"], "seen")
        self.assertEqual(cargo.carrier_reported(st), 16085)
        self.assertEqual(cargo.carrier_total(st), 16076)   # the 9 t no order ever showed
        counts = [("2026-10-07T10:30:00Z", "metaalloys", 3, "Meta-Alloys"),
                  ("2026-10-07T10:30:00Z", "modularterminals", 6, "Modular Terminals")]
        st = cargo.carrier_fold(CARRIER, events, markets, counts)
        self.assertEqual(cargo.carrier_total(st), 16085)
        self.assertEqual(st["lines"]["metaalloys"]["state"], "entered")
        self.assertEqual(st["names"]["metaalloys"], "Meta-Alloys")
        # another carrier's id: none of these events are its (its markets are the caller's to pick)
        self.assertEqual(cargo.carrier_fold(123, events)["lines"], {})

    def test_buy_order_filled_by_others(self):
        """A buy order shows only what it still wants: what others sold you is the order minus that, your own sales
        into it taken off first."""
        events = [(t, e) for t, e in [
            ("2026-10-01T10:00:00Z", ev("2026-10-01T10:00:00Z", "CarrierTradeOrder", CarrierID=CARRIER, Commodity="silver",
                                        PurchaseOrder=10, Price=5000)),
            ("2026-10-01T10:05:00Z", ev("2026-10-01T10:05:00Z", "MarketSell", MarketID=CARRIER, Type="silver", Count=2,
                                        SellPrice=5000))]]
        st = cargo.carrier_fold(CARRIER, events, [("2026-10-01T12:00:00Z", [item("silver", demand=5, sell=5000)])])
        line = st["lines"]["silver"]
        self.assertEqual(line["count"], 5)   # 2 you sold + 3 others did
        self.assertEqual([m[2] for m in line["moves"]], ["sold", "others"])
        self.assertEqual(st["orders"]["silver"]["amount"], 5)
        # filled: the market no longer lists it; the last 5 came in
        st = cargo.carrier_fold(CARRIER, events, [("2026-10-01T12:00:00Z", [item("silver", demand=5, sell=5000)]),
                                                  ("2026-10-01T13:00:00Z", [])])
        self.assertEqual(st["lines"]["silver"]["count"], 10)
        self.assertNotIn("silver", st["orders"])

    def test_entered_line_moves(self):
        """A count you entered keeps its mark through your journaled moves, which say what changed it."""
        events = [("2026-10-08T09:00:00Z", ev("2026-10-08T09:00:00Z", "CargoTransfer", _at=CARRIER,
                                              Transfers=[{"Type": "modularterminals", "Count": 2, "Direction": "toship"}])),
                  ("2026-10-08T09:30:00Z", ev("2026-10-08T09:30:00Z", "CargoTransfer", _at=999,   # another station
                                              Transfers=[{"Type": "modularterminals", "Count": 1, "Direction": "toship"}]))]
        st = cargo.carrier_fold(CARRIER, events, (), [("2026-10-07T10:30:00Z", "modularterminals", 6, "Modular Terminals")])
        line = st["lines"]["modularterminals"]
        self.assertEqual((line["count"], line["state"]), (4, "entered"))
        self.assertEqual(cargo.move_text(line["moves"][0]), "−2 t moved to your ship (2026-10-08)")
        # a count of 0 removes the line
        st = cargo.carrier_fold(CARRIER, events, (), [("2026-10-07T10:30:00Z", "modularterminals", 6, None),
                                                      ("2026-10-09T10:30:00Z", "modularterminals", 0, None)])
        self.assertNotIn("modularterminals", st["lines"])

    def test_sell_orders(self):
        """A sell order the market no longer lists sold out; a cancelled one leaves the line seen at its last count."""
        m1 = [item("platinum", stock=100, buy=9999), item("gold", stock=20, buy=9999)]
        cancel = ev("2026-10-01T11:00:00Z", "CarrierTradeOrder", CarrierID=CARRIER, Commodity="gold", CancelTrade=True)
        st = cargo.carrier_fold(CARRIER, [("2026-10-01T11:00:00Z", cancel)],
                                [("2026-10-01T10:00:00Z", m1), ("2026-10-01T12:00:00Z", [])])
        self.assertNotIn("platinum", st["lines"])
        self.assertEqual((st["lines"]["gold"]["count"], st["lines"]["gold"]["state"], st["lines"]["gold"]["ts"]),
                         (20, "seen", "2026-10-01T10:00:00Z"))

    def test_stale_lines_when_over(self):
        """The author's 2025 history left 34,000 t tracked that others had bought unjournaled: when the carrier holds
        less than is tracked, lines with no news for 30 days go (a real one shows as the gap); a fresh sell order
        resets a tracked line; an open sell order the market does not list sold out."""
        def transfer(ts, typ, n):
            return (ts, ev(ts, "CargoTransfer", _at=CARRIER, Transfers=[{"Type": typ, "Count": n, "Direction": "tocarrier"}]))
        events = [transfer("2025-01-01T10:00:00Z", "aluminium", 500), transfer("2025-01-01T10:00:00Z", "steel", 80),
                  transfer("2026-09-30T10:00:00Z", "water", 10), transfer("2025-01-02T10:00:00Z", "gold", 300),
                  ("2025-01-03T10:00:00Z", ev("2025-01-03T10:00:00Z", "CarrierTradeOrder", CarrierID=CARRIER,
                                              Commodity="gold", SaleOrder=50, Price=1)),
                  ("2025-01-04T10:00:00Z", ev("2025-01-04T10:00:00Z", "CarrierTradeOrder", CarrierID=CARRIER,
                                              Commodity="steel", SaleOrder=80, Price=1))]
        market = [("2026-10-07T10:00:01Z", [item("platinum", stock=100, buy=9)])]
        over = cargo.carrier_fold(CARRIER, events + [("2026-10-07T10:00:00Z", stats("2026-10-07T10:00:00Z", 110))], market)
        self.assertEqual(sorted(over["lines"]), ["platinum", "water"])   # gold 50 (the order's count) sold out too
        kept = cargo.carrier_fold(CARRIER, events + [("2026-10-07T10:00:00Z", stats("2026-10-07T10:00:00Z", 610))], market)
        self.assertEqual(kept["lines"]["aluminium"]["count"], 500)   # nothing says it is wrong
        self.assertNotIn("steel", kept["lines"])   # its open sell order is not listed: sold out
        before = cargo.carrier_fold(CARRIER, events)
        self.assertEqual(before["lines"]["gold"]["count"], 50)   # the order's count: newer news than the transfer

    def test_reported_follows_your_moves(self):
        """The carrier's own total moves with your transfers after its CarrierStats (no false gap until the next)."""
        events = [("2026-10-01T10:00:00Z", stats("2026-10-01T10:00:00Z", 100)),
                  ("2026-10-01T10:05:00Z", ev("2026-10-01T10:05:00Z", "CargoTransfer", _at=CARRIER,
                                              Transfers=[{"Type": "gold", "Count": 30, "Direction": "tocarrier"}]))]
        st = cargo.carrier_fold(CARRIER, events, [("2026-10-01T10:00:00Z", [item("platinum", stock=100, buy=1)])])
        self.assertEqual((cargo.carrier_total(st), cargo.carrier_reported(st)), (130, 130))


class ShipHold(unittest.TestCase):
    """ship_apply: the hold and what you paid (average cost)."""

    def test_average_over_lots(self):
        st = cargo.new_ship()
        cargo.ship_apply(st, ev("2026-10-01T10:00:00Z", "Cargo", Vessel="Ship", Count=0, Inventory=[]))
        cargo.ship_apply(st, ev("2026-10-01T10:01:00Z", "MarketBuy", Type="platinum", Count=40, BuyPrice=44000))
        self.assertEqual(cargo.avg_text(st["lines"]["platinum"]), "44,000 cr/t")
        cargo.ship_apply(st, ev("2026-10-01T10:30:00Z", "MarketBuy", Type="platinum", Count=24, BuyPrice=47227))
        line = st["lines"]["platinum"]
        self.assertEqual((line["count"], line["lots"], round(line["avg"])), (64, 2, 45210))
        self.assertEqual(cargo.avg_text(line), "Avg 45,210 cr/t (2 lots)")
        # mined tons carry no price
        cargo.ship_apply(st, ev("2026-10-01T11:00:00Z", "MiningRefined", Type="$platinum_name;"))
        self.assertEqual(cargo.avg_text(st["lines"]["platinum"]), "Avg 45,210 cr/t on 64 of 65 t")
        # a sale: the game's own average corrects it; the rest stays
        cargo.ship_apply(st, ev("2026-10-01T12:00:00Z", "MarketSell", Type="platinum", Count=5, SellPrice=60000,
                                AvgPricePaid=45300))
        line = st["lines"]["platinum"]
        self.assertEqual((line["count"], line["priced"], line["avg"]), (60, 60, 45300))

    def test_snapshot_same_second(self):
        """A Cargo.json read before its purchase line: the count is not added twice, the price is kept."""
        st = cargo.new_ship()
        cargo.ship_snapshot(st, [{"Name": "gold", "Count": 10, "Stolen": 0}], 10, "2026-10-01T10:00:05Z")
        cargo.ship_apply(st, ev("2026-10-01T10:00:05Z", "MarketBuy", Type="gold", Count=10, BuyPrice=9000))
        line = st["lines"]["gold"]
        self.assertEqual((line["count"], line["priced"], line["avg"]), (10, 10, 9000))
        # a later Inventory keeps what it cost
        cargo.ship_apply(st, ev("2026-10-01T11:00:00Z", "Cargo", Vessel="Ship", Count=10,
                                Inventory=[{"Name": "gold", "Count": 10, "Stolen": 0}]))
        self.assertEqual(st["lines"]["gold"]["avg"], 9000)

    def test_deposit_and_transfer(self):
        """Depositing tritium takes it from the ship's hold (the carrier's only falls with the transfer before)."""
        st = cargo.new_ship()
        cargo.ship_apply(st, ev("2026-09-26T23:41:26Z", "CargoTransfer",
                                Transfers=[{"Type": "tritium", "Count": 934, "Direction": "toship"}]))
        cargo.ship_apply(st, ev("2026-09-26T23:41:34Z", "CarrierDepositFuel", CarrierID=CARRIER, Amount=906, Total=1000))
        self.assertEqual(st["lines"]["tritium"]["count"], 28)
        cargo.ship_apply(st, ev("2026-09-26T23:50:00Z", "CargoTransfer",
                                Transfers=[{"Type": "tritium", "Count": 28, "Direction": "tocarrier"}]))
        self.assertNotIn("tritium", st["lines"])


class CarrierFuel(unittest.TestCase):

    def test_burn_matches_real_jumps(self):
        """The author's recorded jumps (ly, tritium burned, capacity used, depot before the jump)."""
        for ly, burned, used, depot in ((491.8, 121, 21504, 509), (34.14, 13, 20832, 101), (494.63, 125, 22399, 1000),
                                        (348.35, 89, 22399, 875), (497.2, 118, 20112, 385)):
            self.assertEqual(cargo.carrier_burn(ly, used, depot), burned, (ly, used, depot))

    def test_jumps(self):
        # the author's carrier on 2026-10-07: depot 668 t, 13,531 t in the hold, 17,355 t of capacity used
        self.assertEqual(cargo.carrier_jumps(668, 13531, 17355), 151)
        self.assertEqual(cargo.carrier_jumps(100, 0, 20000), 0)   # not even one jump
        self.assertIsNone(cargo.carrier_jumps(668, 100, None))


class CargoState(unittest.TestCase):
    """Journals.handle_cargo, read_market, read_cargo_file and State.cargo_summary / carrier_tritium / cargo_recount."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def feed(self, j, fx):
        for n, e in enumerate(fx["events"]):
            j.line_source = f"Journal.test.log:{n}"
            j.handle(e)
        j.line_source = ""

    def write_market(self, fx):
        with open(os.path.join(self.dir, "Market.json"), "w", encoding="utf-8") as f:
            json.dump(dict(fx["market"], event="Market"), f)

    def test_summary_rereads_the_same(self):
        fx, _, _ = real()
        self.feed(self.j, fx)
        self.write_market(fx)
        self.assertTrue(self.j.read_market(self.dir))
        self.assertFalse(self.j.read_market(self.dir))   # read once
        out, status = self.state.cargo_recount({"Meta-Alloys": 3, "Modular Terminals": 6, "Tritium": 5})
        self.assertEqual(status, 200)
        self.assertEqual(out["skipped"], ["tritium"])   # confirmed by the market: left as it says
        c = self.state.cargo_summary()["carrier"]
        self.assertEqual((c["total"], c["reported"], c["gap"]), (16085, 16085, 0))
        self.assertEqual(next(x for x in c["lines"] if x["id"] == "metaalloys")["state"], "entered")
        # a journal re-read (cargo_events cleared, the market and counts kept) gives the same lines
        before = c["lines"]
        self.db.executescript(ed_outrider.RESET_JOURNAL_DATA)
        self.assertEqual(self.db.execute("SELECT count(*) FROM cargo_events").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM carrier_markets").fetchone()[0], 1)
        j2 = ed_outrider.Journals(self.db)
        self.feed(j2, fx)
        s2 = ed_outrider.State(self.db, j2, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.assertEqual(s2.cargo_summary()["carrier"]["lines"], before)

    def test_tile_tritium(self):
        """The tile's tritium only while tritium is on a sell order (confirmed); else the tile is as before."""
        fx, _, _ = real()
        self.feed(self.j, fx)
        self.assertIsNone(self.state.carrier_summary() and self.state.carrier_tritium())   # no market read yet
        self.write_market(fx)
        self.j.read_market(self.dir)
        t = self.state.carrier_tritium()
        self.assertEqual(t, {"depot": 668, "total": 14199, "jumps": 151})
        self.j.line_source = "Journal.test.log:9999"
        self.j.handle(ev("2026-10-07T11:00:00Z", "CarrierTradeOrder", CarrierID=CARRIER, CarrierType="FleetCarrier",
                         BlackMarket=False, Commodity="tritium", CancelTrade=True))
        self.assertIsNone(self.state.carrier_tritium())

    def test_market_elsewhere_ignored(self):
        fx, _, _ = real()
        self.feed(self.j, fx)
        with open(os.path.join(self.dir, "Market.json"), "w", encoding="utf-8") as f:
            json.dump({"timestamp": "2026-10-07T12:00:00Z", "event": "Market", "MarketID": 128016896,
                       "StationType": "Coriolis", "Items": [item("gold", stock=5, buy=1)]}, f)
        self.assertFalse(self.j.read_market(self.dir))

    def test_cargo_json(self):
        """Cargo.json is the ship's whole hold (the journal's Cargo then lists only the count)."""
        self.j.line_source = "Journal.test.log:1"
        self.j.handle(ev("2026-10-07T09:00:00Z", "MarketBuy", MarketID=1, Type="gold", Count=10, BuyPrice=9000))
        with open(os.path.join(self.dir, "Cargo.json"), "w", encoding="utf-8") as f:
            json.dump({"timestamp": "2026-10-07T09:00:02Z", "event": "Cargo", "Vessel": "Ship", "Count": 12,
                       "Inventory": [{"Name": "gold", "Count": 10, "Stolen": 0},
                                     {"Name": "drones", "Name_Localised": "Limpet", "Count": 2, "Stolen": 0}]}, f)
        self.assertTrue(self.j.read_cargo_file(self.dir))
        self.assertFalse(self.j.read_cargo_file(self.dir))   # not again
        ship = self.state.cargo_summary()["ship"]
        self.assertEqual([(x["name"], x["count"], x["avg"]) for x in ship["lines"]], [("Gold", 10, 9000), ("Limpet", 2, None)])
        self.assertEqual(ship["count"], 12)

    def test_recount_errors(self):
        self.assertEqual(self.state.cargo_recount({"gold": 1})[1], 409)   # no carrier yet
        fx, _, _ = real()
        self.feed(self.j, fx)
        for bad in (None, {}, {"gold": -1}, {"gold": 1.5}, {"gold": True}, {"": 3}, {"gold": 10 ** 6}):
            self.assertEqual(self.state.cargo_recount(bad)[1], 400, bad)


if __name__ == "__main__":
    unittest.main()

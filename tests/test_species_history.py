"""Unit tests: your own runs rank a genus's species on bodies like this one (S24): the grouping (class, atmosphere, 25 K
band, region once it holds 5 runs), your completed runs counted from the database, the guess's `history` in Here's
bodies (the pick stays the likeliest by value), and the backtest replaying runs in time order.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
import unittest.mock

from support import ed_outrider  # also puts the repository root on sys.path
import outrider.bio as bio

SOL = [0.0, 0.0, 0.0]                   # Inner Orion Spur
COLONIA = [-9530.5, -910.28, 19808.1]   # Inner Scutum-Centaurus Arm


class Pure(unittest.TestCase):
    def setUp(self):
        if not bio.load_rules():
            self.skipTest("no bio rules")

    def test_shape_and_label(self):
        # the journal's and Spansh's spellings group together
        self.assertEqual(bio.history_shape("Icy body", "Nitrogen", 80.2), ("Icy body", "nitrogen", 3))
        self.assertEqual(bio.history_shape("Icy body", "Thin Nitrogen", 99.9), ("Icy body", "nitrogen", 3))
        self.assertEqual(bio.history_shape("High metal content world", "Thin Carbon dioxide-rich", 175),
                         ("High metal content body", "carbondioxiderich", 7))
        self.assertIsNone(bio.history_shape("Class I gas giant", None, 80))   # not a landable class
        self.assertIsNone(bio.history_shape("Icy body", "Nitrogen", None))
        self.assertIsNone(bio.history_shape("Icy body", "Nitrogen", float("nan")))
        self.assertEqual(bio.history_label(("Icy body", "nitrogen", 3), "Inner Orion Spur"), "Icy body, thin N2, 75–100 K, Inner Orion Spur")
        self.assertEqual(bio.history_label(("Rocky body", "none", 6)), "Rocky body, no atmosphere, 150–175 K")

    def test_rank_drops_the_region_under_five_runs(self):
        h, shape = bio.SpeciesHistory(), ("Icy body", "nitrogen", 3)
        for _ in range(3):
            h.add("Bacterium", "Bacterium Acies", shape, "Inner Orion Spur")
        h.add("Bacterium", "Bacterium Informem", shape, "Inner Orion Spur")
        for _ in range(10):
            h.add("Bacterium", "Bacterium Informem", shape, "Inner Scutum-Centaurus Arm")
        h.add("Bacterium", "Bacterium Vesicula", ("Icy body", "argon", 3), "Inner Orion Spur")   # another atmosphere
        # 4 runs in Inner Orion Spur: under 5, so every region's counts
        r = h.rank("Bacterium", shape, "Inner Orion Spur")
        self.assertEqual(r, {"label": "Icy body, thin N2, 75–100 K", "total": 14, "region": None,
                             "species": [["Informem", 11], ["Acies", 3]]})
        r = h.rank("Bacterium", shape, "Inner Scutum-Centaurus Arm")   # 10 there: that region's own
        self.assertEqual((r["label"], r["total"], r["species"]),
                         ("Icy body, thin N2, 75–100 K, Inner Scutum-Centaurus Arm", 10, [["Informem", 10]]))
        self.assertIsNone(h.rank("Stratum", shape, None))
        self.assertIsNone(h.rank("Bacterium", ("Rocky body", "nitrogen", 3), None))
        # the favourite among the candidates given
        self.assertEqual(h.pick("Bacterium", shape, None, ["Bacterium Acies", "Bacterium Informem"]), "Bacterium Informem")
        self.assertEqual(h.pick("Bacterium", shape, None, ["Bacterium Acies", "Bacterium Nebulus"]), "Bacterium Acies")
        self.assertIsNone(h.pick("Bacterium", shape, None, ["Bacterium Nebulus"]))


class Server(unittest.TestCase):
    """species_history from the database and the guess's `history` in system_detail."""

    def setUp(self):
        if not bio.load_rules():
            self.skipTest("no bio rules")
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, ed_outrider.Spansh(self.db), 25)
        self.t = 0

    def ts(self):
        self.t += 60
        return ed_outrider.iso_ts(time.time() - 864000 + self.t)

    def scan(self, id64, body_id, name, atmosphere="Argon", temperature=179.2):
        self.j.handle({"event": "Scan", "timestamp": self.ts(), "ScanType": "Detailed", "StarSystem": name, "SystemAddress": id64,
                       "BodyID": body_id, "BodyName": f"{name} {body_id}", "PlanetClass": "Icy body", "Landable": True,
                       "AtmosphereType": atmosphere, "SurfaceGravity": 3.3, "SurfaceTemperature": temperature,
                       "DistanceFromArrivalLS": 1196.0, "WasDiscovered": True, "WasMapped": False})

    def runs(self, id64, name, pos, species, n, done=True, **kw):
        """`n` bodies sampled in system `id64` at `pos`, each a run of `species`."""
        self.j.handle({"event": "FSDJump", "timestamp": self.ts(), "StarSystem": name, "SystemAddress": id64, "StarPos": pos})
        for i in range(n):
            bid = 100 + i
            self.scan(id64, bid, name, **kw)
            self.db.execute("INSERT INTO own_organic (system, body_id, species, genus_name, species_name, samples, done_ts, ts)"
                            " VALUES (?, ?, ?, 'Bacterium', ?, 3, ?, ?)",
                            (id64, bid, "$x;", species, self.ts() if done else None, self.ts()))
        self.db.commit()

    def test_species_history(self):
        self.runs(1, "Sol Near", SOL, "Bacterium Vesicula", 2)
        self.runs(2, "Sol Near 2", SOL, "Bacterium Acies", 1)
        self.runs(3, "Sol Near 3", SOL, "Bacterium Acies", 2, done=False)        # not finished: not counted
        self.runs(4, "Sol Near 4", SOL, "Bacterium Acies", 1, temperature=150)   # another band
        h = ed_outrider.species_history(self.db)
        r = h.rank("Bacterium", ("Icy body", "argon", 7), "Inner Orion Spur")
        self.assertEqual((r["total"], r["species"], r["region"]), (3, [["Vesicula", 2], ["Acies", 1]], None))
        self.assertEqual(h.rank("Bacterium", ("Icy body", "argon", 6), None)["species"], [["Acies", 1]])
        # cached on your completed runs: a new one is counted
        first = self.state.species_history()
        self.assertIs(self.state.species_history(), first)
        self.runs(5, "Sol Near 5", SOL, "Bacterium Acies", 1)
        self.assertIsNot(self.state.species_history(), first)

    def test_guess_history_in_here(self):
        """A body like five of your runs in its region: the guess's hover names them; the pick stays by value."""
        here = 89128321720906
        self.runs(7, "Colonia Near", COLONIA, "Bacterium Vesicula", 4)
        self.runs(8, "Colonia Near 2", COLONIA, "Bacterium Acies", 1)
        self.j.handle({"event": "FSDJump", "timestamp": self.ts(), "StarSystem": "Eol Prou LW-L c8-324", "SystemAddress": here,
                       "StarPos": COLONIA})
        self.scan(here, 32, "Eol Prou LW-L c8-324")
        self.j.handle({"event": "FSSBodySignals", "timestamp": self.ts(), "BodyName": "Eol Prou LW-L c8-324 32", "BodyID": 32,
                       "SystemAddress": here, "Signals": [{"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 1}]})
        self.db.commit()
        body = next(b for b in self.state.system_detail(here)["bodies"] if b["name"] == "32")
        g = next(x for x in body["bio_guess"] if x["genus"] == "Bacterium")
        self.assertEqual(g["history"], {"label": "Icy body, thin Ar, 175–200 K, Inner Scutum-Centaurus Arm", "total": 5,
                                        "region": "Inner Scutum-Centaurus Arm", "species": [["Vesicula", 4], ["Acies", 1]]})
        by_value = g["best"]
        # HISTORY_PICK (off) would make your runs' favourite the pick; the value stays the group's maximum
        with unittest.mock.patch.object(bio, "HISTORY_PICK", True):
            on = next(x for x in next(b for b in self.state.system_detail(here)["bodies"] if b["name"] == "32")["bio_guess"]
                      if x["genus"] == "Bacterium")
        self.assertEqual((on["best"], on["value"]), ("Bacterium Vesicula", g["value"]))
        self.assertEqual(bio.HISTORY_PICK, False)
        self.assertNotEqual(by_value, "Bacterium Vesicula")   # Vesicula is not the likeliest by value: the pick moved


class Backtest(unittest.TestCase):
    """The backtest replays your runs in time order whatever the folders' order: a run is ranked by the runs before it."""

    def test_time_order_across_folders(self):
        if not bio.load_rules():
            self.skipTest("no bio rules")

        def journal(folder, name, lines):
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, name), "w") as f:
                f.write("\n".join(json.dumps(x, separators=(",", ":")) for x in lines) + "\n")   # compact, as the backtest's prefilter expects

        def run(ts, addr, body):
            return [{"timestamp": ts, "event": "FSDJump", "StarSystem": f"S{addr}", "SystemAddress": addr, "StarPos": SOL},
                    {"timestamp": ts, "event": "Scan", "ScanType": "Detailed", "SystemAddress": addr, "BodyID": body,
                     "BodyName": f"S{addr} {body}", "PlanetClass": "Icy body", "AtmosphereType": "Argon",
                     "SurfaceGravity": 0.5, "SurfaceTemperature": 180.0, "Landable": True},
                    {"timestamp": ts, "event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": addr, "Body": body,
                     "Genus_Localised": "Bacterium", "Species_Localised": "Bacterium Cerbrus"}]

        def predict(body, system=None):   # two candidates, the dearer first: the value pick is never Cerbrus
            return [{"name": "Bacterium Aurasus", "genus": "Bacterium", "value": 1000000, "variants": []},
                    {"name": "Bacterium Cerbrus", "genus": "Bacterium", "value": 900000, "variants": []}]
        with tempfile.TemporaryDirectory() as root:
            # the first folder read holds the later run (the one scored, from --since); the second the earlier one
            journal(os.path.join(root, "a"), "Journal.2026-03-01T000000.01.log", run("2026-03-01T00:00:00Z", 2, 3))
            journal(os.path.join(root, "b"), "Journal.2026-01-01T000000.01.log", run("2026-01-01T00:00:00Z", 1, 3))
            out = io.StringIO()
            with unittest.mock.patch.object(bio, "predict", predict), contextlib.redirect_stdout(out):
                bio.backtest([os.path.join(root, "a"), os.path.join(root, "b")], since="2026-02")
        self.assertIn("the likeliest by value was right 0/1 times", out.getvalue())
        self.assertIn("(by value when you had none, 0 times) 1/1", out.getvalue())
        self.assertIn("species: 1/1", out.getvalue())   # only the run from --since on is scored


if __name__ == "__main__":
    unittest.main()

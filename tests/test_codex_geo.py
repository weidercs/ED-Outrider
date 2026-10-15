"""Unit tests: geology as codex entries (outrider/codex_geo.py, S22) and the server's part of the ✦: each body's
candidates in Here, your codex's geology per region in the payload. The pairs are real: EDDN's codex traffic joined to
the scans of the same bodies (2026-10-12).

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import time
import types
import unittest

from support import ed_outrider  # also puts the repository root on sys.path
import outrider.codex_geo as G  # noqa: E402


def body(cls, volcanism, landable=True, geo=2, **kw):
    return dict({"type": "Planet", "subtype": ed_outrider.journal_planet(cls), "landable": landable, "geo": geo,
                 "volcanism": volcanism, "ed": {"PlanetClass": cls}}, **kw)


class Table(unittest.TestCase):
    def test_sets_seen_on_eddn(self):
        """One volcanism logs one of a set; no volcanism text names sulphur dioxide or iron; an icy body's material logs
        its Ice forms (EDDN's geology entries against the scans of their bodies)."""
        cases = [(body("High metal content body", "major metallic magma volcanism"), [1400102, 1400307, 1400402]),
                 (body("Rocky body", "minor rocky magma volcanism"), [1400102, 1400306, 1400402, 1400414]),
                 (body("Metal rich body", "silicate vapour geysers volcanism"), [1400114, 1400306, 1400414]),
                 (body("Icy body", "major water magma volcanism"), [1400158, 1400258]),
                 (body("Icy body", "water geysers volcanism"), [1400158, 1400258]),
                 (body("Icy body", "minor carbon dioxide geysers volcanism"), [1400159, 1400259]),
                 (body("Icy body", "minor ammonia magma volcanism"), [1400160, 1400260]),
                 (body("Icy body", "minor methane magma volcanism"), [1400161, 1400261]),
                 (body("Icy body", "minor nitrogen magma volcanism"), [1400162, 1400262])]
        self.assertEqual([G.entries_for(r) for r, _ in cases], [v for _, v in cases])
        # Spansh's wording (capitals, its own class names, no ed)
        self.assertEqual(G.entries_for({"type": "Planet", "subtype": "High metal content world", "landable": True, "geo": 1,
                                        "volcanism": "Major Silicate Vapour Geysers volcanism"}), [1400114, 1400306, 1400414])

    def test_unverified_and_impossible_left_out(self):
        """Never seen, so no mark: water or CO2 on a rocky body (the non-Ice entries), magma on an icy body, anything on
        a rocky ice body; and nothing without a landing, geological signals or volcanism."""
        for r in (body("Rocky body", "water geysers volcanism"), body("Rocky body", "carbon dioxide geysers volcanism"),
                  body("Icy body", "rocky magma volcanism"), body("Rocky ice body", "minor water magma volcanism"),
                  body("Rocky body", "silicate magma volcanism"), body("Icy body", "helium geysers volcanism"),
                  body("Rocky body", "rocky magma volcanism", landable=False), body("Rocky body", "rocky magma volcanism", geo=0),
                  body("Rocky body", ""), body("Rocky body", None), {"type": "Star", "volcanism": "rocky magma volcanism"}, None):
            self.assertEqual(G.entries_for(r), [], r)

    def test_names_and_range(self):
        every = {i for t in (G.SOLID, G.ICY) for ids in t.values() for i in ids}
        self.assertEqual(sorted(every - set(G.NAMES)), [])
        self.assertTrue(all(G.LOW <= i <= G.HIGH for i in every))
        self.assertEqual(G.NAMES[1400414], "Silicate Vapour Gas Vent")


class Server(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.now = time.time()

    def test_here_candidates_and_payload(self):
        at = lambda s: ed_outrider.iso_ts(self.now - 60 + s)
        name = "Drojau TF-H c13-0"
        self.j.handle({"event": "FSDJump", "timestamp": at(0), "StarSystem": name, "SystemAddress": 9, "StarPos": [-4179.0, -64.0, 3339.0]})
        self.j.handle({"event": "Scan", "timestamp": at(5), "ScanType": "Detailed", "StarSystem": name, "SystemAddress": 9, "BodyID": 4,
                       "BodyName": name + " B 3", "PlanetClass": "Icy body", "TerraformState": "", "Landable": True,
                       "AtmosphereType": "None", "Volcanism": "major water geysers volcanism", "DistanceFromArrivalLS": 900.0,
                       "WasDiscovered": True, "WasMapped": False})
        b3 = lambda: next(b for b in self.state.system_detail(9)["bodies"] if b["name"] == "B 3")
        self.assertIsNone(b3()["codex_geo"])   # no geological signals counted yet
        self.j.handle({"event": "FSSBodySignals", "timestamp": at(6), "BodyName": name + " B 3", "BodyID": 4, "SystemAddress": 9,
                       "Signals": [{"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 3}]})
        self.assertEqual(b3()["codex_geo"], [{"id": 1400158, "name": "Water Ice Fumarole"}, {"id": 1400258, "name": "Water Ice Geyser"}])
        # your codex's geology per region joins the body types; the anomalies above 1400499 do not
        for i, (eid, region) in enumerate(((1400158, "Inner Orion Spur"), (1400601, "Inner Orion Spur"), (1300801, "Norma Expanse"))):
            self.db.execute("INSERT INTO codex (ts, entry_id, name, region) VALUES (?, ?, 'x', ?)", (at(10 + i), eid, region))
        logged = self.state.payload()["codex_types"]
        self.assertIn(1400158, logged["Inner Orion Spur"])
        self.assertNotIn(1400601, logged["Inner Orion Spur"])


if __name__ == "__main__":
    unittest.main()

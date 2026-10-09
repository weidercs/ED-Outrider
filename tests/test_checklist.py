"""Unit tests: the exobiology checklist (outrider.checklist): where each species can grow, its colours, and your best
state with it per region.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import unittest

from support import ed_outrider  # also puts the repository root on sys.path
import outrider.bio  # noqa: E402
import outrider.checklist as cl  # noqa: E402

# regions 1..3; a ruleset's "regions" is the list of region numbers it allows (the stand-in for outrider.bio's)
region_ok = lambda r, region: "regions" not in r or region in r["regions"]   # noqa: E731
SPECIES = [
    {"id": "$A1;", "genus": "Aleoida", "name": "Aleoida Arcus", "value": 7252500, "rulesets": [{"regions": [1, 2]}],
     "colors": {"star": {"F": "Teal", "G": "Teal", "M": "Emerald"}}},
    {"id": "$B1;", "genus": "Bacterium", "name": "Bacterium Nebulus", "value": 5289900, "rulesets": [{}],
     "colors": {"element": {"polonium": "Gold", "antimony": "Magenta"}}},
    {"id": "$T1;", "genus": "Sinuous Tubers", "name": "Roseum Sinuous Tubers", "value": 111300,
     "rulesets": [{"tuber": ["Galactic Center"]}], "colors": None},
    {"id": "$S4;", "genus": "Stratum", "name": "Stratum Aranaemus", "value": 2448900, "rulesets": [], "colors": None},
    {"id": "$S4;", "genus": "Stratum", "name": "Stratum Araneamus", "value": 2448900, "rulesets": [{"regions": [3]}],
     "colors": {"star": {"F": "Lime"}}},
]


def rows(t):
    return {r["name"]: r for g in t["genera"] for r in g["species"]}


class Checklist(unittest.TestCase):
    def test_possibility(self):
        self.assertEqual(cl.possibility(SPECIES[0], 1, region_ok), "yes")
        self.assertIsNone(cl.possibility(SPECIES[0], 3, region_ok))                 # the rules rule it out
        self.assertEqual(cl.possibility(SPECIES[2], 3, region_ok), "parts")        # tubers: in their zones only
        self.assertEqual(cl.possibility(SPECIES[3], 2, region_ok), "yes")          # no rules at all: unknown, not "no"
        both = {"rulesets": [{"guardian": True, "regions": [1]}, {"regions": [1]}]}
        self.assertEqual(cl.possibility(both, 1, region_ok), "yes")                # plainly allowed by one ruleset
        self.assertEqual(cl.possibility({"rulesets": [{"guardian": True}]}, 2, region_ok), "parts")
        self.assertEqual(cl.possibility({"rulesets": [{"guardian": False}]}, 2, region_ok), "yes")   # no tie

    def test_colours(self):
        self.assertEqual(cl.colours(SPECIES[0]), [("Teal", ["F", "G"]), ("Emerald", ["M"])])
        self.assertEqual(cl.colours(SPECIES[1]), [("Gold", ["polonium"]), ("Magenta", ["antimony"])])
        self.assertEqual(cl.colours(SPECIES[2]), [])
        self.assertEqual(cl.colour_of("Aleoida Arcus - Teal", "Aleoida Arcus"), "teal")
        self.assertIsNone(cl.colour_of("Aleoida Arcus", "Aleoida Arcus"))          # before the 2023 patch
        self.assertIsNone(cl.colour_of("Other Thing - Teal", "Aleoida Arcus"))

    def test_duplicate_species_merged(self):
        merged, names = cl.merge_species(SPECIES)
        self.assertEqual([s["name"] for s in merged], ["Aleoida Arcus", "Bacterium Nebulus", "Roseum Sinuous Tubers",
                                                       "Stratum Araneamus"])   # the one with rules
        self.assertEqual(names["stratum aranaemus"], names["stratum araneamus"])
        # the real rules have that duplicate: one row for it, possible somewhere
        R = outrider.bio.load_rules()
        if not R:
            self.skipTest("no bio rules")
        t = cl.table(R["species"], None, outrider.bio.ruleset_region_ok, [], [], len(R["region_names"]) - 1)
        names = [r["name"] for g in t["genera"] for r in g["species"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(t["summary"]["possible"], len(names))   # every species can grow somewhere

    def test_states_by_region(self):
        runs = [{"species_id": "$A1;", "species": "Aleoida Arcus", "variant": "Aleoida Arcus - Teal", "region": 1, "state": "lost"},
                {"species_id": "$A1;", "species": "Aleoida Arcus", "variant": "Aleoida Arcus - Teal", "region": 1, "state": "sold"},
                {"species_id": "$A1;", "species": "Aleoida Arcus", "variant": "Aleoida Arcus - Emerald", "region": 2, "state": "aboard"},
                {"species_id": "$S4;", "species": "Stratum Araneamus", "variant": "Stratum Araneamus", "region": 3,
                 "state": "in progress"},
                {"species_id": None, "species": "Unknown Thing", "variant": None, "region": 1, "state": "sold"}]
        codex = [{"name": "Bacterium Nebulus - Gold", "region": 1}, {"name": "Roseum Sinuous Tubers", "region": 3}]
        t = rows(cl.table(SPECIES, 1, region_ok, runs, codex, 3))
        a = t["Aleoida Arcus"]
        self.assertEqual((a["state"], a["runs"], a["possible"]), ("sold", 2, "yes"))   # sold beats lost; region 2's not here
        self.assertEqual([(v["colour"], v["where"], v["state"]) for v in a["variants"]["list"]],
                         [("Teal", "F, G", "sold"), ("Emerald", "M", None)])
        self.assertEqual((a["variants"]["found"], a["variants"]["total"]), (1, 2))
        self.assertEqual((t["Bacterium Nebulus"]["state"], t["Bacterium Nebulus"]["variants"]["found"]), ("logged", 1))
        self.assertIsNone(t["Stratum Araneamus"]["possible"])                       # region 3 only
        self.assertIsNone(t["Roseum Sinuous Tubers"]["state"])                      # logged in region 3, not here
        self.assertEqual(t["Roseum Sinuous Tubers"]["short"], "Roseum")
        t3 = rows(cl.table(SPECIES, 3, region_ok, runs, codex, 3))
        self.assertEqual(t3["Stratum Araneamus"]["state"], "logged")               # a run under way
        self.assertEqual((t3["Roseum Sinuous Tubers"]["state"], t3["Roseum Sinuous Tubers"]["variants"]["found"]),
                         ("logged", 1))                                              # its own one variant
        everywhere = cl.table(SPECIES, None, region_ok, runs, codex, 3)
        a = rows(everywhere)["Aleoida Arcus"]
        self.assertEqual((a["state"], [v["state"] for v in a["variants"]["list"]]), ("sold", ["sold", "aboard"]))
        s = everywhere["summary"]
        self.assertEqual((s["possible"], s["found"], s["sold"], s["logged"]), (4, 4, 1, 3))
        self.assertEqual(s["colours_found"], 4)   # Teal, Emerald, Gold, the tubers' own one (Araneamus's run has no colour)

    def test_the_server_has_it(self):
        self.assertIs(ed_outrider.outrider.checklist, cl)

    def test_short_names(self):
        self.assertEqual(cl.short_name({"name": "Aleoida Arcus", "genus": "Aleoida"}), "Arcus")
        self.assertEqual(cl.short_name({"name": "Luteolum Anemone", "genus": "Anemone"}), "Luteolum")
        self.assertEqual(cl.short_name({"name": "Bark Mound", "genus": "Bark Mound"}), "Bark Mound")


if __name__ == "__main__":
    unittest.main()

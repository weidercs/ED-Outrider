"""#12: where your landing pad is (outrider/pads.py, after bgol's LandingPad plugin's tables): the layouts, the words, the
spoken sentence with the green-lights assumption, the plugin's test commands."""
import math
import unittest

from support import ed_outrider  # also puts the repository root on sys.path

import outrider.pads as P  # noqa: E402


class Pads(unittest.TestCase):
    def test_the_reader_uses_these(self):
        self.assertIs(ed_outrider.outrider.pads, P)

    def test_which_layout(self):
        self.assertEqual([P.layout(t) for t in ("Coriolis", "Orbis", "Ocellus", "Bernal", "AsteroidBase", "Dodec")],
                         ["starport"] * 6)
        self.assertEqual(P.layout("FleetCarrier", "G0X-85Z"), "fleet")
        self.assertEqual(P.layout("FleetCarrier", "ABCD"), "squadron")   # a four-letter name, as the plugin tells them
        self.assertEqual(P.layout("SurfaceStation", "Trailblazer Dream", 129032183), "colonisation")
        self.assertEqual(P.layout("SurfaceStation", "$EXT_PANEL_ColonisationShip; Something"), "colonisation")
        for t in ("Outpost", "CraterPort", "CraterOutpost", "OnFootSettlement", "SurfaceStation", None):
            self.assertIsNone(P.layout(t, "Somewhere"), t)   # number only

    def test_the_starport_pattern(self):
        """45 pads, the 15-pad pattern repeated four sectors on; every pad has a place, two share a spot at most."""
        places = [P.starport_pad(n) for n in range(1, 46)]
        self.assertEqual(places[:4], [(0, 0), (0, 0), (0, 2), (0, 2)])
        self.assertEqual(places[15], (4, 0))
        self.assertEqual(places[30], (8, 0))
        self.assertTrue(all(0 <= s < 12 and 0 <= d < 3 for s, d in places))
        self.assertTrue(all(places.count(p) <= 2 for p in places))
        self.assertIsNone(P.starport_pad(0))
        self.assertIsNone(P.starport_pad(46))
        pads = P.starport_pads()
        self.assertEqual(len(pads), 45)
        self.assertEqual(pads[0][2:], [1, 2])   # pad 1, the first of two side by side
        self.assertEqual(pads[1][2:], [2, 2])
        self.assertEqual(pads[6][2:], [1, 1])   # pad 7 alone at its spot

    def test_starport_words(self):
        """As you come through the slot with the green lights on your right: depth, then up/down and left/right."""
        self.assertEqual(P.where("starport", 34)["words"], "at the back · up on your right")
        self.assertEqual(P.where("starport", 1)["words"], "near the slot · below you")
        self.assertEqual(P.where("starport", 7)["words"], "halfway in · down on your left")
        self.assertEqual(P.where("starport", 15)["words"], "at the back · on your left")
        self.assertEqual(P.side_words(6), "above you")
        self.assertEqual(P.side_words(9), "on your right")
        self.assertEqual(sorted({P.side_words(s) for s in range(12)}),
                         sorted(["below you", "above you", "on your left", "on your right", "up on your left",
                                 "up on your right", "down on your left", "down on your right"]))

    def test_carrier_words(self):
        self.assertEqual(P.carrier_words("fleet", 7), "port side, toward the bow")
        self.assertEqual(P.carrier_words("fleet", 2), "starboard side, toward the stern")
        self.assertEqual(P.carrier_words("fleet", 14), "starboard side, amidships")
        self.assertEqual(len(P.carrier_boxes("fleet")), 16)
        self.assertEqual(len(P.carrier_boxes("squadron")), 32)
        self.assertEqual(P.carrier_words("squadron", 1), "starboard deck, port side, toward the stern")
        self.assertEqual(P.carrier_words("squadron", 23), "port deck, port side, toward the bow")
        self.assertIsNone(P.carrier_words("fleet", 17))
        self.assertIsNone(P.where("fleet", 17))
        self.assertIsNone(P.where(None, 3))
        # the colonisation ship's small pads in the squadron order (the plugin's)
        self.assertNotEqual(P.carrier_boxes("fleet")[13], P.carrier_boxes("colonisation")[13])

    def test_every_pad_inside_the_deck(self):
        """Kurbo26 (2026-10-15): pads 7 and 8's outer corners poked out of the fleet carrier's bow. Every corner of every
        pad, on each layout and deck, lies inside the deck's outline (CARRIER_OUTLINE, a convex shape) by at least one
        unit, room for the line (the old outline fails it); the map carries the outline the drawings use."""
        def inside(outline, px, py, xo=0):   # on the inner side of every edge, going round, by the margin
            pts = [(x + xo, y) for x, y in outline]
            return all((bx - ax) * (py - ay) - (by - ay) * (px - ax) >= math.hypot(bx - ax, by - ay)
                       for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]))
        for kind in ("fleet", "squadron", "colonisation"):
            decks = (26, -26) if kind == "squadron" else (0,)
            for n, (x, y, w, h) in enumerate(P.carrier_boxes(kind), 1):
                xo = min(decks, key=lambda d: abs(x + w / 2 - d))
                for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
                    self.assertTrue(inside(P.CARRIER_OUTLINE, cx, cy, xo), (kind, n, cx, cy))
        old = ((-26, 40), (-26, -30), (0, -44), (26, -30), (26, 40))
        self.assertFalse(inside(old, -12, -38))   # pad 7's top left corner, outside the old bow
        self.assertEqual(P.where("fleet", 7)["map"]["outline"], [list(p) for p in P.CARRIER_OUTLINE])

    def test_spoken(self):
        """The green lights at a starport when asked for; never at a carrier (no slot)."""
        sp, fc = P.where("starport", 34), P.where("fleet", 7)
        self.assertEqual(P.spoken(sp, True), "With the green lights on your right, it's at the back, up on your right.")
        self.assertEqual(P.spoken(sp, False), "At the back, up on your right.")
        self.assertEqual(P.spoken(fc, True), "Port side, toward the bow.")
        self.assertIsNone(P.spoken(None, True))

    def test_the_test_commands(self):
        self.assertEqual(P.test_command("!sppad 34"), ("starport", 34))
        self.assertEqual(P.test_command("!FCPAD7"), ("fleet", 7))
        self.assertEqual(P.test_command("!scpad 3"), ("squadron", 3))
        self.assertEqual(P.test_command("!cspad 12"), ("colonisation", 12))
        for m in ("hello", "!sppad", "!sppad 345", "o7 !sppad 3", None):
            self.assertIsNone(P.test_command(m), m)


if __name__ == "__main__":
    unittest.main()

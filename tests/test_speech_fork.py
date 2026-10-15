"""This fork's personalities (outrider/speech_fork.py, resources/speech.fork.json): Rocky, kept apart from upstream's
resources/speech.json and merged into it as the lines are loaded."""
import json
import os
import re
import tempfile
import unittest

from support import ed_outrider

import outrider.speech
import outrider.speech_fork as F

HERE = os.path.dirname(ed_outrider.STATIC_DIR)


def shipped():
    with open(os.path.join(HERE, "resources", "speech.json"), encoding="utf-8") as f:
        return json.load(f)


class Rocky(unittest.TestCase):
    def test_rocky_personality(self):
        """Rocky: a personality like the others (a list for every alert the speech file has), in his way of talking: no
        contractions, his tripled words and ", question?" somewhere in most alerts, and never a swearing list."""
        doc = F.merge(shipped())
        self.assertEqual(doc["styles"]["rocky"], "Rocky (Project Hail Mary)")
        triple = re.compile(r"\b(\w+) \1 \1\b", re.I)
        marked = 0
        for key, entry in doc["lines"].items():
            lines = entry.get("rocky")
            self.assertTrue(lines, f"{key}: no Rocky lines (a new alert upstream: write him twelve in resources/speech.fork.json)")
            self.assertEqual((len(lines), len(set(lines))), (12, 12), key)
            self.assertNotIn("rocky_profane", entry)
            for text in lines:
                self.assertNotIn("'", text, f"{key}: {text}")          # no contractions, no possessives
                self.assertLessEqual(len(text), 110, f"{key}: {text}")
            # only placeholders the alert's other lines use: an unknown one would be said as written
            known = set(re.findall(r"\{(\w+)\}", " ".join(v for st, vs in entry.items() if st not in ("when", "rocky") for v in vs))) | {"name"}
            self.assertLessEqual(set(re.findall(r"\{(\w+)\}", " ".join(lines))), known, key)
            marked += any(triple.search(t) or "question?" in t or "Amaze" in t for t in lines)
        self.assertGreaterEqual(marked, len(doc["lines"]) - 2)             # his marks in (nearly) every alert
        # {jumps} may be missing when the tank fills: in few of its lines, as the other personalities have it
        self.assertLessEqual(sum("{jumps}" in t for t in doc["lines"]["tank_full"]["rocky"]), 3)
        self.assertEqual(outrider.speech.check(doc), [])                   # the merged document is a good speech file

    def test_upstreams_file_is_left_alone(self):
        doc = shipped()
        self.assertNotIn("rocky", doc["styles"])
        self.assertFalse([k for k, e in doc["lines"].items() if "rocky" in e])


class Merge(unittest.TestCase):
    FORK = {"styles": {"rocky": "Rocky"}, "lines": {"hull": {"rocky": ["Hull bad bad bad."]}, "nowhere": {"rocky": ["Unused."]}}}

    def test_merge(self):
        doc = {"styles": {"business": "Business"}, "lines": {"hull": {"when": "x", "business": ["Hull."]}, "fuel": {"business": ["Fuel."]}}}
        got = F.merge(doc, self.FORK)
        self.assertEqual(got["styles"], {"business": "Business", "rocky": "Rocky"})
        self.assertEqual(got["lines"]["hull"], {"when": "x", "business": ["Hull."], "rocky": ["Hull bad bad bad."]})
        self.assertEqual(got["lines"]["fuel"], {"business": ["Fuel."]})
        self.assertNotIn("nowhere", got["lines"])                          # an alert only the fork names: nothing says it
        self.assertNotIn("rocky", doc["styles"])                           # the document itself is not changed
        own = {"styles": {"rocky": "Mine"}, "lines": {"hull": {"rocky": ["My own line."]}}}
        self.assertIs(F.merge(own, self.FORK), own)                         # a speech file with its own Rocky keeps it
        for odd in (None, [], {"styles": []}, {"lines": {}}):
            self.assertIs(F.merge(odd, self.FORK), odd)
        self.assertIs(F.merge(doc, {}), doc)

    def test_the_loader_merges(self):
        """SpeechLines (what the page and the server speak from) carries the fork's personalities; a missing or broken
        fork file leaves the speech file as it is."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "speech.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"styles": {"business": "Business"}, "lines": {"hull": {"business": ["Hull at {pct}."]}}}, f)
            got = outrider.speech.SpeechLines(path).lines()
            self.assertEqual(got["styles"]["rocky"], "Rocky (Project Hail Mary)")
            self.assertEqual(len(got["lines"]["hull"]["rocky"]), 12)
            broken = os.path.join(d, "fork.json")
            with open(broken, "w", encoding="utf-8") as f:
                f.write("not json")
            self.assertEqual(F.load(broken), {})
            self.assertEqual(F.load(os.path.join(d, "none.json")), {})


if __name__ == "__main__":
    unittest.main()

"""This fork's fixes to upstream's code that show on Windows, each with a test that fails without it."""
import json
import os
import tempfile
import unittest

from support import ed_outrider

S = ed_outrider.outrider.speech   # the module ed_outrider loaded


class SpeechStamp(unittest.TestCase):
    def test_a_rewrite_in_the_same_tick_is_read(self):
        """The bans and the speech file are read again when their size changes, not only their time: two writes in one
        timestamp tick (common on Windows) kept the first."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "speech.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"styles": {"business": "B"}, "lines": {"hull": {"business": ["Hull {pct}.", "Hull damage.", "Hull low."]}}}, f)
            bans = os.path.join(d, "speech_banned.json")
            with open(bans, "w", encoding="utf-8") as f:
                json.dump({"hull": ["Hull damage."]}, f)
            sl = S.SpeechLines(path)
            self.assertEqual(sl.lines()["lines"]["hull"]["business"], ["Hull {pct}.", "Hull low."])
            stamp = os.stat(bans).st_mtime_ns
            with open(bans, "w", encoding="utf-8") as f:
                json.dump({"hull": ["Hull damage.", "Hull low."]}, f)
            os.utime(bans, ns=(stamp, stamp))                                   # the same tick
            self.assertEqual(sl.lines()["lines"]["hull"]["business"], ["Hull {pct}."])
            stamp = os.stat(path).st_mtime_ns
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"styles": {"business": "B"}, "lines": {"hull": {"business": ["Hull {pct}.", "Hull damage.", "Hull low.", "Hull new."]}}}, f)
            os.utime(path, ns=(stamp, stamp))
            self.assertEqual(sl.lines()["lines"]["hull"]["business"], ["Hull {pct}.", "Hull new."])


if __name__ == "__main__":
    unittest.main()

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



class NewerDatabase(unittest.TestCase):
    def test_columns_a_newer_outrider_added_are_fitted(self):
        """A database a newer Outrider wrote (columns this version does not know) is fitted to this version's tables,
        the rows kept in the columns both know, so inserts that fill a row by position work again; a table only the
        newer version has is left alone."""
        import shutil
        import sqlite3
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)   # after the database is closed (cleanups run last first)
        if True:
            path = os.path.join(d, "outrider.sqlite")
            db = ed_outrider.open_db(path)
            db.execute("INSERT INTO jumps (ts, id64, name, x, y, z) VALUES ('2026-10-15T10:00:00Z', 7, 'Sol', 0, 0, 0)")
            db.execute("ALTER TABLE sale_events ADD COLUMN station TEXT")
            db.execute("ALTER TABLE sale_events ADD COLUMN ship_id INTEGER")
            db.execute("ALTER TABLE jumps ADD COLUMN ship_id INTEGER")
            db.execute("INSERT INTO bookmarks (id64, name, x, y, z, note) VALUES (7, 'Sol', 0, 0, 0, 'home')")
            db.execute("ALTER TABLE bookmarks ADD COLUMN colour TEXT")   # a table the re-read keeps
            db.execute("UPDATE jumps SET ship_id = 3")
            db.execute("CREATE TABLE play_activity (login_ts TEXT, commander TEXT)")
            # stamped with this version's reader number already: the first start on it stamped it, then failed on a
            # sale_events insert (the player's case, 2026-10-15)
            ed_outrider.meta_set(db, "parser_version", ed_outrider.PARSER_VERSION)
            db.commit()
            db.close()
            logged = []
            real = ed_outrider.fit_newer_tables
            ed_outrider.fit_newer_tables = lambda db, log=print: real(db, logged.append)
            self.addCleanup(setattr, ed_outrider, "fit_newer_tables", real)
            db = ed_outrider.open_db(path)
            self.addCleanup(db.close)
            cols = lambda t: [r["name"] for r in db.execute(f"PRAGMA table_info({t})")]
            self.assertNotIn("station", cols("sale_events"))
            self.assertNotIn("ship_id", cols("jumps"))
            self.assertEqual(db.execute("SELECT note FROM bookmarks WHERE id64 = 7").fetchone()["note"], "home")   # the row kept
            self.assertNotIn("colour", cols("bookmarks"))
            self.assertEqual(cols("play_activity"), ["login_ts", "commander"])                                  # left alone
            self.assertEqual(sorted(x.split(" had")[0] for x in logged), ["database: bookmarks", "database: jumps", "database: sale_events"])
            # the insert that failed ("table sale_events has 13 columns but 9 values were supplied") works again
            db.execute("INSERT OR IGNORE INTO sale_events VALUES (?, 'carto', ?, ?, ?, ?, 0, ?, NULL)",
                       ("2026-10-15T10:01:00Z", 100, 0, 100, 1, "live"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sale_events").fetchone()[0], 1)
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jumps__newer'").fetchone() is None)
            self.assertEqual(ed_outrider.fit_newer_tables(db, logged.append), [])                               # nothing more to fit
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("SELECT * FROM jumps__newer")


if __name__ == "__main__":
    unittest.main()

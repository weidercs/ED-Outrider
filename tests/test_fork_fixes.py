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
            db.execute("ALTER TABLE sale_events ADD COLUMN zz_newer_where TEXT")
            db.execute("ALTER TABLE sale_events ADD COLUMN zz_newer_ship INTEGER")
            db.execute("ALTER TABLE jumps ADD COLUMN zz_newer_ship INTEGER")
            db.execute("INSERT INTO bookmarks (id64, name, x, y, z, note) VALUES (7, 'Sol', 0, 0, 0, 'home')")
            db.execute("ALTER TABLE bookmarks ADD COLUMN colour TEXT")   # a table the re-read keeps
            db.execute("UPDATE jumps SET zz_newer_ship = 3")
            db.execute("CREATE TABLE zz_newer_table (login_ts TEXT, commander TEXT)")
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
            self.assertNotIn("zz_newer_where", cols("sale_events"))
            self.assertNotIn("zz_newer_ship", cols("jumps"))
            self.assertEqual(db.execute("SELECT note FROM bookmarks WHERE id64 = 7").fetchone()["note"], "home")   # the row kept
            self.assertNotIn("colour", cols("bookmarks"))
            self.assertEqual(cols("zz_newer_table"), ["login_ts", "commander"])                                  # left alone
            self.assertEqual(sorted(x.split(" had")[0] for x in logged), ["database: bookmarks", "database: jumps", "database: sale_events"])
            # a fitted table has exactly this version's columns, so an insert that fills a row by position fits again
            # (the player's crash: "table sale_events has 13 columns but 9 values were supplied")
            fresh = ed_outrider.open_db(":memory:")
            self.addCleanup(fresh.close)
            for t in ("sale_events", "jumps", "bookmarks"):
                self.assertEqual(cols(t), [r["name"] for r in fresh.execute(f"PRAGMA table_info({t})")], t)
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jumps__newer'").fetchone() is None)
            self.assertEqual(ed_outrider.fit_newer_tables(db, logged.append), [])                               # nothing more to fit
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("SELECT * FROM jumps__newer")


class PageSections(unittest.TestCase):
    def test_no_view_inside_another(self):
        """Every view's <section> is closed before the next opens: a merge that dropped GalNet's </section> put Plot
        Route and every view after it inside GalNet's hidden section, so Plot Route never drew (2026-10-15)."""
        from html.parser import HTMLParser
        import os

        class Walk(HTMLParser):
            def __init__(self):
                super().__init__()
                self.open, self.nested = [], []

            def handle_starttag(self, tag, attrs):
                if tag == "section":
                    me = dict(attrs).get("id") or "?"
                    if self.open:
                        self.nested.append(f"{me} inside {self.open[-1]}")
                    self.open.append(me)

            def handle_endtag(self, tag):
                if tag == "section" and self.open:
                    self.open.pop()
        w = Walk()
        with open(os.path.join(ed_outrider.STATIC_DIR, "page.html"), encoding="utf-8") as f:
            w.feed(f.read())
        self.assertEqual((w.nested, w.open), ([], []))


if __name__ == "__main__":
    unittest.main()

"""Outrider's own log (S5b: outrider/serverlog.py, GET /api/serverlog, Settings -> Server's Show log) and the notices
banner (S5a: outrider/notices.py, the payload's notices, POST /api/notices/dismiss). Nothing here starts a server:
main() runs with run() replaced, and the app runs in aiohttp's test client."""
import argparse
import asyncio
import contextlib
import io
import os
import sys
import tempfile
import unittest
import unittest.mock

from support import ed_outrider  # also puts the repository root on sys.path

import outrider  # noqa: E402
import outrider.auth  # noqa: E402
import outrider.notices as N  # noqa: E402
import outrider.serverlog as L  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_760_000_000.0

    def __call__(self):
        self.t += 1
        return self.t


def forget_secrets(test):
    """hide() is process-wide: a test's secrets are dropped after it."""
    before = set(L._secrets)
    test.addCleanup(lambda: (L._secrets.clear(), L._secrets.update(before)))


class ServerLog(unittest.TestCase):
    def setUp(self):
        forget_secrets(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_tee_keeps_whole_lines_and_writes_the_terminal_first(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            log = L.ServerLog(clock=Clock())
            restore = L.install(log)
            try:
                self.assertIs(L.ACTIVE, log)
                print("one")
                print("two", end="")
                self.assertEqual([x["text"] for x in log.since()["lines"]], ["one"])   # a line waits for its newline
                print(" and a half")
                print("trouble\r", file=sys.stderr)
                sys.stdout.flush()
                self.assertTrue(hasattr(sys.stdout, "encoding"))   # the rest is the terminal's
            finally:
                restore()
            self.assertIs(sys.stdout, out)   # put back as they were
            self.assertIs(sys.stderr, err)
            self.assertIsNone(L.ACTIVE)
        self.assertEqual((out.getvalue(), err.getvalue()), ("one\ntwo and a half\n", "trouble\r\n"))
        got = log.since()
        self.assertEqual([(x["seq"], x["kind"], x["text"]) for x in got["lines"]],
                         [(1, "out", "one"), (2, "out", "two and a half"), (3, "err", "trouble")])
        self.assertEqual([x["text"] for x in log.since(2)["lines"]], ["trouble"])
        self.assertEqual((log.since(3)["lines"], got["last"], got["first"]), ([], 3, 1))
        # no terminal at all (pythonw on Windows): the log still has it
        t = L.Tee(None, log, "out")
        self.assertEqual(t.write("x\n"), 2)
        self.assertEqual(log.since(3)["lines"][0]["text"], "x")

    def test_keeps_the_last_lines_and_the_file_beside_the_database(self):
        log = L.ServerLog(keep=3, clock=Clock())
        for i in range(5):
            log.feed("out", f"line {i}\n")
        self.assertEqual(([x["text"] for x in log.since()["lines"]], log.since()["first"]), (["line 2", "line 3", "line 4"], 3))
        path = os.path.join(self.tmp.name, "outrider.log")
        self.assertTrue(log.open(path))
        log.feed("err", "after\n")
        log.close()
        with open(path, encoding="utf-8") as f:
            text = f.read().splitlines()
        self.assertEqual(len(text), 4)          # the start's lines kept before the file existed come first
        self.assertTrue(text[0].endswith("| line 2") and text[3].endswith("! after"), text)
        self.assertEqual(log.since()["path"], path)

    def test_rotates_and_keeps_appending_when_it_cannot(self):
        path = os.path.join(self.tmp.name, "outrider.log")
        log = L.ServerLog(max_bytes=200, clock=Clock())
        log.open(path)
        for i in range(8):
            log.feed("out", f"{i} " + "x" * 40 + "\n")
        self.assertTrue(os.path.exists(path + ".1"))
        self.assertLessEqual(os.path.getsize(path), 200)
        # a rename that fails (the file held open elsewhere, Windows): the lines still go in
        with unittest.mock.patch.object(L.os, "replace", side_effect=PermissionError("in use")):
            for i in range(8):
                log.feed("out", f"held {i}\n")
        log.close()
        with open(path, encoding="utf-8") as f:
            self.assertIn("held 7", f.read())

    def test_hidden_values_never_show(self):
        log = L.ServerLog(clock=Clock())
        L.ACTIVE, keep = log, L.ACTIVE
        self.addCleanup(setattr, L, "ACTIVE", keep)
        log.feed("err", "config: the key is sk-abcdef-123456\n")
        L.hide("sk-abcdef-123456", "1234", None, "")   # the lines already kept too; a short value is not hidden
        log.feed("out", "again sk-abcdef-123456 and 1234\n")
        texts = [x["text"] for x in log.since()["lines"]]
        self.assertEqual(texts, ["config: the key is •••", "again ••• and 1234"])


class ServerLogMain(unittest.TestCase):
    """main() tees the server's streams for its whole run and puts them back; secrets never reach the log."""

    def setUp(self):
        forget_secrets(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = os.path.join(self.tmp.name, "scratch.toml")
        os.makedirs(os.path.join(self.tmp.name, "journals"))

    def main(self, run, config=""):
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(f'[journals]\nlive = ["{self.tmp.name}/journals"]\nlegacy = []\n' + config)
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")   # main() reconfigures stdout: a real text stream
        try:
            with unittest.mock.patch.object(ed_outrider, "run", run), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(out):
                ed_outrider.main(["--config", self.cfg, "--db", os.path.join(self.tmp.name, "x.sqlite")])
                self.assertIs(sys.stdout, out)   # main() put the streams back
        finally:
            self.assertIsNone(L.ACTIVE)
        out.flush()
        return out.buffer.getvalue().decode("utf-8")

    def test_the_log_runs_with_the_server_only(self):
        seen = {}

        async def fake_run(args, st):
            seen["log"] = L.ACTIVE
            print("server would start")
        printed = self.main(fake_run)
        lines = [x["text"] for x in seen["log"].since()["lines"]]
        self.assertEqual(lines[0], f"ED Outrider {outrider.__version__}")
        self.assertIn("server would start", lines)
        self.assertIn("server would start", printed)
        # --write-config, --list-backups and --restore print and exit: no log
        with contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO(), encoding="utf-8")), \
                unittest.mock.patch.object(L, "install", side_effect=AssertionError("teed")):
            ed_outrider.main(["--config", self.cfg, "--write-config"])   # the file exists: it prints the settings only

    def test_a_crash_is_in_the_log(self):
        seen = {}

        async def fake_run(args, st):
            seen["log"] = L.ACTIVE
            raise RuntimeError("the database is locked")
        with self.assertRaises(RuntimeError):
            self.main(fake_run)
        text = "\n".join(x["text"] for x in seen["log"].since()["lines"])
        self.assertIn("RuntimeError: the database is locked", text)

    @unittest.skipIf(os.name == "nt", "the test writes a Windows path into TOML unescaped: the config does not parse there")
    def test_no_password_or_key_in_the_log(self):
        """The plan's test: a log taken with a password (an unquoted number, whose value the config warning printed),
        the MCP password, the AI key and EDSM / Inara keys set contains none of them, in memory, in GET
        /api/serverlog or in the file."""
        edsm, inara = "0123456789abcdef0123456789abcdef01234567", "inarakey0123456789abcdefghij"
        secrets = ["918273645", "mcp-pass-4242", "sk-test-0123456789", edsm, inara]
        seen = {}

        async def fake_run(args, st):
            log = L.ACTIVE
            log.open(os.path.join(self.tmp.name, L.FILE_NAME))   # as run() does, beside the database
            db = ed_outrider.open_db(":memory:")
            state = ed_outrider.State(db, ed_outrider.Journals(db), None, 25)
            state.password, state.assistant, state.config_path = st["password"], st["assistant"], self.cfg
            state.server_log = log
            state.hide_secrets()
            self.assertEqual(state.set_edsm_account("Sample Pilot", key=edsm)[1], 200)
            self.assertEqual(state.set_inara_account("Sample Pilot", key=inara)[1], 200)
            print(f"a careless line: {' '.join(secrets)}", file=sys.stderr)
            seen["problems"] = state.config_info()["problems"]   # GET /api/config replays the config's warnings
            from aiohttp.test_utils import TestClient, TestServer
            async with TestClient(TestServer(ed_outrider.make_app(state))) as c:
                seen["api"] = await (await c.get("/api/serverlog?after=0")).text()
            db.close()
        printed = self.main(fake_run, '[server]\npassword = 918273645\n[assistant]\napi_key = "sk-test-0123456789"\n'
                                      '[mcp]\npassword = "mcp-pass-4242"\n')
        self.assertIn("a careless line", printed)   # the terminal is the player's own: as it was
        with open(os.path.join(self.tmp.name, L.FILE_NAME), encoding="utf-8") as f:
            file_text = f.read()
        self.assertIn("[server] password should be in quotes", file_text)
        self.assertIn("a careless line: ••• ••• ••• ••• •••", file_text)
        for s in secrets:
            for where, text in (("file", file_text), ("api", seen["api"]), ("problems", " ".join(seen["problems"]))):
                self.assertNotIn(s, text, where)

    def test_the_password_warning_never_says_the_value(self):
        """The config warning for an unquoted password printed its value (into the log and GET /api/config's problems
        now): it no longer does, even for a short one hide() would leave alone."""
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            st = ed_outrider.settings_from({"server": {"password": 1234}}, args, None, ([], []))
        self.assertEqual(st["password"], "1234")
        self.assertIn("should be in quotes", err.getvalue())
        self.assertNotIn("1234", err.getvalue())


class Notices(unittest.TestCase):
    def test_board(self):
        changes = []
        b = N.Board(on_change=lambda: changes.append(1))
        self.assertTrue(b.set("config", "ed_outrider.toml has  1 problem", action="open:server"))
        self.assertFalse(b.set("config", "ed_outrider.toml has 1 problem", action="open:server"))   # the same: no change
        n = b.active()[0]
        self.assertEqual((n["key"], n["text"], n["level"], n["action"]), ("config", "ed_outrider.toml has 1 problem", "warn", "open:server"))
        self.assertEqual(n["id"], N.notice_id("config", n["text"]))
        self.assertTrue(b.dismiss(n["id"]))
        self.assertFalse(b.dismiss(n["id"]))   # once
        self.assertFalse(b.dismiss("nope"))
        self.assertEqual(b.active(), [])
        b.set("config", "ed_outrider.toml has 2 problems")   # a changed message shows again
        self.assertEqual([x["text"] for x in b.active()], ["ed_outrider.toml has 2 problems"])
        b.dismiss(b.active()[0]["id"])
        self.assertTrue(b.clear("config"))   # fixed...
        b.set("config", "ed_outrider.toml has 2 problems")   # ...and back later: shown again
        self.assertEqual(len(b.active()), 1)
        self.assertFalse(b.clear("nothing"))
        self.assertEqual(len(changes), 6)
        for i in range(N.MAX + 3):
            b.set(f"k{i}", f"text {i}", level="bogus")
        self.assertEqual(len(b.active()), N.MAX)
        self.assertEqual((b.active()[0]["key"], b.active()[-1]["level"]), ("k3", "warn"))   # the oldest went

    def test_warn_prints_and_posts(self):
        b = N.Board()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            N.warn("network0", "warning: listening on your network with no [server] password", action="open:server", board=b)
        self.assertEqual(err.getvalue(), "warning: listening on your network with no [server] password\n")
        self.assertEqual(b.active()[0]["text"], "Listening on your network with no [server] password")

    def test_startup_notices(self):
        """run()'s first notices: the journal folders not found and the config file's problems."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = os.path.join(tmp.name, "my.toml")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write('[server]\nradius = "far"\nport = 70000\n')
        st = {"live": [tmp.name, os.path.join(tmp.name, "gone")], "legacy": []}
        with contextlib.redirect_stderr(io.StringIO()) as err:
            board = ed_outrider.startup_notices(st, cfg)
        self.assertIs(board, N.BOARD)
        self.assertIn("journal folder not found, skipping: " + os.path.join(tmp.name, "gone"), err.getvalue())
        got = {n["key"]: n for n in board.active()}
        self.assertEqual(got["journals_missing"]["action"], "open:server:journals")
        self.assertIn(os.path.join(tmp.name, "gone"), got["journals_missing"]["text"])
        self.assertTrue(got["config"]["text"].startswith("my.toml has 2 problems (defaults used): [server] "), got["config"])
        self.assertEqual(got["config"]["action"], "open:server")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write("")
        with contextlib.redirect_stderr(io.StringIO()):
            board = ed_outrider.startup_notices({"live": [tmp.name], "legacy": []}, cfg)
        self.assertEqual(board.active(), [])   # a fresh board each run

    def test_the_payload_and_dismissing(self):
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        state = ed_outrider.State(db, ed_outrider.Journals(db), None, 25)
        state.password = "hunter2"
        state.notices.set("nfs0", "The journal folder /mnt/j is on NFS <b>", action="open:log")
        nid = state.notices.active()[0]["id"]
        log = L.ServerLog(clock=Clock())
        log.feed("out", "ED Outrider\n")
        state.server_log = log

        async def go():
            from aiohttp.test_utils import TestClient, TestServer
            out = {}
            async with TestClient(TestServer(ed_outrider.make_app(state))) as c:
                out["payload"] = (await (await c.get("/api/nearby")).json())["notices"]
                v = state.version
                r = await c.post("/api/notices/dismiss", json={"id": nid})
                out["dismiss"] = (r.status, await r.json(), state.version > v)
                out["again"] = (await (await c.post("/api/notices/dismiss", json={"id": nid})).json())["ok"]
                out["bad"] = [(await c.post("/api/notices/dismiss", json=b)).status for b in ({}, {"id": 5}, {"id": "x" * 201})]
                out["after"] = (await (await c.get("/api/nearby")).json())["notices"]
                out["log"] = await (await c.get("/api/serverlog?after=0")).json()
                out["log_bad"] = (await c.get("/api/serverlog?after=x")).status
                with unittest.mock.patch.object(outrider.auth, "is_loopback", lambda remote: False):   # another device
                    out["lan"] = [(await c.get("/api/serverlog")).status,
                                  (await c.post("/api/notices/dismiss", json={"id": nid})).status]
            return out
        out = asyncio.run(go())
        self.assertEqual(out["payload"], [{"id": nid, "key": "nfs0", "text": "The journal folder /mnt/j is on NFS <b>",
                                           "level": "warn", "action": "open:log"}])
        self.assertEqual(out["dismiss"], (200, {"ok": True, "notices": []}, True))
        self.assertEqual((out["again"], out["bad"], out["after"]), (False, [400, 400, 400], []))
        self.assertEqual(([x["text"] for x in out["log"]["lines"]], out["log"]["last"], out["log_bad"]), (["ED Outrider"], 1, 400))
        self.assertEqual(out["lan"], [401, 401])   # behind the sign-in, as the rest
        state.server_log = None
        self.assertEqual(asyncio.run(self._get(state, "/api/serverlog"))["lines"], [])   # not teed: an empty log

    async def _get(self, state, path):
        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(ed_outrider.make_app(state))) as c:
            return await (await c.get(path)).json()


if __name__ == "__main__":
    unittest.main()

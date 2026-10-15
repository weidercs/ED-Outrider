"""Outrider's own log (S5b; not outrider/log.py, which is the journal's Log view): what the server prints to its
terminal, kept so Settings -> Server's Show log can show it on any device, and in a file beside the database.

`install(log)` puts a `Tee` on sys.stdout and sys.stderr at the start of the server path (main(); restored in its
finally, so a test calling main() leaves nothing installed): each write goes to the original stream first, then
whole lines into the `ServerLog`, which keeps the last KEEP lines in memory (seq, time, "out" | "err", text) and,
once `open(path)` is called (run(), after the database's folder exists), appends them to `<db dir>/outrider.log`
(UTF-8, rotated at MAX_BYTES to outrider.log.1; a rename that fails, a file another program holds open on Windows,
keeps appending). The overlay window's own output comes in through Outrider's (outrider/overlay_runner.py pipes it).
Other programs Outrider runs (the players, the clipboard) still write to the terminal only.

Secrets never reach the log: `hide(value)` (the [server] and [mcp] passwords, the AI key, the EDSM and Inara keys)
replaces a value of SECRET_MIN characters or more wherever it appears, in the lines already kept too. The code also
never prints them; this is the second line of defence.
"""
import collections
import os
import sys
import threading
import time

KEEP = 2000              # lines kept in memory for the page
MAX_BYTES = 2_000_000    # the file is rotated past this (one older copy, outrider.log.1)
LINE_MAX = 4000          # characters kept of one line
FILE_NAME = "outrider.log"
SECRET_MIN = 6           # shorter values are not hidden: "1234" would blank every count that holds it
HIDDEN = "•••"

_secrets = set()
_secrets_lock = threading.Lock()
ACTIVE = None            # the ServerLog installed on sys.stdout/stderr (None: not installed, as in most tests)


def hide(*values):
    """Never show these values in the log (now or in the lines already kept)."""
    added = False
    with _secrets_lock:
        for v in values:
            if isinstance(v, str) and len(v.strip()) >= SECRET_MIN and v not in _secrets:
                _secrets.add(v)
                added = True
    if added and ACTIVE is not None:
        ACTIVE.redact_kept()


def redact(text):
    with _secrets_lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for s in secrets:
        if s in text:
            text = text.replace(s, HIDDEN)
    return text


class ServerLog:
    """The lines Outrider printed: `feed(kind, text)` from the Tee, `since(seq)` for GET /api/serverlog."""

    def __init__(self, keep=KEEP, max_bytes=MAX_BYTES, clock=time.time):
        self.lines = collections.deque(maxlen=keep)
        self.seq, self.clock, self.max_bytes = 0, clock, max_bytes
        self.partial = {"out": "", "err": ""}
        self.lock = threading.RLock()
        self.path, self.file, self.size, self.rotate_at, self.file_error = None, None, 0, max_bytes, None

    def feed(self, kind, text):
        """Part of a stream's output: complete lines are kept, the rest waits for its newline."""
        with self.lock:
            *done, self.partial[kind] = (self.partial[kind] + text).split("\n")
            for line in done:
                self._add(kind, line)

    def _add(self, kind, line):
        line = redact(line.rstrip("\r")[:LINE_MAX])
        self.seq += 1
        row = (self.seq, self.clock(), kind, line)
        self.lines.append(row)
        self._write(row)

    def redact_kept(self):
        with self.lock:
            self.lines = collections.deque(((s, t, k, redact(x)) for s, t, k, x in self.lines), maxlen=self.lines.maxlen)

    @staticmethod
    def file_line(row):
        _, t, kind, text = row
        return f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))} {'!' if kind == 'err' else '|'} {text}\n"

    def open(self, path):
        """Start the file (appending): the lines printed before it existed (the start-up's first ones) go in first."""
        with self.lock:
            self.close()
            self.path = path
            try:
                self.file = open(path, "a", encoding="utf-8", errors="replace")
                self.size = self.file.tell()
            except OSError as e:
                self.file, self.file_error = None, str(e)
                return False
            self.rotate_at = self.max_bytes
            for row in self.lines:
                self._write(row)
            return True

    def _write(self, row):
        if self.file is None:
            return
        text = self.file_line(row)
        try:
            if self.size + len(text) > self.rotate_at:
                self._rotate()
            self.file.write(text)
            self.file.flush()
            self.size += len(text.encode("utf-8", "replace"))
        except (OSError, ValueError) as e:   # a full disk, a file closed under us: the page's lines still work
            self.file_error = str(e)
            self.close()

    def _rotate(self):
        self.file.close()
        try:
            os.replace(self.path, self.path + ".1")
            mode, self.rotate_at = "w", self.max_bytes
        except OSError:   # held open elsewhere (Windows): keep appending, try again another MAX_BYTES on
            mode, self.rotate_at = "a", self.size + self.max_bytes
        self.file = open(self.path, mode, encoding="utf-8", errors="replace")
        self.size = self.file.tell()

    def close(self):
        with self.lock:
            if self.file is not None:
                try:
                    self.file.close()
                except OSError:
                    pass
            self.file = None

    def since(self, after=0):
        """GET /api/serverlog?after=<seq>: the lines after that one (all that are kept for 0), the newest seq, and
        where the file is."""
        with self.lock:
            rows = [r for r in self.lines if r[0] > after] if after < self.seq else []
            return {"lines": [{"seq": s, "t": round(t, 3), "kind": k, "text": x} for s, t, k, x in rows],
                    "last": self.seq, "first": self.lines[0][0] if self.lines else self.seq + 1,
                    "path": self.path, "file_error": self.file_error}


class Tee:
    """A stream that writes to the original first, then into the log. Anything else is the original's (encoding,
    isatty, fileno, reconfigure...). The original may be None (pythonw on Windows has no console)."""

    def __init__(self, stream, log, kind):
        self.stream, self.log, self.kind = stream, log, kind

    def write(self, text):
        try:
            return self.stream.write(text) if self.stream is not None else len(text)
        finally:
            try:
                self.log.feed(self.kind, str(text))
            except Exception:  # noqa: BLE001 -- the log must never break a print
                pass

    def flush(self):
        if self.stream is not None:
            self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def install(log=None):
    """Tee sys.stdout and sys.stderr into `log` (a new ServerLog when None). Returns a function that puts them back
    (the streams in place when it was called) and closes the file."""
    global ACTIVE
    log = log or ServerLog()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Tee(old_out, log, "out"), Tee(old_err, log, "err")
    ACTIVE = log

    def restore():
        global ACTIVE
        if isinstance(sys.stdout, Tee) and sys.stdout.log is log:
            sys.stdout = old_out
        if isinstance(sys.stderr, Tee) and sys.stderr.log is log:
            sys.stderr = old_err
        if ACTIVE is log:
            ACTIVE = None
        log.close()
    return restore

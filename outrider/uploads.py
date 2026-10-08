"""Uploads (EDDN, EDSM; Inara later): the shared foundation. Opt-in, off by default (PLAN-edmc-functionality part A).

Pure where it can be; the server (ed_outrider.py) owns the database, the sender tasks and the settings.

- Session: what the journal says about the game session a line belongs to: the game version and build of each journal
  file (its Fileheader), the commander, Horizons / Odyssey (LoadGame only: a key LoadGame leaves out stays out), where
  you are (SystemAddress, StarSystem, StarPos together, from Location / FSDJump / CarrierJump only), whether you are
  crew in someone else's ship, the body you are at, the station you are docked at, your ship. EDDN's and EDSM's rules
  need all of it (research-edmc-2026-10-08/eddn.md, edsm-inara.md).
- UploadHub: every line of a live journal folder passes through `line()` before the reader's own filter. The startup
  scan feeds the session only ("catchup"); only the running tail ("live") may queue, and only lines no older than
  MAX_AGE_S by this machine's clock: a re-read, a rebuild, a restore or a legacy folder never uploads anything. The
  first line seen from a file primes the session from the top of that file, so a restart mid-file still knows the
  version, the commander and where you are.
- The outbox (`upload_queue`, live only): a message is queued in the same transaction as the line that made it, so a
  tick rolled back drops it too; UNIQUE(service, source) keeps a line handled twice (a retried tick, a twin folder)
  from being queued twice. Senders take rows after the commit.
"""
import copy
import json
import os
import re
import sqlite3
import time

from outrider.core import ts_seconds

MAX_AGE_S = 300          # a live line older than this (by this machine's clock) is not uploaded: NFS delay, clock skew
SKEW_S = 300             # ...and one stamped this far in the future still counts (the game PC's clock ahead)
SOURCE_RE = re.compile(r"^Journal(Beta|Alpha)?\.")

SCHEMA = """
-- Outgoing uploads (EDDN, EDSM), live only: queued in the tick that read the line (a rollback drops them), sent after
-- its commit by the sender tasks. state: queued, sent, dropped (refused for good), held (waiting on the player: a
-- refused key). Kept a week after sending (the UNIQUE check and the status view), then pruned. Not in
-- RESET_JOURNAL_DATA: a journal re-read uploads nothing and must not forget what was sent.
CREATE TABLE IF NOT EXISTS upload_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT NOT NULL, schema TEXT, source TEXT NOT NULL, created TEXT,
    cmdr TEXT, gameversion TEXT, gamebuild TEXT, message TEXT, state TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0, last_status TEXT, done_at REAL,
    UNIQUE (service, source));
CREATE INDEX IF NOT EXISTS upload_queue_state ON upload_queue (service, state, id);
"""


def _seconds(ts):
    """A journal timestamp as epoch seconds, or None for anything else."""
    try:
        return ts_seconds(str(ts))
    except (TypeError, ValueError):
        return None


def version_tuple(v):
    """'4.0.0.1904' -> (4, 0, 0, 1904); () when it has no leading number."""
    out = []
    for part in str(v or "").strip().split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        out.append(int(m.group(0)))
    return tuple(out)


class Session:
    """The game session a journal line belongs to (see the module doc). feed() every line of the live folders, in
    order; nothing here reads the clock or the database."""

    def __init__(self):
        self.versions = {}    # journal file name -> (gameversion, build) from its Fileheader (or LoadGame)
        self.file = None      # the file of the line being fed
        self.cmdr = self.fid = None
        self.horizons = self.odyssey = None   # None: LoadGame did not say (EDDN: leave the key out)
        self.addr = self.system = self.pos = None
        self.crew = False     # crew in another commander's ship: nothing of it is uploaded
        self.body = self.body_id = None       # the body you approached (journal), until LeaveBody / a jump
        self.status_body = None               # Status.json's BodyName (set by the hub from the live reading)
        self.market_id = self.station = None
        self.ship_id = None

    # ---- what the line's session is ----
    @property
    def gameversion(self):
        return (self.versions.get(self.file) or ("", ""))[0]

    @property
    def gamebuild(self):
        return (self.versions.get(self.file) or ("", ""))[1]

    @property
    def beta(self):
        m = SOURCE_RE.match(self.file or "")
        return bool(m and m.group(1)) or any(w in self.gameversion.lower() for w in ("alpha", "beta"))

    @property
    def legacy(self):
        """The Legacy galaxy (a 3.x client): nobody takes its data (EDSM 208, Inara; EDDN's live schemas skip it)."""
        v = version_tuple(self.gameversion)
        return bool(v) and v < (4,)

    def blocked(self):
        """Why nothing from this session may be uploaded now, or None: 'beta', 'legacy', 'crew', 'version' (no
        game version known yet), 'commander' (none yet)."""
        if self.beta:
            return "beta"
        if self.legacy:
            return "legacy"
        if self.crew:
            return "crew"
        if not self.gameversion:
            return "version"
        if not self.cmdr:
            return "commander"
        return None

    def located(self, addr):
        """Whether the tracked position is this SystemAddress (EDDN adds StarSystem/StarPos only then)."""
        return addr is not None and self.addr is not None and addr == self.addr and self.pos is not None

    # ---- following the journal ----
    def _clear_place(self):
        self.addr = self.system = self.pos = None
        self.body = self.body_id = None

    def feed(self, ev, file=None):
        if file:
            self.file = file
        name = ev.get("event")
        if name == "Fileheader":
            self.versions[self.file] = (str(ev.get("gameversion") or ""), str(ev.get("build") or ""))
            self.cmdr = self.fid = None
            self.horizons = self.odyssey = None
            self.crew = False
            self._clear_place()
        elif name == "Commander":
            self.cmdr, self.fid = ev.get("Name") or self.cmdr, ev.get("FID") or self.fid
        elif name == "LoadGame":
            self.cmdr, self.fid = ev.get("Commander") or self.cmdr, ev.get("FID") or self.fid
            self.horizons = bool(ev["Horizons"]) if "Horizons" in ev else None
            self.odyssey = bool(ev["Odyssey"]) if "Odyssey" in ev else None
            if self.file not in self.versions and ev.get("gameversion"):
                self.versions[self.file] = (str(ev.get("gameversion") or ""), str(ev.get("build") or ""))
            self.ship_id = ev.get("ShipID", self.ship_id)
            self.crew = False
            self._clear_place()
            self.market_id = self.station = None
        elif name in ("Location", "FSDJump", "CarrierJump"):
            pos = ev.get("StarPos")
            self.addr = ev.get("SystemAddress")
            self.system = ev.get("StarSystem")
            self.pos = list(pos) if isinstance(pos, (list, tuple)) and len(pos) == 3 else None
            if name == "FSDJump":
                self.body = self.body_id = None
                self.market_id = self.station = None
            else:   # a Location or a carrier's jump: docked or not, at a body or not, as it says
                docked = ev.get("Docked") and not ev.get("Taxi") and not ev.get("Multicrew")
                self.market_id, self.station = (ev.get("MarketID"), ev.get("StationName")) if docked else (None, None)
                if ev.get("BodyType") in ("Planet", "Star") or ev.get("Body"):
                    self.body, self.body_id = ev.get("Body"), ev.get("BodyID")
                elif name == "Location":
                    self.body = self.body_id = None
        elif name == "ApproachBody":
            self.body, self.body_id = ev.get("Body"), ev.get("BodyID")
        elif name == "LeaveBody":
            self.body = self.body_id = None
        elif name == "Docked":
            if not ev.get("Taxi") and not ev.get("Multicrew"):
                self.market_id, self.station = ev.get("MarketID"), ev.get("StationName")
        elif name == "Undocked":
            self.market_id = self.station = None
        elif name in ("Loadout", "ShipyardSwap", "SetUserShipName"):
            self.ship_id = ev.get("ShipID", self.ship_id)
        elif name == "ShipyardBuy":
            self.ship_id = None
        elif name == "JoinACrew":
            self.crew = bool(ev.get("Captain")) and ev.get("Captain") != self.cmdr
            self._clear_place()
        elif name == "QuitACrew":
            self.crew = False
            self._clear_place()

    def snapshot(self):
        return copy.deepcopy(self.__dict__)

    def restore(self, snap):
        self.__dict__.update(copy.deepcopy(snap))


def live_line(ts, now, max_age=MAX_AGE_S, skew=SKEW_S):
    """Whether a line stamped `ts` is recent enough to upload at `now` (both epoch-ish: ts a journal timestamp)."""
    t = _seconds(ts)
    return t is not None and -skew <= now - t <= max_age


# ---- the outbox ----

def enqueue(db, service, schema, source, ts, session, message):
    """Queue one message (in the caller's transaction). False when that line was queued for that service already."""
    cur = db.execute("INSERT OR IGNORE INTO upload_queue (service, schema, source, created, cmdr, gameversion, gamebuild,"
                     " message) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (service, schema, source, ts, session.cmdr, session.gameversion, session.gamebuild,
                      json.dumps(message, separators=(",", ":"))))
    return cur.rowcount > 0


def due(db, service, now, limit=50):
    """Rows of `service` to send now, oldest first."""
    return [dict(r) if isinstance(r, sqlite3.Row) else r for r in db.execute(
        "SELECT * FROM upload_queue WHERE service=? AND state='queued' AND next_try <= ? ORDER BY id LIMIT ?",
        (service, now, limit))]


def settle(db, row_id, state, status, now, retry_in=None):
    """A send's outcome: sent / dropped (done_at stamped), or queued again after retry_in seconds."""
    if state == "queued":
        db.execute("UPDATE upload_queue SET attempts = attempts + 1, next_try = ?, last_status = ? WHERE id = ?",
                   (now + (retry_in or 60), status, row_id))
    else:
        db.execute("UPDATE upload_queue SET state = ?, last_status = ?, done_at = ?, attempts = attempts + 1 WHERE id = ?",
                   (state, status, now, row_id))


def prune(db, now, keep_s=7 * 86400):
    """Forget sent and dropped rows older than keep_s."""
    db.execute("DELETE FROM upload_queue WHERE state IN ('sent', 'dropped') AND done_at < ?", (now - keep_s,))


def counts(db, service):
    """{queued, sent_24h, dropped_24h, last_sent, last_status} for the status view."""
    now = time.time()
    q = lambda sql, *a: db.execute(sql, (service,) + a).fetchone()[0]
    last = db.execute("SELECT done_at, last_status FROM upload_queue WHERE service=? AND state='sent' "
                      "ORDER BY done_at DESC LIMIT 1", (service,)).fetchone()
    return {"queued": q("SELECT count(*) FROM upload_queue WHERE service=? AND state='queued'"),
            "sent_24h": q("SELECT count(*) FROM upload_queue WHERE service=? AND state='sent' AND done_at > ?", now - 86400),
            "dropped_24h": q("SELECT count(*) FROM upload_queue WHERE service=? AND state='dropped' AND done_at > ?",
                             now - 86400),
            "last_sent": last[0] if last else None}


class UploadHub:
    """Every live-folder line goes through line(). builders: {service: fn(ev, session) -> [(schema, message)]}: what a
    line uploads to that service (the EDDN and EDSM parts add theirs). enabled(service) -> bool says which are on now
    (the settings, the leases, simulate). Lines are queued only in "live" mode, recent, and from a session nothing
    blocks."""

    def __init__(self, db, builders=None, enabled=None, clock=time.time, max_age=MAX_AGE_S):
        self.db = db
        self.builders = dict(builders or {})
        self.enabled = enabled or (lambda service: False)
        self.clock, self.max_age = clock, max_age
        self.session = Session()
        self.primed = set()          # files whose top this session has read
        self.queued = 0              # messages queued since start (the status view)

    def active(self):
        return any(self.enabled(s) for s in self.builders)

    def prime(self, path, upto):
        """Feed the session the lines of `path` before byte `upto` (state only): a file met part way through."""
        self.primed.add(os.path.basename(path))
        try:
            with open(path, "rb") as f:
                data = f.read(upto)
        except OSError:
            return
        for raw in data.split(b"\n"):
            if raw.strip():
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    self.session.feed(ev, os.path.basename(path))

    def line(self, path, offset, raw, mode):
        """One journal line (bytes) at `offset` of `path`. mode: "catchup" (state only) or "live" (may queue).
        Returns the number of messages queued. Database errors propagate (the tick is rolled back)."""
        b = os.path.basename(path)
        if b not in self.primed:
            self.prime(path, offset)
        try:
            ev = json.loads(raw)
        except ValueError:
            return 0
        if not isinstance(ev, dict):
            return 0
        self.session.feed(ev, b)
        if mode != "live" or not live_line(ev.get("timestamp"), self.clock(), self.max_age) or self.session.blocked():
            return 0
        n = 0
        for service, build in self.builders.items():
            if not self.enabled(service):
                continue
            try:
                messages = build(ev, self.session) or []
            except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:   # an odd line: skip it
                print(f"{service}: a line could not be prepared ({type(e).__name__}: {e})")
                continue
            for i, (schema, message) in enumerate(messages):
                if enqueue(self.db, service, schema, f"{b}:{offset}" + (f"#{i}" if i else ""), ev.get("timestamp"),
                           self.session, message):
                    n += 1
        self.queued += n
        return n

    def snapshot(self):
        return (self.session.snapshot(), set(self.primed), self.queued)

    def restore(self, snap):
        s, primed, self.queued = snap
        self.session.restore(s)
        self.primed = set(primed)


# ---- settings ----

SERVICES = ("eddn", "edsm")
DEFAULTS = {"eddn": {"enabled": False, "test": False}, "edsm": {"enabled": False}}


def upload_settings(cfg):
    """[eddn] enabled / test and [edsm] enabled from the config (bools; anything else is the default, off). EDSM's
    commander names and API keys are not here: they live in the database (State.edsm_accounts), set from the page."""
    out = {}
    for service, keys in DEFAULTS.items():
        sec = cfg.get(service) if isinstance(cfg.get(service), dict) else {}
        out[service] = {k: sec[k] if isinstance(sec.get(k), bool) else v for k, v in keys.items()}
    return {"uploads": out}


# ---- sending ----

GAP_S = 0.5              # between two sends of one service while the queue drains (EDDN: about 2 a second)
IDLE_S = 2.0             # how often an empty or switched-off queue is looked at
BACKOFF_S = (60, 120, 300, 600, 1800)   # after a network failure or a 5xx: at least a minute (EDDN's rule), growing


async def upload_loop(service, db, send, on, clock=time.time, sleep=None, report=None, batch=50):
    """Drain `service`'s outbox while it is on: send(rows) -> [(row id, state, status text, retry_in or None)] for
    each row it settled (state: sent, dropped, queued (retry after retry_in), held (stop until the player acts)); a raised
    exception is a network failure: those rows wait BACKOFF_S. report(service, outcome dict) after each round (the
    status view). Runs until cancelled."""
    import asyncio
    sleep = sleep or asyncio.sleep
    fails = 0
    while True:
        if not on(service):
            await sleep(IDLE_S)
            continue
        rows = due(db, service, clock(), batch)
        if not rows:
            await sleep(IDLE_S)
            continue
        now = clock()
        try:
            results = await send(rows)
            fails = 0
            error = None
        except Exception as e:   # unreachable, a timeout, a 5xx raised by the sender: wait, then again
            wait = BACKOFF_S[min(fails, len(BACKOFF_S) - 1)]
            fails += 1
            results = [(r["id"], "queued", f"{type(e).__name__}: {e}"[:300], wait) for r in rows]
            error = f"{type(e).__name__}: {e}"
        for row_id, state, status, retry_in in results:
            if state == "held":
                db.execute("UPDATE upload_queue SET last_status = ? WHERE id = ?", (status, row_id))
            else:
                settle(db, row_id, state, status, now, retry_in)
        db.commit()
        if report:
            report(service, {"error": error, "results": results, "at": now})
        if any(state == "held" for _, state, _, _ in results):
            await sleep(IDLE_S * 15)   # waiting on the player (a refused key): look again now and then
        else:
            await sleep(GAP_S)


# ---- one uploader at a time: lease files in the journal folder (the author's idea, 2026-10-08) ----

LEASE_DIR = ".outrider"   # a subfolder of the journal folder: Elite and other tools read only its top level
LEASE_STALE_S = 300       # another instance's lease counts while its content changed this recently (by OUR clock)


def lease_path(journal_dir, instance):
    return os.path.join(journal_dir, LEASE_DIR, f"uploads-{instance}.json")


def write_lease(journal_dir, instance, info):
    """Write (atomically) this instance's lease, or remove it when info is None. False when the folder cannot be
    written (a read-only mount: other instances then cannot see this one)."""
    path = lease_path(journal_dir, instance)
    try:
        if info is None:
            if os.path.exists(path):
                os.remove(path)
            return True
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(info, f)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


class Leases:
    """The other instances' leases, judged by when their content last changed as seen by this instance's own clock
    (the two machines' clocks are never compared). A crashed instance's file goes stale after LEASE_STALE_S."""

    def __init__(self, instance, clock=time.time):
        self.instance, self.clock = instance, clock
        self.seen = {}   # path -> (content, when we saw it change)

    def others(self, journal_dirs):
        """{instance id: {host, services}} of the live leases in these folders (not ours)."""
        now, out = self.clock(), {}
        for d in journal_dirs:
            folder = os.path.join(d, LEASE_DIR)
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for n in names:
                m = re.fullmatch(r"uploads-([A-Za-z0-9_-]+)\.json", n)
                if not m or m.group(1) == self.instance:
                    continue
                path = os.path.join(folder, n)
                try:
                    with open(path, encoding="utf-8") as f:
                        content = f.read()
                    info = json.loads(content)
                except (OSError, ValueError):
                    continue
                prev = self.seen.get(path)
                if not prev or prev[0] != content:
                    self.seen[path] = prev = (content, now)
                if now - prev[1] <= LEASE_STALE_S and isinstance(info, dict):
                    out[m.group(1)] = {"host": str(info.get("host") or "another Outrider"),
                                       "services": [s for s in info.get("services") or [] if s in SERVICES]}
        return out


def edmc_uploads(home=None, environ=None, platform=None, running=None):
    """Whether EDMarketConnector on THIS computer is running with its own EDDN / EDSM / Inara uploads on:
    {running, eddn, edsm, inara} or None when it is not installed here. Its config is config.toml (EDMC 6) in
    ~/.local/share/EDMarketConnector (Linux) or %LOCALAPPDATA%\\EDMarketConnector (Windows): settings.output has
    the EDDN bits (1 station data, 2048 the rest), edsm_out and inara_out are 0/1."""
    import sys
    try:
        import tomllib
    except ImportError:  # Python < 3.11
        return None
    environ = os.environ if environ is None else environ
    platform = platform or sys.platform
    home = home or os.path.expanduser("~")
    if platform == "win32":
        base = environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    else:
        base = environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    path = os.path.join(base, "EDMarketConnector", "config.toml")
    try:
        with open(path, "rb") as f:
            st = tomllib.load(f).get("settings") or {}
    except (OSError, ValueError):
        return None
    out = int(st.get("output") or 0) if str(st.get("output") or "0").lstrip("-").isdigit() else 0
    is_running = running() if running else edmc_running(platform)
    return {"running": bool(is_running), "eddn": bool(out & (1 | 2048)), "edsm": bool(st.get("edsm_out")),
            "inara": bool(st.get("inara_out"))}


def edmc_running(platform):
    """Whether an EDMarketConnector process runs on this computer (Linux: /proc; Windows: tasklist)."""
    if platform == "win32":
        import subprocess
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EDMarketConnector.exe", "/NH"], capture_output=True,
                                 text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return "EDMarketConnector" in out
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return False
    for p in pids:
        try:
            with open(f"/proc/{p}/cmdline", "rb") as f:
                if b"EDMarketConnector" in f.read():
                    return True
        except OSError:
            continue
    return False

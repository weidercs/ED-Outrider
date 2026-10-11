"""Inara ([inara], off by default): your travel, credits, ranks, reputation, ships, materials, missions and combat
log to your own Inara account, with the API key you give. Upstream's uploads (outrider/uploads.py: EDDN and EDSM)
do not cover Inara yet; this module is the fork's, and stands apart from them.

Only live play is sent: it tails the journals on its own (nothing here touches Outrider's database or its journal
reader), reads what is already there at start for the state alone, and sends an event only when its timestamp is
at most LIVE_S old. Nothing from the Legacy galaxy, a beta, or a session aboard another commander's ship. Nothing
is sent while it is off, with --simulate, or while EDMarketConnector on this PC is sending to Inara itself (the
same events would arrive twice).

Pure parts: `inara_settings`, `Tracker`, `inara_events`. `InaraSync` holds the tail, the queue and the sender.
Not covered: a ship's module list, suits, community goals. Not yet tried against the real service.
"""
import asyncio
import collections
import json
import os
import re
import sys
import time
from glob import glob, escape as glob_escape

import outrider
from outrider.core import ts_seconds

SOFTWARE = "ED Outrider"
INARA_URL = "https://inara.cz/inapi/v1/"

LIVE_S = 300            # s: an event older than this is history (a journal being caught up on), never sent
POLL_S = 1.0            # s between looks at the journal
RETRY_S = 60            # s before a failed request is tried again
QUEUE_MAX = 500         # events kept while Inara cannot be reached
INARA_GAP_S = 30        # s between two requests (Inara asks for few, batched)
HTTP_TIMEOUT = 20

DEFAULTS = {"enabled": False, "api_key": ""}


def inara_settings(cfg):
    """[inara] from a parsed config, as DEFAULTS' keys. A wrong value is reported on stderr and the default kept;
    switched on without its key it stays off, with the reason."""
    u = cfg.get("inara") if isinstance(cfg.get("inara"), dict) else {}
    enabled, key = u.get("enabled", False), u.get("api_key", "")
    if not isinstance(enabled, bool):
        print(f"config: [inara] enabled = {enabled!r} must be true or false; using false", file=sys.stderr)
        enabled = False
    if not isinstance(key, str) or len(key) > 200 or any(ord(c) < 32 for c in key):
        print("config: [inara] api_key must be text in quotes; ignored", file=sys.stderr)
        key = ""
    key = key.strip()
    if enabled and not key:
        print("config: [inara] enabled = true needs api_key (inara.cz: Settings, API key); Inara stays off",
              file=sys.stderr)
        enabled = False
    return {"enabled": enabled, "api_key": key}


# ---------------------------------------------------------------------------
# The game session, from the journal lines in order
# ---------------------------------------------------------------------------

def _pos(v):
    return list(v) if isinstance(v, list) and len(v) == 3 and all(
        isinstance(x, (int, float)) and not isinstance(x, bool) for x in v) else None


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


class Tracker:
    """What the uploads need to know of the session: the game's version, the commander, where they are (the last
    Location, FSDJump or CarrierJump: the only source of a system's name and position for an event that lacks them),
    the station, the body, the ship. `apply` takes every journal line in the order written."""

    def __init__(self):
        self.gameversion = self.gamebuild = ""
        self.reset()

    def reset(self):
        self.cmdr = self.fid = None
        self.horizons = self.odyssey = None   # LoadGame's, never Fileheader's (it means something else there)
        self.system = None    # {"name", "address", "pos"}
        self.station = None   # {"name", "market", "type"} while docked
        self.body = None      # (name, id): ApproachBody / Location, until LeaveBody or a jump
        self.ship = None      # {"id", "type"}
        self.crew = False     # aboard another commander's ship: their data, not yours
        self.credits = self.loan = None

    @property
    def beta(self):
        v = self.gameversion.lower()
        return "alpha" in v or "beta" in v

    @property
    def live_galaxy(self):
        """The 4.0 galaxy (Horizons 4 and Odyssey): EDSM and Inara take only this one. Unknown counts as not."""
        m = re.match(r"\s*(\d+)\.", self.gameversion)
        return bool(m) and int(m.group(1)) >= 4

    def apply(self, ev):
        name = ev.get("event")
        if name == "Fileheader":
            if ev.get("part", 1) == 1:   # a new game session (part 2 and on continue the same one)
                self.reset()
            self.gameversion = ev.get("gameversion") if isinstance(ev.get("gameversion"), str) else ""
            self.gamebuild = ev.get("build") if isinstance(ev.get("build"), str) else ""
        elif name in ("LoadGame", "Commander"):
            cmdr = ev.get("Commander" if name == "LoadGame" else "Name")
            if isinstance(cmdr, str) and cmdr:
                self.cmdr = cmdr
            if isinstance(ev.get("FID"), str):
                self.fid = ev["FID"]
            if name == "LoadGame":
                self.horizons = ev["Horizons"] if isinstance(ev.get("Horizons"), bool) else None
                self.odyssey = ev["Odyssey"] if isinstance(ev.get("Odyssey"), bool) else None
                if not self.gameversion and isinstance(ev.get("gameversion"), str):
                    self.gameversion = ev["gameversion"]
                    self.gamebuild = ev.get("build") if isinstance(ev.get("build"), str) else ""
                self.crew = False
                self.credits, self.loan = _int(ev.get("Credits")), _int(ev.get("Loan"))
                if _int(ev.get("ShipID")) is not None and isinstance(ev.get("Ship"), str):
                    self.ship = {"id": ev["ShipID"], "type": ev["Ship"]}
        elif name in ("Location", "FSDJump", "CarrierJump"):
            pos, addr = _pos(ev.get("StarPos")), _int(ev.get("SystemAddress"))
            ok = isinstance(ev.get("StarSystem"), str) and pos and addr is not None
            self.system = {"name": ev["StarSystem"], "address": addr, "pos": pos} if ok else None
            self.station = self._station(ev) if name != "FSDJump" and ev.get("Docked") else None
            planet = name == "Location" and ev.get("BodyType") == "Planet" and isinstance(ev.get("Body"), str)
            self.body = (ev["Body"], _int(ev.get("BodyID"))) if planet else None
        elif name == "Docked":
            self.station = self._station(ev)
        elif name == "Undocked":
            self.station = None
        elif name == "ApproachBody":
            self.body = (ev["Body"], _int(ev.get("BodyID"))) if isinstance(ev.get("Body"), str) else None
        elif name == "LeaveBody":
            self.body = None
        elif name == "Loadout":
            if _int(ev.get("ShipID")) is not None and isinstance(ev.get("Ship"), str):
                self.ship = {"id": ev["ShipID"], "type": ev["Ship"]}
        elif name in ("ShipyardSwap", "ShipyardNew"):
            sid = _int(ev.get("ShipID" if name == "ShipyardSwap" else "NewShipID"))
            if sid is not None and isinstance(ev.get("ShipType"), str):
                self.ship = {"id": sid, "type": ev["ShipType"]}
        elif name == "JoinACrew":
            self.crew = True
        elif name == "QuitACrew":
            self.crew = False

    @staticmethod
    def _station(ev):
        if not isinstance(ev.get("StationName"), str):
            return None
        return {"name": ev["StationName"], "market": _int(ev.get("MarketID")), "type": ev.get("StationType")}


# the lines `Tracker.apply` reads (the prefilter for the journals read at start)
TRACKED = tuple(f'"event":"{e}"'.encode() for e in (
    "Fileheader", "LoadGame", "Commander", "Location", "FSDJump", "CarrierJump", "Docked", "Undocked", "ApproachBody",
    "LeaveBody", "Loadout", "ShipyardSwap", "ShipyardNew", "JoinACrew", "QuitACrew"))


# ---------------------------------------------------------------------------
# The events
# ---------------------------------------------------------------------------

INARA_RANKS = ("Combat", "Trade", "Explore", "Soldier", "Exobiologist", "Empire", "Federation", "CQC")
INARA_MISSION = (("DestinationSystem", "starsystemNameTarget"), ("DestinationStation", "stationNameTarget"),
                 ("TargetFaction", "minorfactionNameTarget"), ("Commodity", "commodityName"), ("Count", "commodityCount"),
                 ("Target", "targetName"), ("TargetType", "targetType"), ("KillCount", "killCount"),
                 ("PassengerType", "passengerType"), ("PassengerCount", "passengerCount"),
                 ("PassengerVIPs", "passengerIsVIP"), ("PassengerWanted", "passengerIsWanted"))
# a later one of these replaces an earlier one still waiting: only the newest state matters
INARA_LATEST = frozenset(("setCommanderCredits", "setCommanderRankPilot", "setCommanderReputationMajorFaction",
                          "setCommanderInventoryMaterials", "setCommanderGameStatistics", "setCommanderTravelLocation"))


def _ship_fields(ev, tr):
    """shipType / shipGameID for a travel event, or the taxi flags (a taxi is nobody's ship); None when unknown."""
    if ev.get("Taxi"):
        return {"isTaxiShuttle": True}
    return {"shipType": tr.ship["type"], "shipGameID": tr.ship["id"]} if tr.ship else None


def inara_events(ev, tr, memo):
    """The Inara events one journal event makes: [(eventName, eventData)]. `tr` has seen the event already; `memo`
    is this translator's own dict across calls (the ranks waiting for their progress, an undock still at the pad).
    Covers travel, credits, ranks, reputation, engineers, Powerplay, statistics, the ships you fly and buy or sell,
    materials, missions and combat; not a ship's module list, suits or community goals."""
    name, s = ev.get("event"), tr.system
    out = []
    add = lambda event, data: out.append((event, data))
    where = {"starsystemName": s["name"], "starsystemCoords": s["pos"]} if s else None
    if name == "LoadGame":
        if _int(ev.get("Credits")) is not None:
            add("setCommanderCredits", {"commanderCredits": ev["Credits"], "commanderLoan": _int(ev.get("Loan")) or 0})
    elif name == "Rank":
        memo["ranks"] = {k: ev[k] for k in INARA_RANKS if _int(ev.get(k)) is not None}
    elif name == "Progress":
        ranks = memo.pop("ranks", None) or {}
        rows = [{"rankName": k.lower(), "rankValue": v,
                 **({"rankProgress": ev[k] / 100.0} if _int(ev.get(k)) is not None else {})} for k, v in ranks.items()]
        if rows:
            add("setCommanderRankPilot", rows)
    elif name == "Promotion":
        rows = [{"rankName": k.lower(), "rankValue": ev[k], "rankProgress": 0} for k in INARA_RANKS
                if _int(ev.get(k)) is not None]
        if rows:
            add("setCommanderRankPilot", rows)
    elif name == "Reputation":
        rows = [{"majorfactionName": k.lower(), "majorfactionReputation": ev[k] / 100.0}
                for k in ("Empire", "Federation", "Alliance", "Independent")
                if isinstance(ev.get(k), (int, float)) and not isinstance(ev.get(k), bool)]
        if rows:
            add("setCommanderReputationMajorFaction", rows)
    elif name == "EngineerProgress":
        rows = ev["Engineers"] if isinstance(ev.get("Engineers"), list) else [ev]
        rows = [{"engineerName": e["Engineer"], **({"rankStage": e["Progress"]} if isinstance(e.get("Progress"), str) else {}),
                 **({"rankValue": e["Rank"]} if _int(e.get("Rank")) is not None else {})}
                for e in rows if isinstance(e, dict) and isinstance(e.get("Engineer"), str)]
        if rows:
            add("setCommanderRankEngineer", rows)
    elif name == "Powerplay":
        if isinstance(ev.get("Power"), str) and _int(ev.get("Rank")) is not None:
            add("setCommanderRankPower", {"powerName": ev["Power"], "rankValue": ev["Rank"],
                                          "meritsValue": _int(ev.get("Merits")) or 0})
    elif name == "Statistics":
        add("setCommanderGameStatistics", {k: v for k, v in ev.items() if k not in ("timestamp", "event")})
    elif name == "Materials":
        rows = [{"itemName": m["Name"], "itemCount": m["Count"]} for kind in ("Raw", "Manufactured", "Encoded")
                for m in (ev.get(kind) or []) if isinstance(m, dict) and isinstance(m.get("Name"), str)
                and _int(m.get("Count")) is not None]
        add("setCommanderInventoryMaterials", rows)
    elif name in ("MaterialCollected", "MaterialDiscarded"):
        if isinstance(ev.get("Name"), str) and _int(ev.get("Count")) is not None:
            add("addCommanderInventoryMaterialsItem" if name == "MaterialCollected" else "delCommanderInventoryMaterialsItem",
                {"itemName": ev["Name"], "itemCount": ev["Count"]})
    elif name == "FSDJump":
        memo["undocked"] = False
        ship = _ship_fields(ev, tr)
        if where and ship and isinstance(ev.get("JumpDist"), (int, float)):
            add("addCommanderTravelFSDJump", dict(where, jumpDistance=ev["JumpDist"], **ship))
        rows = [{"minorfactionName": f["Name"], "minorfactionReputation": f["MyReputation"] / 100.0}
                for f in (ev.get("Factions") or []) if isinstance(f, dict) and isinstance(f.get("Name"), str)
                and isinstance(f.get("MyReputation"), (int, float)) and not isinstance(f.get("MyReputation"), bool)]
        if rows:
            add("setCommanderReputationMinorFaction", rows)
    elif name == "Undocked":
        memo["undocked"] = True   # until it leaves: docking again without leaving is no new visit
    elif name == "SupercruiseEntry":
        memo["undocked"] = False
    elif name in ("Docked", "CarrierJump"):
        ship, st = _ship_fields(ev, tr), tr.station
        again = name == "Docked" and memo.pop("undocked", False)
        if where and ship and st and not again:
            data = dict(where, stationName=st["name"], **ship)
            if st["market"] is not None:
                data["marketID"] = st["market"]
            add("addCommanderTravelDock" if name == "Docked" else "addCommanderTravelCarrierJump", data)
    elif name == "Location":
        memo["undocked"] = False
        if where:
            data = dict(where)
            if tr.station:
                data["stationName"] = tr.station["name"]
                if tr.station["market"] is not None:
                    data["marketID"] = tr.station["market"]
            add("setCommanderTravelLocation", data)
    elif name == "Loadout":
        if tr.ship and _int(ev.get("ShipID")) is not None and isinstance(ev.get("Ship"), str):
            data = {"shipType": ev["Ship"], "shipGameID": ev["ShipID"], "isCurrentShip": True}
            for src, key in (("ShipName", "shipName"), ("ShipIdent", "shipIdent"), ("HullValue", "shipHullValue"),
                             ("ModulesValue", "shipModulesValue"), ("Rebuy", "shipRebuyCost"),
                             ("MaxJumpRange", "shipMaxJumpRange"), ("CargoCapacity", "shipCargoCapacity")):
                if ev.get(src) not in (None, "") and not isinstance(ev.get(src), bool):
                    data[key] = ev[src]
            add("setCommanderShip", data)
    elif name == "ShipyardNew":
        if isinstance(ev.get("ShipType"), str) and _int(ev.get("NewShipID")) is not None:
            add("addCommanderShip", {"shipType": ev["ShipType"], "shipGameID": ev["NewShipID"]})
    elif name == "ShipyardSell":
        if isinstance(ev.get("ShipType"), str) and _int(ev.get("SellShipID")) is not None:
            add("delCommanderShip", {"shipType": ev["ShipType"], "shipGameID": ev["SellShipID"]})
    elif name == "ShipyardSwap":
        if isinstance(ev.get("ShipType"), str) and _int(ev.get("ShipID")) is not None:
            add("setCommanderShip", {"shipType": ev["ShipType"], "shipGameID": ev["ShipID"], "isCurrentShip": True})
    elif name == "MissionAccepted":
        if isinstance(ev.get("Name"), str) and _int(ev.get("MissionID")) is not None:
            data = {"missionName": ev["Name"], "missionGameID": ev["MissionID"]}
            for src, key in (("Expiry", "missionExpiry"), ("Influence", "influenceGain"), ("Reputation", "reputationGain"),
                             ("Faction", "minorfactionNameOrigin")) + INARA_MISSION:
                if ev.get(src) not in (None, ""):
                    data[key] = ev[src]
            if s:
                data["starsystemNameOrigin"] = s["name"]
            if tr.station:
                data["stationNameOrigin"] = tr.station["name"]
            add("addCommanderMission", data)
    elif name in ("MissionAbandoned", "MissionFailed", "MissionCompleted"):
        if _int(ev.get("MissionID")) is not None:
            data = {"missionGameID": ev["MissionID"]}
            if name == "MissionCompleted":
                for src, key in (("Donated", "donationCredits"), ("Reward", "rewardCredits")):
                    if _int(ev.get(src)) is not None:
                        data[key] = ev[src]
            add("setCommanderMission" + name[len("Mission"):], data)
    elif name == "Died" and s:
        data = {"starsystemName": s["name"]}
        if isinstance(ev.get("KillerName"), str):
            data["opponentName"] = ev["KillerName"]
        elif isinstance(ev.get("Killers"), list):
            data["wingOpponentNames"] = [k["Name"] for k in ev["Killers"] if isinstance(k, dict) and isinstance(k.get("Name"), str)]
        add("addCommanderCombatDeath", data)
    elif name in ("Interdicted", "Interdiction", "EscapeInterdiction") and s:
        who = ev.get("Interdicted" if name == "Interdiction" else "Interdictor")
        if isinstance(who, str) and who:
            data = {"starsystemName": s["name"], "opponentName": who}
            if isinstance(ev.get("IsPlayer"), bool):
                data["isPlayer"] = ev["IsPlayer"]
            if name == "Interdicted" and isinstance(ev.get("Submitted"), bool):
                data["isSubmit"] = ev["Submitted"]
            if name == "Interdiction" and isinstance(ev.get("Success"), bool):
                data["isSuccess"] = ev["Success"]
            add({"Interdicted": "addCommanderCombatInterdicted", "Interdiction": "addCommanderCombatInterdiction",
                 "EscapeInterdiction": "addCommanderCombatInterdictionEscape"}[name], data)
    elif name == "PVPKill" and s and isinstance(ev.get("Victim"), str):
        add("addCommanderCombatKill", {"starsystemName": s["name"], "opponentName": ev["Victim"]})
    return out


# ---------------------------------------------------------------------------
# The tail of the journals
# ---------------------------------------------------------------------------

class Tail:
    """The journals, read on their own: `start()` gives the lines already there (for the state: the last few files,
    oldest first), `read()` the complete lines written since, in any journal (the game starts a new one each
    session, and a long session continues in a part 2). Lines come with their folder (Market.json and the others
    are beside the journal)."""

    def __init__(self, dirs, history=3):
        self.dirs, self.history = list(dirs), history
        self.offsets = {}     # a journal's name -> how far it is read; a name not in it is new, read from its start

    def files(self):
        """Every journal once (a file reachable by two folders counts for the first), oldest first: (path, size)."""
        found = {}
        for d in self.dirs:
            for p in glob(os.path.join(glob_escape(d), "Journal.*.log")):
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                found.setdefault(os.path.basename(p), (st.st_mtime, p, st.st_size))
        return [(p, size) for _, p, size in sorted(found.values())]

    def _lines(self, path):
        """The complete lines of `path` not read yet."""
        name = os.path.basename(path)
        offset = self.offsets.get(name, 0)
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                data = f.read()
        except OSError:
            return []
        end = data.rfind(b"\n") + 1
        self.offsets[name] = offset + end
        return [(ln, os.path.dirname(path)) for ln in data[:end].split(b"\n") if ln.strip()]

    def start(self):
        files = self.files()
        for p, size in files[:-self.history]:
            self.offsets[os.path.basename(p)] = size
        return [x for p, _ in files[-self.history:] for x in self._lines(p) if any(w in x[0] for w in TRACKED)]

    def read(self):
        return [x for p, size in self.files() if size > self.offsets.get(os.path.basename(p), 0) for x in self._lines(p)]


def _why(e):
    return "timed out" if isinstance(e, asyncio.TimeoutError) else (str(e) or type(e).__name__)


class InaraSync:
    """The Inara upload as a whole: `run()` is the task (tail, translate, send); `info()` is what the page shows."""

    def __init__(self, settings, dirs, off=None, log=print):
        cfg = dict(DEFAULTS, **(settings or {}))
        self.cfg, self.dirs, self.log = cfg, list(dirs), log
        self.off = off         # why nothing is sent whatever the config says (--simulate, EDMC sending), or None
        self.on = bool(cfg["enabled"]) and not off
        self.tracker = Tracker()
        self.tail = Tail(self.dirs)
        self.memo = {}         # inara_events' own
        self.started = False
        self.queue = collections.deque()
        self.sent = self.dropped = 0
        self.last = None       # wall clock of the last request Inara took
        self.error = None      # the latest problem in words, cleared by the next success
        self.stopped = None    # why sending stopped for good (a refused key), until a restart
        self.wait_until = 0.0  # monotonic: nothing is sent before

    @property
    def active(self):
        return self.on

    def info(self):
        return {"on": self.on, "sent": self.sent, "dropped": self.dropped, "waiting": len(self.queue),
                "last": self.last, "error": self.stopped or self.error, "off": self.off}

    def status_line(self):
        """One line for the start-up log."""
        if self.off:
            return f"off ({self.off})"
        return "on (live play only)" if self.on else "off ([inara] enabled)"

    # -- reading ------------------------------------------------------------

    def start(self):
        """The journals already there, for the state only: nothing in them is sent."""
        for line, _ in self.tail.start():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                self.tracker.apply(ev)
        self.started = True

    def poll(self, now=None):
        """Read what the journals gained and queue what it makes. now: the wall clock (an event's age)."""
        now = time.time() if now is None else now
        if not self.started:
            self.start()
        for line, _ in self.tail.read():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            try:
                self.feed(ev, now)
            except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
                self.log(f"inara: journal line skipped ({type(e).__name__}: {e}): {line[:160]!r}", file=sys.stderr)

    def feed(self, ev, now):
        """One journal line written since the start: the state first, then what Inara gets of it."""
        ts = ev.get("timestamp")
        try:   # an old line (a journal copied into the folder, one caught up on late) is history: it is not sent, and
            if now - ts_seconds(ts) > LIVE_S:   # it says nothing of where the commander is now
                return
        except (TypeError, ValueError):
            return
        tr = self.tracker
        tr.apply(ev)
        if not self.on or self.stopped or not tr.cmdr or tr.crew or tr.beta or not tr.live_galaxy:
            return
        for event, data in inara_events(ev, tr, self.memo):
            if event in INARA_LATEST:
                for old in [x for x in self.queue if x["eventName"] == event]:
                    self.queue.remove(old)
            if len(self.queue) >= QUEUE_MAX:
                self.queue.popleft()
                self.dropped += 1
            self.queue.append({"eventName": event, "eventTimestamp": ts, "eventData": data})

    # -- sending ------------------------------------------------------------

    async def run(self, session_factory=None):
        """The task: every POLL_S read the journals and send what is due. Ends when cancelled."""
        if not self.on:
            return
        if session_factory is None:
            from aiohttp import ClientSession, ClientTimeout
            session_factory = lambda: ClientSession(timeout=ClientTimeout(total=HTTP_TIMEOUT),
                                                    headers={"User-Agent": f"ED-Outrider/{outrider.__version__}"})
        async with session_factory() as session:
            while True:
                try:
                    self.poll()
                    await self.send(session)
                except asyncio.CancelledError:
                    raise
                except Exception as e:   # never the end of the upload: say it once a minute at most
                    self.log(f"inara: {type(e).__name__}: {e}", file=sys.stderr)
                    await asyncio.sleep(RETRY_S)
                await asyncio.sleep(POLL_S)

    async def send(self, session, mono=None):
        """One batch, at most every INARA_GAP_S. A refused key or application stops the sending until a restart; an
        unreachable Inara is tried again after RETRY_S with the events kept."""
        mono = time.monotonic() if mono is None else mono
        tr = self.tracker
        if not self.on or self.stopped or not self.queue or mono < self.wait_until or not tr.cmdr:
            return
        batch = list(self.queue)
        header = {"appName": SOFTWARE, "appVersion": outrider.__version__, "APIkey": self.cfg["api_key"],
                  "commanderName": tr.cmdr}
        if tr.fid:
            header["commanderFrontierID"] = tr.fid
        try:
            async with session.post(INARA_URL, json={"header": header, "events": batch}) as r:
                reply = await r.json(content_type=None) if r.status == 200 else None
                status = r.status
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.error, self.wait_until = f"Inara could not be reached ({_why(e)})", mono + RETRY_S
            return
        head = reply.get("header") if isinstance(reply, dict) else None
        code = head.get("eventStatus") if isinstance(head, dict) else None
        if not isinstance(code, int):
            self.error, self.wait_until = f"Inara answered {status}", mono + RETRY_S
            return
        if code // 100 == 4:   # the key or the application refused: asking again changes nothing
            self.stopped = f"Inara refused the upload: {head.get('eventStatusText')} (check [inara] api_key)"
            self.dropped += len(self.queue)
            self.queue.clear()
            self.log("inara: " + self.stopped, file=sys.stderr)
            return
        for _ in batch:
            self.queue.popleft()
        bad = [e for e in (reply.get("events") or []) if isinstance(e, dict) and isinstance(e.get("eventStatus"), int)
               and e["eventStatus"] // 100 == 4]
        self.sent += len(batch) - len(bad)
        self.dropped += len(bad)
        self.last = time.time()
        self.error = f"Inara did not take {len(bad)} of {len(batch)} events: {bad[0].get('eventStatusText')}" if bad else None
        self.wait_until = mono + INARA_GAP_S

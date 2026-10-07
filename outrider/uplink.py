"""Uploads ([uploads], each off by default): what EDMarketConnector does, done here.

- EDDN: what the game shows everyone (systems, scans, signals, stations, markets, outfitting, shipyards) goes to the
  shared network Spansh, EDSM and Inara read. Its rules (docs/Developers.md and each schema's README in EDCD/EDDN)
  are followed to the letter: personal fields and `_Localised` keys removed, a system's name and position added only
  when the event's own id agrees with the last arrival, one message never retried after a 400/426, a failed one
  not before a minute has passed. tests/test_uplink.py checks every message against EDDN's own schemas.
- EDSM and Inara: your own flight log to your own account, with the API key you give.

Only live play is sent: this module tails the newest journal on its own (nothing here touches Outrider's database
or its journal reader), reads what is already there at start for the state alone, and sends an event only when its
timestamp is at most LIVE_S old. Nothing is sent while every switch is off; --simulate switches them all off.

Pure parts: `uploads_settings`, `Tracker`, `eddn_messages`, `fss_message`, `market_message`, `outfitting_message`,
`shipyard_message`, `edsm_event`, `inara_events`. `Uplink` holds the tail, the queues and the senders.
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

SOFTWARE = "ED Outrider CWeed14 Edition"   # this fork's own name to EDDN, EDSM and Inara: its messages are not upstream's
EDDN_URL = "https://eddn.edcd.io:4430/upload/"
EDDN_SCHEMAS = "https://eddn.edcd.io/schemas/"
EDSM_URL = "https://www.edsm.net/api-journal-v1"
EDSM_DISCARD_URL = "https://www.edsm.net/api-journal-v1/discard"
INARA_URL = "https://inara.cz/inapi/v1/"

LIVE_S = 300            # s: an event older than this is history (a journal being caught up on), never sent
POLL_S = 1.0            # s between looks at the journal
FILE_WAIT_S = 5.0       # s a Market.json (Outfitting, Shipyard, NavRoute, FCMaterials) may take to follow its event
FSS_IDLE_S = 3.0        # s without another line before a run of FSSSignalDiscovered goes out
RETRY_S = 60            # s before a failed request is tried again (EDDN: at least a minute)
EDDN_TRIES = 10         # then a message is dropped
QUEUE_MAX = 500         # messages (EDDN) or events (EDSM, Inara) kept while the service cannot be reached
EDSM_BATCH = 100        # events per request
EDSM_QUIET_S = 300      # s an event waits for a jump or a docking to ride along with, at most
EDSM_GAP_S = 10         # s between two requests
INARA_GAP_S = 30        # s between two requests (Inara asks for few, batched)
HTTP_TIMEOUT = 20

DEFAULTS = {"eddn": False, "eddn_test": False, "edsm": False, "edsm_commander": "", "edsm_api_key": "",
            "inara": False, "inara_api_key": ""}


def uploads_settings(cfg):
    """[uploads] from a parsed config, as DEFAULTS' keys. A wrong value is reported on stderr and the default kept;
    a service switched on without its key stays off, with the reason."""
    u = cfg.get("uploads") if isinstance(cfg.get("uploads"), dict) else {}
    out = dict(DEFAULTS)
    for k, default in DEFAULTS.items():
        v = u.get(k, default)
        if isinstance(default, bool):
            if not isinstance(v, bool):
                print(f"config: [uploads] {k} = {v!r} must be true or false; using false", file=sys.stderr)
                v = False
        elif not isinstance(v, str) or len(v) > 200 or any(ord(c) < 32 for c in v):
            print(f"config: [uploads] {k} must be text in quotes; ignored", file=sys.stderr)
            v = ""
        out[k] = v.strip() if isinstance(v, str) else v
    for service in ("edsm", "inara"):
        if out[service] and not out[f"{service}_api_key"]:
            print(f"config: [uploads] {service} = true needs {service}_api_key (from your account's settings there); "
                  f"{service} stays off", file=sys.stderr)
            out[service] = False
    return out


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
# EDDN
# ---------------------------------------------------------------------------

def strip_localised(v):
    """A copy without any key ending in _Localised, at every depth (EDDN: the player's language is theirs)."""
    if isinstance(v, dict):
        return {k: strip_localised(x) for k, x in v.items() if not k.endswith("_Localised")}
    if isinstance(v, list):
        return [strip_localised(x) for x in v]
    return v


def place(ev, tr, name_key="StarSystem"):
    """The tracked system, only if it is the event's own: EDDN's location cross-check. The journal can stop and
    resume with lines missing, so a name or position is never added on trust: the event's SystemAddress and its
    system name, whichever it has (it must have one), have to agree with the last arrival. None: drop the event."""
    s, addr, name = tr.system, ev.get("SystemAddress"), ev.get(name_key)
    if not s or (addr is None and name is None):
        return None
    if (addr is not None and addr != s["address"]) or (name is not None and name != s["name"]):
        return None
    return s


JOURNAL_EVENTS = frozenset(("Docked", "FSDJump", "Scan", "Location", "SAASignalsFound", "CarrierJump"))
# the journal schema's disallowed keys: the commander's own state, not the galaxy's
JOURNAL_PERSONAL = frozenset(("ActiveFine", "CockpitBreach", "BoostUsed", "FuelLevel", "FuelUsed", "JumpDist", "Latitude",
                              "Longitude", "Wanted", "IsNewEntry", "NewTraitsDiscovered", "Traits", "VoucherAmount"))
FACTION_PERSONAL = frozenset(("HappiestSystem", "HomeSystem", "MyReputation", "SquadronFaction"))

# The schemas that take nothing but their own keys. event -> (schema, the keys kept, the event's key for the system's
# name or None, whether StarSystem is added, the keys it must end up with).
_ORBIT = ("SemiMajorAxis", "Eccentricity", "OrbitalInclination", "Periapsis", "OrbitalPeriod", "AscendingNode", "MeanAnomaly")
CLOSED = {
    "FSSDiscoveryScan": ("fssdiscoveryscan/1", ("SystemName", "SystemAddress", "BodyCount", "NonBodyCount"), "SystemName",
                         False, ("SystemName", "BodyCount", "NonBodyCount")),
    "FSSAllBodiesFound": ("fssallbodiesfound/1", ("SystemName", "SystemAddress", "Count"), "SystemName", False,
                          ("SystemName", "Count")),
    "FSSBodySignals": ("fssbodysignals/1", ("SystemAddress", "BodyID", "BodyName", "Signals"), None, True,
                       ("BodyID", "Signals")),
    "NavBeaconScan": ("navbeaconscan/1", ("SystemAddress", "NumBodies"), None, True, ("NumBodies",)),
    "ScanBaryCentre": ("scanbarycentre/1", ("StarSystem", "SystemAddress", "BodyID") + _ORBIT, "StarSystem", True,
                       ("BodyID",)),
    "ApproachSettlement": ("approachsettlement/1", ("SystemAddress", "Name", "MarketID", "BodyID", "BodyName", "Latitude",
                                                    "Longitude", "StationGovernment", "StationAllegiance",
                                                    "StationEconomies", "StationFaction", "StationServices",
                                                    "StationEconomy"), None, True,
                           ("Name", "BodyID", "BodyName", "Latitude", "Longitude")),
    "CodexEntry": ("codexentry/1", ("System", "SystemAddress", "Name", "Region", "EntryID", "Category", "Latitude",
                                    "Longitude", "SubCategory", "NearestDestination", "VoucherAmount", "Traits"),
                   "System", False, ("System", "EntryID")),
}
DOCKING = {"DockingGranted": ("dockinggranted/1", ("MarketID", "StationName", "StationType", "LandingPad"),
                              ("MarketID", "StationName")),
           "DockingDenied": ("dockingdenied/1", ("MarketID", "StationName", "StationType", "Reason"),
                             ("MarketID", "StationName", "Reason"))}
SUB_KEYS = {"Signals": ("Type", "Count"), "StationEconomies": ("Name", "Proportion")}   # lists of objects, their keys
SIGNAL_KEYS = ("timestamp", "SignalName", "SignalType", "IsStation", "USSType", "SpawningState", "SpawningFaction",
               "SpawningPower", "OpposingPower", "ThreatLevel")
FILE_EVENTS = {"Market": "Market.json", "Outfitting": "Outfitting.json", "Shipyard": "Shipyard.json",
               "NavRoute": "NavRoute.json", "FCMaterials": "FCMaterials.json"}
MODULE_RE = re.compile(r"^hpt_|^int_|_armour_", re.I)   # weapons and utilities, internals, armour: nothing cosmetic


def _flags(msg, tr):
    """horizons / odyssey as LoadGame gave them; a flag it did not give is left out (never sent as false)."""
    for k in ("horizons", "odyssey"):
        if isinstance(getattr(tr, k), bool):
            msg[k] = getattr(tr, k)
    return msg


def eddn_messages(ev, tr, status_body=None):
    """The EDDN messages one journal event makes: [(schema, message)], none for an event EDDN does not take or one
    that fails a check. `tr` has seen the event already. status_body: Status.json's BodyName now (a CodexEntry's
    body is named only when the game's HUD names one, and numbered only when the journal agrees)."""
    name, ts = ev.get("event"), ev.get("timestamp")
    if not isinstance(ts, str):
        return []
    if name in JOURNAL_EVENTS:
        s = place(ev, tr)
        if not s:
            return []
        msg = {k: v for k, v in strip_localised(ev).items() if k not in JOURNAL_PERSONAL}
        if isinstance(msg.get("Factions"), list):
            msg["Factions"] = [{k: v for k, v in f.items() if k not in FACTION_PERSONAL} if isinstance(f, dict) else f
                               for f in msg["Factions"]]
        msg.setdefault("StarSystem", s["name"])
        msg.setdefault("SystemAddress", s["address"])
        if _pos(msg.get("StarPos")) is None:
            msg["StarPos"] = s["pos"]
        return [("journal/1", _flags(msg, tr))]
    if name in DOCKING:
        schema, keys, need = DOCKING[name]
        msg = {"timestamp": ts, "event": name, **{k: ev[k] for k in keys if k in ev}}
        return [(schema, _flags(msg, tr))] if all(k in msg for k in need) else []
    if name not in CLOSED:
        return []
    schema, keys, name_key, add_name, need = CLOSED[name]
    s = place(ev, tr, name_key or "StarSystem")
    if not s:
        return []
    msg = {"timestamp": ts, "event": name}
    for k in keys:
        if k not in ev:
            continue
        v = strip_localised(ev[k])
        if k in SUB_KEYS:
            if not isinstance(v, list):
                continue
            v = [{x: item[x] for x in SUB_KEYS[k] if x in item} for item in v if isinstance(item, dict)]
        msg[k] = v
    if add_name:
        msg["StarSystem"] = s["name"]
    msg["SystemAddress"], msg["StarPos"] = s["address"], s["pos"]
    if any(k not in msg for k in need):
        return []
    if name == "CodexEntry" and status_body:
        msg["BodyName"] = status_body
        if tr.body and tr.body[0] == status_body and tr.body[1] is not None:
            msg["BodyID"] = tr.body[1]
    return [(schema, _flags(msg, tr))]


def fss_message(events, tr):
    """A run of FSSSignalDiscovered as one fsssignaldiscovered/1 message (EDDN wants them batched), or None. A signal
    of another system than the tracked one is dropped, as is a mission's own target (of use to nobody else)."""
    s = tr.system
    if not s:
        return None
    signals = [{k: e[k] for k in SIGNAL_KEYS if k in e} for e in events
               if e.get("SystemAddress") == s["address"] and e.get("USSType") != "$USS_Type_MissionTarget;"
               and isinstance(e.get("timestamp"), str) and isinstance(e.get("SignalName"), str)]
    if not signals:
        return None
    return ("fsssignaldiscovered/1", _flags({
        "event": "FSSSignalDiscovered", "timestamp": signals[0]["timestamp"], "SystemAddress": s["address"],
        "StarSystem": s["name"], "StarPos": s["pos"], "signals": signals}, tr))


def _station_head(f):
    """A station file's own place: Market.json, Outfitting.json and Shipyard.json name their system and station."""
    if not (isinstance(f.get("StarSystem"), str) and isinstance(f.get("StationName"), str)
            and _int(f.get("MarketID")) is not None and isinstance(f.get("timestamp"), str)):
        return None
    return {"timestamp": f["timestamp"], "systemName": f["StarSystem"], "stationName": f["StationName"],
            "marketId": f["MarketID"]}


def commodity_name(name):
    """Market.json's "$gold_name;" as EDDN wants it: "gold"."""
    m = re.fullmatch(r"\$(.+)_name;", name, re.I)
    return (m.group(1) if m else name).lower()


def market_message(f, tr):
    """Market.json as a commodity/3 message, or None (no market, or a line that is not what the game writes)."""
    head, items = _station_head(f), f.get("Items")
    if not head or not isinstance(items, list) or not items:
        return None
    out = []
    for it in items:
        try:
            row = {"name": commodity_name(it["Name"]), "meanPrice": it["MeanPrice"], "buyPrice": it["BuyPrice"],
                   "stock": it["Stock"], "stockBracket": it["StockBracket"], "sellPrice": it["SellPrice"],
                   "demand": it["Demand"], "demandBracket": it["DemandBracket"]}
        except (KeyError, TypeError, AttributeError):
            return None
        if any(_int(row[k]) is None for k in ("meanPrice", "buyPrice", "stock", "sellPrice", "demand")) \
                or any(row[k] not in (0, 1, 2, 3, "") or isinstance(row[k], bool) for k in ("stockBracket", "demandBracket")):
            return None
        out.append(row)
    for src, key in (("StationType", "stationType"), ("CarrierDockingAccess", "carrierDockingAccess")):
        if isinstance(f.get(src), str):
            head[key] = f[src]
    return ("commodity/3", _flags(dict(head, commodities=out), tr))


def outfitting_message(f, tr):
    """Outfitting.json as an outfitting/2 message: the names of the modules the station sells, or None."""
    head, items = _station_head(f), f.get("Items")
    if not head or not isinstance(items, list):
        return None
    names = sorted({it["Name"] for it in items if isinstance(it, dict) and isinstance(it.get("Name"), str)
                    and MODULE_RE.search(it["Name"]) and it["Name"].lower() != "int_planetapproachsuite"})
    return ("outfitting/2", _flags(dict(head, modules=names), tr)) if names else None


def shipyard_message(f, tr):
    """Shipyard.json as a shipyard/2 message: the ships on sale, or None."""
    head, items = _station_head(f), f.get("PriceList")
    if not head or not isinstance(items, list):
        return None
    ships = sorted({it["ShipType"] for it in items if isinstance(it, dict) and isinstance(it.get("ShipType"), str)})
    if not ships:
        return None
    if isinstance(f.get("AllowCobraMkIV"), bool):
        head["allowCobraMkIV"] = f["AllowCobraMkIV"]
    return ("shipyard/2", _flags(dict(head, ships=ships), tr))


def navroute_message(f, tr):
    """NavRoute.json as a navroute/1 message, or None (a cleared route)."""
    route = f.get("Route")
    if not isinstance(route, list) or not route or not isinstance(f.get("timestamp"), str):
        return None
    rows = []
    for r in route:
        if not (isinstance(r, dict) and isinstance(r.get("StarSystem"), str) and _int(r.get("SystemAddress")) is not None
                and _pos(r.get("StarPos")) and isinstance(r.get("StarClass"), str)):
            return None
        rows.append({k: r[k] for k in ("StarSystem", "SystemAddress", "StarPos", "StarClass")})
    return ("navroute/1", _flags({"timestamp": f["timestamp"], "event": "NavRoute", "Route": rows}, tr))


def fcmaterials_message(f, tr):
    """FCMaterials.json (a carrier's bartender) as an fcmaterials_journal/1 message, or None."""
    items = f.get("Items")
    if not (isinstance(items, list) and _int(f.get("MarketID")) is not None and isinstance(f.get("CarrierName"), str)
            and isinstance(f.get("CarrierID"), str) and isinstance(f.get("timestamp"), str)):
        return None
    rows = []
    for it in items:
        if not (isinstance(it, dict) and isinstance(it.get("Name"), str)
                and all(_int(it.get(k)) is not None for k in ("id", "Price", "Stock", "Demand"))):
            return None
        rows.append({k: it[k] for k in ("id", "Name", "Price", "Stock", "Demand")})
    return ("fcmaterials_journal/1", _flags({
        "timestamp": f["timestamp"], "event": "FCMaterials", "MarketID": f["MarketID"], "CarrierName": f["CarrierName"],
        "CarrierID": f["CarrierID"], "Items": rows}, tr))


FILE_MESSAGES = {"Market": market_message, "Outfitting": outfitting_message, "Shipyard": shipyard_message,
                 "NavRoute": navroute_message, "FCMaterials": fcmaterials_message}


def eddn_envelope(schema, message, tr, test=False):
    """The whole EDDN message. A beta or alpha game, and [uploads] eddn_test, go to the schema's /test form."""
    return {"$schemaRef": EDDN_SCHEMAS + schema + ("/test" if test or tr.beta else ""),
            "header": {"uploaderID": tr.cmdr, "softwareName": SOFTWARE, "softwareVersion": outrider.__version__,
                       "gameversion": tr.gameversion, "gamebuild": tr.gamebuild},
            "message": message}


# ---------------------------------------------------------------------------
# EDSM
# ---------------------------------------------------------------------------

EDSM_FLUSH = frozenset(("Location", "FSDJump", "CarrierJump", "Docked", "Shutdown"))


def edsm_event(ev, tr):
    """The journal event as EDSM's journal API takes it: the line itself plus where and in what it happened."""
    out = dict(ev)
    if tr.system:
        out.update(_systemName=tr.system["name"], _systemAddress=tr.system["address"],
                   _systemCoordinates=tr.system["pos"])
    if tr.station:
        out["_stationName"] = tr.station["name"]
        if tr.station["market"] is not None:
            out["_marketId"] = tr.station["market"]
    if tr.ship:
        out["_shipId"] = tr.ship["id"]
    return out


# ---------------------------------------------------------------------------
# Inara
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
# The tail of the live journal
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


def read_json(folder, name):
    """A game file beside the journal as a dict, or None (missing, or caught mid-write)."""
    try:
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            v = json.load(f)
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) else None


# ---------------------------------------------------------------------------
# The services: what waits, and how it is sent
# ---------------------------------------------------------------------------

class Service:
    """One destination's switch, queue and tally (what the page shows)."""

    def __init__(self, on):
        self.on = bool(on)
        self.queue = collections.deque()
        self.sent = self.dropped = 0
        self.last = None       # wall clock of the last request the service took
        self.error = None      # the latest problem in words, cleared by the next success
        self.stopped = None    # why sending stopped for good (a refused key), until a restart
        self.wait_until = 0.0  # monotonic: nothing is sent before

    def push(self, item):
        if len(self.queue) >= QUEUE_MAX:
            self.queue.popleft()
            self.dropped += 1
        self.queue.append(item)

    def info(self):
        return {"on": self.on, "sent": self.sent, "dropped": self.dropped, "waiting": len(self.queue),
                "last": self.last, "error": self.stopped or self.error}

    def ok(self, n=1):
        self.sent += n
        self.last, self.error = time.time(), None

    def failed(self, why, now):
        self.error, self.wait_until = why, now + RETRY_S


def _why(e):
    return "timed out" if isinstance(e, asyncio.TimeoutError) else (str(e) or type(e).__name__)


class Uplink:
    """The uploads as a whole: `run()` is the task (tail, translate, send); `info()` is what the page shows."""

    def __init__(self, settings, dirs, off=None, log=print):
        cfg = dict(DEFAULTS, **(settings or {}))
        self.cfg, self.dirs, self.log = cfg, list(dirs), log
        self.off = off         # why nothing is sent whatever the config says (--simulate), or None
        on = lambda k: bool(cfg[k]) and not off
        self.eddn, self.edsm, self.inara = Service(on("eddn")), Service(on("edsm")), Service(on("inara"))
        self.tracker = Tracker()
        self.tail = Tail(self.dirs)
        self.fss = []          # the FSSSignalDiscovered run being collected
        self.fss_at = 0.0      # monotonic time of its last line
        self.files = []        # [(event, folder, deadline)]: station files still to follow their event
        self.sent_files = {}   # schema -> the last message's content (a market opened twice is sent once)
        self.discard = None    # EDSM's list of events it does not want (asked for before the first batch)
        self.discard_at = 0.0
        self.memo = {}         # inara_events' own
        self.started = False

    @property
    def active(self):
        return self.eddn.on or self.edsm.on or self.inara.on

    def info(self):
        return {"eddn": dict(self.eddn.info(), test=bool(self.cfg["eddn_test"])), "edsm": self.edsm.info(),
                "inara": self.inara.info(), "off": self.off}

    def status_line(self):
        """One line for the start-up log."""
        if self.off:
            return f"off ({self.off})"
        on = [n for n, s in (("EDDN" + (" (test schemas)" if self.cfg["eddn_test"] else ""), self.eddn),
                             ("EDSM", self.edsm), ("Inara", self.inara)) if s.on]
        return "to " + ", ".join(on) + " (live play only)" if on else "off ([uploads]): nothing is sent anywhere"

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

    def poll(self, now=None, mono=None):
        """Read what the journal gained and queue what it makes. now: the wall clock (an event's age); mono: the
        monotonic clock (waits)."""
        now = time.time() if now is None else now
        mono = time.monotonic() if mono is None else mono
        if not self.started:
            self.start()
        for line, folder in self.tail.read():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            try:
                self.feed(ev, folder, now, mono)
            except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
                self.log(f"uploads: journal line skipped ({type(e).__name__}: {e}): {line[:160]!r}", file=sys.stderr)
        if self.fss and mono - self.fss_at >= FSS_IDLE_S:
            self.flush_fss()
        self.follow_files(mono)

    def feed(self, ev, folder, now, mono):
        """One journal line written since the start, in order: the state first, then what each service gets of it."""
        name, ts = ev.get("event"), ev.get("timestamp")
        try:   # an old line (a journal copied into the folder, one caught up on late) is history: it is not sent, and
            if now - ts_seconds(ts) > LIVE_S:   # it says nothing of where the commander is now
                return
        except (TypeError, ValueError):
            return
        signal = name == "FSSSignalDiscovered"
        if self.fss and not signal and name not in ("Location", "FSDJump", "CarrierJump"):
            self.flush_fss()   # with the system the run was seen in: before this line changes anything
        self.tracker.apply(ev)
        if self.fss and not signal:
            self.flush_fss()   # the arrival written after its signals (Odyssey): they are the new system's
        tr = self.tracker
        if not tr.cmdr:
            return
        if self.eddn.on:
            if signal:
                self.fss.append(ev)
                self.fss_at = mono
            elif name in FILE_EVENTS:
                self.files.append((ev, folder, mono + FILE_WAIT_S))
            else:
                body = (read_json(folder, "Status.json") or {}).get("BodyName") if name == "CodexEntry" else None
                for schema, msg in eddn_messages(ev, tr, body if isinstance(body, str) and body else None):
                    self.queue_eddn(schema, msg)
        mine = not tr.crew and not tr.beta and tr.live_galaxy
        if self.edsm.on and mine and not self.edsm.stopped:
            self.edsm.push(edsm_event(ev, tr))
        if self.inara.on and mine and not self.inara.stopped:
            for event, data in inara_events(ev, tr, self.memo):
                if event in INARA_LATEST:
                    for old in [x for x in self.inara.queue if x["eventName"] == event]:
                        self.inara.queue.remove(old)
                self.inara.push({"eventName": event, "eventTimestamp": ts, "eventData": data})

    def queue_eddn(self, schema, msg):
        self.eddn.push({"body": eddn_envelope(schema, msg, self.tracker, self.cfg["eddn_test"]), "tries": 0, "after": 0.0})

    def flush_fss(self):
        made = fss_message(self.fss, self.tracker)
        self.fss = []
        if made and self.tracker.cmdr:
            self.queue_eddn(*made)

    def follow_files(self, mono):
        """Market.json and the others, once the game has written the one their event announced (same timestamp)."""
        waiting, self.files = self.files, []
        for ev, folder, deadline in waiting:
            name = ev["event"]
            f = read_json(folder, FILE_EVENTS[name])
            if not f or f.get("timestamp") != ev.get("timestamp") or \
                    (name != "NavRoute" and f.get("MarketID") != ev.get("MarketID")):
                if mono < deadline:
                    self.files.append((ev, folder, deadline))
                continue
            made = FILE_MESSAGES[name](f, self.tracker)
            if not made:
                continue
            same = {k: v for k, v in made[1].items() if k != "timestamp"}
            if self.sent_files.get(made[0]) == same:
                continue   # the same screen opened again: nothing new to tell
            self.sent_files[made[0]] = same
            self.queue_eddn(*made)

    # -- sending ------------------------------------------------------------

    async def run(self, session_factory=None):
        """The task: every POLL_S read the journal and send what is due. Ends when cancelled."""
        if not self.active:
            return
        if session_factory is None:
            from aiohttp import ClientSession, ClientTimeout
            session_factory = lambda: ClientSession(timeout=ClientTimeout(total=HTTP_TIMEOUT),
                                                    headers={"User-Agent": f"{SOFTWARE}/{outrider.__version__}"})
        async with session_factory() as session:
            while True:
                try:
                    self.poll()
                    await self.send(session)
                except asyncio.CancelledError:
                    raise
                except Exception as e:   # never the end of the uploads: say it once a minute at most
                    self.log(f"uploads: {type(e).__name__}: {e}", file=sys.stderr)
                    await asyncio.sleep(RETRY_S)
                await asyncio.sleep(POLL_S)

    async def send(self, session, mono=None):
        mono = time.monotonic() if mono is None else mono
        if self.eddn.on:
            await self.send_eddn(session, mono)
        if self.edsm.on and not self.edsm.stopped:
            await self.send_edsm(session, mono)
        if self.inara.on and not self.inara.stopped:
            await self.send_inara(session, mono)

    async def send_eddn(self, session, mono):
        """One request per message. A 400, 413 or 426 is the message's own fault: dropped, never sent again. Anything
        else (no connection, a 5xx) is tried again after RETRY_S, EDDN_TRIES times, and holds the rest back too."""
        sv = self.eddn
        while sv.queue and mono >= sv.wait_until:
            item = sv.queue[0]
            try:
                async with session.post(EDDN_URL, data=json.dumps(item["body"]).encode("utf-8"),
                                        headers={"Content-Type": "application/json"}) as r:
                    status, text = r.status, (await r.text())[:300]
            except asyncio.CancelledError:
                raise
            except Exception as e:
                status, text = None, _why(e)
            if status == 200:
                sv.queue.popleft()
                sv.ok()
            elif status in (400, 413, 426):
                sv.queue.popleft()
                sv.dropped += 1
                sv.error = f"EDDN refused a {item['body']['$schemaRef'].rsplit('/schemas/', 1)[-1]} message ({status}): {text}"
                self.log("uploads: " + sv.error, file=sys.stderr)
            else:
                item["tries"] += 1
                if item["tries"] >= EDDN_TRIES:
                    sv.queue.popleft()
                    sv.dropped += 1
                sv.failed(f"EDDN could not be reached ({status or text})", mono)

    async def send_edsm(self, session, mono):
        sv = self.edsm
        if mono < sv.wait_until:
            return
        if self.discard is None:
            if not sv.queue:
                return
            try:
                async with session.get(EDSM_DISCARD_URL) as r:
                    got = await r.json(content_type=None) if r.status == 200 else None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                got = None
                sv.error = f"EDSM could not be reached ({_why(e)})"
            if not isinstance(got, list):
                sv.failed(sv.error or "EDSM did not say which events it wants", mono)
                return
            self.discard = frozenset(x for x in got if isinstance(x, str))
        for ev in [e for e in sv.queue if e.get("event") in self.discard]:
            sv.queue.remove(ev)
        if not sv.queue:
            return
        first = sv.queue[0].get("_queued")
        if first is None:
            for ev in sv.queue:
                ev.setdefault("_queued", mono)
            first = mono
        if not any(e.get("event") in EDSM_FLUSH for e in sv.queue) and mono - first < EDSM_QUIET_S:
            return
        batch = list(sv.queue)[:EDSM_BATCH]
        tr = self.tracker
        form = {"commanderName": self.cfg["edsm_commander"] or tr.cmdr or "", "apiKey": self.cfg["edsm_api_key"],
                "fromSoftware": SOFTWARE, "fromSoftwareVersion": outrider.__version__,
                "fromGameVersion": tr.gameversion, "fromGameBuild": tr.gamebuild,
                "message": json.dumps([{k: v for k, v in e.items() if k != "_queued"} for e in batch])}
        try:
            async with session.post(EDSM_URL, data=form) as r:
                reply = await r.json(content_type=None) if r.status == 200 else None
                status = r.status
        except asyncio.CancelledError:
            raise
        except Exception as e:
            sv.failed(f"EDSM could not be reached ({_why(e)})", mono)
            return
        num = reply.get("msgnum") if isinstance(reply, dict) else None
        if not isinstance(num, int):
            sv.failed(f"EDSM answered {status}", mono)
            return
        if num // 100 == 2:   # the commander's name or key refused, or the software: asking again changes nothing
            sv.stopped = f"EDSM refused the upload: {reply.get('msg')} (check [uploads] edsm_commander and edsm_api_key)"
            sv.dropped += len(sv.queue)
            sv.queue.clear()
            self.log("uploads: " + sv.stopped, file=sys.stderr)
            return
        for _ in batch:
            sv.queue.popleft()
        sv.ok(len(batch))
        sv.wait_until = mono + EDSM_GAP_S

    async def send_inara(self, session, mono):
        sv, tr = self.inara, self.tracker
        if not sv.queue or mono < sv.wait_until or not tr.cmdr:
            return
        batch = list(sv.queue)
        header = {"appName": SOFTWARE, "appVersion": outrider.__version__, "APIkey": self.cfg["inara_api_key"],
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
            sv.failed(f"Inara could not be reached ({_why(e)})", mono)
            return
        head = reply.get("header") if isinstance(reply, dict) else None
        code = head.get("eventStatus") if isinstance(head, dict) else None
        if not isinstance(code, int):
            sv.failed(f"Inara answered {status}", mono)
            return
        if code // 100 == 4:   # the key or the application refused: asking again changes nothing
            sv.stopped = f"Inara refused the upload: {head.get('eventStatusText')} (check [uploads] inara_api_key)"
            sv.dropped += len(sv.queue)
            sv.queue.clear()
            self.log("uploads: " + sv.stopped, file=sys.stderr)
            return
        for _ in batch:
            sv.queue.popleft()
        bad = [e for e in (reply.get("events") or []) if isinstance(e, dict) and isinstance(e.get("eventStatus"), int)
               and e["eventStatus"] // 100 == 4]
        sv.ok(len(batch) - len(bad))
        sv.dropped += len(bad)
        if bad:
            sv.error = f"Inara did not take {len(bad)} of {len(batch)} events: {bad[0].get('eventStatusText')}"
        sv.wait_until = mono + INARA_GAP_S

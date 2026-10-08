"""EDDN, the Elite Dangerous Data Network: the messages Outrider sends (opt-in; PLAN-edmc-functionality parts B-F).
Pure: build(ev, session) turns one journal event into EDDN messages; outcome() says what an EDDN answer means. The
sending (gzip, one message per POST, the outbox) is outrider/uploads.py's loop with the server's sender.

The rules are EDDN's own (docs/Developers.md and each schema's README on its `live` branch; research notes in
project/research-edmc-2026-10-08/eddn.md). Some of the logic follows EDMarketConnector's plugins/eddn.py (Copyright (c)
EDCD, GPL v2 or later), whose rules these are.

Every message:
- carries the header EDDN asks for: uploaderID (the session's commander), softwareName "ED Outrider", its version,
  and the journal file's own gameversion / gamebuild (never left out: "" when unknown);
- has every *_Localised key removed, at any depth, and each schema's personal fields;
- adds StarSystem / StarPos only when the event's SystemAddress is where the session last jumped or logged in to
  (EDDN's location cross-check), else is not sent at all;
- adds horizons / odyssey only when LoadGame said them (a key LoadGame left out stays out);
- is never built for the beta, the Legacy game or a crew session (UploadHub checks that before asking).
"""
import re

UPLOAD_URL = "https://eddn.edcd.io:4430/upload/"
SOFTWARE = "ED Outrider"
SCHEMA_BASE = "https://eddn.edcd.io/schemas"

# journal/1: the events it takes, and the keys it refuses (personal data; schema "disallowed")
JOURNAL_EVENTS = ("Docked", "FSDJump", "Scan", "Location", "SAASignalsFound", "CarrierJump")
JOURNAL_DROP = ("ActiveFine", "CockpitBreach", "BoostUsed", "FuelLevel", "FuelUsed", "JumpDist", "Latitude",
                "Longitude", "Wanted", "IsNewEntry", "NewTraitsDiscovered", "Traits", "VoucherAmount")
FACTION_DROP = ("HappiestSystem", "HomeSystem", "MyReputation", "SquadronFaction")


def schema_ref(name, version=1, test=False):
    return f"{SCHEMA_BASE}/{name}/{version}" + ("/test" if test else "")


def unlocalised(obj):
    """A copy without any key ending _Localised, at any depth."""
    if isinstance(obj, dict):
        return {k: unlocalised(v) for k, v in obj.items() if not k.endswith("_Localised")}
    if isinstance(obj, list):
        return [unlocalised(v) for v in obj]
    return obj


def envelope(name, message, session, software_version, version=1, test=False):
    """The whole EDDN message: $schemaRef, header, message (horizons / odyssey added when LoadGame said them)."""
    msg = dict(message)
    if session.horizons is not None:
        msg["horizons"] = session.horizons
    if session.odyssey is not None:
        msg["odyssey"] = session.odyssey
    return {"$schemaRef": schema_ref(name, version, test),
            "header": {"uploaderID": session.cmdr or "", "softwareName": SOFTWARE, "softwareVersion": software_version,
                       "gameversion": session.gameversion or "", "gamebuild": session.gamebuild or ""},
            "message": msg}


def journal_message(ev, session):
    """journal/1 for FSDJump, Location, CarrierJump, Docked, Scan, SAASignalsFound; None when it must not be sent
    (another system than the session's: a stalled journal, a delayed Scan)."""
    name = ev.get("event")
    if name not in JOURNAL_EVENTS:
        return None
    addr = ev.get("SystemAddress")
    if not session.located(addr):
        return None
    m = unlocalised({k: v for k, v in ev.items() if k not in JOURNAL_DROP})
    if isinstance(m.get("Factions"), list):
        m["Factions"] = [{k: v for k, v in f.items() if k not in FACTION_DROP} if isinstance(f, dict) else f
                         for f in m["Factions"]]
    m.setdefault("StarSystem", session.system)
    if not m.get("StarPos"):
        m["StarPos"] = list(session.pos)
    if not m.get("StarSystem"):
        return None
    return m


def build(ev, session, software_version, test=False):
    """The EDDN messages a journal event makes: [(schema name, envelope)]."""
    out = []
    m = journal_message(ev, session)
    if m is not None:
        out.append(("journal", envelope("journal", m, session, software_version, 1, test)))
    return out


# ---- EDDN's answers (docs/Developers.md "Server responses") ----

def outcome(status):
    """(state, retry_in) for an EDDN answer: 200 sent; 400 / 426 / 413 dropped for good (never retried: EDDN's rule);
    408 / 429 / 5xx and anything else queued again after a minute or more."""
    if status == 200:
        return "sent", None
    if status in (400, 413, 426):
        return "dropped", None
    return "queued", 60 if status not in (429, 503) else 120


SCHEMA_RE = re.compile(r"/schemas/([a-z_]+)/")


def schema_of(ref):
    m = SCHEMA_RE.search(ref or "")
    return m.group(1) if m else None


class SchemaHold:
    """EDMC's killswitch, ours: a schema EDDN refused three times within an hour is not sent again until Outrider
    restarts (a game update EDDN does not take yet; its new release must catch up first). Rows of it are dropped."""

    def __init__(self, limit=3, window=3600):
        self.limit, self.window, self.refusals, self.held = limit, window, {}, {}

    def refused(self, schema, now, why):
        times = [t for t in self.refusals.get(schema, []) if now - t < self.window] + [now]
        self.refusals[schema] = times
        if len(times) >= self.limit:
            self.held[schema] = why

    def is_held(self, schema):
        return self.held.get(schema)


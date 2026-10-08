"""Nearest place to dock: stations and fleet carriers you can land at and use, nearest first. Pure: no I/O.

Three sources, read only, never anything uploaded:
- Spansh's station search: stations and carriers as players last reported them (EDDN). A carrier's place is as
  current as the last time someone with an uploader docked there: months or years old for some, so every row says
  how old it is and the finder hides what is older than the player's limit (30 days by default).
- The Deep Space Support Array's carrier list, as EDAstro publishes it (`DSSA_URL`, rebuilt from the DSSA tracker and
  EDDN dockings): carriers stationed for years in the black for explorers, open to all by the network's rules.
- Your own carrier, from your journal.

A carrier in Spansh and the DSSA list (by callsign) is one row: the DSSA badge, the fresher of the two places, and the
services of both. Docking access other than "All" is shown with a warning, not hidden (the author, 2026-10-08):
Friends and Squadron need you on the owner's list, which Outrider cannot see, and Spansh has no access recorded for
some carriers at all.
"""
import calendar
import math
import time

from outrider.cargo import CARRIER_TYPE, LARGE, MEDIUM, jumps_estimate

DSSA_URL = "https://edastro.com/json/DSSA-carriers.json"
DSSA_MAX_AGE_S = 3600        # the list is asked for again (conditionally) at most this often, when the finder opens
SEARCH_LY = 10000            # how far the station search reaches
SEARCH_SIZE = 50             # stations and carriers each, nearest first
DEFAULT_AGE_DAYS = 30
FAR_LS = 5000
SERVICES = ("UC", "Vista", "Repair", "Refuel", "Shipyard", "Outfitting")
SPANSH_SERVICES = {"Universal Cartographics": "UC", "Vista Genomics": "Vista", "Repair": "Repair", "Refuel": "Refuel",
                   "Shipyard": "Shipyard", "Outfitting": "Outfitting"}
# Docking access as Spansh spells it -> the warning the row shows ("All" and your own carrier need none)
ACCESS = {"Friends": "friends only", "Squadron": "squadron only", "Squadron Friends": "squadron and friends only",
          "None": "closed to visitors", None: "docking not reported"}


def _secs(ts):
    """'2026-10-08 14:20:51', '2026-10-08T14:20:51Z' or epoch seconds -> epoch seconds (None if neither)."""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return float(ts)
    if not isinstance(ts, str) or len(ts) < 19:
        return None
    try:
        return float(calendar.timegm(time.strptime(ts[:19].replace(" ", "T"), "%Y-%m-%dT%H:%M:%S")))
    except ValueError:
        return None


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def dssa_services(words):
    """The DSSA list's services, written as words split at spaces ("Universal", "Cartographics", "Vista", "Genomics",
    or "UC"), as the finder's names."""
    w = {str(x).strip().lower() for x in words or [] if isinstance(x, str)}
    out = set()
    if w & {"uc", "cartographics"}:
        out.add("UC")
    if w & {"vista", "genomics"}:
        out.add("Vista")
    out |= {s for s in ("Repair", "Refuel", "Shipyard", "Outfitting") if s.lower() in w}
    return out


def dssa_rows(data):
    """EDAstro's DSSA-carriers.json as rows (operational carriers with coordinates; anything malformed skipped)."""
    rows = []
    for x in data if isinstance(data, list) else []:
        if not isinstance(x, dict) or not x.get("callsign"):
            continue
        if x.get("status") and "operational" not in str(x["status"]).lower():
            continue
        c = x.get("coords") if isinstance(x.get("coords"), dict) else {}
        xyz = [_num(c.get(k)) for k in "xyz"]
        if None in xyz:
            continue
        home, seen = str(x.get("designatedSystem") or ""), str(x.get("lastSeenSystem") or "")
        rows.append({"kind": "carrier", "callsign": str(x["callsign"]).upper(), "name": str(x.get("name") or "").strip(),
                     "system": seen if seen.lower() == home.lower() and seen else home or seen,
                     "id64": None, "x": xyz[0], "y": xyz[1], "z": xyz[2], "ls": None,
                     "services": dssa_services(x.get("services")), "pads": "L M", "large": True, "medium": True,
                     "access": "All", "seen": _secs(x.get("lastSeenDate")), "source": "DSSA", "dssa": True,
                     "until": str(x.get("until") or ""),
                     # stationed elsewhere just now (a restock run): its home is kept, with a warning
                     "away": seen if seen and home and seen.lower() != home.lower() else None})
    return rows


def spansh_rows(results):
    """Spansh's station search results (stations and carriers) as rows."""
    rows = []
    for r in results or []:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        carrier = r.get("type") == CARRIER_TYPE
        services = {SPANSH_SERVICES[s.get("name")] for s in r.get("services") or []
                    if isinstance(s, dict) and s.get("name") in SPANSH_SERVICES}
        large = carrier or bool(r.get("has_large_pad") or r.get("large_pads"))
        medium = carrier or large or bool(r.get("medium_pads"))
        rows.append({"kind": "carrier" if carrier else "station",
                     "callsign": str(r["name"]).upper() if carrier else "",
                     "name": str(r.get("carrier_name") or "").strip() if carrier else r["name"],
                     "station_type": None if carrier else r.get("type"),
                     "system": r.get("system_name"), "id64": r.get("system_id64"),
                     "x": _num(r.get("system_x")), "y": _num(r.get("system_y")), "z": _num(r.get("system_z")),
                     "ls": _num(r.get("distance_to_arrival")), "services": services,
                     "pads": "L M" if carrier else " ".join(p for p, on in (("L", large), ("M", medium), ("S", True)) if on),
                     "large": large, "medium": medium,
                     "access": r.get("carrier_docking_access") if carrier else "All",
                     "seen": _secs(r.get("updated_at")), "source": "Spansh", "dssa": False, "until": "", "away": None})
    return rows


def own_row(carrier):
    """Your own carrier (Journals.carrier with its place), always usable by you."""
    c = carrier or {}
    if c.get("id") is None or c.get("x") is None or (c.get("decommission") or {}).get("done"):
        return None
    # the services its last Docked listed (the game's ids); repair and refuel are optional on a carrier too
    ids = {str(x).lower() for x in c.get("services") or []}
    services = {name for sid, name in (("exploration", "UC"), ("vistagenomics", "Vista"), ("repair", "Repair"),
                                        ("refuel", "Refuel"), ("shipyard", "Shipyard"), ("outfitting", "Outfitting"))
                if sid in ids}
    if c.get("has_uc"):
        services.add("UC")
    if c.get("has_vista"):
        services.add("Vista")
    return {"kind": "carrier", "callsign": str(c.get("callsign") or "").upper(), "name": c.get("name") or "",
            "system": c.get("system"), "id64": c.get("id64"), "x": c["x"], "y": c["y"], "z": c["z"], "ls": 0,
            "services": services, "pads": "L M", "large": True, "medium": True, "access": "yours",
            "seen": None, "source": "journal", "dssa": False, "until": "", "away": None, "own": True}


def merge(spansh, dssa, own=None):
    """One row per place: a carrier known to both Spansh and the DSSA list (same callsign) keeps the DSSA badge, the
    fresher place and the services of both; your own carrier replaces any report of it."""
    by_call = {}
    out = []
    for r in spansh:
        if r["kind"] == "carrier" and r["callsign"]:
            by_call[r["callsign"]] = r
        out.append(r)
    for d in dssa:
        s = by_call.get(d["callsign"])
        if s is None:
            out.append(d)
            continue
        fresher = d if (d["seen"] or 0) >= (s["seen"] or 0) else s
        s.update(dssa=True, until=d["until"], name=s["name"] or d["name"], away=d["away"],
                 services=s["services"] | d["services"], access=s["access"] or "All", source="DSSA + Spansh",
                 seen=max(d["seen"] or 0, s["seen"] or 0) or None,
                 **{k: fresher[k] for k in ("system", "x", "y", "z")})
    if own:
        out = [r for r in out if not (r["kind"] == "carrier" and r["callsign"] == own["callsign"])] + [own]
    return out


def nearest(rows, pos, need=(), stations=True, carriers=True, pad=None, age_days=DEFAULT_AGE_DAYS, permit=False,
            permits=(), laden=None, now=None, limit=30):
    """The rows a player can use, nearest first, and how many each filter hid: {"rows": [...], "hidden": {...}}.

    need: services every row must have; pad: "L" or "M" (your ship's; None: any); age_days: reports older than this go
    (your own carrier never); permit: whether systems needing a permit stay (permits: the id64s that do)."""
    now = time.time() if now is None else now
    need = set(need)
    hidden = {"old": 0, "pad": 0, "permit": 0, "service": 0}
    kept = []
    for r in rows:
        if r["kind"] == "station" and not stations or r["kind"] == "carrier" and not carriers and not r.get("own"):
            continue
        if r["x"] is None or not pos:
            continue
        if not need <= r["services"]:
            hidden["service"] += 1
            continue
        if pad == LARGE and not r["large"] or pad == MEDIUM and not r["medium"]:
            hidden["pad"] += 1
            continue
        age = None if r["seen"] is None else max(0, now - r["seen"])
        if not r.get("own") and (age is None or age > age_days * 86400):
            hidden["old"] += 1
            continue
        if not permit and r.get("id64") is not None and r["id64"] in permits:
            hidden["permit"] += 1
            continue
        ly = math.dist((pos["x"], pos["y"], pos["z"]), (r["x"], r["y"], r["z"]))
        warn = []
        if r["access"] not in ("All", "yours"):
            warn.append(ACCESS.get(r["access"], f"docking: {r['access']}"))
        if r.get("away"):
            warn.append(f"last seen at {r['away']}")
        kept.append(dict(r, services=sorted(r["services"], key=SERVICES.index), ly=round(ly, 1),
                         ls=None if r["ls"] is None else round(r["ls"]),
                         here=ly < 0.5, jumps=None if ly < 0.5 else jumps_estimate(ly, laden),
                         far=bool(r["ls"] and r["ls"] > FAR_LS), age_s=None if age is None else round(age), warn=warn))
    kept.sort(key=lambda r: (r["ly"], not r.get("own")))
    return {"rows": kept[:limit], "hidden": hidden, "more": max(0, len(kept) - limit)}


def spoken(result, need=(), kind=None):
    """The voice's answer ("nearest station", "nearest Vista"... asked of Outrider): the nearest place and what to know
    about it, in one sentence or two. kind: "station" or "carrier" when the question named one."""
    rows = [r for r in result["rows"] if not r.get("here")]
    what = " and ".join({"UC": "Universal Cartographics", "Vista": "Vista Genomics"}.get(n, n.lower()) for n in need)
    place = kind or "place to dock"
    if not rows:
        return f"No {place} {'with ' + what + ' ' if what else ''}is known nearby with recent enough reports."
    r = rows[0]
    sort = "fleet carrier" if r["kind"] == "carrier" else (r.get("station_type") or "station").lower()
    name = r["name"] or r["callsign"]
    out = (f"Nearest {place}{' with ' + what if what else ''}: {name}, a {sort}"
           f"{' of the Deep Space Support Array' if r.get('dssa') else ''}, {round(r['ly']):,} light years away"
           f"{', in ' + r['system'] if r['system'] else ''}.")
    if r["warn"]:
        out += " Careful: " + ", ".join(r["warn"]) + "."
    return out

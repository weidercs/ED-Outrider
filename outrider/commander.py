"""The Commander view: who you are in the game (ranks, credits, assets, the fleet), what you own, what engineering takes, the missions you hold, and how your combat
and mining sessions went. All of it from the journals as they are (outrider/jscan.py: read when asked, nothing
stored), the blueprints from resources/blueprints.json. The functions taking events are pure; `add_routes` serves
them (GET /api/commander/profile, /inventory, /engineering, /missions, /sessions).

What the journal does not state is not shown: a ship or stored module appears once the game has listed it (the
shipyard's and outfitting's StoredShips / StoredModules), suits and weapons only as a loadout you have worn, and a
mission's progress only where the game logs it (cargo deliveries).
"""
import json
import os
import re
import time

from . import RESOURCES_DIR, jscan, materials, shipinfo
from .core import iso_ts, ts_seconds

BLUEPRINTS_FILE = os.path.join(RESOURCES_DIR, "blueprints.json")
INVENTORY_DAYS = 365    # how far back the last StoredShips / StoredModules is looked for
MISSION_DAYS = 45       # missions run at most a few weeks
SESSION_DAYS = 30       # the sessions listed
SESSIONS_MAX = 40

# ---- inventory: ships, stored modules, the ship locker, suit loadouts ----

INVENTORY_EVENTS = ("StoredShips", "StoredModules", "ShipLocker", "SuitLoadout", "Loadout")
LOCKER_KINDS = (("Items", "Goods"), ("Components", "Assets"), ("Data", "Data"), ("Consumables", "Consumables"))


def _text(ev, key):
    """A journal text: its localised form when the game gave one, else the symbol tidied ("$x_name;" -> "x")."""
    v = ev.get(key + "_Localised") or ev.get(key)
    if not isinstance(v, str):
        return None
    return re.sub(r"^\$|_name;$|;$", "", v, flags=re.I) if v.startswith("$") else v


def _last(events, name, has=None):
    return next((e for e in reversed(events) if e.get("event") == name and (has is None or isinstance(e.get(has), list))), None)


def ships(events):
    """Your ships: the one you fly (the newest Loadout) and those stored (the newest StoredShips: where each is,
    its value, what moving it here costs). {ts (of the list), here (where the list was made), ships: [...]}."""
    stored, load = _last(events, "StoredShips", "ShipsHere"), _last(events, "Loadout", "Modules")
    rows = []
    if load:
        rows.append({"id": load.get("ShipID"), "type": load.get("Ship"), "name": load.get("ShipName") or None,
                     "ident": load.get("ShipIdent") or None, "current": True, "system": None, "station": None,
                     "value": (load.get("HullValue") or 0) + (load.get("ModulesValue") or 0) or None,
                     "hot": bool(load.get("Hot")), "transfer_cost": None, "transfer_s": None, "in_transit": False})
    if stored:
        here = {"system": stored.get("StarSystem"), "station": stored.get("StationName")}
        for key, local in (("ShipsHere", True), ("ShipsRemote", False)):
            for s in stored.get(key) or []:
                if not isinstance(s, dict) or (load and s.get("ShipID") == load.get("ShipID")):
                    continue
                rows.append({"id": s.get("ShipID"), "type": s.get("ShipType"), "type_name": s.get("ShipType_Localised"),
                             "name": s.get("Name") or None, "ident": None, "current": False,
                             "system": here["system"] if local else s.get("StarSystem"),
                             "station": here["station"] if local else None, "value": s.get("Value"),
                             "hot": bool(s.get("Hot")), "transfer_cost": None if local else s.get("TransferPrice"),
                             "transfer_s": None if local else s.get("TransferTime"), "in_transit": bool(s.get("InTransit"))})
    return {"ts": stored.get("timestamp") if stored else None, "ships": rows,
            "here": {"system": stored.get("StarSystem"), "station": stored.get("StationName")} if stored else None}


_RATING = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A"}
_HARDPOINT = {"tiny": 0, "small": 1, "medium": 2, "large": 3, "huge": 4}
_MOUNT = {"fixed": "Fixed", "gimbal": "Gimballed", "turret": "Turreted"}


def module_label(symbol, localised=None):
    """A stored module from its journal symbol ("$int_hyperdrive_size5_class5_name;"): (name, size, rating, mount).
    The name is the game's own when it gave one, else the symbol's words; size and rating are the symbol's
    (_size5 _class5: 5A), a weapon's size its mount point's (small 1 to huge 4), the mount fixed, gimballed or
    turreted."""
    it = re.sub(r"^\$|_name;$", "", str(symbol or ""), flags=re.I).lower()
    size = rating = mount = None
    m = re.search(r"_size(\d)", it)
    if m:
        size = int(m.group(1))
    m = re.search(r"_class(\d)", it)
    if m:
        rating = _RATING.get(int(m.group(1)))
    m = re.search(r"_(fixed|gimbal|turret)(?:_|$)", it)
    if m:
        mount = _MOUNT[m.group(1)]
    m = re.search(r"_(tiny|small|medium|large|huge)(?:_|$)", it)
    if m and it.startswith("hpt_"):
        size = _HARDPOINT[m.group(1)]
    if isinstance(localised, str) and localised.strip():
        return localised.strip(), size, rating, mount
    words = re.sub(r"^(int|hpt)_|_size\d|_class\d|_(fixed|gimbal|turret|tiny|small|medium|large|huge)(?=_|$)", "", it)
    return " ".join(words.split("_")).strip().capitalize() or "?", size, rating, mount


def stored_modules(events):
    """Your stored modules as outfitting last listed them: name (class, rating, mount), where, the engineering,
    what moving it here costs. {ts, modules: [...]}, the engineered first, then by name."""
    ev = _last(events, "StoredModules", "Items")
    rows = []
    for m in (ev or {}).get("Items") or []:
        if not isinstance(m, dict):
            continue
        name, size, rating, mount = module_label(m.get("Name"), m.get("Name_Localised"))
        # "FSD_LongRange" -> "Long range": the blueprint's own words, without the module it is for
        blueprint = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", re.sub(r"^[A-Za-z]+_", "", str(m.get("EngineerModifications") or ""))).capitalize() or None
        rows.append({"name": name, "size": size, "rating": rating, "mount": mount,
                     "system": m.get("StarSystem"), "in_transit": bool(m.get("InTransit")), "hot": bool(m.get("Hot")),
                     "value": m.get("BuyPrice"), "transfer_cost": m.get("TransferCost"), "transfer_s": m.get("TransferTime"),
                     "blueprint": blueprint,
                     "level": m.get("Level"), "quality": m.get("Quality")})
    rows.sort(key=lambda r: (r["blueprint"] is None, r["name"], -(r["size"] or 0)))
    return {"ts": ev.get("timestamp") if ev else None, "modules": rows}


def locker(events):
    """The ship locker (Odyssey) as the game last wrote it whole: each kind's items with their counts, a mission's
    own kept apart. {ts, kinds: [{name, items: [{name, count, mission}]}]}."""
    ev = _last(events, "ShipLocker", "Items")
    kinds = []
    for key, title in LOCKER_KINDS:
        tally = {}
        for it in (ev or {}).get(key) or []:
            if isinstance(it, dict) and isinstance(it.get("Count"), int):
                k = (_text(it, "Name") or "?", it.get("MissionID") is not None)
                tally[k] = tally.get(k, 0) + it["Count"]
        kinds.append({"name": title, "items": [{"name": n, "count": c, "mission": ms} for (n, ms), c in sorted(tally.items())]})
    return {"ts": ev.get("timestamp") if ev else None, "kinds": kinds}


def suits(events):
    """The suit loadouts you have worn (the journal lists no others): suit, its class and mods, the weapons with
    theirs. Newest first."""
    seen = {}
    for e in events:
        if e.get("event") == "SuitLoadout" and e.get("LoadoutID") is not None:
            seen[e["LoadoutID"]] = e
    rows = []
    for e in sorted(seen.values(), key=lambda e: e["timestamp"], reverse=True):
        suit = _text(e, "SuitName") or "?"
        cls = re.search(r"_class(\d)", str(e.get("SuitName") or ""))
        rows.append({"loadout": e.get("LoadoutName"), "suit": suit, "class": int(cls.group(1)) if cls else None,
                     "mods": [_mod(m) for m in e.get("SuitMods") or []], "ts": e["timestamp"],
                     "weapons": [{"name": _text(w, "ModuleName") or "?", "class": w.get("Class"), "slot": w.get("SlotName"),
                                  "mods": [_mod(m) for m in w.get("WeaponMods") or []]}
                                 for w in e.get("Modules") or [] if isinstance(w, dict)]})
    return rows


def _mod(symbol):
    """A suit or weapon mod's symbol in words: "suit_increasedsprintduration" -> "Increased sprint duration"."""
    s = re.sub(r"^(suit|weapon)_", "", str(symbol or ""), flags=re.I)
    s = re.sub(r"(increased|improved|reduced|added|extra|night|quieter|faster|greater|higher|stowed|combat|damage|"
               r"backpack|ammo|magazine|scope|range|stability|handling|reload|battery|shield|sprint|jump|melee|tool|"
               r"duration|capacity|assist|vision|size|rate|accuracy|speed|headshot)", r" \1", s)
    return " ".join(s.split()).capitalize() or "?"


def inventory(dirs, days=INVENTORY_DAYS, now=None):
    evs = jscan.events(dirs, INVENTORY_EVENTS, days, now)
    return {"ships": ships(evs), "modules": stored_modules(evs), "locker": locker(evs), "suits": suits(evs)}


# ---- engineering: the blueprints against your materials, and where the engineers stand ----

_BLUEPRINTS = {}


def load_blueprints(path=BLUEPRINTS_FILE):
    """resources/blueprints.json's list (read once per file time), [] when it cannot be read."""
    try:
        stamp = os.path.getmtime(path)
        if _BLUEPRINTS.get("key") != (path, stamp):
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)["blueprints"]
            _BLUEPRINTS.update(key=(path, stamp), rows=rows)
        return _BLUEPRINTS["rows"]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _plain(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def engineers(events):
    """Where each engineer stands, from the newest EngineerProgress lines: {name: {progress ("Known", "Invited",
    "Unlocked"...), rank (0 to 5, None until unlocked)}}. The login's list, then each change since."""
    out = {}
    for e in events:
        if e.get("event") != "EngineerProgress":
            continue
        for row in (e["Engineers"] if isinstance(e.get("Engineers"), list) else [e]):
            if isinstance(row, dict) and row.get("Engineer"):
                had = out.get(row["Engineer"]) or {}
                out[row["Engineer"]] = {"progress": row.get("Progress") or had.get("progress"),
                                        "rank": row.get("Rank") if row.get("Rank") is not None else had.get("rank")}
    return out


# Where each engineer works: (system, what they engineer, region). Their workshops have not moved since 2020 (Professor
# Palin's to Arque); the journal never says where an engineer is.
ENGINEER_SYSTEMS = {
    "Bill Turner": ("Alioth", "ship", "bubble"), "Broo Tarquin": ("Muang", "ship", "bubble"),
    "Chloe Sedesi": ("Shenve", "ship", "bubble"), "Colonel Bris Dekker": ("Sol", "ship", "bubble"),
    "Didi Vatermann": ("Leesti", "ship", "bubble"), "Elvira Martuuk": ("Khun", "ship", "bubble"),
    "Felicity Farseer": ("Deciat", "ship", "bubble"), "Hera Tani": ("Kuwemaki", "ship", "bubble"),
    "Juri Ishmaak": ("Giryak", "ship", "bubble"), "Lei Cheung": ("Laksak", "ship", "bubble"),
    "Liz Ryder": ("Eurybia", "ship", "bubble"), "Lori Jameson": ("Shinrarta Dezhra", "ship", "bubble"),
    "Marco Qwent": ("Sirius", "ship", "bubble"), "Professor Palin": ("Arque", "ship", "bubble"),
    "Ram Tah": ("Meene", "ship", "bubble"), "Selene Jean": ("Kuk", "ship", "bubble"),
    "The Dweller": ("Wyrd", "ship", "bubble"), "The Sarge": ("Beta-3 Tucani", "ship", "bubble"),
    "Tiana Fortune": ("Achenar", "ship", "bubble"), 'Tod "The Blaster" McQuinn': ("Wolf 397", "ship", "bubble"),
    "Zacariah Nemo": ("Yoru", "ship", "bubble"),
    "Etienne Dorn": ("Los", "ship", "Colonia"), "Marsha Hicks": ("Tir", "ship", "Colonia"),
    "Mel Brandon": ("Luchtaine", "ship", "Colonia"), "Petra Olmanova": ("Asura", "ship", "Colonia"),
    "Domino Green": ("Orishis", "suit & weapon", "bubble"), "Hero Ferrari": ("Siris", "suit & weapon", "bubble"),
    "Jude Navarro": ("Aurai", "suit & weapon", "bubble"), "Kit Fowler": ("Capoya", "suit & weapon", "bubble"),
    "Oden Geiger": ("Candiaei", "suit & weapon", "bubble"), "Terra Velasquez": ("Shou Xing", "suit & weapon", "bubble"),
    "Uma Laszlo": ("Xuane", "suit & weapon", "bubble"), "Wellington Beck": ("Jolapa", "suit & weapon", "bubble"),
    "Yarden Bond": ("Bayan", "suit & weapon", "bubble"),
    "Baltanos": ("Deriso", "suit & weapon", "Colonia"), "Eleanor Bresa": ("Desy", "suit & weapon", "Colonia"),
    "Rosa Dayette": ("Kojeara", "suit & weapon", "Colonia"), "Yi Shen": ("Einheriar", "suit & weapon", "Colonia"),
}


def engineer_system(name):
    """(system, kind, region) of an engineer by any spelling of the name ("Tod 'The Blaster' McQuinn"), or None."""
    want = _plain(name)
    return next((v for k, v in ENGINEER_SYSTEMS.items() if _plain(k) == want), None)


def engineer_list(known):
    """Every engineer the table knows, and any other the journal names: [{name, system, kind, region, progress,
    rank}], the ship engineers first, then by name. known: engineers()."""
    mine = {_plain(k): (k, v) for k, v in (known or {}).items()}
    out = []
    for name, (system, kind, region) in ENGINEER_SYSTEMS.items():
        st = (mine.pop(_plain(name), (None, {}))[1]) or {}
        out.append({"name": name, "system": system, "kind": kind, "region": region,
                    "progress": st.get("progress"), "rank": st.get("rank")})
    for name, st in mine.values():   # one the table does not have yet: listed, no system to go to
        out.append({"name": name, "system": None, "kind": None, "region": None, "progress": st.get("progress"), "rank": st.get("rank")})
    return sorted(out, key=lambda e: (e["kind"] != "ship", e["name"].lower()))


def blueprints(counts, known=None, name=None, rows=None):
    """Every blueprint with what each grade takes against the materials you hold: [{id, module, name, grades:
    [{grade, materials: [{id, name, need, have}], rolls (how many times you could craft it now), engineers:
    [{name, progress, rank, ready (unlocked far enough for this grade)}]}]}]. counts: {material id: held};
    known: engineers(); name: fn(material id) -> its name."""
    known = {_plain(k): v for k, v in (known or {}).items()}
    name = name or (lambda mid: materials.MATERIALS.get(mid, (mid,))[0])
    out = []
    for b in load_blueprints() if rows is None else rows:
        grades = []
        for g, v in sorted(b["grades"].items()):
            need = [{"id": mid, "name": name(mid), "need": n, "have": int(counts.get(mid, 0))} for mid, n in v["materials"].items()]
            who = []
            for e in v.get("engineers") or []:
                st = known.get(_plain(e)) or {}
                rank = st.get("rank")
                # an engineer crafts up to one grade past the rank reached (rank 0: grade 1)
                who.append({"name": e, "progress": st.get("progress"), "rank": rank, "system": (engineer_system(e) or (None,))[0],
                            "ready": st.get("progress") == "Unlocked" and (rank or 0) + 1 >= int(g)})
            by_kind = {kind: [x for x in who if x["name"] in names] for kind, names in (v.get("by_kind") or {}).items()}
            grades.append({"grade": int(g), "materials": need, "engineers": who, "by_kind": by_kind,
                           "rolls": min((m["have"] // m["need"] for m in need if m["need"]), default=0)})
        out.append({"id": b["id"], "module": b["module"], "name": b["name"], "grades": grades, "for": b.get("for") or []})
    return out


def engineering(dirs, material_state, days=INVENTORY_DAYS, now=None):
    known = engineers(jscan.events(dirs, ("EngineerProgress",), days, now))
    counts = (material_state or {}).get("counts") or {}
    return {"blueprints": blueprints(counts, known, lambda mid: materials.display_name(material_state, mid)),
            "engineers": engineer_list(known)}


# ---- missions ----

MISSION_EVENTS = ("Missions", "MissionAccepted", "MissionCompleted", "MissionFailed", "MissionAbandoned",
                  "MissionRedirected", "CargoDepot")
MISSION_SOON_S = 1800   # an expiry within this is marked


def missions(events, now=None):
    """The missions you hold, the soonest to expire first: [{id, name, faction, system, station, target, commodity,
    count, delivered, reward, expiry (ISO or None), expires_in (s; None without one), soon, expired, wing,
    passengers, redirected, influence, reputation}]. The login's Missions line says which are still active (one the
    journals here never saw accepted is listed by its name alone); accept, redirect, a cargo depot, and the endings
    follow in order."""
    now = time.time() if now is None else now
    held = {}
    for e in events:
        name, mid = e["event"], e.get("MissionID")
        if name == "Missions":
            active = {m.get("MissionID"): m for m in e.get("Active") or [] if isinstance(m, dict)}
            at = ts_seconds(e["timestamp"])
            for k in [k for k in held if k not in active]:
                del held[k]
            for k, m in active.items():
                row = held.setdefault(k, _mission({"MissionID": k, "Name": m.get("Name")}))
                if not row["expiry"] and isinstance(m.get("Expires"), (int, float)) and m["Expires"] > 0:
                    row["expiry"] = iso_ts(at + m["Expires"])
                row["passengers"] = row["passengers"] or bool(m.get("PassengerMission"))
        elif mid is None:
            continue
        elif name == "MissionAccepted":
            held[mid] = _mission(e)
        elif name in ("MissionCompleted", "MissionFailed", "MissionAbandoned"):
            held.pop(mid, None)
        elif mid in held and name == "MissionRedirected":
            held[mid].update(system=e.get("NewDestinationSystem") or held[mid]["system"],
                             station=e.get("NewDestinationStation") or held[mid]["station"], redirected=True)
        elif mid in held and name == "CargoDepot":
            if isinstance(e.get("TotalItemsToDeliver"), int):
                held[mid].update(count=e["TotalItemsToDeliver"], delivered=e.get("ItemsDelivered") or 0)
    out = []
    for row in held.values():
        left = ts_seconds(row["expiry"]) - now if row["expiry"] else None
        out.append(dict(row, expires_in=None if left is None else int(left), soon=left is not None and 0 <= left <= MISSION_SOON_S,
                        expired=left is not None and left < 0))
    out.sort(key=lambda r: (r["expires_in"] is None, r["expires_in"] or 0, r["name"] or ""))
    return out


def _mission(e):
    name = e.get("LocalisedName") or re.sub(r"_name$", "", re.sub(r"^Mission_", "", str(e.get("Name") or "?"))).replace("_", " ")
    return {"id": e.get("MissionID"), "name": name, "faction": e.get("Faction"), "system": e.get("DestinationSystem"),
            "station": e.get("DestinationStation") or e.get("DestinationSettlement"),
            "target": _text(e, "Target") or e.get("TargetFaction"), "commodity": _text(e, "Commodity"),
            "count": e.get("Count") if e.get("Count") is not None else e.get("KillCount") or e.get("PassengerCount"),
            "delivered": None, "reward": e.get("Reward"), "expiry": e.get("Expiry"), "wing": bool(e.get("Wing")),
            "passengers": e.get("PassengerCount") is not None, "redirected": False,
            "influence": e.get("Influence"), "reputation": e.get("Reputation"), "accepted": e.get("timestamp")}


def missions_now(dirs, days=MISSION_DAYS, now=None):
    return {"missions": missions(jscan.events(dirs, MISSION_EVENTS, days, now), now)}


# ---- sessions: combat and mining, from login to logout ----

SESSION_EVENTS = ("LoadGame", "Shutdown", "Bounty", "FactionKillBond", "PVPKill", "CapShipBond", "Died", "Interdicted",
                  "RedeemVoucher", "MiningRefined", "ProspectedAsteroid", "AsteroidCracked", "LaunchDrone", "MarketSell")
_KILLS = ("Bounty", "FactionKillBond", "PVPKill", "CapShipBond")
_MINING = ("MiningRefined", "ProspectedAsteroid", "AsteroidCracked")


def _span(first, last):
    """Seconds between two ISO stamps, a minute at least (a rate over one event means nothing)."""
    return max(60, ts_seconds(last) - ts_seconds(first)) if first and last else None


def sessions(events):
    """The play sessions with fighting or mining in them, newest first; each from a LoadGame to the next (or a
    Shutdown): {start, end, commander, ship, combat: {kills, bounties, bonds, by_ship, deaths, interdicted,
    redeemed, seconds, per_hour} or None, mining: {tons, refined: {name: t}, prospected, content: {High, Medium,
    Low}, motherlodes, cracked, prospectors, collectors, sold, seconds, per_hour} or None}."""
    out, cur = [], None

    def close():
        if cur and (cur["_c"]["n"] or cur["_m"]["n"]):
            out.append(_session(cur))
    for e in events:
        name = e["event"]
        if name == "LoadGame" or cur is None:
            close()
            cur = {"start": e["timestamp"], "end": e["timestamp"], "commander": e.get("Commander") if name == "LoadGame" else None,
                   "ship": (_text(e, "Ship") if name == "LoadGame" else None),
                   "_c": {"n": 0, "kills": 0, "bounties": 0, "bonds": 0, "by_ship": {}, "deaths": 0, "interdicted": 0,
                          "redeemed": 0, "first": None, "last": None},
                   "_m": {"n": 0, "refined": {}, "prospected": 0, "content": {}, "motherlodes": 0, "cracked": 0,
                          "prospectors": 0, "collectors": 0, "sold": 0, "first": None, "last": None}}
            if name == "LoadGame":
                continue
        cur["end"] = e["timestamp"]
        c, m = cur["_c"], cur["_m"]
        if name in _KILLS:
            c["n"] += 1
            c["kills"] += 1
            c["first"], c["last"] = c["first"] or e["timestamp"], e["timestamp"]
            if name == "Bounty":
                c["bounties"] += e.get("TotalReward") or sum((r.get("Reward") or 0) for r in e.get("Rewards") or [] if isinstance(r, dict)) \
                    or e.get("Reward") or 0
                ship = _text(e, "Target") or "?"
                c["by_ship"][ship] = c["by_ship"].get(ship, 0) + 1
            elif name in ("FactionKillBond", "CapShipBond"):
                c["bonds"] += e.get("Reward") or 0
        elif name == "Died":
            c["n"] += 1
            c["deaths"] += 1
        elif name == "Interdicted":
            c["interdicted"] += 1
        elif name == "RedeemVoucher" and e.get("Type") in ("bounty", "CombatBond"):
            c["redeemed"] += e.get("Amount") or 0
        elif name in _MINING:
            m["n"] += 1
            m["first"], m["last"] = m["first"] or e["timestamp"], e["timestamp"]
            if name == "MiningRefined":
                what = _text(e, "Type") or "?"
                m["refined"][what] = m["refined"].get(what, 0) + 1
            elif name == "AsteroidCracked":
                m["cracked"] += 1
            else:
                m["prospected"] += 1
                level = re.sub(r"^\$AsteroidMaterialContent_|;$", "", str(e.get("Content") or "?"))
                m["content"][level] = m["content"].get(level, 0) + 1
                m["motherlodes"] += bool(e.get("MotherlodeMaterial"))
        elif name == "LaunchDrone":
            if e.get("Type") == "Prospector":
                m["prospectors"] += 1
            elif e.get("Type") == "Collection":
                m["collectors"] += 1
        elif name == "MarketSell" and m["refined"] and (_text(e, "Type") or "").lower() in {k.lower() for k in m["refined"]}:
            m["sold"] += e.get("TotalSale") or 0
        elif name == "Shutdown":
            close()
            cur = None
    close()
    return out[::-1][:SESSIONS_MAX]


def _session(s):
    c, m = s["_c"], s["_m"]
    combat = mining = None
    if c["n"]:
        secs = _span(c["first"], c["last"])
        combat = {"kills": c["kills"], "bounties": c["bounties"], "bonds": c["bonds"], "deaths": c["deaths"],
                  "interdicted": c["interdicted"], "redeemed": c["redeemed"], "seconds": secs,
                  "by_ship": dict(sorted(c["by_ship"].items(), key=lambda kv: (-kv[1], kv[0]))),
                  "per_hour": round(c["kills"] * 3600 / secs, 1) if secs and c["kills"] > 1 else None}
    if m["n"]:
        secs, tons = _span(m["first"], m["last"]), sum(m["refined"].values())
        mining = {"tons": tons, "refined": dict(sorted(m["refined"].items(), key=lambda kv: (-kv[1], kv[0]))),
                  "prospected": m["prospected"], "content": m["content"], "motherlodes": m["motherlodes"],
                  "cracked": m["cracked"], "prospectors": m["prospectors"], "collectors": m["collectors"], "sold": m["sold"],
                  "seconds": secs, "per_hour": round(tons * 3600 / secs, 1) if secs and tons > 1 else None}
    return {"start": s["start"], "end": s["end"], "commander": s["commander"], "ship": s["ship"], "combat": combat, "mining": mining}


def totals(rows):
    """The listed sessions summed: {combat: {sessions, kills, bounties, bonds, deaths}, mining: {sessions, tons,
    prospected, sold}}."""
    c, m = [r["combat"] for r in rows if r["combat"]], [r["mining"] for r in rows if r["mining"]]
    return {"combat": {"sessions": len(c), **{k: sum(x[k] for x in c) for k in ("kills", "bounties", "bonds", "deaths")}},
            "mining": {"sessions": len(m), **{k: sum(x[k] for x in m) for k in ("tons", "prospected", "sold")}}}


def sessions_now(dirs, days=SESSION_DAYS, now=None):
    rows = sessions(jscan.events(dirs, SESSION_EVENTS, days, now))
    return {"sessions": rows, "totals": totals(rows), "days": days}


# ---- the commander: ranks with what the next one takes, credits and assets, the fleet, the career ----

PROFILE_EVENTS = ("LoadGame", "Rank", "Progress", "Promotion", "Statistics", "Reputation", "Powerplay", "SquadronStartup",
                  "CarrierStats", "StoredShips", "StoredModules", "Loadout")
_PILOT = ("Elite", "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V")
# the journal's rank keys in the order shown: (title, the ranks' names by number)
RANKS = (
    ("Combat", "Combat", ("Harmless", "Mostly Harmless", "Novice", "Competent", "Expert", "Master", "Dangerous", "Deadly") + _PILOT),
    ("Trade", "Trade", ("Penniless", "Mostly Penniless", "Peddler", "Dealer", "Merchant", "Broker", "Entrepreneur", "Tycoon") + _PILOT),
    ("Explore", "Exploration", ("Aimless", "Mostly Aimless", "Scout", "Surveyor", "Trailblazer", "Pathfinder", "Ranger", "Pioneer") + _PILOT),
    ("Exobiologist", "Exobiology", ("Directionless", "Mostly Directionless", "Compiler", "Collector", "Cataloguer", "Taxonomist",
                                    "Ecologist", "Geneticist") + _PILOT),
    ("Soldier", "Mercenary", ("Defenceless", "Mostly Defenceless", "Rookie", "Soldier", "Gunslinger", "Warrior", "Gladiator",
                              "Deadeye") + _PILOT),
    ("CQC", "CQC", ("Helpless", "Mostly Helpless", "Amateur", "Semi Professional", "Professional", "Champion", "Hero", "Legend") + _PILOT),
    ("Federation", "Federal Navy", ("None", "Recruit", "Cadet", "Midshipman", "Petty Officer", "Chief Petty Officer", "Warrant Officer",
                                    "Ensign", "Lieutenant", "Lieutenant Commander", "Post Commander", "Post Captain", "Rear Admiral",
                                    "Vice Admiral", "Admiral")),
    ("Empire", "Imperial Navy", ("None", "Outsider", "Serf", "Master", "Squire", "Knight", "Lord", "Baron", "Viscount", "Count", "Earl",
                                 "Marquis", "Duke", "Prince", "King")),
)
# What each rank up to Elite takes, in credits earned in that career (the community's figures, as the game's Codex
# and the wikis give them; Frontier publishes none): what is left to the next rank is the step times the share of it
# still to go. Combat, Mercenary, CQC and the navies go by points nobody outside can count: their percentage only.
RANK_CREDITS = {
    "Trade": (0, 5_000, 100_000, 800_000, 3_700_000, 30_000_000, 140_000_000, 390_000_000, 1_050_000_000),
    "Explore": (0, 40_000, 270_000, 1_140_000, 4_200_000, 10_000_000, 35_000_000, 116_000_000, 320_000_000),
    "Exobiologist": (0, 2_000, 50_000, 250_000, 1_000_000, 5_000_000, 15_000_000, 50_000_000, 150_000_000),
}
RANK_EARNED_BY = {"Trade": "trade profit", "Explore": "exploration data sold", "Exobiologist": "exobiology data sold"}
# the career figures shown, from the login's Statistics: (section, key, label, kind)
CAREER = (
    ("Exploration", "Time_Played", "Time played", "time"), ("Exploration", "Systems_Visited", "Systems visited", "n"),
    ("Exploration", "Total_Hyperspace_Jumps", "Jumps", "n"), ("Exploration", "Total_Hyperspace_Distance", "Distance jumped", "ly"),
    ("Exploration", "Greatest_Distance_From_Start", "Farthest from the start", "ly"),
    ("Exploration", "Exploration_Profits", "Exploration profits", "cr"), ("Exobiology", "Organic_Data_Profits", "Exobiology profits", "cr"),
    ("Trading", "Market_Profits", "Trade profits", "cr"), ("Mining", "Mining_Profits", "Mining profits", "cr"),
    ("Combat", "Bounty_Hunting_Profit", "Bounty profits", "cr"), ("Combat", "Combat_Bond_Profits", "Combat bond profits", "cr"),
    ("Combat", "Bounties_Claimed", "Bounties claimed", "n"), ("Bank_Account", "Insurance_Claims", "Insurance claims", "n"),
    ("Bank_Account", "Spent_On_Ships", "Spent on ships", "cr"), ("Bank_Account", "Spent_On_Outfitting", "Spent on outfitting", "cr"),
)


def rank_rows(rank, progress):
    """The ranks as rows: {key, title, rank, name, progress (% of the way to the next, None at the top or unknown),
    next (its name, None at the top), to_next (credits still to earn in that career, about; None where the game
    counts points), earned_by}."""
    out = []
    for key, title, names in RANKS:
        n = (rank or {}).get(key)
        if not isinstance(n, int):
            continue
        top = n >= len(names) - 1
        pct = (progress or {}).get(key)
        pct = None if top or not isinstance(pct, (int, float)) else max(0, min(100, pct))
        steps = RANK_CREDITS.get(key)
        left = None
        if steps and pct is not None and n + 1 < len(steps):
            left = int(round((steps[n + 1] - steps[n]) * (100 - pct) / 100))
        out.append({"key": key, "title": title, "rank": n, "name": names[n] if 0 <= n < len(names) else str(n), "progress": pct,
                    "next": None if top or n + 1 >= len(names) else names[n + 1], "to_next": left,
                    "earned_by": RANK_EARNED_BY.get(key) if left is not None else None})
    return out


def profile(events):
    """The commander as the journals last said: {commander, ts (the login it is from), credits, loan (both at that
    login), ranks (rank_rows), reputation {Federation, Empire, Alliance, Independent: %}, power {name, rank, merits},
    squadron, assets {wealth (the game's own total at login), fleet (your ships' value), ships, modules (stored
    modules' value), carrier (its balance)}, fleet (ships(): the one you fly first), carrier {name, callsign,
    balance, fuel}, career [{label, value, kind}]}. None before any login is on record."""
    login = _last(events, "LoadGame")
    if not login:
        return None
    rank, prog = {}, {}
    last = {}
    for e in events:
        name = e["event"]
        if name == "Rank":
            rank = {k: v for k, v in e.items() if isinstance(v, int) and not isinstance(v, bool)}
        elif name == "Progress":
            prog = {k: v for k, v in e.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        elif name == "Promotion":
            for k, v in e.items():
                if isinstance(v, int) and not isinstance(v, bool) and k in rank:
                    rank[k], prog[k] = v, 0
        elif name in ("Statistics", "Reputation", "Powerplay", "SquadronStartup", "CarrierStats"):
            last[name] = e
    stats = last.get("Statistics") or {}
    bank = stats.get("Bank_Account") if isinstance(stats.get("Bank_Account"), dict) else {}
    fleet = ships(events)["ships"]
    stored = stored_modules(events)["modules"]
    rep, pp, sq, cs = (last.get(k) or {} for k in ("Reputation", "Powerplay", "SquadronStartup", "CarrierStats"))
    finance = cs.get("Finance") if isinstance(cs.get("Finance"), dict) else {}
    career = []
    for section, key, label, kind in CAREER:
        v = (stats.get(section) or {}).get(key) if isinstance(stats.get(section), dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            career.append({"label": label, "value": v, "kind": kind})
    return {
        "commander": login.get("Commander"), "ts": login["timestamp"], "credits": login.get("Credits"), "loan": login.get("Loan") or 0,
        "ranks": rank_rows(rank, prog),
        "reputation": {k: round(rep[k], 1) for k in ("Federation", "Empire", "Alliance", "Independent") if isinstance(rep.get(k), (int, float))},
        "power": {"name": pp.get("Power"), "rank": pp.get("Rank"), "merits": pp.get("Merits")} if pp.get("Power") else None,
        "squadron": sq.get("SquadronName"),
        "assets": {"wealth": bank.get("Current_Wealth"), "ships": len(fleet), "fleet": sum(s["value"] or 0 for s in fleet) or None,
                   "modules": sum(m["value"] or 0 for m in stored) or None, "carrier": finance.get("CarrierBalance")},
        "fleet": sorted(fleet, key=lambda s: (not s["current"], -(s["value"] or 0))),
        "carrier": {"name": cs.get("Name"), "callsign": cs.get("Callsign"), "balance": finance.get("CarrierBalance"),
                    "fuel": cs.get("FuelLevel")} if cs.get("Callsign") else None,
        "career": career,
    }


def profile_now(dirs, days=INVENTORY_DAYS, now=None):
    return {"profile": profile(jscan.events(dirs, PROFILE_EVENTS, days, now))}


# ---- the engineers' systems: where they lie, and how far from you ----

PLACES_KEY = "engineer_places"   # meta: {system: [x, y, z]}, kept for good (the workshops do not move)
PLACES_GAP_S = 0.3               # s between two Spansh lookups of a system not known here


def _places(db):
    row = db.execute("SELECT value FROM meta WHERE key=?", (PLACES_KEY,)).fetchone()
    try:
        got = json.loads(row["value"]) if row else {}
    except (ValueError, TypeError):
        got = {}
    return got if isinstance(got, dict) else {}


def ly(a, b):
    return round(sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5, 1)


async def engineer_distances(state, gap=PLACES_GAP_S):
    """GET /api/commander/engineer_distances: {from (where you are), distances {system: ly}, missing [systems not
    found], error}. Each system's place is found once: a system known here (your visits, bookmarks, Spansh's cached
    records: State.find_local), else Spansh by its exact name; then kept (meta engineer_places). Without a position
    yet, no distances."""
    import asyncio
    places, asked, err = _places(state.db), False, None
    for system in sorted({v[0] for v in ENGINEER_SYSTEMS.values()}):
        if system in places:
            continue
        local = state.find_local(system)
        if local and None not in local[2:5]:
            places[system] = list(local[2:5])
            continue
        if err:
            continue   # Spansh failed once: the rest only from what is known here, Spansh asked again next time
        try:
            if asked:
                await asyncio.sleep(gap)
            asked = True
            rec = await state.spansh.system_record(system)
        except Exception as e:   # Spansh down or slow
            err = f"Spansh could not be asked where every engineer is ({type(e).__name__})"
            continue
        if rec and None not in (rec.get("x"), rec.get("y"), rec.get("z")):
            places[system] = [rec["x"], rec["y"], rec["z"]]
    if places != _places(state.db):
        state.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (PLACES_KEY, json.dumps(places)))
        state.db.commit()
    pos = state.journals.pos
    here = (pos["x"], pos["y"], pos["z"]) if pos and None not in (pos.get("x"), pos.get("y"), pos.get("z")) else None
    systems = sorted({v[0] for v in ENGINEER_SYSTEMS.values()})
    return {"from": pos.get("name") if here else None,
            "distances": {s: ly(here, places[s]) for s in systems if here and s in places},
            "missing": [s for s in systems if s not in places], "error": err}


# ---- the ship you fly, as the Engineering tab's parts: "Load my ship" ----

# a module's journal symbol (Loadout's Item, lower case) -> the Engineering tab's parts it is: the blueprint table's module
# names, and for a blueprint shared by several kinds of module the kind's name. The first prefix that matches wins (the
# longer ones first where one begins another: pulselaserburst before pulselaser).
SHIP_PARTS = (
    ("int_powerplant", ("Power plant",)), ("int_hyperdrive", ("Frame shift drive",)), ("int_engine", ("Thrusters",)),
    ("int_powerdistributor", ("Power distributor",)), ("int_sensors", ("Sensors",)), ("int_lifesupport", ("Life support",)),
    ("int_shieldcellbank", ("Shield cell bank",)), ("int_hullreinforcement", ("Hull reinforcement",)),
    ("int_fuelscoop", ("Fuel scoop",)), ("int_refinery", ("Refinery",)), ("int_detailedsurfacescanner", ("Detailed surface scanner",)),
    ("int_fsdinterdictor", ("Frame shift drive interdictor",)), ("int_repairer", ("Auto field maintenance unit",)),
    ("int_dronecontrol_collection", ("Collector limpet controller",)), ("int_dronecontrol_fueltransfer", ("Fuel transfer limpet controller",)),
    ("int_dronecontrol_resourcesiphon", ("Hatch breaker limpet controller",)), ("int_dronecontrol_prospector", ("Prospector limpet controller",)),
    ("hpt_shieldbooster", ("Shield booster",)),
    ("hpt_chafflauncher", ("Chaff launcher", "chaff launchers")), ("hpt_plasmapointdefence", ("Point defence", "point defence")),
    ("hpt_heatsinklauncher", ("heat sink launchers",)), ("hpt_causticsinklauncher", ("caustic sink launchers",)),
    ("hpt_electroniccountermeasure", ("electronic countermeasures",)), ("hpt_cargoscanner", ("manifest scanners",)),
    ("hpt_cloudscanner", ("frame shift wake scanners",)), ("hpt_crimescanner", ("kill warrant scanners",)),
    ("hpt_pulselaserburst", ("burst lasers",)), ("hpt_pulselaser", ("pulse lasers",)), ("hpt_beamlaser", ("beam lasers",)),
    ("hpt_multicannon", ("multi-cannons",)), ("hpt_cannon", ("cannons",)), ("hpt_slugshot", ("fragment cannons",)),
    ("hpt_plasmaaccelerator", ("plasma accelerators",)), ("hpt_railgun", ("rail guns",)),
    ("hpt_dumbfiremissilerack", ("missile racks",)), ("hpt_basicmissilerack", ("missile racks",)), ("hpt_drunkmissilerack", ("missile racks",)),
    ("hpt_minelauncher", ("mine launchers",)), ("hpt_advancedtorppylon", ("torpedo pylons",)),
)


def ship_part(item):
    """The parts a module is, by its journal symbol: a shield generator by its kind (bi-weave _fast, prismatic _strong),
    bulkheads by "_armour_"; () for one the blueprint table has nothing for (cargo racks, the cockpit, a paint job)."""
    it = str(item or "").lower()
    if it.startswith("int_shieldgenerator"):
        return ("bi-weave shield generators",) if it.endswith("_fast") else ("prismatic shield generators",) if it.endswith("_strong") \
            else ("shield generators",)
    if "_armour_" in it:
        return ("Bulkheads",)
    return next((parts for prefix, parts in SHIP_PARTS if it.startswith(prefix)), ())


def ship_parts(loadout):
    """The ship of a Loadout as the Engineering tab's picks: {ship: {name, type}, modules: [{slot, name, parts,
    blueprint_id, blueprint, level, quality, experimental}] (only modules the table has a part for), parts: the
    parts, grades: ["<blueprint id>|<level>"] of the engineered modules}. Experimental effects are named, not picked:
    the blueprint table has none."""
    mods, parts, grades = [], [], []
    for m in (loadout or {}).get("Modules") or []:
        if not isinstance(m, dict):
            continue
        these = ship_part(m.get("Item"))
        if not these:
            continue
        e = m.get("Engineering") if isinstance(m.get("Engineering"), dict) else {}
        bid, level = e.get("BlueprintName"), e.get("Level") if isinstance(e.get("Level"), int) else None
        name = shipinfo.module_name(m.get("Item"))[0]
        mods.append({"slot": m.get("Slot"), "name": name, "parts": list(these), "blueprint_id": bid,
                     "blueprint": shipinfo.engineering(e)["blueprint"] if e else None, "level": level,
                     "quality": e.get("Quality"), "experimental": e.get("ExperimentalEffect_Localised") or None})
        parts += [p for p in these if p not in parts]
        if bid and level and f"{bid}|{level}" not in grades:
            grades.append(f"{bid}|{level}")
    return {"ship": {"name": (loadout or {}).get("ShipName") or None, "type": (loadout or {}).get("Ship")} if loadout else None,
            "modules": mods, "parts": parts, "grades": grades}


def ship_parts_now(dirs, state):
    """GET /api/commander/ship_parts: the ship you fly (its newest Loadout, as the Ship view reads it)."""
    sid = (getattr(state.journals, "ship", None) or {}).get("ship_id")
    ev = (shipinfo.latest_loadout(dirs, sid) if sid is not None else None) or shipinfo.latest_loadout(dirs)
    return ship_parts(ev)


# ---- the engineers' trip: which engineers cover the picks for the fewest light years (outrider/engtour.py) ----

def engineer_progress(dirs, days=INVENTORY_DAYS, now=None):
    """{engineer: {progress, rank}} from the journals' EngineerProgress lines (reads files: off the event loop)."""
    return engineers(jscan.events(dirs, ("EngineerProgress",), days, now))


def tour_body_problem(body):
    """What is wrong with a POST /api/commander/engineer_tour body, or None."""
    if not isinstance(body, dict) or not isinstance(body.get("requirements"), list):
        return "requirements: a list of {label, grade, engineers}"
    for r in body["requirements"]:
        if not (isinstance(r, dict) and isinstance(r.get("label"), str) and isinstance(r.get("engineers"), list)
                and all(isinstance(e, str) for e in r["engineers"])
                and (r.get("grade") is None or (isinstance(r["grade"], int) and not isinstance(r["grade"], bool) and 1 <= r["grade"] <= 5))):
            return "requirements: each {label: text, grade: 1 to 5 or null, engineers: [names]}"
    for k in ("include_locked", "return_carrier"):
        if k in body and not isinstance(body[k], bool):
            return f"{k}: true or false"
    if len(body["requirements"]) > 60:
        return "requirements: 60 at most"
    return None


async def engineer_tour(state, body, dirs):
    """POST /api/commander/engineer_tour {requirements, include_locked?, return_carrier?}: the trip (engtour.plan) from
    where you are, each stop with its system; with return_carrier, ending at your fleet carrier. ({...}, status)."""
    import asyncio
    from . import engtour
    problem = tour_body_problem(body)
    if problem:
        return {"error": problem}, 400
    pos = state.journals.pos
    if not pos or None in (pos.get("x"), pos.get("y"), pos.get("z")):
        return {"error": "no position yet: after your first jump"}, 409
    places = (await engineer_distances(state)) and _places(state.db)
    at = {name: places[v[0]] for name, v in ENGINEER_SYSTEMS.items() if v[0] in places}
    end, carrier = None, None
    if body.get("return_carrier"):
        summary = state.carrier_summary() if hasattr(state, "carrier_summary") else None
        c = getattr(state.journals, "carrier", None) or {}
        if not summary or c.get("x") is None:
            return {"error": "no fleet carrier on record, or not where it is yet"}, 409
        end, carrier = (c["x"], c["y"], c["z"]), {"name": summary.get("name"), "system": summary.get("system")}
    progress = await asyncio.get_running_loop().run_in_executor(None, engineer_progress, dirs())
    out = engtour.plan(body["requirements"], progress, at, (pos["x"], pos["y"], pos["z"]), end,
                       include_locked=bool(body.get("include_locked")))
    for s in out["stops"]:
        s["system"] = (engineer_system(s["engineer"]) or (None,))[0]
    return dict(out, **{"from": pos.get("name"), "carrier": carrier}), 200


# ---- the server's routes ----

def add_routes(app, state, dirs):
    """GET /api/commander/<part>: each reads journal files, so each runs off the event loop. dirs: fn() -> the
    live journal folders."""
    import asyncio
    from aiohttp import web

    def route(part, fn):
        async def view(_):
            try:
                return web.json_response(await asyncio.get_running_loop().run_in_executor(None, fn))
            except (OSError, ValueError, KeyError, TypeError) as e:   # a journal line nobody expected: say so, do not fail
                return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=500)
        app.router.add_get(f"/api/commander/{part}", view)
    route("profile", lambda: profile_now(dirs()))
    route("inventory", lambda: inventory(dirs()))
    route("engineering", lambda: engineering(dirs(), state.journals.materials))
    route("missions", lambda: missions_now(dirs()))
    route("sessions", lambda: sessions_now(dirs()))
    route("ship_parts", lambda: ship_parts_now(dirs(), state))

    async def distances(_):
        return web.json_response(await engineer_distances(state))
    app.router.add_get("/api/commander/engineer_distances", distances)

    async def tour(request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        out, status = await engineer_tour(state, body, dirs)
        return web.json_response(out, status=status)
    app.router.add_post("/api/commander/engineer_tour", tour)

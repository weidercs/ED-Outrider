"""This fork: suit and weapon engineering for Commander → Engineering → Suits & weapons (static/fork.js, forkGearHtml):
each suit's and weapon's upgrades (G2 to G5, bought at Pioneer Supplies) and modifications (an engineer's), what each
takes against your ship locker, the engineers offering each mod and where you stand with them, and the suits and
weapons you own with their grade and mods. The table is resources/gear_blueprints.json (scripts/build_gear_blueprints.py).

    gear(locker_snap, known, suit_state)   # GET /api/engineers/gear (outrider/engineers.py)

A suit or weapon takes one mod per grade above G1 (G5: four). The game never takes a mod back off.
"""
import json
import os
import re

from .commander import _mod

GEAR_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "gear_blueprints.json")
_TABLE = {}


def _plain(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def load(path=GEAR_FILE):
    """resources/gear_blueprints.json (read once per file time), None when it cannot be read."""
    try:
        stamp = os.path.getmtime(path)
        if _TABLE.get("key") != (path, stamp):
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            _TABLE.update(key=(path, stamp), doc={k: doc[k] for k in ("items", "mods", "materials")})
        return _TABLE["doc"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def locker_counts(snap, materials):
    """{material symbol: count you hold} from the ship locker (commander.locker_apply's snap), a mission's own left
    out (it is not yours to use). A line is matched by its journal name, else by its English name (materials: the
    table's {symbol: {name}})."""
    by_name = {_plain(v["name"]): k for k, v in (materials or {}).items()}
    out = {}
    for key in ("Items", "Components", "Data"):
        for it in (snap or {}).get(key) or []:
            if not isinstance(it, dict) or not isinstance(it.get("Count"), int) or it.get("MissionID") is not None:
                continue
            sym = str(it.get("Name") or "").lower()
            if sym not in (materials or {}):
                sym = by_name.get(_plain(it.get("Name_Localised")), sym)
            out[sym] = out.get(sym, 0) + it["Count"]
    return out


def item_of(symbol, items):
    """The table's suit or weapon for a journal symbol ("utilitysuit_class3", "wpn_m_sniper_plasma_charged"), or None."""
    s = re.sub(r"_class\d$", "", str(symbol or "").lower())
    return next((it for it in items if it["symbol"] == s), None)


def owned(suit_state, doc):
    """The suits and weapons in your loadouts (commander.suit_apply's), each once (by its id): {item name: [{loadout,
    class, mods: [names]}]}; a piece the table does not know is left out. A mod is named as the table names it, else
    in words (commander._mod)."""
    names = {m["symbol"]: m["name"] for m in doc["mods"]}
    out, seen = {}, set()

    def add(symbol, pid, cls, mods, loadout):
        it = item_of(symbol, doc["items"])
        key = (it and it["name"], pid if pid is not None else (loadout, symbol))
        if not it or key in seen:
            return
        seen.add(key)
        out.setdefault(it["name"], []).append({"loadout": loadout, "class": cls,
                                               "mods": [names.get(str(m).lower()) or _mod(m) for m in mods or []]})
    for e in sorted((suit_state or {}).values(), key=lambda e: e.get("ts") or "", reverse=True):
        add(e.get("suit"), e.get("suit_id"), e.get("class"), e.get("mods"), e.get("loadout"))
        for w in e.get("weapons") or []:
            add(w.get("name"), w.get("id"), w.get("class"), w.get("mods"), e.get("loadout"))
    return out


def _need(materials, counts, table):
    need = [{"id": k, "name": table.get(k, {}).get("name") or k, "kind": table.get(k, {}).get("kind"), "need": n,
             "have": int(counts.get(k, 0))} for k, n in materials.items()]
    return need, min((m["have"] // m["need"] for m in need if m["need"]), default=0)


def gear(locker_snap, known, suit_state):
    """GET /api/engineers/gear: {items: [{name, kind, family, owned: [{loadout, class, mods}], upgrades: [{grade,
    materials: [{id, name, kind (Goods, Assets, Data), need, have}], rolls}], mods: [{name, materials, rolls,
    engineers: [{name, progress, ready}]}]}], unreadable}. A suit lists the suit mods, a weapon the weapon mods at its
    family's cost. known: EngineerProgress (commander.engineer_apply's)."""
    doc = load()
    if doc is None:
        return {"items": [], "unreadable": True}
    counts = locker_counts(locker_snap, doc["materials"])
    status = {_plain(k): v or {} for k, v in (known or {}).items()}
    mine = owned(suit_state, doc)
    items = []
    for it in doc["items"]:
        ups = []
        for g, mats in sorted(it["upgrades"].items()):
            need, rolls = _need(mats, counts, doc["materials"])
            ups.append({"grade": int(g), "materials": need, "rolls": rolls})
        mods = []
        for m in doc["mods"]:
            if m["kind"] != it["kind"] or (m["family"] and m["family"] != it["family"]):
                continue
            need, rolls = _need(m["materials"], counts, doc["materials"])
            who = [{"name": e, "progress": status.get(_plain(e), {}).get("progress"),
                    "ready": status.get(_plain(e), {}).get("progress") == "Unlocked"} for e in m["engineers"]]
            mods.append({"name": m["name"], "materials": need, "rolls": rolls, "engineers": who})
        items.append({"name": it["name"], "kind": it["kind"], "family": it["family"], "owned": mine.get(it["name"], []),
                      "upgrades": ups, "mods": mods})
    return {"items": items, "unreadable": False}

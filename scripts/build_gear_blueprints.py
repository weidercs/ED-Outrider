#!/usr/bin/env python3
"""This fork: build resources/gear_blueprints.json (Commander → Engineering → Suits & weapons, outrider/gear.py) from
EDEngineer's data (MIT), fetched at a pinned commit: Resources/Data/blueprints.json (each suit's and weapon's upgrade
G2 to G5 and each modification, with what it takes and the engineers offering it) and entryData.json (each Odyssey
material's journal name and kind). EDEngineer's data predates the Colonia engineers: COLONIA adds them (the ED Field
Manual's engineer table, edfieldmanual.com/wiki/Engineers, read 2026-10-18).

    .venv/bin/python scripts/build_gear_blueprints.py            (two downloads, about 1 MB)

It stops, writing nothing, on a material, a suit, a weapon or a modification it cannot name.
"""
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "resources", "gear_blueprints.json")
REPO = "https://github.com/msarilar/EDEngineer"
COMMIT = "2cadd66d19509221ea2e5c2c132b8f04dc8167c8"   # master, "Merge pull request #747 from seedubya/master"
COMMIT_DATE = "2024-03-22"
FILES = ("EDEngineer/Resources/Data/blueprints.json", "EDEngineer/Resources/Data/entryData.json")
URL = "https://raw.githubusercontent.com/msarilar/EDEngineer/{commit}/{path}"
LICENCE = "EDEngineer is MIT-licensed (its LICENSE); the game data in it is Frontier Developments plc's"
HEADERS = {"User-Agent": "ED-Outrider gear blueprints build"}

# the suits and weapons: (name, kind, family: what a weapon's modifications cost by, journal symbol without _classN)
ITEMS = [
    ("Artemis", "suit", None, "explorationsuit"), ("Dominator", "suit", None, "tacticalsuit"),
    ("Maverick", "suit", None, "utilitysuit"),
    ("Karma AR-50", "weapon", "kinetic", "wpn_m_assaultrifle_kinetic_fauto"),
    ("Karma C-44", "weapon", "kinetic", "wpn_m_submachinegun_kinetic_fauto"),
    ("Karma L-6", "weapon", "kinetic", "wpn_m_launcher_rocket_sauto"),
    ("Karma P-15", "weapon", "kinetic", "wpn_s_pistol_kinetic_sauto"),
    ("Manticore Executioner", "weapon", "plasma", "wpn_m_sniper_plasma_charged"),
    ("Manticore Intimidator", "weapon", "plasma", "wpn_m_shotgun_plasma_doublebarrel"),
    ("Manticore Oppressor", "weapon", "plasma", "wpn_m_assaultrifle_plasma_fauto"),
    ("Manticore Tormentor", "weapon", "plasma", "wpn_s_pistol_plasma_charged"),
    ("TK Aphelion", "weapon", "laser", "wpn_m_assaultrifle_laser_fauto"),
    ("TK Eclipse", "weapon", "laser", "wpn_m_submachinegun_laser_fauto"),
    ("TK Zenith", "weapon", "laser", "wpn_s_pistol_laser_sauto"),
]
ITEM_FIX = {"Manticore Opressor": "Manticore Oppressor"}   # the source's typos
# the modifications by EDEngineer's names: (our name, the journal's symbol in SuitMods / WeaponMods)
MODS = {
    "Added melee damage": ("Added melee damage", "suit_increasedmeleedamage"),
    "Combat Movement Speed": ("Combat movement speed", "suit_adsmovementspeed"),
    "Damage resistance": ("Damage resistance", "suit_improvedarmourrating"),
    "Enhanced tracking": ("Enhanced tracking", "suit_improvedradar"),
    "Extra ammo capacity": ("Extra ammo capacity", "suit_increasedammoreserves"),
    "Extra backpack capacity": ("Extra backpack capacity", "suit_backpackcapacity"),
    "Faster shield regen": ("Faster shield regen", "suit_increasedshieldregen"),
    "Improved battery capacity": ("Improved battery capacity", "suit_increasedbatterycapacity"),
    "Improved jump assist": ("Improved jump assist", "suit_improvedjumpassist"),
    "Increased air reserves": ("Increased air reserves", "suit_increasedo2capacity"),
    "Increased sprint duration": ("Increased sprint duration", "suit_increasedsprintduration"),
    "Night vision": ("Night vision", "suit_nightvision"),
    "Quieter footsteps": ("Quieter footsteps", "suit_quieterfootsteps"),
    "Reduced tool battery consumption": ("Reduced tool battery consumption", "suit_reducedtoolbatteryconsumption"),
    "Audio Masking": ("Audio masking", "weapon_suppression_unpressurised"),
    "Faster handling": ("Faster handling", "weapon_handling"),
    "Greater range": ("Greater range", "weapon_range"),
    "Headshot damage": ("Headshot damage", "weapon_headshotdamage"),
    "Improved Hip Fire Accuracy": ("Improved hip fire accuracy", "weapon_accuracy"),
    "Magazine size": ("Magazine size", "weapon_clipsize"),
    "Noise suppressor": ("Noise suppressor", "weapon_suppression_pressurised"),
    "Reload speed": ("Reload speed", "weapon_reloadspeed"),
    "Scope": ("Scope", "weapon_scope"),
    "Stability": ("Stability", "weapon_stability"),
    "Stowed reloading": ("Stowed reloading", "weapon_backpackreloading"),
}
DROP = {"Higher Accuracy"}   # EDEngineer lists the hip fire accuracy mod twice, by both names, at the same cost
FAMILY = {"Kinematic kinetic": "kinetic", "Kinetic Weapons": "kinetic", "Manticore plasma": "plasma",
          "Plasma Weapons": "plasma", "Takada laser": "laser", "Thermal Weapons": "laser"}
# the Colonia engineers and what each offers (the ED Field Manual, read 2026-10-18)
COLONIA = {
    "Baltanos": ["Improved jump assist", "Increased air reserves", "Increased sprint duration", "Combat movement speed",
                 "Noise suppressor", "Improved hip fire accuracy", "Faster handling"],
    "Eleanor Bresa": ["Added melee damage", "Damage resistance", "Extra ammo capacity", "Faster shield regen",
                      "Magazine size", "Reload speed", "Stowed reloading"],
    "Rosa Dayette": ["Extra backpack capacity", "Enhanced tracking", "Reduced tool battery consumption",
                     "Improved battery capacity", "Greater range", "Scope", "Stability"],
    "Yi Shen": ["Quieter footsteps", "Night vision", "Audio masking", "Headshot damage"],
}
KINDS = {"Item": "Goods", "Data": "Data", "Chemicals": "Assets", "Circuits": "Assets", "Tech": "Assets"}


def get(path):
    url = URL.format(commit=COMMIT, path=path)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
        return json.loads(r.read().decode("utf-8-sig"))


def build(bp, entries):
    """(items, mods, materials) from EDEngineer's two files: items [{name, kind, family, symbol, upgrades: {grade:
    {material symbol: count}}}], mods [{name, kind, family (a weapon mod's cost by weapon family, else None), symbol,
    engineers, materials}], materials {symbol: {name, kind (Goods, Assets, Data)}}."""
    mats = {}
    for e in entries:
        if e.get("Kind") == "OdysseyIngredient" and e.get("FormattedName"):
            mats[e["Name"]] = (e["FormattedName"], KINDS.get(e.get("Group")))
    unknown, used = set(), {}

    def need(ingredients):
        out = {}
        for i in ingredients:
            m = mats.get(i["Name"])
            if m is None or m[1] is None:
                unknown.add(i["Name"])
                continue
            out[m[0]] = i["Size"]
            used[m[0]] = {"name": i["Name"], "kind": m[1]}
        return out

    items = {n: {"name": n, "kind": k, "family": f, "symbol": s, "upgrades": {}} for n, k, f, s in ITEMS}
    mods, odd = [], set()
    for b in bp:
        if b.get("Type") not in ("Suit", "Weapon"):
            continue
        if b.get("Grade") is not None:
            name = ITEM_FIX.get(b["Name"], b["Name"])
            if name not in items:
                odd.add(f"item {name}")
                continue
            items[name]["upgrades"][str(b["Grade"])] = need(b["Ingredients"])
            continue
        m = re.match(r"^(.*?)(?: \((.*)\))?$", b["Name"])
        base, fam = m.group(1), m.group(2)
        if base in DROP:
            continue
        if base not in MODS or (fam and fam not in FAMILY):
            odd.add(f"mod {b['Name']}")
            continue
        name, symbol = MODS[base]
        mods.append({"name": name, "kind": "suit" if b["Type"] == "Suit" else "weapon", "family": FAMILY.get(fam),
                     "symbol": symbol, "engineers": sorted(set(b["Engineers"])), "materials": need(b["Ingredients"])})
    for eng, offered in COLONIA.items():
        for name in offered:
            hit = [m for m in mods if m["name"] == name]
            if not hit:
                odd.add(f"Colonia mod {name}")
            for m in hit:
                m["engineers"] = sorted(set(m["engineers"]) | {eng})
    missing = [n for n, it in items.items() if sorted(it["upgrades"]) != ["2", "3", "4", "5"]]
    if unknown or odd or missing:
        sys.exit(f"materials not named: {sorted(unknown)}; not known: {sorted(odd)}; upgrades missing: {missing}. Nothing written")
    mods.sort(key=lambda m: (m["kind"], m["name"].lower(), m["family"] or ""))
    return list(items.values()), mods, dict(sorted(used.items()))


def main():
    bp, entries = (get(p) for p in FILES)
    items, mods, mats = build(bp, entries)
    doc = {"_readme": "This fork's suit and weapon engineering for Commander → Engineering → Suits & weapons (outrider/gear.py): "
                      "each suit's and weapon's upgrade G2 to G5 (bought at Pioneer Supplies) and each modification (an "
                      "engineer's, by weapon family where its cost differs), the materials by their journal names. Built by "
                      f"scripts/build_gear_blueprints.py from EDEngineer ({REPO}, commit {COMMIT} of {COMMIT_DATE}: "
                      f"{', '.join(FILES)}; {LICENCE}), the Colonia engineers added from the ED Field Manual.",
           "source": {"repo": REPO, "commit": COMMIT, "date": COMMIT_DATE, "files": list(FILES), "licence": LICENCE},
           "items": items, "mods": mods, "materials": mats}
    with open(OUT + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(OUT + ".tmp", OUT)
    print(f"wrote {OUT}: {len(items)} suits and weapons, {len(mods)} modifications, {len(mats)} materials, "
          f"{os.path.getsize(OUT)} bytes")


if __name__ == "__main__":
    main()

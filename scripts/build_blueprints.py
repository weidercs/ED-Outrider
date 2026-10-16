"""Build resources/blueprints.json (the Commander view's Engineering list) from EDCD's coriolis-data and FDevIDs tables,
downloaded into a folder (https://github.com/EDCD/coriolis-data: modifications/blueprints.json and modules.json;
https://github.com/EDCD/FDevIDs: material.csv): every ship-module blueprint with its materials per grade, by the journal's material names, and
the engineers who offer each grade. Run from the repository: python -I build_blueprints.py <dl folder> <out file>."""
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.getcwd())
import outrider.materials as M   # noqa: E402

src, out = sys.argv[1], sys.argv[2]
bp = json.load(io.open(os.path.join(src, "blueprints.json"), encoding="utf-8"))
mods = json.load(io.open(os.path.join(src, "modules.json"), encoding="utf-8"))
ids = {r["name"].strip().lower(): r["symbol"].strip().lower() for r in csv.DictReader(io.open(os.path.join(src, "material.csv"), encoding="utf-8"))}
ids["untypical shield scans"] = "shielddensityreports"
assert "shielddensityreports" in ids.values()

FIX = {"Felicty Farseer": "Felicity Farseer", "Auto field mainentance unit": "Auto field maintenance unit"}
engineers = {}   # blueprint -> grade -> names
by_kind = {}     # blueprint -> grade -> module kind -> names (a shared blueprint's engineers differ by kind)
for code, kind in mods.items():
    for name, b in (kind.get("blueprints") or {}).items():
        for g, v in b["grades"].items():
            names = {FIX.get(e, e) for e in v.get("engineers") or []}
            engineers.setdefault(name, {}).setdefault(g, set()).update(names)
            by_kind.setdefault(name, {}).setdefault(g, {}).setdefault(code, set()).update(names)

# what each of coriolis-data's module kinds is called, for a blueprint shared by several ("for: missile racks, ...")
KIND_NAMES = {
    "bl": "beam lasers", "ul": "burst lasers", "pl": "pulse lasers", "mc": "multi-cannons", "advmc": "advanced multi-cannons",
    "c": "cannons", "fc": "fragment cannons", "pa": "plasma accelerators", "rg": "rail guns", "mr": "missile racks",
    "amr": "advanced missile racks", "nl": "mine launchers", "tp": "torpedo pylons",
    "ch": "chaff launchers", "cs": "manifest scanners", "csl": "caustic sink launchers", "ec": "electronic countermeasures",
    "hs": "heat sink launchers", "kw": "kill warrant scanners", "po": "point defence", "ws": "frame shift wake scanners",
    "sg": "shield generators", "bsg": "bi-weave shield generators", "psg": "prismatic shield generators",
}
users = {}
for code, kind in mods.items():
    for name in kind.get("blueprints") or {}:
        users.setdefault(name, []).append(code)

rows, unknown, unnamed = [], set(), set()
for key, b in sorted(bp.items(), key=lambda kv: (kv[1]["modulename"][0].lower(), kv[1]["name"].lower())):
    grades = {}
    for g, v in sorted(b["grades"].items()):
        need = {}
        for name, n in (v.get("components") or {}).items():
            mid = ids[name.strip().lower()]
            if mid not in M.MATERIALS:
                unknown.add(mid)
            need[mid] = n
        if need:   # a grade the source lists without materials is left out
            grades[g] = {"materials": need, "engineers": sorted(engineers.get(key, {}).get(g, ()))}
            kinds_here = by_kind.get(key, {}).get(g, {})
            if len(users.get(key, [])) > 1 or FIX.get(b["modulename"][0], b["modulename"][0]).lower() == "weapon":
                grades[g]["by_kind"] = {KIND_NAMES.get(k, k): sorted(v) for k, v in sorted(kinds_here.items())}
    if not grades:
        continue
    module = FIX.get(b["modulename"][0], b["modulename"][0])
    kinds = sorted(users.get(key, []))
    # the modules a blueprint shared by several kinds is for (a weapon's: missile racks, multi-cannons...), by name
    used_by = [KIND_NAMES.get(k, k) for k in kinds] if len(kinds) > 1 or module.lower() == "weapon" else []
    unnamed.update(k for k in kinds if k not in KIND_NAMES and used_by)
    rows.append({"id": key, "module": module[0].upper() + module[1:], "name": b["name"], "grades": grades, "for": used_by})
print(len(rows), "blueprints; materials Outrider's table does not list:", sorted(unknown), "; kinds without a name:", sorted(unnamed))
doc = {"_readme": "Ship-module engineering blueprints for the Commander view's Engineering list (outrider/commander.py): the "
                  "materials each grade takes, by the journal's material names, and the engineers offering it. Built by "
                  "scripts/build_blueprints.py from EDCD's coriolis-data (modifications/blueprints.json, modules.json) and FDevIDs "
                  "(material.csv); the game data is Frontier Developments'. Experimental effects and Odyssey suit and "
                  "weapon upgrades are not in it.",
       "blueprints": rows}
with io.open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    f.write("\n")
print(os.path.getsize(out), "bytes")

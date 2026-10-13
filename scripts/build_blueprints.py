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
for kind in mods.values():
    for name, b in (kind.get("blueprints") or {}).items():
        for g, v in b["grades"].items():
            engineers.setdefault(name, {}).setdefault(g, set()).update(FIX.get(e, e) for e in v.get("engineers") or [])

rows, unknown = [], set()
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
    if not grades:
        continue
    module = FIX.get(b["modulename"][0], b["modulename"][0])
    rows.append({"id": key, "module": module[0].upper() + module[1:], "name": b["name"], "grades": grades})
print(len(rows), "blueprints; materials Outrider's table does not list:", sorted(unknown))
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

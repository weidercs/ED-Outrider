#!/usr/bin/env python3
"""Build resources/blueprints.json (the Commander view's Engineering list) from EDCD's coriolis-data, fetched at a
pinned commit: modifications/blueprints.json (each blueprint's materials per grade, by their English names) and
modifications/modules.json (which blueprints each kind of module takes and the engineers offering each grade FOR THAT
KIND: a pulse laser's Overcharged is not a cannon's). One row per kind of module and blueprint; the materials by the
journal's own names, from outrider.materials (its names and ids are Outrider's own table: no other source needed).

    .venv/bin/python scripts/build_blueprints.py            (two downloads, about 400 kB)

To move to a newer coriolis-data, set COMMIT and COMMIT_DATE to its commit and run it again; it stops, writing nothing,
on a material or a kind of module it cannot name.
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import outrider.materials as M   # noqa: E402

REPO = "https://github.com/EDCD/coriolis-data"
COMMIT = "0db9234b5b9ce8c939ea84133d7ce336eea88e27"   # master, "Merge pull request #131 from EDCD/develop"
COMMIT_DATE = "2026-04-24"
FILES = ("modifications/blueprints.json", "modifications/modules.json")
URL = "https://raw.githubusercontent.com/EDCD/coriolis-data/{commit}/{path}"
# coriolis-data's LICENSE.md, as read at that commit
LICENCE = ("coriolis-data's LICENSE.md: the data and its JSON files are the intellectual property and copyright of "
           "Frontier Developments plc and subject to its terms and conditions (https://www.frontierstore.net/terms-and-conditions/); "
           "only coriolis.io's own code is MIT")
OUT = os.path.join(ROOT, "resources", "blueprints.json")
HEADERS = {"User-Agent": "ED-Outrider blueprints build"}

# coriolis-data's kinds of module (its "grp" codes) in words; a kind it adds with blueprints stops the build until named
KINDS = {
    "am": "Auto field maintenance unit", "bh": "Bulkheads", "bl": "Beam laser", "bsg": "Bi-weave shield generator",
    "c": "Cannon", "cc": "Collector limpet controller", "ch": "Chaff launcher", "cr": "Cargo rack", "cs": "Cargo scanner",
    "csl": "Caustic sink launcher", "ec": "Electronic countermeasure", "fc": "Fragment cannon",
    "fi": "Frame shift drive interdictor", "fs": "Fuel scoop", "fsd": "Frame shift drive",
    "fx": "Fuel transfer limpet controller", "hb": "Hatch breaker limpet controller", "hr": "Hull reinforcement package",
    "hs": "Heat sink launcher", "kw": "Kill warrant scanner", "ls": "Life support", "mc": "Multi-cannon",
    "advmc": "Advanced multi-cannon", "mr": "Missile rack", "amr": "Advanced missile rack", "nl": "Mine launcher",
    "pa": "Plasma accelerator", "pc": "Prospector limpet controller", "pd": "Power distributor", "pl": "Pulse laser",
    "po": "Point defence", "pp": "Power plant", "psg": "Prismatic shield generator", "rf": "Refinery", "rg": "Rail gun",
    "s": "Sensors", "sb": "Shield booster", "scb": "Shield cell bank", "sg": "Shield generator",
    "ss": "Detailed surface scanner", "t": "Thrusters", "tp": "Torpedo pylon", "ul": "Burst laser",
    "ws": "Frame shift wake scanner",
}
FIX = {"Felicty Farseer": "Felicity Farseer"}   # the source's typos in engineers' names


def get(path):
    url = URL.format(commit=COMMIT, path=path)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
        return json.loads(r.read())


def build(bp, mods):
    """The rows from coriolis-data's two files: [{id (the blueprint, as the journal's EngineerModifications names it),
    kind, module, name, grades: {grade: {materials: {journal id: per roll}, engineers: [...]}}}], by module then name."""
    by_name = {v[0].strip().lower(): k for k, v in M.MATERIALS.items()}
    rows, unknown, kinds = [], set(), set()
    for kind, m in mods.items():
        for key, offered in sorted((m.get("blueprints") or {}).items()):
            if kind not in KINDS:
                kinds.add(kind)
                continue
            b = bp[key]
            grades = {}
            for g, v in sorted(b["grades"].items()):
                need = {}
                for name, n in (v.get("components") or {}).items():
                    mid = by_name.get(name.strip().lower())
                    if mid is None:
                        unknown.add(name)
                    need[mid] = n
                who = ((offered.get("grades") or {}).get(g) or {}).get("engineers") or []
                if need and who:   # a grade the source lists without materials or engineers is left out
                    grades[g] = {"materials": need, "engineers": sorted({FIX.get(e, e) for e in who})}
            if grades:
                rows.append({"id": key, "kind": kind, "module": KINDS[kind], "name": b["name"], "grades": grades})
    if unknown or kinds:
        sys.exit(f"materials outrider.materials does not name: {sorted(unknown)}; kinds of module KINDS does not name: "
                 f"{sorted(kinds)}. Nothing written")
    rows.sort(key=lambda r: (r["module"].lower(), r["name"].lower()))
    return rows


def main():
    bp, mods = (get(p) for p in FILES)
    rows = build(bp, mods)
    doc = {"_readme": "Ship-module engineering blueprints for the Commander view's Engineering list (outrider/commander.py): "
                      "one row per kind of module and blueprint, the materials each grade takes (by the journal's material "
                      "names) and the engineers offering it for that kind. Built by scripts/build_blueprints.py from EDCD's "
                      f"coriolis-data ({REPO}, commit {COMMIT} of {COMMIT_DATE}: {', '.join(FILES)}); {LICENCE}. "
                      "Experimental effects and Odyssey suit and weapon upgrades are not in it.",
           "source": {"repo": REPO, "commit": COMMIT, "date": COMMIT_DATE, "files": list(FILES), "licence": LICENCE},
           "blueprints": rows}
    with open(OUT + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(OUT + ".tmp", OUT)
    print(f"wrote {OUT}: {len(rows)} blueprints for {len({r['kind'] for r in rows})} kinds of module, {os.path.getsize(OUT)} bytes")


if __name__ == "__main__":
    main()

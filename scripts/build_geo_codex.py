#!/usr/bin/env python3
"""Build resources/geo_codex.json: the codex's Geology and Anomalies entries (fumaroles, gas vents, geysers, lava spouts,
Lagrange clouds, the lettered anomalies) and how many sites of each the community has reported per galactic region,
for the Samples tab's geology checklist.

Source: Canonn's codex reference (every codex entry: id, name, kind) and its per-entry dumps (every reported site:
system, x, y, z, entry id, id64, region). Read only. Run it again to bring the counts up to date:

    .venv/bin/python scripts/build_geo_codex.py            (about 90 downloads, a few tens of MB; a minute or two)
"""
import csv
import io
import json
import os
import sys
import time
import urllib.request

REF = "https://us-central1-canonn-api-236217.cloudfunctions.net/query/codex/ref"
SUBCATEGORY = "$Codex_SubCategory_Geology_and_Anomalies;"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "geo_codex.json")
HEADERS = {"User-Agent": "ED-Outrider geo codex build"}


def get(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
        return r.read()


def main():
    ref = json.loads(get(REF))
    entries = [x for x in (ref.values() if isinstance(ref, dict) else ref) if x.get("sub_category") == SUBCATEGORY]
    if not entries:
        sys.exit("no Geology and Anomalies entries in Canonn's codex reference: its shape may have changed")
    out = []
    for n, e in enumerate(sorted(entries, key=lambda x: x["entryid"]), 1):
        regions = {}
        if e.get("dump"):
            try:
                rows = csv.reader(io.StringIO(get(e["dump"]).decode("utf-8", "replace")))
            except OSError as err:
                sys.exit(f"{e['english_name']}: its dump could not be fetched ({err}); nothing written")
            for row in rows:
                # system, x, y, z, entry id, id64, region, region: the region is a number 1-42
                if len(row) >= 7 and row[6].isdigit() and 1 <= int(row[6]) <= 42:
                    regions[row[6]] = regions.get(row[6], 0) + 1
        out.append({"id": e["entryid"], "name": e["english_name"], "codex": e.get("name"), "kind": e.get("hud_category"),
                    "group": e.get("sub_class"), "regions": dict(sorted(regions.items(), key=lambda kv: int(kv[0])))})
        print(f"{n}/{len(entries)} {e['english_name']}: {sum(regions.values())} sites in {len(regions)} regions", flush=True)
    doc = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": "Canonn (canonn.science): the codex reference and its reported sites, counted per galactic region",
           "entries": out}
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    os.replace(OUT + ".tmp", OUT)
    print(f"wrote {OUT}: {len(out)} entries")


if __name__ == "__main__":
    main()

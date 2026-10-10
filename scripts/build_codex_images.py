#!/usr/bin/env python3
"""Build resources/codex_images.json: for each biology and Geology and Anomalies codex entry, the link to a screenshot
of it on Canonn's storage and the commander who took it, for the checklists' detail panels. Links only: no image is
copied; the page loads one from Canonn when you open an entry, with its credit.

Source: Canonn's codex reference (image_url, image_cmdr per entry). Read only. Run it again to pick up new images:

    .venv/bin/python scripts/build_codex_images.py
"""
import json
import os
import sys
import time
import urllib.request

REF = "https://us-central1-canonn-api-236217.cloudfunctions.net/query/codex/ref"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "codex_images.json")


def main():
    req = urllib.request.Request(REF, headers={"User-Agent": "ED-Outrider codex images build"})
    with urllib.request.urlopen(req, timeout=120) as r:
        ref = json.loads(r.read())
    images = {}
    for e in ref.values() if isinstance(ref, dict) else ref:
        biology = e.get("hud_category") == "Biology"
        geology = e.get("sub_category") == "$Codex_SubCategory_Geology_and_Anomalies;"
        url = e.get("image_url")
        if (biology or geology) and isinstance(url, str) and url.startswith("https://") and e.get("english_name"):
            # keyed by the entry's English name as your codex has it ("Stratum Tectonicas - Lime", "Water Ice Geyser")
            images[e["english_name"].strip().lower()] = [url, (e.get("image_cmdr") or "").strip() or None]
    if len(images) < 500:
        sys.exit(f"only {len(images)} images in Canonn's codex reference: its shape may have changed; nothing written")
    doc = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": "Canonn (canonn.science): its codex reference's screenshot of each entry, credited to the commander "
                     "who took it. Links only. Elite Dangerous imagery: Frontier Developments plc.",
           "images": dict(sorted(images.items()))}
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=0)
    os.replace(OUT + ".tmp", OUT)
    print(f"wrote {OUT}: {len(images)} images")


if __name__ == "__main__":
    main()

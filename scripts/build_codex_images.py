#!/usr/bin/env python3
"""Build resources/codex_images.json: for each biology and Geology and Anomalies codex entry, the link to a screenshot
of it on Canonn's storage and the commander who took it, for the checklists' detail panels. Links only: no image is
copied; the page loads one from Canonn when you open an entry, with its credit.

The running server refreshes its own copy from Canonn once a day (data/codex_images.json); this shipped one is the
fallback for a fresh install or an offline server. Source: Canonn's codex reference. Read only:

    .venv/bin/python scripts/build_codex_images.py
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import outrider.codex_images as ci  # noqa: E402


def main():
    req = urllib.request.Request(ci.REF, headers={"User-Agent": "ED-Outrider codex images build"})
    with urllib.request.urlopen(req, timeout=120) as r:
        ref = json.loads(r.read())
    try:
        images = ci.parse(ref)
    except ValueError as e:
        sys.exit(f"{e}; nothing written")
    ci.save(ci.SHIPPED, images)
    print(f"wrote {ci.SHIPPED}: {len(images)} images")


if __name__ == "__main__":
    main()

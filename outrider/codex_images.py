"""The checklists' pictures: for each biology and Geology and Anomalies codex entry, the link to a screenshot of it on
Canonn's storage and the commander who took it. Links only: no image is copied; the page loads one from Canonn when an
entry is opened, with its credit.

Two copies of the list: the one shipped in resources/codex_images.json (scripts/build_codex_images.py), and a fresher
one the server fetches from Canonn's codex reference once a day into data/codex_images.json (State.watch_codex_images).
The fresher is used when it is sound; else the shipped one.
"""
import json
import os
import time

from . import DATA_DIR, RESOURCES_DIR

REF = "https://us-central1-canonn-api-236217.cloudfunctions.net/query/codex/ref"
SHIPPED = os.path.join(RESOURCES_DIR, "codex_images.json")
CACHE = os.path.join(DATA_DIR, "codex_images.json")
MIN_ENTRIES = 500   # fewer than this from Canonn: its answer changed shape, the list is not replaced
SOURCE = ("Canonn (canonn.science): its codex reference's screenshot of each entry, credited to the commander who took "
          "it. Links only. Elite Dangerous imagery: Frontier Developments plc.")


def parse(ref):
    """Canonn's codex reference -> {English name lower-cased: [image url, commander or None]} for the biology and
    Geology and Anomalies entries with an https image; ValueError when it has fewer than MIN_ENTRIES (a changed shape)."""
    images = {}
    for e in ref.values() if isinstance(ref, dict) else ref if isinstance(ref, list) else []:
        if not isinstance(e, dict):
            continue
        biology = e.get("hud_category") == "Biology"
        geology = e.get("sub_category") == "$Codex_SubCategory_Geology_and_Anomalies;"
        url, name = e.get("image_url"), e.get("english_name")
        if (biology or geology) and isinstance(url, str) and url.startswith("https://") and isinstance(name, str) and name.strip():
            cmdr = e.get("image_cmdr")
            images[name.strip().lower()] = [url, cmdr.strip() if isinstance(cmdr, str) and cmdr.strip() else None]
    if len(images) < MIN_ENTRIES:
        raise ValueError(f"only {len(images)} images in Canonn's codex reference: its shape may have changed")
    return dict(sorted(images.items()))


def save(path, images):
    """Write the list (atomically) to `path`."""
    doc = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": SOURCE, "images": images}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=0)
    os.replace(path + ".tmp", path)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            images = json.load(f).get("images")
    except (OSError, ValueError, AttributeError):
        return None
    return images if isinstance(images, dict) and len(images) >= MIN_ENTRIES else None


def load(cache=None, shipped=None):
    """The list to use: the fetched copy when it is sound, else the shipped one ({} when neither is). The paths are
    looked up now, not at import (tests point CACHE into a scratch folder)."""
    return _read(cache or CACHE) or _read(shipped or SHIPPED) or {}


def cache_age(cache=None, now=None):
    """Seconds since the fetched copy was written, or None when there is none."""
    try:
        return (now or time.time()) - os.path.getmtime(cache or CACHE)
    except OSError:
        return None

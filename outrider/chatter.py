"""Space chatter (this fork): things the co-pilot says unprompted when nothing has been said for a while. The lines
are resources/chatter.json's, one list per personality of speech.json; the page (static/fork.js) does the timing,
since it is the page that knows what was said and when: no sooner than a set time after the last line, no later than
another. Only a personality with a list chatters (Rocky's is the first).

    lines()                # {personality: [line, ...]}, checked
    add_routes(app)        # GET /api/chatter
"""
import json
import os

from . import RESOURCES_DIR

CHATTER_FILE = os.path.join(RESOURCES_DIR, "chatter.json")
MAX_CHARS = 140
_CACHE = {}


def check(doc):
    """What is wrong with a chatter file, as a list of sentences ([] when it is fine)."""
    lines = doc.get("lines") if isinstance(doc, dict) else None
    if not isinstance(lines, dict):
        return ['"lines" must be an object: one list of sentences per personality']
    bad = []
    for style, rows in lines.items():
        if not isinstance(rows, list) or not all(isinstance(x, str) and x.strip() for x in rows):
            bad.append(f"{style}: a list of sentences")
            continue
        if len(set(rows)) != len(rows):
            bad.append(f"{style}: a line is there twice")
        for x in rows:
            if len(x) > MAX_CHARS or "{" in x or "'" in x:
                bad.append(f"{style}: no placeholders or apostrophes, at most {MAX_CHARS} characters: {x[:40]}")
    return bad


def lines(path=CHATTER_FILE):
    """{personality: [line, ...]} from the file (read again when it changes); {} when it is missing or wrong."""
    try:
        stamp = os.path.getmtime(path)
        if _CACHE.get("key") != (path, stamp):
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            _CACHE.update(key=(path, stamp), lines={} if check(doc) else {k: list(v) for k, v in doc["lines"].items() if v})
        return _CACHE["lines"]
    except (OSError, ValueError):
        return {}


def add_routes(app):
    """GET /api/chatter: {lines: {personality: [...]}}."""
    from aiohttp import web

    async def view(_):
        return web.json_response({"lines": lines()})
    app.router.add_get("/api/chatter", view)

"""Journal events by name, read straight from the journal files: what the Commander view's lists are
built from. Nothing is stored: the files are the source of truth, and a file that has not grown is read once.

    events(dirs, names, days=30)   # every event with one of those names in the last `days`, oldest first
"""
import json
import re
import threading
import time
from collections import OrderedDict

from outrider.core import iso_ts
from outrider.log import journal_files, window

_CACHE = OrderedDict()   # (path, size, names) -> [events]
_CACHE_MAX = 400
_LOCK = threading.Lock()


def _read(path, names):
    """The events of one file with one of `names` (a frozenset), in file order. A line is parsed only when it
    carries one of the names, so a long session costs little."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return []
    key = (path, len(raw), names)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    mark = re.compile(rb'"event"\s*:\s*"(?:' + b"|".join(re.escape(n.encode()) for n in sorted(names)) + rb')"')
    out = []
    for line in raw.split(b"\n"):
        if not mark.search(line):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("event") in names and isinstance(ev.get("timestamp"), str):
            out.append(ev)
    with _LOCK:
        _CACHE[key] = out
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return out


def events(dirs, names, days=30, now=None):
    """Every journal event named in `names` from the files that can hold the last `days`, oldest first."""
    names = frozenset(names)
    now = time.time() if now is None else now
    since = iso_ts(now - days * 86400)
    out = []
    for _, path in window(journal_files(dirs), days, now):   # the files that can hold them: one may begin earlier
        out.extend(e for e in _read(path, names) if e["timestamp"] >= since)
    return out

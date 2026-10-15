"""This fork's personalities (Rocky), kept apart from upstream's resources/speech.json so that file merges unchanged:
resources/speech.fork.json is merged into the speech document as it is loaded (outrider.speech.SpeechLines).

    merge(doc)   # the document with the fork's styles and lists added (what the file already has wins)
"""
import json
import os

from . import RESOURCES_DIR

FORK_FILE = os.path.join(RESOURCES_DIR, "speech.fork.json")
_CACHE = {}


def load(path=FORK_FILE):
    """The fork's speech document ({styles, lines}), read again when it changes; {} when it is missing or broken."""
    try:
        stamp = os.path.getmtime(path)
        if _CACHE.get("key") != (path, stamp):
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            ok = isinstance(doc, dict) and isinstance(doc.get("styles"), dict) and isinstance(doc.get("lines"), dict)
            _CACHE.update(key=(path, stamp), doc=doc if ok else {})
        return _CACHE["doc"]
    except (OSError, ValueError):
        return {}


def merge(doc, fork=None):
    """`doc` with the fork's personalities added: each style the speech file does not name, and each of their lists
    for an alert the speech file has (an alert only the fork names is left out: nothing would say it). A speech file
    that already has the style keeps its own lines. A new document: `doc` is not changed."""
    fork = load() if fork is None else fork
    if not fork or not isinstance(doc, dict) or not isinstance(doc.get("styles"), dict) or not isinstance(doc.get("lines"), dict):
        return doc
    new = [st for st in fork["styles"] if st not in doc["styles"]]
    if not new:
        return doc
    lines = {}
    for key, entry in doc["lines"].items():
        extra = fork["lines"].get(key) or {} if isinstance(entry, dict) else {}
        add = {st: list(extra[st]) for st in new if isinstance(extra.get(st), list) and extra[st]}
        lines[key] = dict(entry, **add) if add else entry
    return dict(doc, styles=dict(doc["styles"], **{st: fork["styles"][st] for st in new}), lines=lines)

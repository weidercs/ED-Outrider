"""Road to Riches (spansh.co.uk/riches): Spansh's answer as route rows, which row a system is, which of a system's
bodies are still to do, and the line said on arriving. Pure helpers: the route's state, its tables and the plot
under way live in ed_outrider.State, as the Neutron Highway's do (outrider/highway.py).

Spansh publishes no description of this API: the field names below follow what other tools read from it (EDXD,
issue 176) and are read leniently. A missing field is a missing value, a body or system that is not a dict or has no
name is skipped, and an answer with no usable system is a RichesError."""
import math

from outrider.highway import number_words

RICHES_MAX_SYSTEMS = 2000   # a route longer than this is refused (Spansh's own cap is far lower)
RICHES_MAX_BODIES = 300     # bodies kept per system


class RichesError(Exception):
    """A plot that failed, or an answer that cannot be used, in words for the page."""


def _num(v, conv=float):
    """A number from Spansh's answer, or None (a missing or broken field)."""
    try:
        out = conv(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if not isinstance(out, float) or math.isfinite(out) else None


def norm_name(name):
    """A body or system name as compared: spaces collapsed, case folded."""
    return " ".join(name.split()).casefold() if isinstance(name, str) else ""


def riches_rows(result):
    """Spansh's finished route as a list of systems (dicts), in route order. Each: {system, id64, x, y, z, jumps,
    bodies: [{name, type, subtype, ls, scan, map, terraformable, body_id}]}. `result` is the list itself or a dict
    holding it under "result" or "systems". Bodies without a name are dropped; a system without one is skipped."""
    if isinstance(result, dict):
        result = result.get("result") if isinstance(result.get("result"), list) else result.get("systems")
    if not isinstance(result, list):
        raise RichesError("Spansh sent a route in a shape Outrider does not know")
    rows = []
    for s in result:
        if not isinstance(s, dict):
            continue
        name = s.get("name") if isinstance(s.get("name"), str) else s.get("system")
        if not isinstance(name, str) or not name.strip():
            continue
        id64 = _num(s.get("id64"), int)
        bodies = []
        for b in (s.get("bodies") if isinstance(s.get("bodies"), list) else [])[:RICHES_MAX_BODIES]:
            if not isinstance(b, dict) or not isinstance(b.get("name"), str) or not b["name"].strip():
                continue
            bid = _num(b.get("id64"), int)
            bodies.append({
                "name": " ".join(b["name"].split()), "type": b.get("type") if isinstance(b.get("type"), str) else None,
                "subtype": b.get("subtype") if isinstance(b.get("subtype"), str) else None,
                "ls": _num(b.get("distance_to_arrival")),
                "scan": _num(b.get("estimated_scan_value"), int), "map": _num(b.get("estimated_mapping_value"), int),
                "terraformable": 1 if b.get("is_terraformable") or b.get("terraforming_state") == "Candidate for terraforming"
                else 0, "body_id": bid if bid is not None and bid >= 0 else None})
        rows.append({"system": name.strip(), "id64": id64 if id64 is not None and 0 <= id64 < 2 ** 63 else None,
                     "x": _num(s.get("x")), "y": _num(s.get("y")), "z": _num(s.get("z")),
                     "jumps": max(0, _num(s.get("jumps"), int) or 0) if rows else 0, "bodies": bodies})
    if not rows:
        raise RichesError("Spansh found no route with those settings: try a larger radius or a lower minimum value")
    if len(rows) > RICHES_MAX_SYSTEMS:
        raise RichesError(f"a route of {len(rows)} systems is longer than Outrider keeps ({RICHES_MAX_SYSTEMS})")
    return rows


def riches_match(rows, id64, name, near=0):
    """The route row a system is, or None: by id64 (by name when a row has none). A system on the route twice gives
    the occurrence at or after `near` (where you were), else the latest before it."""
    low = norm_name(name)
    hits = [i for i, r in enumerate(rows)
            if (r["id64"] == id64 if r["id64"] is not None and id64 is not None else norm_name(r["system"]) == low)]
    if not hits:
        return None
    ahead = [i for i in hits if i >= near]
    return ahead[0] if ahead else hits[-1]


def body_value(body, mapping):
    """What a body is worth to Spansh's estimate: the scan, plus the map when `mapping`. None when it has no figure."""
    scan, mapped = body.get("scan"), body.get("map")
    if scan is None and (mapped is None or not mapping):
        return None
    return (scan or 0) + ((mapped or 0) if mapping else 0)


def todo(bodies, scanned, mapped, mapping):
    """The bodies of a system still to do: not scanned, or (with `mapping`) not mapped. `scanned` and `mapped` are
    sets of norm_name'd body names read from the journal (the player's own record). Each body gains `scanned` and
    `mapped` flags; the list keeps Spansh's order."""
    out = []
    for b in bodies:
        key = norm_name(b["name"])
        out.append(dict(b, scanned=key in scanned, mapped=key in mapped,
                        done=(key in scanned) and (key in mapped or not mapping)))
    return out


def money(n):
    """A credit amount as said aloud: 1.2 million, 800 thousand."""
    if n is None:
        return None
    if n >= 1_000_000:
        v = round(n / 1_000_000, 1)
        return f"{v:g} million"
    if n >= 1000:
        return f"{round(n / 1000):d} thousand"
    return str(int(n))


def riches_text(rows, i, left):
    """The line said on arriving at route row i: how many bodies are worth the stop and what they are, then where
    next. `left` is the system's bodies still to do (todo() output, not done). Plain words (the page's personality
    lines can replace them later)."""
    here = rows[i]
    last = i == len(rows) - 1
    nxt = None if last else rows[i + 1]["system"]
    if not left:
        return (f"Nothing left to do in {here['system']}. " if here["bodies"] else "") + (
            "Road to Riches complete." if last else f"Next stop: {nxt}.")
    n = len(left)
    best = max(left, key=lambda b: b.get("scan") or 0)
    what = best.get("subtype") or best.get("type") or "body"
    val = money(best.get("scan"))
    text = f"{number_words(n).capitalize()} {'body' if n == 1 else 'bodies'} here" if n < 11 else f"{n} bodies here"
    text += f": the best is a {what.lower()}" + (f", about {val} credits" if val else "")
    if best.get("ls") is not None:
        text += f", {round(best['ls']):d} light seconds out"
    return text + "."

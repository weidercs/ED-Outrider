"""Road to Riches (spansh.co.uk/riches) and Expressway to Exomastery (spansh.co.uk/exobiology), the survey routes:
Spansh's answer as route rows, which row a system is, which of a system's bodies (or species) are still to do, and the
lines said on arriving. Exomastery's answer is Road to Riches' layout with each body's species added (`landmarks`:
{type: genus, subtype: species, value, count}, and `landmark_value`): bodies where life is already reported, so the
values are base values (first footfall is unlikely). Pure helpers: the route's state, its tables and the plot
under way live in ed_outrider.State, as the Neutron Highway's do (outrider/highway.py).

Spansh publishes no description of this API. Checked against the live site on 2026-10-06 (tests/fixtures/
spansh_riches.json is that answer, trimmed): POST /api/riches/route with form fields, then /api/results/{job}; each
system has name, id64, x, y, z, jumps and bodies, each body name, type, subtype, distance_to_arrival,
estimated_scan_value, estimated_mapping_value, is_terraformable and id64 (a string). scripts/riches_probe.py checks it
again. Fields are read leniently: a missing field is a missing value, a body or system that is not a dict or has no
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
                else 0,
                # the game's BodyID, as body_id is everywhere else: a body id64's top 9 bits
                "body_id": bid >> 55 if bid is not None and 0 <= bid < 2 ** 64 else None,
                # Exomastery: the species Spansh lists on it (none on a Road to Riches body)
                "species": _species(b.get("landmarks"))})
        rows.append({"system": name.strip(), "id64": id64 if id64 is not None and 0 <= id64 < 2 ** 63 else None,
                     "x": _num(s.get("x")), "y": _num(s.get("y")), "z": _num(s.get("z")),
                     "jumps": max(0, _num(s.get("jumps"), int) or 0) if rows else 0, "bodies": bodies})
    if not rows:
        raise RichesError("Spansh found no route with those settings: try a larger radius or a lower minimum value")
    if len(rows) > RICHES_MAX_SYSTEMS:
        raise RichesError(f"a route of {len(rows)} systems is longer than Outrider keeps ({RICHES_MAX_SYSTEMS})")
    return rows


def _species(landmarks):
    """A body's `landmarks` (Exomastery) as [{genus, species, value, count}], best first; lenient (a broken entry
    is skipped)."""
    out = []
    for x in landmarks if isinstance(landmarks, list) else []:
        if not isinstance(x, dict) or not isinstance(x.get("subtype"), str) or not x["subtype"].strip():
            continue
        out.append({"genus": x["type"].strip() if isinstance(x.get("type"), str) else None,
                    "species": " ".join(x["subtype"].split()), "value": _num(x.get("value"), int),
                    "count": _num(x.get("count"), int)})
    return sorted(out, key=lambda x: -(x["value"] or 0))


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
    if n >= 999_500:   # rounds to a million: "1 million", never "1000 thousand"
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


def exo_todo(bodies, sampled):
    """Exomastery: the bodies with their species marked `done` (a completed sample of it on that body: `sampled` is a
    set of (BodyID, species name lower-cased) from the journal), each body `done` once all its species are, and
    `left` (its species not done)."""
    out = []
    for b in bodies:
        sp = [dict(x, done=(b.get("body_id"), x["species"].lower()) in sampled) for x in b.get("species") or []]
        left = [x for x in sp if not x["done"]]
        out.append(dict(b, species=sp, left=len(left), done=bool(sp) and not left))
    return out


def exo_left(bodies, sampled):
    """The species still to sample in a system: [(body, species)], best first."""
    return sorted(((b, x) for b in exo_todo(bodies, sampled) for x in b["species"] if not x["done"]),
                  key=lambda bx: -(bx[1]["value"] or 0))


def body_short(name, system):
    """A body's name without its system's ("Eol Prou PX-T d3-813 ABC 2 e" -> "ABC 2 e")."""
    return name[len(system) + 1:] if name.lower().startswith(system.lower() + " ") else name


def exo_text(rows, i, left):
    """The line said on arriving at an Exomastery route row: how many species on how many bodies are left to sample,
    the best of them and its body, then nothing more (the next stop is said once they are sampled). `left` is
    exo_left()'s. Plain words, as riches_text."""
    here = rows[i]
    last = i == len(rows) - 1
    nxt = None if last else rows[i + 1]["system"]
    if not left:
        return (f"Every species in {here['system']} is sampled. " if any(b.get("species") for b in here["bodies"]) else "") + (
            "Exomastery complete." if last else f"Next stop: {nxt}.")
    n, bodies = len(left), len({b["name"] for b, _x in left})
    b, best = left[0]
    words = lambda k, one, many: f"{number_words(k) if k < 11 else k} {one if k == 1 else many}"
    text = f"{words(n, 'species', 'species').capitalize()} on {words(bodies, 'body', 'bodies')} here: the best, {best['species']}"
    text += f" on {body_short(b['name'], here['system'])}"
    val = money(best.get("value"))
    return text + (f", about {val} credits." if val else ".")

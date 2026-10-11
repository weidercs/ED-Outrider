"""The Unscanned (bio) plotter (this fork): a chain of systems nobody has reported a body of, picked for how likely
they are to hold life, each hop as close to the ship's jump range as there is one. Pure: the server (State) does the
asking (Spansh's systems with no scan value) and the storing (a Highway route, followed like any other).

What is known of a system nobody has scanned is its name and place. A procedural name carries a mass code, the
letter before its last number ("Swoilz QK-O b26-2": b), a to h for the heaviest star's mass class: the one
characteristic to go by. How often a system of each code turned out to have biological signals is counted from the
player's own journals (State.bio_mass_counts) and blended with a starting guess (PRIOR) until there are enough of
their own. It is a guess about where to look, never a promise: the route says the odds it used.
"""
import math
import re

# "<sector> <AB-C> <mass code><n1>-<n2>" or "... <mass code><n2>"
NAME = re.compile(r"^.+ [A-Z]{2}-[A-Z] ([a-h])(?:\d+-)?\d+$")
MASS_CODES = "abcdefgh"
# The starting guess: the share of scanned systems of each mass code with at least one biological signal. Rough
# figures (the middle codes, with the F, G, K and A stars and the most bodies, lead), only until the player's own
# counts outweigh them; OTHER is a hand-named system, whose star nothing in the name gives away.
PRIOR = {"a": 0.20, "b": 0.30, "c": 0.45, "d": 0.60, "e": 0.50, "f": 0.40, "g": 0.35, "h": 0.30}
OTHER = 0.35
PRIOR_WEIGHT = 20       # the guess counts as this many systems of the player's own
MIN_HOP = 0.5           # ly: nearer than this is the same place
REACH_STEPS = (1, 2, 4)  # how far a hop may look, in jump ranges, when nothing unscanned is within one jump


def mass_code(name):
    """The mass code of a procedurally named system ("a" to "h"), or None for a hand-named one."""
    m = NAME.match(" ".join(str(name or "").split()))
    return m.group(1) if m else None


def rates(counts=None):
    """{mass code: the share of systems expected to have biology}, PRIOR blended with the player's own counts
    ({code: (systems scanned, systems with a bio signal)}): (bio + prior * PRIOR_WEIGHT) / (scanned + PRIOR_WEIGHT)."""
    out = {}
    for code in MASS_CODES:
        n, bio = (counts or {}).get(code) or (0, 0)
        n, bio = max(0, int(n)), max(0, int(bio))
        out[code] = round((min(bio, n) + PRIOR[code] * PRIOR_WEIGHT) / (n + PRIOR_WEIGHT), 3)
    return out


def odds(name, rate):
    """The share expected for one system by its name."""
    return (rate or PRIOR).get(mass_code(name), OTHER)


def _xyz(p):
    return (p["x"], p["y"], p["z"])


def ly(a, b):
    return math.dist(_xyz(a), _xyz(b))


def pick(candidates, here, reach, rate=None, start=None, toward=None, taken=()):
    """The next system of the route from `here` ({x, y, z}), or None: (candidate, ly, jumps).

    A candidate ({id64, name, x, y, z}) must be new to the route (`taken`: id64s) and must lead on: nearer to
    `toward` than `here` is when a destination is given, else farther from `start` (so the chain neither circles
    nor doubles back). Among those, the best of odds x closeness: a hop within one jump scores by how much of the
    range it uses (ly / reach: the nearer the range the better); a longer one, which needs jumps between, far less
    (half of reach / ly), so it is taken only when nothing is within reach."""
    best = None
    for c in candidates:
        if c.get("id64") in taken or None in (c.get("x"), c.get("y"), c.get("z")):
            continue
        d = ly(here, c)
        if d < MIN_HOP:
            continue
        if toward is not None:
            if ly(c, toward) >= ly(here, toward):
                continue
        elif start is not None and ly(here, start) >= MIN_HOP and ly(c, start) <= ly(here, start):
            continue
        close = d / reach if d <= reach else 0.5 * reach / d
        score = odds(c.get("name"), rate) * close
        if best is None or score > best[0]:
            best = (score, c, d)
    if best is None:
        return None
    _, c, d = best
    return c, round(d, 2), max(1, math.ceil(d / reach - 1e-9))


def rows(stops):
    """The chain ([{name, id64, x, y, z}, ...], its start first) as highway_route rows: `distance` the hop into each
    system, `jumps` the jumps that hop takes (set on the stop by the plot: `hop_jumps`), `remaining` the light years
    left along the chain. No fuel figures, no neutron stars, no refuel stops: the game plots each hop itself."""
    out, dists = [], [0.0] + [ly(a, b) for a, b in zip(stops, stops[1:])]
    total = sum(dists)
    flown = 0.0
    for i, s in enumerate(stops):
        flown += dists[i]
        out.append({"system": s["name"], "id64": s.get("id64"), "x": s["x"], "y": s["y"], "z": s["z"],
                    "distance": round(dists[i], 2) if i else 0.0, "fuel_used": None, "fuel_left": None, "neutron": 0,
                    "refuel": 0, "jumps": int(s.get("hop_jumps") or 1) if i else 0, "remaining": round(total - flown, 2)})
    return out


def odds_text(rate):
    """The odds the route used, in words for its heading: the mass codes from the likeliest down."""
    r = rate or PRIOR
    return ", ".join(f"{c} {round(r[c] * 100)}%" for c in sorted(MASS_CODES, key=lambda c: -r[c]))

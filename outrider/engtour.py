"""The engineers' trip (this fork, Commander → Engineering → Plan the trip): the engineers to visit so every pick is
covered (a blueprint at a grade, or a part at any grade), and the order to visit them in, for the fewest light years
from where you are (ending at your fleet carrier when asked). Pure: the server (outrider/commander.py) gives it where
the engineers are, what you have unlocked with them and where you and your carrier are.

    plan(requirements, engineers, places, start, end=None, include_locked=False)

It tries every set of engineers that covers the picks with no engineer to spare (a minimal cover), and for each the
shortest order exactly (Held-Karp, up to EXACT_STOPS stops; past that, nearest neighbour then 2-opt), then keeps the
shortest trip. Light years are straight lines between the systems: a fair guide to the jumps, not the jumps.
"""
import itertools
import math
import re

EXACT_STOPS = 11       # stops ordered exactly (2^n * n^2 work: 11 stops ~ 250k steps)
MAX_COVERS = 5000      # minimal covers looked at, at most (a handful of picks has a few dozen)


def plain(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def ly(a, b):
    return math.dist(a, b)


def usable(st, grade):
    """Can this engineer do it for you now: unlocked, and (for a grade) a rank that reaches it. (ok, why not)."""
    st = st or {}
    if st.get("progress") != "Unlocked":
        return False, "not unlocked yet" if st.get("progress") else "not met yet"
    if grade is not None and (st.get("rank") or 0) < grade:
        return False, f"rank {st.get('rank') or 0} of {grade} needed"
    return True, None


def _covers(reqs, cands, limit=MAX_COVERS):
    """Every minimal cover: sets of engineers that between them have a candidate for every requirement, none of them
    to spare. Branches on the uncovered requirement with the fewest candidates."""
    out, seen = [], set()
    coverable = [i for i in range(len(reqs)) if cands[i]]

    def left_of(chosen):
        return [i for i in coverable if not cands[i] & chosen]

    def go(chosen, left):
        if len(out) >= limit:
            return
        if not left:
            # minimal: every engineer in it is the only one there for some pick
            if chosen not in seen and all(left_of(chosen - {e}) for e in chosen):
                seen.add(chosen)
                out.append(chosen)
            return
        r = min(left, key=lambda i: len(cands[i]))
        for e in sorted(cands[r]):
            go(chosen | {e}, [i for i in left if e not in cands[i]])

    go(frozenset(), coverable)
    return out


def _order(points, start, end=None):
    """The shortest order to visit `points` ({name: xyz}) from `start`, ending at `end` when given: (names, length)."""
    names = sorted(points)
    n = len(names)
    if not n:
        return [], ly(start, end) if end else 0.0
    d = [[ly(points[a], points[b]) for b in names] for a in names]
    first = [ly(start, points[a]) for a in names]
    last = [ly(points[a], end) if end else 0.0 for a in names]
    if n <= EXACT_STOPS:
        # Held-Karp: best[mask][j] = the shortest way to visit `mask` ending at j
        best = {(1 << j, j): (first[j], None) for j in range(n)}
        for size in range(2, n + 1):
            for combo in itertools.combinations(range(n), size):
                mask = sum(1 << j for j in combo)
                for j in combo:
                    prev = mask & ~(1 << j)
                    best[(mask, j)] = min(((best[(prev, k)][0] + d[k][j], k) for k in combo if k != j), key=lambda t: t[0])
        full = (1 << n) - 1
        j = min(range(n), key=lambda j: best[(full, j)][0] + last[j])
        length = best[(full, j)][0] + last[j]
        order, mask = [], full
        while j is not None:
            order.append(names[j])
            mask, j = mask & ~(1 << j), best[(mask, j)][1]
        return order[::-1], length
    # many stops: nearest neighbour, then 2-opt until nothing shortens it
    left, cur, order = set(range(n)), None, []
    while left:
        j = min(left, key=lambda k: first[k] if cur is None else d[cur][k])
        order.append(j)
        left.discard(j)
        cur = j

    def total(o):
        return first[o[0]] + sum(d[a][b] for a, b in zip(o, o[1:])) + last[o[-1]]
    better = True
    while better:
        better = False
        for i in range(n - 1):
            for k in range(i + 1, n):
                o = order[:i] + order[i:k + 1][::-1] + order[k + 1:]
                if total(o) < total(order) - 1e-9:
                    order, better = o, True
    return [names[j] for j in order], total(order)


def plan(requirements, engineers, places, start, end=None, include_locked=False):
    """requirements: [{label, grade (int, or None for a part at any grade), engineers: [names]}]; engineers: {name:
    {progress, rank}} (EngineerProgress); places: {engineer name: (x, y, z)}; start, end: (x, y, z) or None.

    {stops: [{engineer, covers: [labels], leg_ly, locked: why or None}], total_ly, back_ly (the leg to `end`),
    uncovered: [{label, why}], covers_tried}. Only engineers you can use now count, unless include_locked (then any
    engineer whose place is known, each stop saying what it still needs)."""
    status = {plain(k): v for k, v in (engineers or {}).items()}
    where = {plain(k): (k, tuple(v)) for k, v in (places or {}).items() if v and len(v) == 3}
    reqs, cands, uncovered = [], [], []
    for r in requirements or []:
        ok, why_not = set(), None
        for e in r.get("engineers") or []:
            p = plain(e)
            if p not in where:
                why_not = why_not or "no workshop known"
                continue
            can, why = usable(status.get(p), r.get("grade"))
            if can or include_locked:
                ok.add(p)
            else:
                why_not = why_not or why
        reqs.append(r)
        cands.append(ok)
        if not ok:
            uncovered.append({"label": r.get("label"), "why": "nobody listed for it" if not r.get("engineers") else
                              f"no engineer you can use ({why_not})" if why_not else "no engineer you can use"})
    covers = _covers(reqs, cands)
    best = None
    for cover in covers:
        order, length = _order({e: where[e][1] for e in cover}, tuple(start), tuple(end) if end else None)
        if best is None or length < best[1] - 1e-9 or (abs(length - best[1]) < 1e-9 and len(order) < len(best[0])):
            best = (order, length)
    stops, prev = [], tuple(start)
    for e in (best[0] if best else []):
        name, xyz = where[e]
        # each pick goes to the first stop on the way that does it
        mine = [r.get("label") for i, r in enumerate(reqs) if e in cands[i] and not any(
            s["_key"] in cands[i] for s in stops)]
        can, why = usable(status.get(e), max((r.get("grade") or 0 for i, r in enumerate(reqs) if e in cands[i]), default=0) or None)
        stops.append({"_key": e, "engineer": name, "covers": mine, "leg_ly": round(ly(prev, xyz), 1), "locked": None if can else why})
        prev = xyz
    back = round(ly(prev, tuple(end)), 1) if end and stops else None
    for s in stops:
        del s["_key"]
    return {"stops": stops, "total_ly": round(best[1], 1) if best else 0.0, "back_ly": back, "uncovered": uncovered,
            "covers_tried": len(covers)}

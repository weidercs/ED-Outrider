"""The route plotted in the game's galaxy map (NavRoute.json) as a list, with the fuel it takes (this fork). Pure.

`project` walks the route jump by jump with the ship's fuel model (outrider/fsd.py: the mass falls as fuel burns, so
each jump is worked out at the mass it is made at) from the fuel aboard now, WITHOUT refuelling: where the tank no
longer covers a jump is where you must have scooped or docked by. `nearest_hops` says which reachable system of the
route each refuelling place is closest to.
"""
import math

from outrider.fsd import hop_fuel


def _xyz(p):
    return (p["x"], p["y"], p["z"])


def project(hops, pos, model=None, fuel=None, cargo=None):
    """(rows, fuel summary) for the hops ahead of `pos` ({x, y, z}).

    rows: per hop {i, ly (this jump), total_ly, fuel_used, fuel_left}; the two fuel figures are None from the first
    jump the tank does not cover, and everywhere without a model. The summary (None without model, fuel and cargo):
      start      the fuel aboard now (t)
      empty_at   the index of the first jump that cannot be made, None when the fuel lasts the route
      why        "fuel" (not enough left for that jump) or "range" (the jump is longer than the ship jumps at that
                 mass: plotted with a boost the model does not know of), None when it lasts
      last       the index of the last hop reached (-1: not even the first jump)
      need       what the jump at empty_at would burn (None for "range"), left: the fuel aboard then
      end        the fuel left at the route's end (None when it does not last)"""
    rows, total, prev = [], 0.0, pos
    known = bool(model) and fuel is not None and cargo is not None
    left, stop = (float(fuel) if known else None), None
    for i, h in enumerate(hops):
        d = math.dist(_xyz(prev), _xyz(h))
        total += d
        used = after = None
        if known and stop is None:
            need = hop_fuel(model, d, model["unladen"] + left + cargo)
            if need is None:
                stop = {"empty_at": i, "why": "range", "need": None, "left": round(left, 2)}
            elif need > left + 1e-9:
                stop = {"empty_at": i, "why": "fuel", "need": round(need, 2), "left": round(left, 2)}
            else:
                left -= need
                used, after = round(need, 2), round(left, 2)
        rows.append({"i": i, "ly": round(d, 1), "total_ly": round(total, 1), "fuel_used": used, "fuel_left": after})
        prev = h
    if not known:
        return rows, None
    summary = {"start": round(float(fuel), 2), "empty_at": None, "why": None, "last": len(hops) - 1, "need": None,
               "left": None, "end": round(left, 2)}
    if stop:
        summary.update(stop, last=stop["empty_at"] - 1, end=None)
    return rows, summary


def nearest_hops(places, pos, hops, last):
    """Each place ({x, y, z, ...}) with `near`: the system of the route you can still reach (where you are, or a hop
    up to index `last`) it is closest to: {i (-1: where you are), name, ly}."""
    reach = [(-1, pos)] + [(i, h) for i, h in enumerate(hops[:max(0, last + 1)])]
    out = []
    for p in places:
        i, h = min(reach, key=lambda r: math.dist(_xyz(r[1]), _xyz(p)))
        out.append(dict(p, near={"i": i, "name": h.get("name"), "ly": round(math.dist(_xyz(h), _xyz(p)), 1)}))
    return out

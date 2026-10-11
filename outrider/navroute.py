"""The route plotted in the game's galaxy map (NavRoute.json) as a list (this fork). Pure."""
import math


def _xyz(p):
    return (p["x"], p["y"], p["z"])


def rows(hops, pos):
    """The hops ahead of `pos` ({x, y, z}) as rows: {i, ly (this jump), total_ly (flown by then)}."""
    out, total, prev = [], 0.0, pos
    for i, h in enumerate(hops):
        d = math.dist(_xyz(prev), _xyz(h))
        total += d
        out.append({"i": i, "ly": round(d, 1), "total_ly": round(total, 1)})
        prev = h
    return out

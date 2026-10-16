"""Locate (this fork): the nearest places for a need, as EDCoPilot's Location search has them. Interstellar Factors,
black markets, the material traders, the technology brokers (Guardian, Human), outfitting, shipyards and repair are
Spansh's station search, nearest first; mining is Spansh's body search for rings with a hotspot of the mineral asked
for. Read only. The commodities tile (and where a mined mineral sells) is the page's own Sell / Buy lookup.

    station_body(kind, pos, pad), station_rows(results, now)   # pure
    hotspot_body(mineral, pos), hotspot_rows(results, mineral)  # pure
    await locate(state, what, mineral, pad, urls)               # GET /api/locate
"""
import calendar
import time

SIZE = 25              # results per search, nearest first
REACH_LY = 1000        # how far a search reaches
# what -> (its title, Spansh's station search filters)
STATIONS = {
    "factors": ("Interstellar Factors", {"services": [{"name": "Interstellar Factors Contact"}]}),
    "raw": ("Raw material trader", {"material_trader": {"value": ["Raw"]}}),
    "encoded": ("Encoded material trader", {"material_trader": {"value": ["Encoded"]}}),
    "manufactured": ("Manufactured material trader", {"material_trader": {"value": ["Manufactured"]}}),
    "outfitting": ("Ship outfitting", {"services": [{"name": "Outfitting"}]}),
    "shipyard": ("Shipyard", {"services": [{"name": "Shipyard"}]}),
    "repair": ("Repair", {"services": [{"name": "Repair"}]}),
    "black": ("Black market", {"services": [{"name": "Black Market"}]}),
    "guardian": ("Guardian technology broker", {"technology_broker": {"value": ["Guardian"]}}),
    "human": ("Human technology broker", {"technology_broker": {"value": ["Human"]}}),
}
# the minerals rings have hotspots of (Spansh's ring signal names)
MINERALS = ("Alexandrite", "Benitoite", "Bromellite", "Grandidierite", "Low Temperature Diamonds", "Monazite", "Musgravite",
            "Painite", "Platinum", "Rhodplumsite", "Serendibite", "Tritium", "Void Opals", "Osmium", "Gold", "Silver",
            "Palladium", "Samarium", "Praseodymium")
PADS = ("any", "M", "L")
# station types with no landing pad for a ship (Spansh's types): never offered
NO_PADS = {"Settlement", "Odyssey Settlement", "Planetary Construction Depot", "Space Construction Depot", "Drake-Class Carrier"}


def _secs(ts):
    if not isinstance(ts, str) or len(ts) < 19:
        return None
    try:
        return float(calendar.timegm(time.strptime(ts[:19].replace(" ", "T"), "%Y-%m-%dT%H:%M:%S")))
    except ValueError:
        return None


def _id(x):
    """the system's id64 as a string: the page's JSON numbers lose the last digits of one above 2^53"""
    return str(x["system_id64"]) if isinstance(x.get("system_id64"), int) else None


def station_body(kind, pos, pad="any", size=SIZE):
    """Spansh's station search for one kind, nearest `pos` first; pad "L" asks for a large pad."""
    filters = dict(STATIONS[kind][1], distance={"min": "0", "max": str(REACH_LY)})
    if pad == "L":
        filters["has_large_pad"] = {"value": True}
    return {"filters": filters, "sort": [{"distance": {"direction": "asc"}}],
            "reference_coords": {"x": pos["x"], "y": pos["y"], "z": pos["z"]}, "size": size, "page": 0}


def station_rows(results, now=None):
    """Spansh's stations as rows: {name, system, id64 (the system's, a string), distance, ls, pad ("L" or "M"), type, planetary,
    age (s since a player reported it), broker, trader}. Fleet carriers and places without pads are left out."""
    now = time.time() if now is None else now
    out = []
    for x in results or []:
        if not isinstance(x, dict) or not x.get("name") or not x.get("system_name"):
            continue
        if x.get("type") in NO_PADS:
            continue
        seen = _secs(x.get("updated_at"))
        out.append({"name": x["name"], "system": x["system_name"], "id64": _id(x),
                    "distance": round(x["distance"], 1) if isinstance(x.get("distance"), (int, float)) else None,
                    "ls": round(x["distance_to_arrival"]) if isinstance(x.get("distance_to_arrival"), (int, float)) else None,
                    "pad": "L" if x.get("has_large_pad") else "M", "type": x.get("type"), "planetary": bool(x.get("is_planetary")),
                    "age": int(now - seen) if seen is not None else None,
                    "broker": x.get("technology_broker"), "trader": x.get("material_trader")})
    return out


def hotspot_body(mineral, pos, size=SIZE):
    """Spansh's body search for rings with a hotspot of `mineral`, nearest `pos` first."""
    return {"filters": {"ring_signals": [{"name": mineral, "comparison": "<=>", "value": [1, 99]}],
                        "distance": {"min": "0", "max": str(REACH_LY)}},
            "sort": [{"distance": {"direction": "asc"}}], "reference_coords": {"x": pos["x"], "y": pos["y"], "z": pos["z"]},
            "size": size, "page": 0}


def hotspot_rows(results, mineral):
    """Spansh's bodies as hotspot rows: each ring with the mineral, {body, system, id64 (the system's), distance, ls,
    ring (its name), ring_type, count (hotspots of the mineral), others ([[name, count]] of its other hotspots)}."""
    out = []
    for x in results or []:
        if not isinstance(x, dict) or not x.get("system_name"):
            continue
        for ring in x.get("rings") or []:
            if not isinstance(ring, dict):
                continue
            sig = {s.get("name"): s.get("count") for s in ring.get("signals") or [] if isinstance(s, dict) and s.get("name")}
            if not sig.get(mineral):
                continue
            out.append({"body": x.get("name"), "system": x["system_name"], "id64": _id(x),
                        "distance": round(x["distance"], 1) if isinstance(x.get("distance"), (int, float)) else None,
                        "ls": round(x["distance_to_arrival"]) if isinstance(x.get("distance_to_arrival"), (int, float)) else None,
                        "ring": ring.get("name"), "ring_type": ring.get("type"), "count": sig[mineral],
                        "others": sorted(([k, v] for k, v in sig.items() if k != mineral), key=lambda kv: (-(kv[1] or 0), kv[0]))})
    return out


async def locate(state, what, mineral=None, pad="any", urls=None):
    """GET /api/locate?what=&mineral=&pad=: ({title, from, rows, mineral?}, status). urls: fn() -> (Spansh's station
    search, its body search), read when asked (the scratch server points them nowhere)."""
    pos = state.journals.pos
    if what not in STATIONS and what != "mining":
        return {"error": f"what: one of {', '.join(list(STATIONS) + ['mining'])}"}, 400
    if pad not in PADS:
        return {"error": "pad: any, M or L"}, 400
    if what == "mining" and mineral not in MINERALS:
        return {"error": f"mineral: one of {', '.join(MINERALS)}"}, 400
    if not pos or None in (pos.get("x"), pos.get("y"), pos.get("z")):
        return {"error": "no position yet: after your first jump"}, 409
    session = getattr(state.spansh, "session", None)
    if session is None:
        return {"error": "Spansh cannot be reached (no network session)"}, 503
    station_url, body_url = urls()
    body = hotspot_body(mineral, pos) if what == "mining" else station_body(what, pos, pad)
    try:
        async with state.spansh.sem_fast:
            async with session.post(body_url if what == "mining" else station_url, json=body) as r:
                r.raise_for_status()
                d = await r.json()
    except Exception as e:   # Spansh down, slow or odd: said, not raised
        return {"error": f"Spansh could not be asked ({type(e).__name__})"}, 502
    results = (d or {}).get("results") if isinstance(d, dict) else None
    if what == "mining":
        return {"title": f"{mineral} hotspots", "from": pos.get("name"), "mineral": mineral, "rows": hotspot_rows(results, mineral)}, 200
    return {"title": STATIONS[what][0], "from": pos.get("name"), "rows": station_rows(results)}, 200


def add_routes(app, state, urls):
    """GET /api/locate. urls: fn() -> (station search URL, body search URL)."""
    from aiohttp import web

    async def view(request):
        q = request.query
        out, status = await locate(state, q.get("what") or "", q.get("mineral"), q.get("pad") or "any", urls)
        return web.json_response(out, status=status)
    app.router.add_get("/api/locate", view)

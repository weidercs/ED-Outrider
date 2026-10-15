"""The CMDR tab's Earnings (NEXT-VERSION #7): what exploration, exobiology and mining paid you, when, where, with which
ship and for what. Everything comes from what the journal reader keeps (ed_outrider.py, PARSER_VERSION 52 and 53):
sale_events (each cartographic and Vista Genomics sale, where you were docked and the ship you flew), bio_sales (what
each species in a sale paid), mining_sales (the mined part of each MarketSell, Journals.note_mined's rule), jumps,
own_bodies and own_organic (each with its ship) and play_activity (the tons refined per login).

`read` gathers a period's rows from the database (SQL only, nothing written); `summary` folds them into GET
/api/commander/earnings' answer and `csv_rows` into /api/export?what=earnings' rows, both pure. State.commander_earnings
hands in what it owns: the ships' names, the commodities' names, the stars' names, History's Ledger's losses and its own
estimate of each system sold.

Exact figures are the game's, what each sale paid. Outrider's estimates only where nothing else answers, always under
`estimates`: the systems sold by value (the game pays per page of systems, not per system) and the data lost to deaths
(the Ledger's, never counted again here). Sales of mined ore to your own carrier are left out of every total (your own
money); cartographic and exobiology data sold at your carrier count (the game pays them). Times are the journal's, UTC:
a month is a UTC month.
"""
import json
import re

SALES_MAX = 500     # the sales listed, the newest first; `more` says how many were left out (the CSV has them all)
TOP = 10            # the rows of each "most" list: species, stations, systems, star classes, body types
BEST_MINING = 5     # the best mining sales listed
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December")


def period(year=None, month=None):
    """The period asked for, from the query's strings ("" or None: not given): {kind: all | year | month, label, year,
    month, start, end} (start inclusive, end exclusive, ISO times as the journal's; all time "" .. "~"). year: four
    digits; month: 1 to 12, only with a year. A bad one raises ValueError with the words to answer."""
    year = None if year in (None, "") else str(year)
    month = None if month in (None, "") else str(month)
    if year is None:
        if month is not None:
            raise ValueError("month: only with a year")
        return {"kind": "all", "label": "All time", "year": None, "month": None, "start": "", "end": "~"}
    if not re.fullmatch(r"[0-9]{4}", year):
        raise ValueError("year: four digits")
    y = int(year)
    if month is None:
        return {"kind": "year", "label": year, "year": y, "month": None, "start": f"{y:04d}-01-01T00:00:00Z",
                "end": f"{y + 1:04d}-01-01T00:00:00Z"}
    if not re.fullmatch(r"[0-9]{1,2}", month) or not 1 <= int(month) <= 12:
        raise ValueError("month: 1 to 12")
    m = int(month)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return {"kind": "month", "label": f"{MONTHS[m - 1]} {y}", "year": y, "month": m,
            "start": f"{y:04d}-{m:02d}-01T00:00:00Z", "end": f"{ny:04d}-{nm:02d}-01T00:00:00Z"}


def _rows(db, sql, *args):
    return [dict(r) for r in db.execute(sql, args)]


def read(db, p):
    """The period's rows (p: period()'s), and the all-time monthly sums the chart shows whatever the period. Reads only.
    {sales: sale_events newest first, mining: mining_sales newest first, bio: bio_sales, jumps: in time order, before:
    the arrival before the period's first (where its first jump started), bodies: your first scans (own_firsts' first_ts,
    else the scan's), organic: completed sample runs, refined: play_activity's mining by login, systems: the systems sold
    (sales: name, latest sale), names: {species key: name} from your runs, markets: {market_id: station type} from the
    data sales (a mining sale's own type is NULL in a database read before it was kept), months: [(month, kind,
    total)]}."""
    a, b = p["start"], p["end"]
    return {
        "sales": _rows(db, "SELECT ts, kind, base, bonus, total, systems, species, station, market_id, station_type, ship_id "
                           "FROM sale_events WHERE ts >= ? AND ts < ? ORDER BY ts DESC, source DESC", a, b),
        "mining": _rows(db, "SELECT ts, commodity, tons, mined_tons, price, total, mined_total, station, market_id, station_type, "
                            "ship_id, own_carrier FROM mining_sales WHERE ts >= ? AND ts < ? ORDER BY ts DESC, source DESC", a, b),
        "bio": _rows(db, "SELECT ts, bio_data FROM bio_sales WHERE ts >= ? AND ts < ?", a, b),
        "jumps": _rows(db, "SELECT ts, id64, x, y, z, star_class, kind, ship_id FROM jumps WHERE ts >= ? AND ts < ? "
                           "ORDER BY ts", a, b),
        "before": next(iter(_rows(db, "SELECT x, y, z FROM jumps WHERE ts < ? ORDER BY ts DESC LIMIT 1", a)), None),
        "bodies": _rows(db, "SELECT b.ship_id, coalesce(f.first_ts, b.ts) AS ts, json_extract(b.record, '$.type') AS type, "
                            "json_extract(b.record, '$.subtype') AS subtype FROM own_bodies b LEFT JOIN own_firsts f "
                            "ON f.system = b.system AND f.body_id = b.body_id "
                            "WHERE coalesce(f.first_ts, b.ts) >= ? AND coalesce(f.first_ts, b.ts) < ?", a, b),
        "organic": _rows(db, "SELECT species, species_name, done_ts AS ts, ship_id FROM own_organic "
                             "WHERE done_ts >= ? AND done_ts < ?", a, b),
        "refined": [json.loads(r["mining"]) for r in db.execute(
            "SELECT mining FROM play_activity WHERE mining IS NOT NULL AND login_ts >= ? AND login_ts < ?", (a, b))],
        "systems": _rows(db, "SELECT name, max(ts) AS ts FROM sales WHERE ts >= ? AND ts < ? AND name IS NOT NULL "
                             "GROUP BY name", a, b),
        "names": {(r[0] or "").lower(): r[1] for r in db.execute(
            "SELECT species, species_name FROM own_organic WHERE species_name IS NOT NULL")},
        "markets": {r[0]: r[1] for r in db.execute(
            "SELECT market_id, max(station_type) FROM sale_events WHERE market_id IS NOT NULL AND station_type IS NOT NULL "
            "GROUP BY market_id")},
        "months": [tuple(r) for r in db.execute("SELECT substr(ts, 1, 7), kind, sum(total) FROM sale_events GROUP BY 1, 2")]
                  + [(r[0], "mining", r[1]) for r in db.execute(
                      "SELECT substr(ts, 1, 7), sum(mined_total) FROM mining_sales WHERE own_carrier = 0 GROUP BY 1")],
    }


def month_series(months):
    """The chart's bars: every month from the first with a sale to the last, the empty ones too (no gaps), each
    {month "YYYY-MM", carto, bio, mining} in credits. months: [(month, kind, total)] (read's)."""
    got = {}
    for m, kind, total in months:
        if m and kind in ("carto", "bio", "mining"):
            got.setdefault(m, {"carto": 0, "bio": 0, "mining": 0})[kind] += int(total or 0)
    if not got:
        return []
    out, (y, m) = [], map(int, min(got).split("-"))
    last = max(got)
    while True:
        key = f"{y:04d}-{m:02d}"
        out.append(dict({"month": key}, **got.get(key, {"carto": 0, "bio": 0, "mining": 0})))
        if key >= last:
            return out
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _station_type(data, r):
    """A mining sale's station type: its own, else the one a data sale at that market recorded."""
    return r.get("station_type") or data["markets"].get(r["market_id"])


def _ship(ships, sid):
    """A sale's or a row's ship: {id, name, type (the game's symbol), type_name} from `ships` (by ShipID), None when the
    ship was not known (a ride, a line from before PARSER_VERSION 52, one read out of order). A blank name (the game keeps
    " " for a ship whose name was cleared) is no name."""
    if sid is None:
        return None
    s = ships.get(sid) or {}
    return {"id": sid, "name": (s.get("name") or "").strip() or None, "type": s.get("type") or None, "type_name": s.get("type_name") or None}


def sales(data, ships=None, commodity=None):
    """Every sale of the period, the newest first: {ts, kind (carto | bio | mining), station, station_type, market_id,
    ship, what ({systems} | {species} | {commodity, tons, of}: the tons mined of the tons sold), base, bonus, total}. A
    mining sale is its mined part only (base and bonus None: the market pays one price), never one to your own carrier.
    commodity: the journal id -> its name (else the id as it is)."""
    ships, commodity = ships or {}, commodity or (lambda i: i)
    out = [{"ts": r["ts"], "kind": r["kind"], "station": r["station"], "station_type": r["station_type"],
            "market_id": r["market_id"], "ship": _ship(ships, r["ship_id"]),
            "what": {"systems": r["systems"] or 0} if r["kind"] == "carto" else {"species": r["species"] or 0},
            "base": r["base"], "bonus": r["bonus"], "total": r["total"] or 0} for r in data["sales"]]
    out += [{"ts": r["ts"], "kind": "mining", "station": r["station"], "station_type": _station_type(data, r),
             "market_id": r["market_id"], "ship": _ship(ships, r["ship_id"]),
             "what": {"commodity": commodity(r["commodity"]), "tons": r["mined_tons"], "of": r["tons"]},
             "base": None, "bonus": None, "total": r["mined_total"] or 0} for r in data["mining"] if not r["own_carrier"]]
    out.sort(key=lambda s: s["ts"], reverse=True)   # stable: each table's own order kept within a second
    return out


def crew_share(r):
    """What your NPC crew took of one data sale: base + bonus - total, the game's own figures (a hired crew member takes a
    share of every cartographic sale: 9 % in the author's journals until the crew was fired), 0 when none."""
    if r.get("base") is None or r.get("total") is None:
        return 0
    return max(0, (r["base"] or 0) + (r["bonus"] or 0) - (r["total"] or 0))


def totals(data):
    """{carto: {base, bonus, crew, total, sales, systems}, bio: {base, bonus, crew, total, sales, species}, mining: {total,
    tons, sales}, total, sales}: what the period's sales paid (mining: the mined part, your own carrier left out). total
    is what you were paid: base + bonus less your NPC crew's share (crew)."""
    out = {}
    for kind, count in (("carto", "systems"), ("bio", "species")):
        rows = [r for r in data["sales"] if r["kind"] == kind]
        out[kind] = {k: sum(r[k] or 0 for r in rows) for k in ("base", "bonus", "total")}
        out[kind].update({"crew": sum(crew_share(r) for r in rows), "sales": len(rows), count: sum(r[count] or 0 for r in rows)})
    mined = [r for r in data["mining"] if not r["own_carrier"]]
    out["mining"] = {"total": sum(r["mined_total"] or 0 for r in mined), "tons": sum(r["mined_tons"] or 0 for r in mined),
                     "sales": len(mined)}
    out["total"] = out["carto"]["total"] + out["bio"]["total"] + out["mining"]["total"]
    out["sales"] = out["carto"]["sales"] + out["bio"]["sales"] + out["mining"]["sales"]
    return out


def species(data, limit=TOP):
    """The species that paid most in the period, exact from each sale's BioData: [{name, count (entries sold), value,
    bonus, total}], the most paid first. A sale stored before PARSER_VERSION 53 named its species without their pay: they
    count with 0 cr."""
    got = {}
    for r in data["bio"]:
        for e in json.loads(r["bio_data"]) if r["bio_data"] else []:
            key = e[0]
            name = (e[4] if len(e) > 4 else None) or data["names"].get(key) or _tidy(key)
            s = got.setdefault(key, {"name": name, "count": 0, "value": 0, "bonus": 0})
            s["count"] += 1
            s["value"] += e[2] if len(e) > 2 else 0
            s["bonus"] += e[3] if len(e) > 3 else 0
    rows = [dict(s, total=s["value"] + s["bonus"]) for s in got.values()]
    rows.sort(key=lambda s: (-s["total"], -s["count"], s["name"]))
    return rows[:limit]


def _tidy(key):
    """A codex key with no name on record: "$codex_ent_bacterial_01_name;" -> "bacterial 01"."""
    return re.sub(r"^\$?codex_ent_|_name;$|;$", "", key or "?").replace("_", " ")


def stations(sold, limit=TOP):
    """Where you sold most in the period: [{name, type, sales, total}], by market (a station renamed keeps its row), the
    most paid first. sold: sales()'s rows; those with no known place are left out."""
    got = {}
    for s in sold:
        if not s["station"]:
            continue
        r = got.setdefault(s["market_id"] or s["station"], {"name": s["station"], "type": s["station_type"], "sales": 0,
                                                            "total": 0})
        r["sales"] += 1
        r["total"] += s["total"]
        r["type"] = r["type"] or s["station_type"]
    rows = sorted(got.values(), key=lambda r: (-r["total"], -r["sales"], r["name"]))
    return rows[:limit]


def _dist(a, b):
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2) ** 0.5


def per_ship(data, sold, ships=None):
    """Each ship's period: [{id, name, type, type_name, jumps, ly, bodies, species, earnings, days}], the most earned
    first. jumps and ly: its own FSD jumps (a carrier's jump or a ride is not the ship's), each measured from the
    arrival before it, whichever way you got there (a ship swapped at a station starts where the last one stopped);
    bodies: the bodies you first scanned flying it; species: the sample runs completed with it (on foot or in the SRV, the
    ship you came in); earnings: the sales made while flying it (sold: sales()'s); days: the UTC days with any of
    those."""
    ships, got = ships or {}, {}

    def row(sid):
        return got.setdefault(sid, dict(_ship(ships, sid), jumps=0, ly=0.0, bodies=0, species=0, earnings=0, days=set()))
    prev = data["before"]
    for j in data["jumps"]:
        if j["kind"] == "FSDJump" and j["ship_id"] is not None:
            r = row(j["ship_id"])
            r["jumps"] += 1
            if prev and None not in (prev["x"], j["x"]):
                r["ly"] += _dist(prev, j)
            r["days"].add(j["ts"][:10])
        prev = j
    for key, rows in (("bodies", data["bodies"]), ("species", data["organic"])):
        for x in rows:
            if x["ship_id"] is not None:
                r = row(x["ship_id"])
                r[key] += 1
                r["days"].add(x["ts"][:10])
    for s in sold:
        if s["ship"]:
            r = row(s["ship"]["id"])
            r["earnings"] += s["total"]
            r["days"].add(s["ts"][:10])
    out = [dict(r, ly=round(r["ly"], 1), days=len(r["days"])) for r in got.values()]
    out.sort(key=lambda r: (-r["earnings"], -r["jumps"], r["id"]))
    return out


def mining(data, commodity=None):
    """The period's mining: {earned (the mined part of each sale, your own carrier left out), tons (mined tons sold),
    sales, commodities: [{name, refined (t, the ship's refinery), refined_srv (t, the SRV's), sold (mined t sold),
    earned, per_ton}], stations: [{name, type, sales, tons, earned, per_ton}], best: [{ts, commodity, tons, earned,
    per_ton, station}], own_carrier: {sales, tons, total}: left out}. Refined tons are the logins' (play_activity) that
    began in the period, as the Sessions part counts them; sold tons are the sales'."""
    commodity = commodity or (lambda i: i)
    mine = [r for r in data["mining"] if not r["own_carrier"]]
    own = [r for r in data["mining"] if r["own_carrier"]]
    per = lambda e, t: round(e / t) if t else None
    goods = {}

    def good(name):
        return goods.setdefault(name, {"name": name, "refined": 0, "refined_srv": 0, "sold": 0, "earned": 0})
    for m in data["refined"]:
        for key, into in (("refined", "refined"), ("srv", "refined_srv")):
            for name, t in (m.get(key) or {}).items():
                good(name)[into] += t
    for r in mine:
        g = good(commodity(r["commodity"]))
        g["sold"] += r["mined_tons"] or 0
        g["earned"] += r["mined_total"] or 0
    where = {}
    for r in mine:
        if not r["station"]:
            continue
        w = where.setdefault(r["market_id"] or r["station"], {"name": r["station"], "type": _station_type(data, r),
                                                              "sales": 0, "tons": 0, "earned": 0})
        w["sales"] += 1
        w["tons"] += r["mined_tons"] or 0
        w["earned"] += r["mined_total"] or 0
    best = sorted(mine, key=lambda r: (-(r["mined_total"] or 0), r["ts"]))[:BEST_MINING]
    return {"earned": sum(r["mined_total"] or 0 for r in mine), "tons": sum(r["mined_tons"] or 0 for r in mine),
            "sales": len(mine),
            "commodities": sorted((dict(g, per_ton=per(g["earned"], g["sold"])) for g in goods.values()),
                                  key=lambda g: (-g["earned"], -(g["refined"] + g["refined_srv"]), g["name"])),
            "stations": sorted((dict(w, per_ton=per(w["earned"], w["tons"])) for w in where.values()),
                               key=lambda w: (-w["earned"], w["name"]))[:TOP],
            "best": [{"ts": r["ts"], "commodity": commodity(r["commodity"]), "tons": r["mined_tons"], "earned": r["mined_total"],
                      "per_ton": per(r["mined_total"] or 0, r["mined_tons"]), "station": r["station"]} for r in best],
            "own_carrier": {"sales": len(own), "tons": sum(r["mined_tons"] or 0 for r in own),
                            "total": sum(r["mined_total"] or 0 for r in own)}}


def _count(values, limit=TOP):
    got = {}
    for v in values:
        if v:
            got[v] = got.get(v, 0) + 1
    return sorted(got.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def common(data, star_name=None):
    """What you met most in the period: {stars: [{class, name, count}] (the main star of each system you arrived at,
    once per system), bodies: [{type, count}] (the planets you first scanned; stars are the list above), species:
    [{name, count}] (your completed sample runs)}. star_name: a star class -> its name."""
    star_name = star_name or (lambda c: c)
    systems = {j["id64"]: j["star_class"] for j in data["jumps"] if j["kind"] != "Location"}
    return {"stars": [{"class": c, "name": star_name(c), "count": n} for c, n in _count(systems.values())],
            "bodies": [{"type": t, "count": n} for t, n in _count(b["subtype"] for b in data["bodies"] if b["type"] == "Planet")],
            "species": [{"name": s, "count": n} for s, n in _count(o["species_name"] or _tidy(o["species"])
                                                                  for o in data["organic"])]}


def estimates(data, p, systems=None, losses=()):
    """Outrider's estimates, labelled as such: {label: "estimate", top_systems: [{name, id, value, bodies, sold}] (the
    systems sold in the period by Outrider's value of your scans of them: `systems` {name: {id, value, bodies}}; the game
    pays per page, so no sale says what one system paid), systems (how many were sold), lost: {deaths, ships, value,
    carto, bio}: History's Ledger's losses (its ship_losses rows) in the period, taken as they are}."""
    systems = systems or {}
    top = []
    for s in data["systems"]:
        v = systems.get(s["name"])
        if v and v.get("value"):
            top.append({"name": s["name"], "id": v.get("id"), "value": v["value"], "bodies": v.get("bodies"), "sold": s["ts"]})
    top.sort(key=lambda s: (-s["value"], s["name"]))
    lost = [x for x in losses if p["start"] <= x["ts"] < p["end"]]
    carto, bio = round(sum(x.get("value") or 0 for x in lost)), round(sum(x.get("bio_value") or 0 for x in lost))
    return {"label": "estimate", "top_systems": top[:TOP], "systems": len(data["systems"]),
            "lost": {"deaths": len(lost), "ships": sum(1 for x in lost if x.get("ship")), "value": carto + bio,
                     "carto": carto, "bio": bio}}


def notes(t, m):
    """The short lines the page shows under the figures (t: totals(), m: mining())."""
    out = ["Exact: what each sale paid, as the journal says."]
    crew = t["carto"]["crew"] + t["bio"]["crew"]
    if crew:
        out.append(f"Your NPC crew's share of your data sales ({crew:,} cr) went to them: a total is the base and bonus "
                   f"less that share, what you were paid.")
    out += ["Mining counts the ore you mined, from refining to its sale; tons bought and sold with it are trade, left out."]
    if m["own_carrier"]["sales"]:
        out.append(f"Mined ore sold to your own carrier is left out (your own money): {m['own_carrier']['sales']} "
                   f"sale{'s' if m['own_carrier']['sales'] != 1 else ''}, {m['own_carrier']['total']:,} cr.")
    else:
        out.append("Mined ore sold to your own carrier is left out (your own money).")
    out += ["Cartographic and exobiology data sold at your carrier counts: the game pays it.",
            "Estimates: a system's value is Outrider's from your scans (the game pays per page of systems), and the data "
            "lost to deaths is History's Ledger's.",
            "Months are UTC, as the journal's times."]
    return out


def summary(p, data, ships=None, commodity=None, star_name=None, systems=None, losses=(), limit=SALES_MAX):
    """GET /api/commander/earnings' answer for period p (period()'s) over read()'s data: {period: {kind, label, year,
    month}, totals, months (all time, for the chart), years (with a sale), sales (at most `limit`, the newest first),
    more (how many were left out), species, stations, ships, mining, common, estimates, notes}. ships: {ShipID: {name,
    type, type_name}}; commodity, star_name: id -> name; systems, losses: estimates()'s."""
    sold = sales(data, ships, commodity)
    t, m = totals(data), mining(data, commodity)
    months = month_series(data["months"])
    return {"period": {k: p[k] for k in ("kind", "label", "year", "month")}, "totals": t, "months": months,
            "years": sorted({int(x["month"][:4]) for x in months if x["carto"] or x["bio"] or x["mining"]}),
            "sales": sold[:limit], "more": max(0, len(sold) - limit), "species": species(data),
            "stations": stations(sold), "ships": per_ship(data, sold, ships), "mining": m,
            "common": common(data, star_name), "estimates": estimates(data, p, systems, losses), "notes": notes(t, m)}


CSV_COLUMNS = ["ts", "kind", "station", "station_type", "ship", "what", "base", "bonus", "total"]


def csv_rows(sold):
    """/api/export?what=earnings: every sale as a CSV row (CSV_COLUMNS), the ship and what was sold in words."""
    def ship(s):
        if not s:
            return ""
        kind = s["type_name"] or s["type"]
        return f"{s['name']} ({kind})" if s["name"] and kind else s["name"] or kind or str(s["id"])

    def what(w):
        if "systems" in w:
            return f"{w['systems']} system{'s' if w['systems'] != 1 else ''}"
        if "species" in w:
            return f"{w['species']} species"
        return f"{w['tons']} t {w['commodity']}" + (f" (of {w['of']} t sold)" if w["of"] and w["of"] > w["tons"] else "")
    return [{"ts": s["ts"], "kind": s["kind"], "station": s["station"] or "", "station_type": s["station_type"] or "",
             "ship": ship(s["ship"]), "what": what(s["what"]), "base": s["base"], "bonus": s["bonus"], "total": s["total"]}
            for s in sold]

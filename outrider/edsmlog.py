"""Your EDSM flight log from before your journals (S67), its database half: the server (ed_outrider.py) walks EDSM's
get-logs back a week at a time (outrider/readclient.py, paced) and hands each week's entries to `store`; this module
keeps them in the table edsm_log and answers which of them count as visits.

Which entries count is decided at every read, never at the import: an entry before the oldest journal (the first row
of `jumps`) with no journal arrival within MATCH_S of it. Both move after a journal re-read or a legacy folder's import,
so every fetched entry is kept and the rule is applied in the query: journal data always wins. Not a VIEW over visits
(the review's correction): the places that show visits ask this module with a second, small query of their own (a box
on edsm_log's own x, y, z index, the id64 set once per refresh).

What it is NOT used for: firsts, sales, discoveries, the codex, your own scans or anything counted from them. Those come
from the journals only (EDSM's firstDiscover is not even kept). Every commander whose log was imported counts as "you".
"""
import math

from outrider.core import iso_ts, ts_seconds

GAME_LAUNCH = "2014-12-16T00:00:00Z"   # Elite Dangerous's release: the import goes back no further
MATCH_S = 60                           # an entry this close to a journal arrival is that arrival
SESSION_GAP_S = 7200                   # History's sessions: a gap of 2 h splits them, as the journal's
RESOLVE_MAX = 500                      # systems EDSM gave no position for, looked up by name after an import at most


def cutoff(db):
    """The oldest journal arrival's time (jumps_ts index: one step), or None with no journals read."""
    return db.execute("SELECT min(ts) FROM jumps").fetchone()[0]


def _counts(cut):
    """The WHERE clause (on edsm_log e) of the entries that count as visits, and its parameters. An entry well before the
    cutoff cannot have a journal arrival near it: the per-entry look into jumps is only made at the edge."""
    return ("(?1 IS NULL OR e.ts < ?1) AND (e.hi < ?1 OR NOT EXISTS (SELECT 1 FROM jumps j WHERE j.ts BETWEEN e.lo AND e.hi))",
            [cut])


def store(db, commander, logs):
    """Keep get-logs' entries ({system, id64, coords, date} as readclient.edsm_logs_answer gives them); one row per time
    and system, so a week read twice (a resumed import) never doubles. -> how many were new."""
    n = 0
    for e in logs:
        t = ts_seconds(e["date"])
        c = e.get("coords") or {}
        cur = db.execute("INSERT OR IGNORE INTO edsm_log (ts, name, id64, x, y, z, lo, hi, commander) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (e["date"], e["system"], e.get("id64"), c.get("x"), c.get("y"), c.get("z"), iso_ts(t - MATCH_S),
                          iso_ts(t + MATCH_S), commander))
        n += cur.rowcount
    return n


def stored(db):
    """Every entry kept, counting or not."""
    return db.execute("SELECT count(*) FROM edsm_log").fetchone()[0]


def counted(db):
    """{visits, systems, first, last} of the entries that count now (the Settings line), or None with none."""
    where, p = _counts(cutoff(db))
    r = db.execute(f"SELECT count(*), count(DISTINCT coalesce(id64, name)), min(ts), max(ts) FROM edsm_log e WHERE {where}", p).fetchone()
    return {"visits": r[0], "systems": r[1], "first": r[2], "last": r[3]} if r[0] else None


def rows(db, box=None, ids=None, name=None, like=None):
    """The systems visited by EDSM's log, one row each: [{id64, name, x, y, z, first_ts, last_ts, count}]. box: (x0, x1,
    y0, y1, z0, z1); ids: only these id64s; name: this name (any case); like: a LIKE pattern on the name (escaped with
    a backslash)."""
    where, p = _counts(cutoff(db))
    if box:
        where += " AND e.x BETWEEN ? AND ? AND e.y BETWEEN ? AND ? AND e.z BETWEEN ? AND ?"
        p += list(box)
    if ids is not None:
        ids = list(ids)
        if not ids:
            return []
        where += f" AND e.id64 IN ({','.join('?' * len(ids))})"
        p += ids
    if name is not None:
        where += " AND e.name = ? COLLATE NOCASE"
        p.append(name)
    if like is not None:
        where += " AND e.name LIKE ? ESCAPE '\\'"
        p.append(like)
    sql = (f"SELECT id64, name, max(x) AS x, max(y) AS y, max(z) AS z, min(ts) AS first_ts, max(ts) AS last_ts, count(*) AS count "
           f"FROM edsm_log e WHERE {where} GROUP BY coalesce(id64, name)")
    return [dict(r) for r in db.execute(sql, p)]


def ids(db):
    """The id64s of the systems EDSM's log has you visit (Nearby's and Search's visited marks, extended once per read)."""
    where, p = _counts(cutoff(db))
    return {r[0] for r in db.execute(f"SELECT DISTINCT id64 FROM edsm_log e WHERE id64 IS NOT NULL AND {where}", p)}


def visit(db, id64):
    """{first_ts, last_ts, count, edsm: True} of one system by EDSM's log, or None."""
    r = rows(db, ids=[id64])
    return {"first_ts": r[0]["first_ts"], "last_ts": r[0]["last_ts"], "count": r[0]["count"], "edsm": True} if r else None


def locate(db, id64):
    """(name, x, y, z) of a system any kept entry places (counting or not: a position is a position), or None."""
    r = db.execute("SELECT name, x, y, z FROM edsm_log WHERE id64 = ? AND x IS NOT NULL LIMIT 1", (id64,)).fetchone()
    return tuple(r) if r else None


def unlocated(db, limit=RESOLVE_MAX):
    """The names of systems kept without an id64 or a position (EDSM did not know where they are), at most `limit`."""
    return [r[0] for r in db.execute("SELECT DISTINCT name FROM edsm_log WHERE id64 IS NULL OR x IS NULL LIMIT ?", (limit,))]


def set_location(db, name, id64, x, y, z):
    """A position (and id64) found by name for the entries that lacked it."""
    db.execute("UPDATE edsm_log SET id64 = coalesce(id64, ?), x = ?, y = ?, z = ? WHERE name = ? AND (id64 IS NULL OR x IS NULL)",
               (id64, x, y, z, name))


def remove(db):
    """Every imported entry forgotten (Remove them): your journals' visits are not touched. -> how many."""
    return db.execute("DELETE FROM edsm_log").rowcount


def sessions(db, since=""):
    """History's sessions from EDSM's log (since `since`), newest first, shaped as State.sessions' with every count from
    your journals 0 (EDSM's log holds where you went, nothing of what you did there) and edsm True."""
    where, p = _counts(cutoff(db))
    out, cur, prev = [], None, None
    for r in db.execute(f"SELECT ts, id64, name, x, y, z FROM edsm_log e WHERE {where} AND e.ts >= ? ORDER BY ts", p + [since]):
        t = ts_seconds(r["ts"])
        if not cur or t - cur["_last"] > SESSION_GAP_S:
            cur = {"start": r["ts"], "end": r["ts"], "from": r["ts"], "until": None, "_last": t, "jumps": 0, "ly": 0.0,
                   "max_sol": 0.0, "systems": [], "deaths": [], "edsm": True, "firsts": 0, "bodies_first": 0, "mapped": 0,
                   "footfalls": 0, "samples": 0, "codex_new": 0, "sold": 0, "died": 0, "lost": 0}
            out.append(cur)
            prev = None
        cur["end"], cur["_last"] = r["ts"], t
        cur["jumps"] += 1
        if r["x"] is not None:
            if prev is not None:
                cur["ly"] += math.dist((prev["x"], prev["y"], prev["z"]), (r["x"], r["y"], r["z"]))
            cur["max_sol"] = max(cur["max_sol"], math.sqrt(r["x"] ** 2 + r["y"] ** 2 + r["z"] ** 2))
            prev = r
        cur["systems"].append({"ts": r["ts"], "id": str(r["id64"]) if r["id64"] is not None else None, "name": r["name"],
                               "kind": "FSDJump"})
    for s in out:
        s["ly"], s["max_sol"] = round(s["ly"], 1), round(s["max_sol"])
        s.pop("_last")
    out.reverse()
    return out


def summary(sessions_):
    """History's From EDSM line over every EDSM session: {sessions, jumps, ly, since, until}, or None."""
    if not sessions_:
        return None
    return {"sessions": len(sessions_), "jumps": sum(s["jumps"] for s in sessions_),
            "ly": round(sum(s["ly"] for s in sessions_), 1), "since": sessions_[-1]["start"], "until": sessions_[0]["end"]}

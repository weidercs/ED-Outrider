"""One-off probe of Spansh's Earth-like / ammonia world routes and its tourist router (S52, S51): the requests Spansh's
own pages send, and the answers saved.

    python scripts/route_probe.py elw "Colonia" 50 [out.json]      (an Earth-like world route: start, jump range)
    python scripts/route_probe.py aw "Colonia" 50 [out.json]       (an ammonia world route)
    python scripts/route_probe.py tourist "Sol" 30 "Alpha Centauri" "Barnard's Star" [--loop] [--out out.json]

Found 2026-10-13 (tests/fixtures/spansh_body_types.json and spansh_tourist.json hold those answers): there is no
/api/earth/route or /api/ammonia/route; spansh.co.uk/earth and /ammonia POST /api/riches/route with body_types (a
repeated form field: "Earth-like world", "Ammonia world") and min_value 1, and the answer is Road to Riches'.
spansh.co.uk/tourist POSTs /api/tourist/route with source, range, loop, final_destination (optional) and destination
(repeated); its result's system_jumps are the systems in the order to visit, each with the jumps from the one before;
an unknown destination is refused at once (HTTP 400, "Could not find destination systems [A, B]"). Compare with
outrider/riches.py (SURVEY_KINDS, tourist_rows, unknown_systems). Not part of the tests or of Outrider."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://spansh.co.uk/api"
UA = {"User-Agent": "ED-Outrider route probe"}


def call(method, url, params=None):
    data = urllib.parse.urlencode(params, doseq=True).encode() if params else None   # doseq: repeated fields
    req = urllib.request.Request(url, data=data, method=method, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:300]


def job(path, params, out_path):
    status, out = call("POST", BASE + path, params)
    print("POST", path, "->", status, str(out)[:200])
    j = out.get("job") if isinstance(out, dict) else None
    if not j:
        return
    for _ in range(60):
        time.sleep(2)
        status, res = call("GET", f"{BASE}/results/{j}")
        if isinstance(res, dict) and res.get("status") not in (None, "queued", "running"):
            break
    else:
        print("the job did not finish in 2 minutes")
        return
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    r = res.get("result") if isinstance(res, dict) else None
    print("saved", out_path, "· answer keys:", sorted(res) if isinstance(res, dict) else type(res).__name__)
    first = (r.get("system_jumps") if isinstance(r, dict) else r or [None])[0]
    print("system keys:", sorted(first) if isinstance(first, dict) else first)


def main():
    args = sys.argv[1:]
    kind = args[0] if args else "elw"
    if kind in ("elw", "aw"):
        frm = args[1] if len(args) > 1 else "Colonia"
        rng = args[2] if len(args) > 2 else "50"
        out = args[3] if len(args) > 3 else f"{kind}_probe.json"
        params = {"from": frm, "range": rng, "radius": 50, "max_results": 4, "max_distance": 50000, "min_value": 1,
                  "body_types": ["Earth-like world" if kind == "elw" else "Ammonia world"], "loop": 0, "avoid_thargoids": 1}
        return job("/riches/route", params, out)
    if kind == "tourist":
        out = args[args.index("--out") + 1] if "--out" in args else "tourist_probe.json"
        rest = [a for i, a in enumerate(args[1:], 1) if a not in ("--loop", "--out") and args[i - 1] != "--out"]
        if len(rest) < 3:
            sys.exit("give the start, the range and at least one system to visit")
        params = {"source": rest[0], "range": rest[1], "destination": rest[2:], "loop": int("--loop" in args)}
        return job("/tourist/route", params, out)
    sys.exit("elw, aw or tourist")


if __name__ == "__main__":   # imported (a one-off check), it probes nothing
    main()

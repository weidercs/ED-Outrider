"""One-off probe of Spansh's exact plotter (P1 of the held-suggestions plan): does a route's every jump say whether
its star is scoopable? Saves the real answers.

    python scripts/exact_probe.py [out.json]    (where to save the answers; exact_probe.json in the current folder)

Three read-only route jobs for a made-up 30 ly explorer (Sol to Jackson's Lighthouse, Sol to Polaris, and Sol to Polaris
again with a 128 t tank, so scoopable stars need not all be refuel stops): each end's id64 from Spansh's search by name,
the job submitted with GET (as Spansh.plot does), its result polled. Prints every key a
jump carries, and whether any looks like a scoopable flag or a star class. tests/fixtures/spansh_exact.json is a
trimmed copy of one run (2026-10-13), so it is not overwritten by default. Compare with outrider/highway.py
(highway_rows). Not part of the tests or of Outrider."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://spansh.co.uk/api"
UA = {"User-Agent": "ED-Outrider exact plotter probe"}
SHIP = {"is_supercharged": 0, "use_supercharge": 1, "use_injections": 0, "exclude_secondary": 0, "fuel_power": 2.3,
        "fuel_multiplier": 0.012, "optimal_mass": 900, "supercharge_multiplier": 4, "base_mass": 280.5, "tank_size": 32,
        "internal_tank_size": 0.5, "max_fuel_per_jump": 3.0, "range_boost": 0, "cargo": 0}


def get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode(errors="replace")[:300]}
    except (OSError, ValueError) as e:
        return {"http_error": str(e)}


def id64(name):
    d = get(BASE + "/search/systems", {"q": name})
    for x in (d.get("results") or []) if isinstance(d, dict) else []:
        if str(x.get("name") or "").lower() == name.lower():
            return x["id64"]
    return None


def route(frm, to, **ship):
    d = get(BASE + "/generic/route", dict(SHIP, source=id64(frm), destination=id64(to), **ship))
    for _ in range(90):
        if not isinstance(d, dict) or d.get("result") is not None or d.get("http_error") or not d.get("job"):
            return d
        time.sleep(2)
        d = get(f"{BASE}/results/{d['job']}")
    return {"http_error": "the job did not finish in 3 minutes"}


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "exact_probe.json"
    answers = {}
    for frm, to, ship in (("Sol", "Jackson's Lighthouse", {}), ("Sol", "Polaris", {}), ("Sol", "Polaris", {"tank_size": 128})):
        name = f"{frm} to {to}" + (f", {ship['tank_size']} t tank" if ship else "")
        d = route(frm, to, **ship)
        answers[name] = d
        jumps = ((d or {}).get("result") or {}).get("jumps") or []
        keys = sorted({k for j in jumps for k in j})
        print(f"{name}: {len(jumps)} jumps", d.get("http_error") or "")
        print("   scoopable without a refuel:", [j["name"] for j in jumps if j.get("is_scoopable") and not j.get("must_refuel")])
        print("   refuel, not scoopable:", [j["name"] for j in jumps if j.get("must_refuel") and not j.get("is_scoopable")])
        print("   jump keys:", keys)
        print("   scoop-like keys:", [k for k in keys if "scoop" in k.lower() or "star" in k.lower() or "class" in k.lower()])
        time.sleep(2)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=1)
    print("saved", out_path)


main()

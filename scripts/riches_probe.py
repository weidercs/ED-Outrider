"""One-off probe of Spansh's Road to Riches API: finds out whether it takes POST or GET, and saves the real answer.

    python scripts/riches_probe.py "Colonia" 50 [out.json]    (start system, jump range in ly, where to save the answer)

It asks for a small route (5 systems), tries POST (form fields) and then GET, polls the job and saves the finished
answer (riches_probe.json in the current folder unless given; tests/fixtures/spansh_riches.json is a trimmed copy of
one, so it is not overwritten by default), then prints which method worked and the field names it saw. Compare those
with outrider/riches.py (riches_rows) and RICHES_METHOD in ed_outrider.py. Not part of the tests or of Outrider."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://spansh.co.uk/api"
UA = {"User-Agent": "ED-Outrider riches probe"}


def call(method, url, params=None):
    data = None
    if params and method == "POST":
        data = urllib.parse.urlencode(params).encode()
    elif params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:300]


def main():
    frm = sys.argv[1] if len(sys.argv) > 1 else "Sol"
    rng = sys.argv[2] if len(sys.argv) > 2 else "50"
    out_path = sys.argv[3] if len(sys.argv) > 3 else "riches_probe.json"
    params = {"from": frm, "range": rng, "radius": 25, "max_results": 5, "max_distance": 50000, "min_value": 100000,
              "use_mapping_value": 1, "avoid_thargoids": 1, "loop": 0}
    for method in ("POST", "GET"):
        status, out = call(method, BASE + "/riches/route", params)
        print(method, "->", status, str(out)[:200])
        job = out.get("job") if isinstance(out, dict) else None
        if status not in (200, 202) or not job:
            continue
        for _ in range(60):
            time.sleep(2)
            status, res = call("GET", f"{BASE}/results/{job}")
            if isinstance(res, dict) and res.get("status") not in (None, "queued", "running"):
                break
        else:
            print("the job did not finish in 2 minutes")
            continue
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        r = res.get("result", res) if isinstance(res, dict) else res
        first = r[0] if isinstance(r, list) and r else {}
        print(method, "worked: saved", out_path)
        print("answer keys:", sorted(res) if isinstance(res, dict) else type(res).__name__)
        print("system keys:", sorted(first) if isinstance(first, dict) else first)
        bodies = first.get("bodies") if isinstance(first, dict) else None
        print("body keys:", sorted(bodies[0]) if bodies and isinstance(bodies[0], dict) else bodies)
        return
    print("neither POST nor GET gave a route: send this output back")


main()

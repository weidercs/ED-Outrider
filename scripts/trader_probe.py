"""One-off probe of Spansh's station search for material traders (S54): which field says the trader's kind, whether
the search can filter on it, and how many traders have no kind reported. Saves the real answers.

    python scripts/trader_probe.py [out.json]    (where to save the answers; trader_probe.json in the current folder)

Four read-only searches: the nearest traders to Sol by the "Material Trader" service, the nearest raw ones by the
`material_trader` field, the nearest to Colonia (where outposts with a trader and no kind were seen), and the whole
galaxy's counts both ways. tests/fixtures/spansh_traders.json is a trimmed copy of one run (2026-10-12), so it is not
overwritten by default. Compare what it prints with outrider/dock.py (spansh_rows, TRADER_KINDS) and
Spansh.dock_search in ed_outrider.py. Not part of the tests or of Outrider."""
import json
import sys
import time
import urllib.error
import urllib.request

URL = "https://spansh.co.uk/api/stations/search"
UA = {"User-Agent": "ED-Outrider trader probe", "Content-Type": "application/json"}
SOL = {"x": 0, "y": 0, "z": 0}
COLONIA = {"x": -9530.5, "y": -910.28125, "z": 19808.125}


def search(filters, ref, size=10):
    body = {"filters": filters, "sort": [{"distance": {"direction": "asc"}}], "reference_coords": ref, "size": size, "page": 0}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:   # answers took 50-90 s on 2026-10-12
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode(errors="replace")[:300]}
    except (OSError, ValueError) as e:   # a timeout, no network, not JSON: said, and the next search still runs
        return {"http_error": str(e)}


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "trader_probe.json"
    near = {"min": "0", "max": "20000"}
    asks = {"sol_by_service": ({"services": [{"name": "Material Trader"}], "distance": near}, SOL, 10),
            "sol_raw_by_kind": ({"material_trader": {"value": ["Raw"]}, "distance": near}, SOL, 10),
            "colonia_by_service": ({"services": [{"name": "Material Trader"}], "distance": near}, COLONIA, 10)}
    answers = {}
    for name, (filters, ref, size) in asks.items():
        answers[name] = search(filters, ref, size)
        d = answers[name]
        print(name, "->", d.get("count"), "found", d.get("http_error") or "")
        for r in d.get("results") or []:
            print(f"   {r.get('name')} ({r.get('system_name')}, {r.get('type')}): material_trader={r.get('material_trader')!r}, "
                  f"economy {r.get('primary_economy')}, service listed: {'Material Trader' in [s.get('name') for s in r.get('services') or []]}")
        time.sleep(1)
    everywhere = {"min": "0", "max": "100000"}
    answers["galaxy_by_service"] = {"count": search({"services": [{"name": "Material Trader"}], "distance": everywhere}, SOL, 1).get("count")}
    time.sleep(1)
    answers["galaxy_by_kind"] = {"count": search({"material_trader": {"value": ["Raw", "Manufactured", "Encoded"]},
                                                  "distance": everywhere}, SOL, 1).get("count")}
    print("galaxy: by service", answers["galaxy_by_service"]["count"], "· with a kind", answers["galaxy_by_kind"]["count"])
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=1)
    print("saved", out_path)


main()

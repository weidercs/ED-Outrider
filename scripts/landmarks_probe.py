"""One-off probe of what Spansh reports about the life on a body (S23, S27, S29): whether its system dumps and its body
search carry each body's `landmarks` (the species commanders' uploads reported), what else a search result carries
(earth_masses, radius, a full-precision surface_temperature: what the green gas giant model needs), and which filter
shapes the body search really applies. Saves the real answers.

    python scripts/landmarks_probe.py [out.json]    (where to save the answers; landmarks_probe.json in the current folder)

Spansh silently ignores a filter shape it does not know (the answer is then simply the nearest bodies), so every filter
tried here is checked against what comes back, and its count compared with the same search without it. A handful of
read-only requests, a second apart: a search near Colonia for landable bodies with biological signals, the dump of the
first system found, the same search with each candidate landmark filter shape, a temperature range in three shapes,
that one system's bodies with life alone (by its name, and out to 1 ly from it) and one gas giant search.

Its answer on 2026-10-12 (tests/fixtures/spansh_landmarks.json is a trimmed copy, so it is not overwritten by default):
search results carry `landmarks` (species, its colour as `variant`, the place), `earth_masses`, `radius` and the
journal's own temperature; dumps carry no landmarks; {landmarks: [{subtype}]} (and landmark_subtype {value}) filters,
{landmarks: {value}} finds nothing; surface_temperature takes {value: [lo, hi], comparison: "<=>"}, not {min, max};
one system alone is the search out to 1 ly of it (a system_name filter and a max of "0" are ignored). Compare what it
prints with reported_life / Spansh.reported_search / record_from_body_search in ed_outrider.py. Not part of the tests or
of Outrider."""
import json
import sys
import time
import urllib.error
import urllib.request

SEARCH = "https://spansh.co.uk/api/bodies/search"
DUMP = "https://spansh.co.uk/api/dump/{id64}"
UA = {"User-Agent": "ED-Outrider landmarks probe", "Content-Type": "application/json"}
COLONIA = {"x": -9530.5, "y": -910.28125, "z": 19808.125}
NEAR = {"min": "0", "max": "200"}
BIO = [{"name": "Biological", "value": [1, 999], "comparison": "<=>"}]


def fetch(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode(errors="replace")[:300]}
    except (OSError, ValueError) as e:   # a timeout, no network, not JSON: said, and the next request still runs
        return {"http_error": str(e)}


def search(filters, size=10):
    time.sleep(1)
    return fetch(SEARCH, {"filters": dict(filters, distance=NEAR), "sort": [{"distance": {"direction": "asc"}}],
                          "reference_coords": COLONIA, "size": size, "page": 0})


def species_of(b):
    return sorted({x.get("subtype") for x in b.get("landmarks") or [] if isinstance(x, dict)} - {None})


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "landmarks_probe.json"
    answers = {}
    base = answers["bio_search"] = search({"signals": BIO, "is_landable": {"value": True}})
    results = base.get("results") or []
    print("(b) bio search ->", base.get("count"), "found", base.get("http_error") or "")
    if not results:
        print("nothing found: stopping")
        return save(out_path, answers)
    first = results[0]
    print("    a result's keys:", sorted(first))
    for k in ("landmarks", "earth_masses", "radius", "surface_temperature", "landmark_value"):
        print(f"    {k}: {first.get(k)!r}"[:300])
    with_lm = [b for b in results if b.get("landmarks")]
    print(f"    results with landmarks: {len(with_lm)} of {len(results)}")
    pick = (with_lm or results)[0]
    time.sleep(1)
    dump = fetch(DUMP.format(id64=pick["system_id64"]))
    bodies = ((dump or {}).get("system") or {}).get("bodies") or []
    answers["dump"] = {"system": pick["system_name"], "id64": pick["system_id64"], "http_error": (dump or {}).get("http_error"),
                       "bodies": [b for b in bodies if b.get("type") == "Planet"]}
    lm_bodies = [b for b in bodies if "landmarks" in b]
    print(f"(a) dump of {pick['system_name']}: {len(bodies)} bodies, {len(lm_bodies)} with a landmarks key")
    for b in lm_bodies[:3]:
        print("    ", b.get("name"), json.dumps(b.get("landmarks"))[:300])
    target = next((s for b in with_lm for s in species_of(b)), None)
    genus = next((x.get("type") for b in with_lm for x in b.get("landmarks") or [] if x.get("subtype") == target), None)
    print("(c) the species tried as a filter:", target, "genus", genus)
    if target:
        shapes = {"landmarks_list": {"landmarks": [{"type": genus, "subtype": target}]},
                  "landmarks_subtype_list": {"landmarks": [{"subtype": target}]},
                  "landmark_subtype_value": {"landmark_subtype": {"value": [target]}},
                  "landmarks_value": {"landmarks": {"value": [target]}}}
        for name, f in shapes.items():
            d = answers[f"filter_{name}"] = search(dict(f, is_landable={"value": True}))
            got = d.get("results") or []
            ok = sum(1 for b in got if target in species_of(b))
            print(f"    {name}: count {d.get('count')} (without it {base.get('count')}), {ok} of {len(got)} carry {target}",
                  d.get("http_error") or "")
    for name, rng in (("numbers", {"min": 150, "max": 160}), ("strings", {"min": "150", "max": "160"}),
                      ("comparison", {"value": [150, 160], "comparison": "<=>"})):
        d = answers[f"temperature_{name}"] = search({"signals": BIO, "surface_temperature": rng})
        temps = [b.get("surface_temperature") for b in d.get("results") or []]
        print(f"(d) surface_temperature 150-160 as {name}: count {d.get('count')} (without it {base.get('count')}),"
              f" temperatures {temps}")
    # one system's bodies with life (S23: dumps carry no landmarks): by its name, and the search around it out to 1 ly
    # (a max of "0" was ignored on 2026-10-12)
    for name, f in (("by_name", {"system_name": {"value": pick["system_name"]}}), ("within_1ly", {"distance": {"min": "0", "max": "1"}})):
        time.sleep(1)
        d = answers[f"one_system_{name}"] = fetch(SEARCH, {"filters": dict({"signals": BIO, "distance": {"min": "0", "max": "100"}}, **f),
                                                          "reference_coords": {k: pick[f"system_{k}"] for k in "xyz"},
                                                          "sort": [{"distance": {"direction": "asc"}}], "size": 50, "page": 0})
        got = d.get("results") or []
        print(f"(e) {pick['system_name']} alone, {name}: count {d.get('count')}, systems {sorted({b.get('system_name') for b in got})[:5]},"
              f" {sum(1 for b in got if b.get('landmarks'))} with landmarks")
    d = answers["gas_giant"] = search({"subtype": {"value": ["Class I gas giant", "Class III gas giant", "Class IV gas giant",
                                                             "Gas giant with water-based life",
                                                             "Gas giant with ammonia-based life", "Water giant"]}}, 5)
    for b in d.get("results") or []:
        print(f"    giant {b.get('name')}: {b.get('subtype')}, earth_masses {b.get('earth_masses')!r}, radius {b.get('radius')!r},"
              f" surface_temperature {b.get('surface_temperature')!r}")
    save(out_path, answers)


def save(path, answers):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=1)
    print("saved", path)


main()

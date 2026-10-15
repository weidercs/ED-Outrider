"""Unit tests: potential green gas giants (outrider/ggg.py, the community's seven-layer ladder model; the author's
ask, 2026-10-12), and the server's alert, Here's and Nearby's marks.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import time
import types
import unittest

from support import ed_outrider  # also puts the repository root on sys.path
import outrider.ggg as G  # noqa: E402

# a Class I giant whose bottom cloud layer sits exactly on its 250 K border (capped ladder: the exact float32 path)
GREEN = {"PlanetClass": "Sudarsky class I gas giant", "SurfaceTemperature": 250.0, "MassEM": 300.0, "Radius": 7.0e7}


class Model(unittest.TestCase):
    def test_predictions(self):
        p = G.predict(GREEN)
        self.assertEqual((p["chance"], p["class"], p["rung"], p["border"]), ("likely", "class1", 1, 250))
        self.assertIsNone(G.predict(dict(GREEN, SurfaceTemperature=251.3)))                     # no layer on a border
        self.assertIsNone(G.predict(dict(GREEN, SurfaceTemperature=100.0)))                     # the nudged window
        self.assertIsNone(G.predict(dict(GREEN, PlanetClass="Sudarsky class II gas giant")))    # no rule known
        self.assertIsNone(G.predict(dict(GREEN, MassEM=None)))                                  # needs mass and radius
        self.assertIsNone(G.predict({"PlanetClass": "Icy body", "SurfaceTemperature": 250.0, "MassEM": 1.0, "Radius": 1e6}))
        q = G.predict({"PlanetClass": "Sudarsky class III gas giant", "SurfaceTemperature": 700.0, "MassEM": 500.0, "Radius": 7e7})
        self.assertEqual(q["chance"], "possible")    # a derived rule (680-900 K): "possible", not "likely"
        self.assertEqual([G.gas_class(c) for c in ("Sudarsky class IV gas giant", "Class V gas giant", "Gas giant with water based life",
                                                    "Gas giant with ammonia based life", "Water giant", "Helium rich gas giant", "Rocky body")],
                         ["class4", "class5", "water_life", "ammonia_life", "water_giant", "helium", None])

    def test_records_and_codex(self):
        """Outrider's records (yours and Spansh's keep the journal's temperature; radius in km), and the codex names."""
        rec = {"type": "Planet", "subtype": "Class I gas giant", "temperature": 250.0, "radius_km": 70000.0,
               "ed": {"PlanetClass": "Sudarsky class I gas giant", "MassEM": 300.0}}
        self.assertEqual(G.predict_record(rec)["chance"], "likely")
        self.assertIsNone(G.predict_record(dict(rec, type="Star")))
        self.assertTrue(G.confirmed(["Green Class I Gas Giant"]))
        self.assertFalse(G.confirmed(["Stratum Tectonicas - Grey", None]))


class Server(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.now = time.time()

    def test_alert_here_and_nearby(self):
        at = lambda s: ed_outrider.iso_ts(self.now - 60 + s)
        self.j.handle({"event": "FSDJump", "timestamp": at(0), "StarSystem": "Gree Sector AB-C d1-2", "SystemAddress": 9, "StarPos": [0, 0, 0]})
        scan = {"event": "Scan", "timestamp": at(5), "ScanType": "Detailed", "StarSystem": "Gree Sector AB-C d1-2", "SystemAddress": 9,
                "BodyID": 4, "BodyName": "Gree Sector AB-C d1-2 B 3", "DistanceFromArrivalLS": 900.0, "WasDiscovered": False, "WasMapped": False,
                **GREEN}
        self.j.handle(scan)
        said = [m for m in self.j.moments if m["kind"] == "ggg"]
        self.assertEqual([(m["body"], m["chance"], m["what"]) for m in said], [("B 3", "likely", "a class one gas giant")])
        self.j.handle(dict(scan, timestamp=at(6)))   # the same body again: no second alert
        self.assertEqual(len([m for m in self.j.moments if m["kind"] == "ggg"]), 1)
        body = next(b for b in self.state.system_detail(9)["bodies"] if b["name"] == "B 3")
        self.assertEqual((body["ggg"]["chance"], body["ggg"]["border"]), ("likely", 250))
        # Nearby's row: a system worth going to
        recs = [{"name": "Gree Sector AB-C d1-2 B 3", "body_id": 4, "type": "Planet", "temperature": 250.0, "radius_km": 70000.0,
                 "ed": {"PlanetClass": "Sudarsky class I gas giant", "MassEM": 300.0}}]
        self.assertEqual(ed_outrider.ggg_bodies(self.db, 9, "Gree Sector AB-C d1-2", recs), ([{"body": "B 3", "chance": "likely"}], 0))
        # the codex confirms it: no longer a guess
        self.db.execute("INSERT INTO codex (ts, entry_id, name, category, subcategory, region, system, system_name, body_id, is_new, new_traits, voucher) "
                        "VALUES (?, 1, 'Green Class I Gas Giant', 'Astronomical Bodies', 'Gas Giants', 18, 9, 'Gree Sector AB-C d1-2', 4, 1, 0, 0)", (at(9),))
        self.assertEqual(ed_outrider.ggg_bodies(self.db, 9, "Gree Sector AB-C d1-2", recs), ([], 1))
        body = next(b for b in self.state.system_detail(9)["bodies"] if b["name"] == "B 3")
        self.assertEqual(body["ggg"], {"confirmed": True})


def fixture():
    import json
    import os
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "spansh_landmarks.json"), encoding="utf-8") as f:
        return json.load(f)


class Find(unittest.TestCase):
    """S27: find potential green gas giants: Search's planet option (Local over your cache, Spansh's giants checked by
    the model), GET /api/ggg and the voice's answer from it."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.now = time.time()
        at = lambda s: ed_outrider.iso_ts(self.now - 60 + s)
        self.j.handle({"event": "FSDJump", "timestamp": at(0), "StarSystem": "Gree Sector AB-C d1-2", "SystemAddress": 9, "StarPos": [0, 0, 0]})
        # a cached Spansh system 30 ly away with a green-looking giant (a dump's record: mass in ed, the journal's temperature)
        rec = {"name": "B 3", "body_id": 4, "type": "Planet", "subtype": "Class I gas giant", "temperature": 250.0, "radius_km": 70000.0,
               "ed": {"PlanetClass": "Sudarsky class I gas giant", "MassEM": 300.0}, "full": True}
        plain = dict(rec, name="B 4", body_id=5, temperature=251.3)
        base = {"name": "Far Green", "x": 30.0, "y": 0.0, "z": 0.0, "records": [rec, plain]}
        self.db.execute("INSERT INTO spansh_systems (id64, updated_at, summary, fetched_ts, x, y, z) VALUES (77, 'x', ?, ?, 30, 0, 0)",
                        (ed_outrider.json.dumps(base), self.now))
        self.db.commit()

    def state(self, spansh=None):
        return ed_outrider.State(self.db, self.j, spansh or ed_outrider.Spansh(self.db), 25)

    def search(self, params, spansh=None):
        import asyncio
        s = ed_outrider.Searcher(self.state(spansh))

        async def go():
            s.start(dict({"radius": 50}, **params))
            await s.task
        asyncio.run(go())
        return s.result

    def test_search_option_local(self):
        self.assertEqual(ed_outrider.SEARCH_OPTIONS["ggg"], ["ggg", "Potential green gas giant"])
        r = self.search({"source": "local", "planets": ["ggg"]})
        self.assertEqual([x["name"] for x in r["results"]], ["Far Green"])
        self.assertEqual(r["results"][0]["matches"]["planets"], [{"t": "B 3 · potential green gas giant (likely)", "body": "B 3"}])
        # with a class ticked too, the section ORs them
        r = self.search({"source": "local", "planets": ["ggg", "Class I gas giant"]})
        self.assertEqual([h["body"] for h in r["results"][0]["matches"]["planets"]], ["B 3", "B 4", "B 3"])

    def test_search_option_spansh(self):
        """One query for the giants the model can judge; its answer checked by the model (a search result carries the
        mass, the radius and the journal's temperature: the probe's answer, 2026-10-12)."""
        giants = fixture()["gas_giant"]["results"]
        self.assertTrue(all(isinstance(g.get(k), float) for g in giants for k in ("earth_masses", "radius", "surface_temperature")))
        near = lambda g, name, i: dict(g, system_name=name, system_id64=i, name=f"{name} {g['name'].split()[-1]}",
                                       system_x=10.0, system_y=0.0, system_z=0.0)   # within the radius of you
        green = dict(near(giants[4], "Near Giant", 501), name="Near Giant 2", subtype="Class I gas giant",
                     surface_temperature=250.0, earth_masses=300.0, radius=70000.0, body_id=99)
        giants = [near(g, f"Giant {i}", 600 + i) for i, g in enumerate(giants)]
        asked = []

        class Fake:
            async def body_search(self, filters, pos, radius, pages):
                asked.append(filters)
                return giants + [green], None
        r = self.search({"source": "spansh", "planets": ["ggg"]}, Fake())
        self.assertEqual(asked, [{"subtype": {"value": sorted(ed_outrider.GGG_SPANSH.values())}}])   # "ggg" itself never sent
        self.assertEqual([(x["name"], x["matches"]["planets"][0]["body"]) for x in r["results"]], [("Near Giant", "2")])
        self.assertEqual(sorted(G.searchable_classes()), sorted(ed_outrider.GGG_SPANSH))   # every class the model judges
        rec = ed_outrider.record_from_body_search(green)
        self.assertEqual((rec["mass_em"], rec["radius_km"], G.predict_record(rec)["chance"]), (300.0, 70000.0, "likely"))

    def test_nearest_route_and_voice(self):
        import asyncio
        import outrider.ask as ask
        st = self.state()
        d = asyncio.run(st.nearest_ggg())
        self.assertEqual((d["origin"], d["radius"], d["bodies"]),
                         ("Gree Sector AB-C d1-2", 500, [{"system": "Far Green", "id": "77", "body": "B 3", "chance": "likely", "distance": 30.0}]))
        self.assertEqual(asyncio.run(st.nearest_ggg(10))["bodies"], [])   # out of reach
        self.assertEqual(ask.match("Vespa, where's the nearest green gas giant?", ask.load_phrases()), "nearest_ggg")
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(st))) as c:
                async def http(path, params):
                    return await (await c.get(path, params=params)).json()
                get = ed_outrider.outrider.tools.guarded(http)
                first = await ask.fixed_answer("nearest_ggg", get)
                # the codex confirms it: no longer listed (you have been there)
                self.db.execute("INSERT INTO codex (ts, entry_id, name, system, body_id) VALUES ('t', 1, 'Green Class I Gas Giant', 77, 4)")
                bad = (await c.get("/api/ggg", params={"radius": "nan"})).status
                return first, await ask.fixed_answer("nearest_ggg", get), bad
        first, then, bad = asyncio.run(go())
        self.assertEqual(first, "Nearest potential green gas giant: B 3 in Far Green, 30.0 light years. "
                                "A guess from the ladder model: check it in the system map.")
        self.assertEqual((then, bad), ("None within 500 light years in what Outrider has cached.", 400))


if __name__ == "__main__":
    unittest.main()

"""Where the engineers work, and the fork's Engineering additions beside upstream's CMDR tab (outrider/commander.py):
each engineer's system and its distance from you, the ship you fly as the tab's picks ("Load my ship"), and the
engineers' trip (outrider/engtour.py). The page side is static/fork.js (forkEngineeringHtml).

    engineer_list(known)              # every engineer with their system and what EngineerProgress says
    await engineer_distances(state)   # {from, distances {system: ly}, missing, error}
    ship_parts(loadout)               # the ship as the tab's picks: its modules' parts and engineered grades
    await engineer_tour(state, body)  # the trip
    add_routes(app, state, dirs)      # GET /api/engineers, GET /api/engineers/ship, GET /api/engineers/gear,
                                      # POST /api/engineers/tour
"""
import json
import re

from . import engtour, gear, shipinfo

PLACES_KEY = "engineer_places"   # meta: {system: [x, y, z]}, kept for good (the workshops do not move)
PLACES_GAP_S = 0.3               # s between two Spansh lookups of a system not known here


def _plain(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


# Where each engineer works: (system, what they engineer, region). Their workshops have not moved since 2020 (Professor
# Palin's to Arque); the journal never says where an engineer is.
ENGINEER_SYSTEMS = {
    "Bill Turner": ("Alioth", "ship", "bubble"), "Broo Tarquin": ("Muang", "ship", "bubble"),
    "Chloe Sedesi": ("Shenve", "ship", "bubble"), "Colonel Bris Dekker": ("Sol", "ship", "bubble"),
    "Didi Vatermann": ("Leesti", "ship", "bubble"), "Elvira Martuuk": ("Khun", "ship", "bubble"),
    "Felicity Farseer": ("Deciat", "ship", "bubble"), "Hera Tani": ("Kuwemaki", "ship", "bubble"),
    "Juri Ishmaak": ("Giryak", "ship", "bubble"), "Lei Cheung": ("Laksak", "ship", "bubble"),
    "Liz Ryder": ("Eurybia", "ship", "bubble"), "Lori Jameson": ("Shinrarta Dezhra", "ship", "bubble"),
    "Marco Qwent": ("Sirius", "ship", "bubble"), "Professor Palin": ("Arque", "ship", "bubble"),
    "Ram Tah": ("Meene", "ship", "bubble"), "Selene Jean": ("Kuk", "ship", "bubble"),
    "The Dweller": ("Wyrd", "ship", "bubble"), "The Sarge": ("Beta-3 Tucani", "ship", "bubble"),
    "Tiana Fortune": ("Achenar", "ship", "bubble"), 'Tod "The Blaster" McQuinn': ("Wolf 397", "ship", "bubble"),
    "Zacariah Nemo": ("Yoru", "ship", "bubble"),
    "Etienne Dorn": ("Los", "ship", "Colonia"), "Marsha Hicks": ("Tir", "ship", "Colonia"),
    "Mel Brandon": ("Luchtaine", "ship", "Colonia"), "Petra Olmanova": ("Asura", "ship", "Colonia"),
    "Domino Green": ("Orishis", "suit & weapon", "bubble"), "Hero Ferrari": ("Siris", "suit & weapon", "bubble"),
    "Jude Navarro": ("Aurai", "suit & weapon", "bubble"), "Kit Fowler": ("Capoya", "suit & weapon", "bubble"),
    "Oden Geiger": ("Candiaei", "suit & weapon", "bubble"), "Terra Velasquez": ("Shou Xing", "suit & weapon", "bubble"),
    "Uma Laszlo": ("Xuane", "suit & weapon", "bubble"), "Wellington Beck": ("Jolapa", "suit & weapon", "bubble"),
    "Yarden Bond": ("Bayan", "suit & weapon", "bubble"),
    "Baltanos": ("Deriso", "suit & weapon", "Colonia"), "Eleanor Bresa": ("Desy", "suit & weapon", "Colonia"),
    "Rosa Dayette": ("Kojeara", "suit & weapon", "Colonia"), "Yi Shen": ("Einheriar", "suit & weapon", "Colonia"),
}


def engineer_system(name):
    """(system, kind, region) of an engineer by any spelling of the name ("Tod 'The Blaster' McQuinn"), or None."""
    want = _plain(name)
    return next((v for k, v in ENGINEER_SYSTEMS.items() if _plain(k) == want), None)


def engineer_list(known):
    """Every engineer the table knows, and any other the journal names: [{name, system, kind, region, progress,
    rank}], the ship engineers first, then by name. known: engineers()."""
    mine = {_plain(k): (k, v) for k, v in (known or {}).items()}
    out = []
    for name, (system, kind, region) in ENGINEER_SYSTEMS.items():
        st = (mine.pop(_plain(name), (None, {}))[1]) or {}
        out.append({"name": name, "system": system, "kind": kind, "region": region,
                    "progress": st.get("progress"), "rank": st.get("rank")})
    for name, st in mine.values():   # one the table does not have yet: listed, no system to go to
        out.append({"name": name, "system": None, "kind": None, "region": None, "progress": st.get("progress"), "rank": st.get("rank")})
    return sorted(out, key=lambda e: (e["kind"] != "ship", e["name"].lower()))


# ---- the engineers' systems: where they lie, and how far from you ----

def _places(db):
    row = db.execute("SELECT value FROM meta WHERE key=?", (PLACES_KEY,)).fetchone()
    try:
        got = json.loads(row["value"]) if row else {}
    except (ValueError, TypeError):
        got = {}
    return got if isinstance(got, dict) else {}


def _ly(a, b):
    return round(sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5, 1)


async def engineer_distances(state, gap=PLACES_GAP_S):
    """{from (where you are), distances {system: ly}, missing [systems not found], error}. Each system's place is found
    once: a system known here (State.find_local), else Spansh by its exact name; then kept (meta engineer_places).
    Spansh failing once: the rest only from what is known here, Spansh asked again next time."""
    import asyncio
    places, asked, err = _places(state.db), False, None
    systems = sorted({v[0] for v in ENGINEER_SYSTEMS.values()})
    for system in systems:
        if system in places:
            continue
        local = state.find_local(system)
        if local and None not in local[2:5]:
            places[system] = list(local[2:5])
            continue
        if err:
            continue
        try:
            if asked:
                await asyncio.sleep(gap)
            asked = True
            rec = await state.spansh.system_record(system)
        except Exception as e:   # Spansh down or slow
            err = f"Spansh could not be asked where every engineer is ({type(e).__name__})"
            continue
        if rec and None not in (rec.get("x"), rec.get("y"), rec.get("z")):
            places[system] = [rec["x"], rec["y"], rec["z"]]
    if places != _places(state.db):
        state.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (PLACES_KEY, json.dumps(places)))
        state.db.commit()
    pos = state.journals.pos
    here = (pos["x"], pos["y"], pos["z"]) if pos and None not in (pos.get("x"), pos.get("y"), pos.get("z")) else None
    return {"from": pos.get("name") if here else None,
            "distances": {s: _ly(here, places[s]) for s in systems if here and s in places},
            "missing": [s for s in systems if s not in places], "error": err}


def known_engineers(state):
    """{engineer: {progress, rank}} as upstream's Commander fold has it (EngineerProgress)."""
    return (getattr(state.journals, "cmdr_view", None) or {}).get("engineers") or {}


# ---- the ship you fly, as the Engineering tab's picks: "Load my ship" ----

# a module's journal symbol (Loadout's Item, lower case) -> the blueprint table's module (upstream's rows: one per kind
# of module). The first prefix that matches wins (pulselaserburst before pulselaser); "_advanced" makes a missile rack
# or multi-cannon its advanced kind.
SHIP_PARTS = (
    ("int_powerplant", "Power plant"), ("int_hyperdrive", "Frame shift drive"), ("int_engine", "Thrusters"),
    ("int_powerdistributor", "Power distributor"), ("int_sensors", "Sensors"), ("int_lifesupport", "Life support"),
    ("int_shieldcellbank", "Shield cell bank"), ("int_hullreinforcement", "Hull reinforcement package"),
    ("int_fuelscoop", "Fuel scoop"), ("int_refinery", "Refinery"), ("int_detailedsurfacescanner", "Detailed surface scanner"),
    ("int_fsdinterdictor", "Frame shift drive interdictor"), ("int_repairer", "Auto field maintenance unit"),
    ("int_dronecontrol_collection", "Collector limpet controller"), ("int_dronecontrol_fueltransfer", "Fuel transfer limpet controller"),
    ("int_dronecontrol_resourcesiphon", "Hatch breaker limpet controller"), ("int_dronecontrol_prospector", "Prospector limpet controller"),
    ("hpt_shieldbooster", "Shield booster"), ("hpt_chafflauncher", "Chaff launcher"), ("hpt_plasmapointdefence", "Point defence"),
    ("hpt_heatsinklauncher", "Heat sink launcher"), ("hpt_causticsinklauncher", "Caustic sink launcher"),
    ("hpt_electroniccountermeasure", "Electronic countermeasure"), ("hpt_cargoscanner", "Cargo scanner"),
    ("hpt_cloudscanner", "Frame shift wake scanner"), ("hpt_crimescanner", "Kill warrant scanner"),
    ("hpt_pulselaserburst", "Burst laser"), ("hpt_pulselaser", "Pulse laser"), ("hpt_beamlaser", "Beam laser"),
    ("hpt_multicannon", "Multi-cannon"), ("hpt_cannon", "Cannon"), ("hpt_slugshot", "Fragment cannon"),
    ("hpt_plasmaaccelerator", "Plasma accelerator"), ("hpt_railgun", "Rail gun"),
    ("hpt_dumbfiremissilerack", "Missile rack"), ("hpt_basicmissilerack", "Missile rack"), ("hpt_drunkmissilerack", "Missile rack"),
    ("hpt_minelauncher", "Mine launcher"), ("hpt_advancedtorppylon", "Torpedo pylon"),
)
ADVANCED = {"Missile rack": "Advanced missile rack", "Multi-cannon": "Advanced multi-cannon"}


def ship_part(item):
    """The blueprint table's module a ship's module is, by its journal symbol, or None (a cargo rack, the cockpit, a
    paint job: nothing to engineer)."""
    it = str(item or "").lower()
    if it.startswith("int_shieldgenerator"):
        return "Bi-weave shield generator" if it.endswith("_fast") else "Prismatic shield generator" if it.endswith("_strong") \
            else "Shield generator"
    if "_armour_" in it:
        return "Bulkheads"
    part = next((p for prefix, p in SHIP_PARTS if it.startswith(prefix)), None)
    return ADVANCED.get(part, part) if part and it.endswith("_advanced") else part


def ship_parts(loadout):
    """The ship of a Loadout as the Engineering tab's picks: {ship: {name, type}, modules: [{slot, name, part,
    blueprint_id, blueprint, level, quality, experimental}] (only modules with a part), parts: [modules], grades:
    ["<module>|<blueprint id>|<level>"] of the engineered ones}. Experimental effects are named, not picked: the
    blueprint table has none."""
    mods, parts, grades = [], [], []
    for m in (loadout or {}).get("Modules") or []:
        if not isinstance(m, dict):
            continue
        part = ship_part(m.get("Item"))
        if not part:
            continue
        e = m.get("Engineering") if isinstance(m.get("Engineering"), dict) else {}
        bid = e.get("BlueprintName") if isinstance(e.get("BlueprintName"), str) else None
        level = e.get("Level") if isinstance(e.get("Level"), int) and not isinstance(e.get("Level"), bool) else None
        mods.append({"slot": m.get("Slot"), "name": shipinfo.module_name(m.get("Item"))[0], "part": part, "blueprint_id": bid,
                     "blueprint": shipinfo.engineering(e)["blueprint"] if e else None, "level": level,
                     "quality": e.get("Quality"), "experimental": e.get("ExperimentalEffect_Localised") or None})
        if part not in parts:
            parts.append(part)
        if bid and level and f"{part}|{bid}|{level}" not in grades:
            grades.append(f"{part}|{bid}|{level}")
    return {"ship": {"name": (loadout or {}).get("ShipName") or None, "type": (loadout or {}).get("Ship")} if loadout else None,
            "modules": mods, "parts": parts, "grades": grades}


# ---- the engineers' trip: which engineers cover the picks for the fewest light years (outrider/engtour.py) ----

def tour_body_problem(body):
    """What is wrong with a POST /api/engineers/tour body, or None."""
    if not isinstance(body, dict) or not isinstance(body.get("requirements"), list):
        return "requirements: a list of {label, grade, engineers}"
    for r in body["requirements"]:
        if not (isinstance(r, dict) and isinstance(r.get("label"), str) and isinstance(r.get("engineers"), list)
                and all(isinstance(e, str) for e in r["engineers"])
                and (r.get("grade") is None or (isinstance(r["grade"], int) and not isinstance(r["grade"], bool) and 1 <= r["grade"] <= 5))):
            return "requirements: each {label: text, grade: 1 to 5 or null, engineers: [names]}"
    for k in ("include_locked", "return_carrier"):
        if k in body and not isinstance(body[k], bool):
            return f"{k}: true or false"
    if len(body["requirements"]) > 60:
        return "requirements: 60 at most"
    return None


async def engineer_tour(state, body):
    """POST /api/engineers/tour {requirements, include_locked?, return_carrier?}: the trip (engtour.plan) from where you
    are, each stop with its system; with return_carrier, ending at your fleet carrier. ({...}, status)."""
    problem = tour_body_problem(body)
    if problem:
        return {"error": problem}, 400
    pos = state.journals.pos
    if not pos or None in (pos.get("x"), pos.get("y"), pos.get("z")):
        return {"error": "no position yet: after your first jump"}, 409
    await engineer_distances(state)
    places = _places(state.db)
    at = {name: places[v[0]] for name, v in ENGINEER_SYSTEMS.items() if v[0] in places}
    end, carrier = None, None
    if body.get("return_carrier"):
        summary = state.carrier_summary() if hasattr(state, "carrier_summary") else None
        c = getattr(state.journals, "carrier", None) or {}
        if not summary or c.get("x") is None:
            return {"error": "no fleet carrier on record, or not where it is yet"}, 409
        end, carrier = (c["x"], c["y"], c["z"]), {"name": summary.get("name"), "system": summary.get("system")}
    out = engtour.plan(body["requirements"], known_engineers(state), at, (pos["x"], pos["y"], pos["z"]), end,
                       include_locked=bool(body.get("include_locked")))
    for s in out["stops"]:
        s["system"] = (engineer_system(s["engineer"]) or (None,))[0]
    return dict(out, **{"from": pos.get("name"), "carrier": carrier}), 200


# ---- the server's routes ----

def add_routes(app, state, dirs):
    """GET /api/engineers (every engineer with their system, progress and distance), GET /api/engineers/ship (the ship
    you fly as the Engineering tab's picks; reads files: off the event loop), POST /api/engineers/tour. dirs: fn() ->
    the live journal folders."""
    import asyncio
    from aiohttp import web

    async def listing(_):
        out = await engineer_distances(state)
        out["engineers"] = engineer_list(known_engineers(state))
        return web.json_response(out)

    def ship_now():
        sid = (getattr(state.journals, "ship", None) or {}).get("ship_id")
        ev = (shipinfo.latest_loadout(dirs(), sid) if sid is not None else None) or shipinfo.latest_loadout(dirs())
        return ship_parts(ev)

    async def ship(_):
        return web.json_response(await asyncio.get_running_loop().run_in_executor(None, ship_now))

    async def gear_view(_):   # suits and weapons (outrider/gear.py)
        v = getattr(state.journals, "cmdr_view", None) or {}
        return web.json_response(gear.gear(v.get("ship_locker"), v.get("engineers"), v.get("suit_loadouts")))

    async def tour(request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        out, status = await engineer_tour(state, body)
        return web.json_response(out, status=status)
    app.router.add_get("/api/engineers", listing)
    app.router.add_get("/api/engineers/ship", ship)
    app.router.add_get("/api/engineers/gear", gear_view)
    app.router.add_post("/api/engineers/tour", tour)

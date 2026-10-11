"""The ship you fly, from the journal's own Loadout (this fork): its figures and every module with its class,
rating, mount and engineering, the engineered stats as the game states them (value, stock value, the change). Pure
but for `latest_loadout`, which reads the journals.

Inara's API offers no ship or module data to read, and the journal has it whole. What the journal does NOT state is
a stock module's figures or the ship's totals (shields, speed, power): those need a module database, which this
does not carry; `links` opens the same Loadout in EDSY and Coriolis, which do.
"""
import base64
import gzip
import io
import json
import os
import re
from glob import glob, escape as glob_escape

RATING = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A"}
MOUNTS = {"fixed": "Fixed", "gimbal": "Gimballed", "turret": "Turreted"}
HARDPOINT_SIZE = {"tiny": 0, "small": 1, "medium": 2, "large": 3, "huge": 4}
CORE = {"PowerPlant": "Power Plant", "MainEngines": "Thrusters", "FrameShiftDrive": "Frame Shift Drive",
        "LifeSupport": "Life Support", "PowerDistributor": "Power Distributor", "Radar": "Sensors",
        "FuelTank": "Fuel Tank", "Armour": "Bulkheads"}
GROUPS = ("Hardpoints", "Utility mounts", "Core internals", "Optional internals")
# slots that hold no equipment: paint, decals, name plates, the cockpit, the cargo hatch and what every ship has
_SKIP = re.compile(r"PaintJob|Decal|ShipName|ShipID|ShipKit|Bobble|StringLights|Colour|VesselVoice|ShipCockpit|"
                   r"CargoHatch|PlanetaryApproachSuite|DataLinkScanner|CodexScanner|DiscoveryScanner|ColonisationSuite", re.I)

# a module family's name by the start of its journal symbol, the longest match first (built below)
_NAMES = {
    "int_hyperdrive_overcharge": "Frame Shift Drive (SCO)", "int_hyperdrive": "Frame Shift Drive",
    "int_engine_enhanced": "Enhanced Performance Thrusters", "int_engine": "Thrusters",
    "int_powerplant": "Power Plant", "int_guardianpowerplant": "Guardian Hybrid Power Plant",
    "int_powerdistributor": "Power Distributor", "int_guardianpowerdistributor": "Guardian Hybrid Power Distributor",
    "int_lifesupport": "Life Support", "int_sensors": "Sensors", "int_fueltank": "Fuel Tank",
    "int_shieldgenerator": "Shield Generator",
    "int_shieldcellbank": "Shield Cell Bank", "int_guardianshieldreinforcement": "Guardian Shield Reinforcement",
    "int_hullreinforcement": "Hull Reinforcement Package", "int_guardianhullreinforcement": "Guardian Hull Reinforcement",
    "int_metaalloyhullreinforcement": "Meta-Alloy Hull Reinforcement",
    "int_modulereinforcement": "Module Reinforcement Package", "int_guardianmodulereinforcement": "Guardian Module Reinforcement",
    "int_cargorack": "Cargo Rack", "int_corrosionproofcargorack": "Corrosion Resistant Cargo Rack",
    "int_fuelscoop": "Fuel Scoop", "int_guardianfsdbooster": "Guardian FSD Booster",
    "int_detailedsurfacescanner": "Detailed Surface Scanner", "int_stellarbodydiscoveryscanner": "Discovery Scanner",
    "int_repairer": "Auto Field-Maintenance Unit", "int_buggybay": "Planetary Vehicle Hangar",
    "int_fighterbay": "Fighter Hangar", "int_refinery": "Refinery", "int_fsdinterdictor": "FSD Interdictor",
    "int_supercruiseassist": "Supercruise Assist", "int_dockingcomputer_advanced": "Advanced Docking Computer",
    "int_dockingcomputer": "Standard Docking Computer", "int_passengercabin": "Passenger Cabin",
    "int_dronecontrol_collection": "Collector Limpet Controller", "int_dronecontrol_prospector": "Prospector Limpet Controller",
    "int_dronecontrol_fueltransfer": "Fuel Transfer Limpet Controller", "int_dronecontrol_repair": "Repair Limpet Controller",
    "int_dronecontrol_resourcesiphon": "Hatch Breaker Limpet Controller", "int_dronecontrol_recon": "Recon Limpet Controller",
    "int_dronecontrol_decontamination": "Decontamination Limpet Controller",
    "int_dronecontrol_unkvesselresearch": "Research Limpet Controller", "int_dronecontrol": "Limpet Controller",
    "int_multidronecontrol_mining": "Mining Multi Limpet Controller", "int_multidronecontrol_operations": "Operations Multi Limpet Controller",
    "int_multidronecontrol_rescue": "Rescue Multi Limpet Controller", "int_multidronecontrol_xeno": "Xeno Multi Limpet Controller",
    "int_multidronecontrol_universal": "Universal Multi Limpet Controller", "int_multidronecontrol": "Multi Limpet Controller",
    "int_expmodulestabiliser": "Experimental Weapon Stabiliser",
    "hpt_pulselaserburst": "Burst Laser", "hpt_pulselaser": "Pulse Laser", "hpt_beamlaser": "Beam Laser",
    "hpt_multicannon": "Multi-Cannon", "hpt_cannon": "Cannon", "hpt_slugshot": "Fragment Cannon",
    "hpt_plasmaaccelerator": "Plasma Accelerator", "hpt_railgun": "Rail Gun",
    "hpt_dumbfiremissilerack": "Missile Rack", "hpt_basicmissilerack": "Seeker Missile Rack",
    "hpt_advancedtorppylon": "Torpedo Pylon", "hpt_minelauncher": "Mine Launcher",
    "hpt_mininglaser": "Mining Laser", "hpt_mining_abrblstr": "Abrasion Blaster", "hpt_mining_seismchrgwarhd": "Seismic Charge Launcher",
    "hpt_mining_subsurfdispmisle": "Sub-Surface Displacement Missile", "hpt_mrascanner": "Pulse Wave Analyser",
    "hpt_shieldbooster": "Shield Booster", "hpt_heatsinklauncher": "Heat Sink Launcher", "hpt_chafflauncher": "Chaff Launcher",
    "hpt_plasmapointdefence": "Point Defence", "hpt_electroniccountermeasure": "Electronic Countermeasure",
    "hpt_cargoscanner": "Manifest Scanner", "hpt_crimescanner": "Kill Warrant Scanner", "hpt_cloudscanner": "Frame Shift Wake Scanner",
    "hpt_xenoscanner": "Xeno Scanner", "hpt_shutdownfieldneutraliser": "Shutdown Field Neutraliser",
    "hpt_antiunknownshutdown": "Shutdown Field Neutraliser", "hpt_causticsinklauncher": "Caustic Sink Launcher",
    "hpt_atdumbfiremissile": "AX Missile Rack", "hpt_atmulticannon": "AX Multi-Cannon", "hpt_flakmortar": "Remote Release Flak Launcher",
    "hpt_guardian_gausscannon": "Guardian Gauss Cannon", "hpt_guardian_plasmalauncher": "Guardian Plasma Charger",
    "hpt_guardian_shardcannon": "Guardian Shard Cannon",
}
_PREFIXES = sorted(_NAMES, key=len, reverse=True)
_ARMOUR = {"grade1": "Lightweight Alloy", "grade2": "Reinforced Alloy", "grade3": "Military Grade Composite",
           "mirrored": "Mirrored Surface Composite", "reactive": "Reactive Surface Composite"}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def words(label):
    """A journal label in words: "FSDOptimalMass" -> "FSD Optimal Mass", "DamagePerSecond" -> "Damage Per Second"."""
    s = re.sub(r"_+", " ", str(label or "")).strip()
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return " ".join(s.split())


def module_name(item):
    """What a module is, from its journal symbol: (name, size or None, rating letter or None, mount or None). An
    unknown family keeps its symbol, tidied, so a new module is still listed."""
    it = str(item or "").lower()
    size = rating = mount = None
    m = re.search(r"_size(\d)", it)
    if m:
        size = int(m.group(1))
    m = re.search(r"_class(\d)", it)
    if m:
        rating = RATING.get(int(m.group(1)))
    m = re.search(r"_(fixed|gimbal|turret)_", it + "_")
    if m:
        mount = MOUNTS[m.group(1)]
    m = re.search(r"_(tiny|small|medium|large|huge)(?:_|$)", it)
    if m and it.startswith("hpt_"):
        size = HARDPOINT_SIZE[m.group(1)]
    arm = re.search(r"_armour_(\w+)$", it)
    if arm:
        return _ARMOUR.get(arm.group(1), words(arm.group(1)).title() + " Armour"), None, None, None
    if it.startswith("int_shieldgenerator_") and it.endswith(("_fast", "_strong")):   # the kind is at the symbol's end
        return ("Bi-Weave" if it.endswith("_fast") else "Prismatic") + " Shield Generator", size, rating, mount
    name = next((_NAMES[p] for p in _PREFIXES if it.startswith(p)), None)
    if not name:
        tidy = re.sub(r"^(int|hpt)_", "", it)
        tidy = re.sub(r"_(size\d|class\d|fixed|gimbal|turret|tiny|small|medium|large|huge)(?=_|$)", "", tidy)
        name = tidy.replace("_", " ").strip().title() or "?"
    return name, size, rating, mount


def slot_group(slot):
    """(group, label) of a Loadout slot, or None for one that holds no equipment (paint, decals, the cockpit...)."""
    s = str(slot or "")
    if not s or _SKIP.search(s):
        return None
    if s in CORE:
        return "Core internals", CORE[s]
    m = re.fullmatch(r"(Tiny|Small|Medium|Large|Huge)Hardpoint(\d+)", s)
    if m:
        return ("Utility mounts", f"Utility {int(m.group(2))}") if m.group(1) == "Tiny" else ("Hardpoints", f"{m.group(1)} {int(m.group(2))}")
    m = re.fullmatch(r"Slot(\d+)_Size(\d)", s)
    if m:
        return "Optional internals", f"Size {m.group(2)}"
    m = re.fullmatch(r"Military(\d+)", s)
    if m:
        return "Optional internals", "Military"
    return "Optional internals", words(s)


def engineering(e):
    """A module's Engineering as {blueprint, level, quality, experimental, engineer, mods}; mods: the engineered
    stats as the game states them, each {label, value, original, pct (the change, None for a stock value of 0),
    good (the change is for the better: by the journal's LessIsGood)}. None for a stock module."""
    if not isinstance(e, dict):
        return None
    mods = []
    for m in e.get("Modifiers") or []:
        if not isinstance(m, dict) or not m.get("Label"):
            continue
        v, o = _num(m.get("Value")), _num(m.get("OriginalValue"))
        if v is None:      # a text value (a weapon's damage type): shown as it is
            if isinstance(m.get("ValueStr_Localised") or m.get("ValueStr"), str):
                mods.append({"label": words(m["Label"]), "text": m.get("ValueStr_Localised") or words(m.get("ValueStr")),
                             "value": None, "original": None, "pct": None, "good": None})
            continue
        pct = round(100 * (v - o) / abs(o), 1) if o not in (None, 0) else None
        good = None if o is None or v == o else (v < o) == bool(m.get("LessIsGood"))
        mods.append({"label": words(m["Label"]), "value": v, "original": o, "pct": pct, "good": good})
    return {"blueprint": words(re.sub(r"^[A-Za-z]+_", "", str(e.get("BlueprintName") or ""))) or None,
            "level": e.get("Level") if isinstance(e.get("Level"), int) else None,
            "quality": _num(e.get("Quality")), "engineer": e.get("Engineer") if isinstance(e.get("Engineer"), str) else None,
            "experimental": (e.get("ExperimentalEffect_Localised") or words(re.sub(r"^special_", "", str(e.get("ExperimentalEffect") or ""))))
            or None, "mods": mods}


def links(ev):
    """The Loadout as EDSY and Coriolis import it (the event itself, gzipped and base64'd into the address, as
    EDMarketConnector does): their pages open with this ship, where every figure this page lacks is worked out."""
    raw = json.dumps(ev, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="w", mtime=0) as f:
        f.write(raw)
    data = base64.urlsafe_b64encode(out.getvalue()).decode().replace("=", "%3D")
    return {"edsy": "https://edsy.org/#/I=" + data, "coriolis": "https://coriolis.io/import?data=" + data}


def summary(ev):
    """A Loadout event as the Ship view shows it: the ship's own figures, and its modules by group in slot order."""
    groups = {g: [] for g in GROUPS}
    for m in ev.get("Modules") or []:
        if not isinstance(m, dict) or not m.get("Item"):
            continue
        where = slot_group(m.get("Slot"))
        if not where:
            continue
        name, size, rating, mount = module_name(m["Item"])
        groups[where[0]].append({
            "slot": m.get("Slot"), "slot_label": where[1], "item": str(m["Item"]).lower(), "name": name, "size": size,
            "rating": rating, "mount": mount, "on": m.get("On") if isinstance(m.get("On"), bool) else None,
            "priority": m["Priority"] + 1 if isinstance(m.get("Priority"), int) and not isinstance(m.get("Priority"), bool) else None,
            "health": _num(m.get("Health")), "value": _num(m.get("Value")),
            "ammo": _num(m.get("AmmoInHopper")), "engineering": engineering(m.get("Engineering"))})
    order = list(CORE)
    groups["Core internals"].sort(key=lambda x: order.index(x["slot"]) if x["slot"] in order else len(order))
    for g in ("Hardpoints", "Utility mounts"):
        groups[g].sort(key=lambda x: (-(x["size"] or 0), x["slot"] or ""))
    groups["Optional internals"].sort(key=lambda x: (x["slot_label"] == "Military", x["slot"] or ""))
    cap = ev.get("FuelCapacity") if isinstance(ev.get("FuelCapacity"), dict) else {}
    mods = [m for g in GROUPS for m in groups[g]]
    return {"ts": ev.get("timestamp"), "ship_id": ev.get("ShipID"), "type": ev.get("Ship"),
            "name": ev.get("ShipName") or None, "ident": ev.get("ShipIdent") or None,
            "hull_value": _num(ev.get("HullValue")), "modules_value": _num(ev.get("ModulesValue")), "rebuy": _num(ev.get("Rebuy")),
            "hull_health": _num(ev.get("HullHealth")), "unladen": _num(ev.get("UnladenMass")),
            "cargo": _num(ev.get("CargoCapacity")), "max_range": _num(ev.get("MaxJumpRange")),
            "fuel_main": _num(cap.get("Main")), "fuel_reserve": _num(cap.get("Reserve")), "hot": bool(ev.get("Hot")),
            "engineered": sum(1 for m in mods if m["engineering"]), "count": len(mods),
            "groups": [{"name": g, "modules": groups[g]} for g in GROUPS if groups[g]], "links": links(ev)}


LOADOUT = b'"event":"Loadout"'


def latest_loadout(dirs, ship_id=None, files=8):
    """The newest Loadout event in the journals (of `ship_id` when given), or None: the last `files` journals are
    read, newest first, each from its end. The game writes one at login and after every change in outfitting."""
    found = {}
    for d in dirs:
        for p in glob(os.path.join(glob_escape(d), "Journal.*.log")):
            try:
                found.setdefault(os.path.basename(p), (os.path.getmtime(p), p))
            except OSError:
                pass
    for _, path in sorted(found.values(), reverse=True)[:files]:
        try:
            with open(path, "rb") as f:
                lines = f.read().split(b"\n")
        except OSError:
            continue
        for line in reversed(lines):
            if LOADOUT not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("event") == "Loadout" and isinstance(ev.get("Modules"), list) \
                    and (ship_id is None or ev.get("ShipID") == ship_id):
                return ev
    return None

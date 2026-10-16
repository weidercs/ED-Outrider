"""Engineering materials: what you are carrying, and what it lets you synthesise.

The journal's `Materials` event (written at every login) is a full snapshot; the events after it
are deltas. `apply(state, ev)` folds one event into a state dict, so the next login's snapshot
corrects any drift from an event this module does not understand.

Names are the journal's lowercase ids (`carbon`, `conductivecomponents`). Raw materials carry no
localised name in the journal, so the table below is the only place their display name comes from.
"""

# id -> (display name, category, grade). Grade decides the storage cap.
_RAW = {
    1: "carbon iron lead nickel phosphorus rhenium sulphur",
    2: "arsenic chromium germanium manganese vanadium zinc zirconium",
    3: "boron cadmium mercury molybdenum niobium tin tungsten",
    4: "antimony polonium ruthenium selenium technetium tellurium yttrium",
}
_MANUFACTURED = {
    1: ["salvagedalloys", "gridresistors", "chemicalstorageunits", "compactcomposites", "basicconductors",
        "crystalshards", "heatconductionwiring", "mechanicalscrap", "wornshieldemitters", "temperedalloys",
        "guardian_powercell", "guardian_sentinel_wreckagecomponents"],
    2: ["galvanisingalloys", "hybridcapacitors", "chemicalprocessors", "filamentcomposites", "conductivecomponents",
        "uncutfocuscrystals", "heatdispersionplate", "mechanicalequipment", "shieldemitters", "heatresistantceramics",
        "guardian_powerconduit", "unknowncarapace"],
    3: ["phasealloys", "electrochemicalarrays", "chemicaldistillery", "highdensitycomposites", "conductiveceramics",
        "focuscrystals", "heatexchangers", "mechanicalcomponents", "shieldingsensors", "precipitatedalloys",
        "guardian_sentinel_weaponparts", "guardian_techcomponent", "unknownenergycell", "tg_biomechanicalconduits",
        "tg_weaponparts", "tg_wreckagecomponents", "tg_causticshard", "tg_causticgeneratorparts"],
    4: ["protolightalloys", "polymercapacitors", "chemicalmanipulators", "fedproprietarycomposites", "conductivepolymers",
        "refinedfocuscrystals", "heatvanes", "configurablecomponents", "compoundshielding", "thermicalloys",
        "unknowntechnologycomponents", "tg_propulsionelement", "tg_causticcrystal"],
    5: ["protoradiolicalloys", "militarysupercapacitors", "pharmaceuticalisolators", "fedcorecomposites",
        "biotechconductors", "exquisitefocuscrystals", "protoheatradiators", "improvisedcomponents",
        "imperialshielding", "militarygradealloys", "unknownorganiccircuitry", "unknownenergysource"],
}
_ENCODED = {
    1: ["scrambledemissiondata", "disruptedwakeechoes", "shieldcyclerecordings", "encryptedfiles", "bulkscandata",
        "legacyfirmware"],
    2: ["archivedemissiondata", "fsdtelemetry", "shieldsoakanalysis", "encryptioncodes", "scanarchives",
        "consumerfirmware", "tg_structuraldata"],
    3: ["emissiondata", "wakesolutions", "shielddensityreports", "symmetrickeys", "scandatabanks",
        "industrialfirmware", "tg_shipflightdata", "tg_shipsystemsdata", "unknownshipsignature"],
    4: ["decodedemissiondata", "hyperspacetrajectories", "shieldpatternanalysis", "encryptionarchives",
        "encodedscandata", "securityfirmware", "unknownwakedata", "tg_interdictiondata", "tg_residuedata",
        "guardian_moduleblueprint", "guardian_weaponblueprint",
        # obelisk data: the game's Materials snapshots stop at 150, the grade 4 cap
        "ancientbiologicaldata", "ancientculturaldata", "ancienthistoricaldata", "ancientlanguagedata",
        "ancienttechnologicaldata"],
    5: ["compactemissionsdata", "dataminedwake", "shieldfrequencydata", "adaptiveencryptors", "classifiedscandata",
        "embeddedfirmware", "guardian_vesselblueprint"],
}
# Display names for manufactured and encoded ids the journal may not have localised yet.
_NAMES = {
    "salvagedalloys": "Salvaged Alloys", "gridresistors": "Grid Resistors", "chemicalstorageunits": "Chemical Storage Units",
    "compactcomposites": "Compact Composites", "basicconductors": "Basic Conductors", "crystalshards": "Crystal Shards",
    "heatconductionwiring": "Heat Conduction Wiring", "mechanicalscrap": "Mechanical Scrap",
    "wornshieldemitters": "Worn Shield Emitters", "temperedalloys": "Tempered Alloys",
    "guardian_powercell": "Guardian Power Cell", "guardian_sentinel_wreckagecomponents": "Guardian Wreckage Components",
    "galvanisingalloys": "Galvanising Alloys", "hybridcapacitors": "Hybrid Capacitors",
    "chemicalprocessors": "Chemical Processors", "filamentcomposites": "Filament Composites",
    "conductivecomponents": "Conductive Components", "uncutfocuscrystals": "Flawed Focus Crystals",
    "heatdispersionplate": "Heat Dispersion Plate", "mechanicalequipment": "Mechanical Equipment",
    "shieldemitters": "Shield Emitters", "heatresistantceramics": "Heat Resistant Ceramics",
    "guardian_powerconduit": "Guardian Power Conduit", "unknowncarapace": "Thargoid Carapace",
    "phasealloys": "Phase Alloys", "electrochemicalarrays": "Electrochemical Arrays",
    "chemicaldistillery": "Chemical Distillery", "highdensitycomposites": "High Density Composites",
    "conductiveceramics": "Conductive Ceramics", "focuscrystals": "Focus Crystals", "heatexchangers": "Heat Exchangers",
    "mechanicalcomponents": "Mechanical Components", "shieldingsensors": "Shielding Sensors",
    "precipitatedalloys": "Precipitated Alloys", "guardian_sentinel_weaponparts": "Guardian Sentinel Weapon Parts",
    "guardian_techcomponent": "Guardian Technology Component", "unknownenergycell": "Thargoid Energy Cell",
    "tg_biomechanicalconduits": "Bio-Mechanical Conduits", "tg_weaponparts": "Weapon Parts",
    "tg_wreckagecomponents": "Wreckage Components", "tg_causticshard": "Caustic Shard",
    "tg_causticgeneratorparts": "Corrosive Mechanisms", "protolightalloys": "Proto Light Alloys",
    "polymercapacitors": "Polymer Capacitors", "chemicalmanipulators": "Chemical Manipulators",
    "fedproprietarycomposites": "Proprietary Composites", "conductivepolymers": "Conductive Polymers",
    "refinedfocuscrystals": "Refined Focus Crystals", "heatvanes": "Heat Vanes",
    "configurablecomponents": "Configurable Components", "compoundshielding": "Compound Shielding",
    "thermicalloys": "Thermic Alloys", "unknowntechnologycomponents": "Thargoid Technological Components",
    "tg_propulsionelement": "Propulsion Elements", "tg_causticcrystal": "Caustic Crystal",
    "protoradiolicalloys": "Proto Radiolic Alloys", "militarysupercapacitors": "Military Supercapacitors",
    "pharmaceuticalisolators": "Pharmaceutical Isolators", "fedcorecomposites": "Core Dynamics Composites",
    "biotechconductors": "Biotech Conductors", "exquisitefocuscrystals": "Exquisite Focus Crystals",
    "protoheatradiators": "Proto Heat Radiators", "improvisedcomponents": "Improvised Components",
    "imperialshielding": "Imperial Shielding", "militarygradealloys": "Military Grade Alloys",
    "unknownorganiccircuitry": "Thargoid Organic Circuitry", "unknownenergysource": "Sensor Fragment",
    "scrambledemissiondata": "Exceptional Scrambled Emission Data", "disruptedwakeechoes": "Atypical Disrupted Wake Echoes",
    "shieldcyclerecordings": "Distorted Shield Cycle Recordings", "encryptedfiles": "Unusual Encrypted Files",
    "bulkscandata": "Anomalous Bulk Scan Data", "legacyfirmware": "Specialised Legacy Firmware",
    "archivedemissiondata": "Irregular Emission Data", "fsdtelemetry": "Anomalous FSD Telemetry",
    "shieldsoakanalysis": "Inconsistent Shield Soak Analysis", "encryptioncodes": "Tagged Encryption Codes",
    "scanarchives": "Unidentified Scan Archives", "consumerfirmware": "Modified Consumer Firmware",
    "tg_structuraldata": "Thargoid Structural Data", "emissiondata": "Unexpected Emission Data",
    "wakesolutions": "Strange Wake Solutions", "shielddensityreports": "Untypical Shield Scans",
    "symmetrickeys": "Open Symmetric Keys", "scandatabanks": "Classified Scan Databanks",
    "industrialfirmware": "Cracked Industrial Firmware", "ancientbiologicaldata": "Pattern Alpha Obelisk Data",
    "ancientculturaldata": "Pattern Beta Obelisk Data", "ancienthistoricaldata": "Pattern Gamma Obelisk Data",
    "ancientlanguagedata": "Pattern Delta Obelisk Data", "ancienttechnologicaldata": "Pattern Epsilon Obelisk Data",
    "tg_shipflightdata": "Ship Flight Data", "tg_shipsystemsdata": "Ship Systems Data",
    "unknownshipsignature": "Thargoid Ship Signature", "decodedemissiondata": "Decoded Emission Data",
    "hyperspacetrajectories": "Eccentric Hyperspace Trajectories", "shieldpatternanalysis": "Aberrant Shield Pattern Analysis",
    "encryptionarchives": "Atypical Encryption Archives", "encodedscandata": "Divergent Scan Data",
    "securityfirmware": "Security Firmware Patch", "unknownwakedata": "Thargoid Wake Data",
    "tg_interdictiondata": "Thargoid Interdiction Telemetry", "tg_residuedata": "Thargoid Residue Data",
    "guardian_moduleblueprint": "Guardian Module Blueprint Fragment",
    "guardian_weaponblueprint": "Guardian Weapon Blueprint Fragment", "compactemissionsdata": "Abnormal Compact Emissions Data",
    "dataminedwake": "Datamined Wake Exceptions", "shieldfrequencydata": "Peculiar Shield Frequency Data",
    "adaptiveencryptors": "Adaptive Encryptors Capture", "classifiedscandata": "Classified Scan Fragment",
    "embeddedfirmware": "Modified Embedded Firmware", "guardian_vesselblueprint": "Guardian Vessel Blueprint Fragment",
}

MATERIALS = {}
for _g, _ids in _RAW.items():
    for _m in _ids.split():
        MATERIALS[_m] = (_m.capitalize(), "Raw", _g)
for _cat, _table in (("Manufactured", _MANUFACTURED), ("Encoded", _ENCODED)):
    for _g, _ids in _table.items():
        for _m in _ids:
            MATERIALS[_m] = (_NAMES.get(_m, _m), _cat, _g)

# Storage caps per grade (the same for every category since the 2020 material-storage change).
CAPS = {1: 300, 2: 250, 3: 200, 4: 150, 5: 100}

# Synthesis recipes an explorer reaches for. `verified` recipes were checked against the materials
# a real Synthesis journal event consumed; the rest are the published in-game recipes.
SYNTH = {
    "FSD injection basic": {"materials": {"carbon": 1, "vanadium": 1, "germanium": 1}, "boost": "+25%",
                            "verified": False},
    "FSD injection standard": {"materials": {"carbon": 1, "vanadium": 1, "germanium": 1, "cadmium": 1, "niobium": 1},
                               "boost": "+50%", "verified": False},
    "FSD injection premium": {"materials": {"carbon": 1, "germanium": 1, "arsenic": 1, "niobium": 1, "yttrium": 1,
                                            "polonium": 1}, "boost": "+100%", "verified": False},
    # the SRV's refuel and repair ("Fuel Basic" / "Repair Basic" in the journal): no synthesis refuels or
    # repairs the ship itself
    "SRV refuel basic": {"materials": {"phosphorus": 1, "sulphur": 1}, "verified": True},
    "SRV repair basic": {"materials": {"iron": 2, "nickel": 1}, "verified": True},
    "Limpet basic": {"materials": {"iron": 10, "nickel": 10}, "verified": True},
    # the Rhino's mining rigs (CMDR Dunn Actual's Rhino Planetary Mining guide, v0.6)
    "Mining rig restock": {"materials": {"iron": 3, "nickel": 2, "mechanicalequipment": 1}, "verified": False},
}
BOOSTS = ("basic", "standard", "premium")
# The jumponium call-out: the scarce FSD-injection materials worth a landing, with the least share of a body's
# surface worth one (roughly 1% for grade 4, 1.5% for the others); a boost you can still make more often than
# JUMPONIUM_MAX times is not short of anything.
JUMPONIUM_SCARCE = {"arsenic": 1.5, "cadmium": 1.5, "yttrium": 1.0, "polonium": 1.0}
JUMPONIUM_MAX = 2


def new_state():
    return {"counts": {}, "names": {}, "snapshot_ts": None, "ts": None}


def _add(state, name, n, localised=None):
    if not name:
        return
    name = name.lower()
    if localised and not localised.startswith("$"):
        state["names"][name] = localised
    c = state["counts"].get(name, 0) + int(n or 0)
    cap = CAPS.get(MATERIALS.get(name, (None, None, None))[2])
    if cap:
        c = min(c, cap)   # the game logs the pickup's nominal count even when the bin fills before it
    if c > 0:
        state["counts"][name] = c
    else:
        state["counts"].pop(name, None)


def apply(state, ev):
    """Fold one journal event into `state`. Returns True if it changed anything."""
    name, ts = ev.get("event"), ev.get("timestamp", "")
    if name == "Materials":
        if state.get("snapshot_ts") and ts < state["snapshot_ts"]:
            return False       # an older snapshot read out of order
        state.update(counts={}, snapshot_ts=ts, ts=ts)
        for cat in ("Raw", "Manufactured", "Encoded"):
            for m in ev.get(cat) or []:
                _add(state, m.get("Name"), m.get("Count"), m.get("Name_Localised"))
        return True
    if state.get("snapshot_ts") and ts < state["snapshot_ts"]:
        return False           # already counted in the snapshot that followed it
    before = dict(state["counts"])
    if name == "MaterialCollected":
        _add(state, ev.get("Name"), ev.get("Count", 1), ev.get("Name_Localised"))
    elif name == "MaterialDiscarded":
        _add(state, ev.get("Name"), -ev.get("Count", 1))
    elif name == "Synthesis":
        for m in ev.get("Materials") or []:
            _add(state, m.get("Name"), -m.get("Count", 1))
    elif name == "EngineerCraft":
        for m in ev.get("Ingredients") or []:
            if (m.get("Name") or "").lower() in state["counts"] or (m.get("Name") or "").lower() in MATERIALS:
                _add(state, m.get("Name"), -m.get("Count", 1))
    elif name == "TechnologyBroker":
        for m in ev.get("Materials") or []:
            _add(state, m.get("Name"), -m.get("Count", 1))
    elif name == "ScientificResearch":
        _add(state, ev.get("Name"), -ev.get("Count", 1))
    elif name == "MaterialTrade":
        paid, got = ev.get("Paid") or {}, ev.get("Received") or {}
        _add(state, paid.get("Material"), -paid.get("Quantity", 0), paid.get("Material_Localised"))
        _add(state, got.get("Material"), got.get("Quantity", 0), got.get("Material_Localised"))
    elif name == "EngineerContribution":
        if ev.get("Type") == "Materials":   # donations to unlock an engineer (commodities are cargo)
            _add(state, ev.get("Material"), -ev.get("Quantity", 0))
    elif name == "MissionCompleted":
        for m in ev.get("MaterialsReward") or []:
            _add(state, m.get("Name"), m.get("Count", 1), m.get("Name_Localised"))
    else:
        return False
    if state["counts"] != before:
        state["ts"] = ts
        return True
    return False


def craftable(counts, recipe):
    """How many times a recipe can be made, and the material that runs out first."""
    best, limit = None, None
    for m, need in recipe.items():
        n = counts.get(m, 0) // need
        if best is None or n < best:
            best, limit = n, m
    return best or 0, limit


def jumponium_short(counts, threshold=JUMPONIUM_MAX):
    """The scarce materials holding back FSD injections: for the standard and premium recipes you can make at most
    `threshold` times, every material whose floor(have / need) equals that count (the tie set: craftable() names
    only one), kept to JUMPONIUM_SCARCE and to those not near their grade's cap. {material id: count held}."""
    out = {}
    for b in ("standard", "premium"):
        recipe = SYNTH[f"FSD injection {b}"]["materials"]
        n, _ = craftable(counts, recipe)
        if n > threshold:
            continue
        for m, need in recipe.items():
            have = counts.get(m, 0)
            if m in JUMPONIUM_SCARCE and have // need == n and have < 0.9 * CAPS[MATERIALS[m][2]]:
                out[m] = have
    return out


def jumponium_pick(body_materials, short):
    """What a body's surface offers of the `short` materials (jumponium_short): the scarcest one you hold (the
    richest share on a tie) at or over its floor, as {material, pct}, or None. `body_materials` is a Scan's
    Materials list ([{Name, Percent}])."""
    best = None
    for x in body_materials or []:
        m, pct = (x.get("Name") or "").lower(), x.get("Percent") or 0
        if m in short and pct >= JUMPONIUM_SCARCE[m]:
            if best is None or (short[m], -pct) < (short[best["material"]], -best["pct"]):
                best = {"material": m, "pct": round(pct, 1)}
    return best


def boosts(counts):
    return {b: craftable(counts, SYNTH[f"FSD injection {b}"]["materials"])[0] for b in BOOSTS}


def display_name(state, mid):
    return (state or {}).get("names", {}).get(mid) or MATERIALS.get(mid, (mid,))[0]


def inventory(state):
    """The full inventory for the Materials view: every known material, held or not."""
    state = state or new_state()
    counts = state.get("counts") or {}
    rows = []
    for mid in sorted(set(MATERIALS) | set(counts)):
        _, cat, grade = MATERIALS.get(mid, (mid, "Other", None))
        rows.append({"id": mid, "name": display_name(state, mid), "category": cat, "grade": grade,
                     "count": counts.get(mid, 0), "cap": CAPS.get(grade)})
    synth = []
    for rname, r in SYNTH.items():
        n, limit = craftable(counts, r["materials"])
        synth.append({"name": rname, "craftable": n, "limit": display_name(state, limit) if limit else None,
                      "boost": r.get("boost"), "verified": r["verified"],
                      "materials": [{"id": m, "name": display_name(state, m), "need": q, "have": counts.get(m, 0)}
                                    for m, q in r["materials"].items()]})
    return {"rows": rows, "synthesis": synth, "snapshot_ts": state.get("snapshot_ts"), "ts": state.get("ts")}

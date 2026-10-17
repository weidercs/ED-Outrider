"""Space chatter (NEXT-VERSION #15, the author 2026-10-16): idle talk when nothing has happened for a while.

In quiet supercruise, or while you are on foot or in the SRV on a planet, a personality says something now and then:
a monologue (each personality's own, some knowing where you are), or, with the crew on, one station asks another
something and gets an answer (now and then a third word back). Roles pick WHAT they talk about (mostly their
station: fuel for the Engineer and the Navigator, biology for the Exobiologist and the Science Officer...; sometimes
something personal), their personalities HOW. Two roles of the same personality, or of the same voice, never talk to
each other.

This module is pure: the chatter lines' keys and their placeholders (they live in the speech files beside the alerts',
so personality files, bans, the voice lab and the checks work on them), the topics and who asks and answers them,
and where you are for chatter, from Status.json's flags. The page keeps the clocks and picks the lines.
"""

# ---- Status.json bits (Frontier's journal manual) ----
F_DOCKED, F_LANDED, F_SUPERCRUISE = 1 << 0, 1 << 1, 1 << 4
F_FSD_CHARGING, F_LOW_FUEL, F_OVERHEATING = 1 << 17, 1 << 19, 1 << 20
F_HAS_LAT_LONG, F_IN_DANGER, F_INTERDICTED = 1 << 21, 1 << 22, 1 << 23
F_IN_MAIN_SHIP, F_IN_SRV, F_FSD_JUMP = 1 << 24, 1 << 26, 1 << 30
F2_ON_FOOT, F2_IN_TAXI, F2_IN_MULTICREW, F2_ON_FOOT_IN_STATION, F2_ON_FOOT_ON_PLANET = 1 << 0, 1 << 1, 1 << 2, 1 << 3, 1 << 4
F2_LOW_OXYGEN, F2_LOW_HEALTH, F2_VERY_COLD, F2_VERY_HOT = 1 << 6, 1 << 7, 1 << 10, 1 << 11
F2_ON_FOOT_IN_HANGAR, F2_ON_FOOT_SOCIAL_SPACE = 1 << 13, 1 << 14
# on foot in a station, a hangar or a social space counts as docked, as for the rest of the server (ON_FOOT_DOCKED in
# ed_outrider.py): a planetary port's concourse also sets on-foot-on-planet, and is no place for surface chatter
F2_ON_FOOT_DOCKED = F2_ON_FOOT_IN_STATION | F2_ON_FOOT_IN_HANGAR | F2_ON_FOOT_SOCIAL_SPACE
F2_HYPERDRIVE_CHARGING = 1 << 19
GUI_BUSY = {6: "the galaxy map", 7: "the system map", 8: "the orrery", 9: "the FSS", 10: "the DSS", 11: "the codex"}


def where(flags, flags2=0, gui_focus=0):
    """(where, why_not) for chatter now: where is "space" (supercruise in your ship) or "planet" (on foot or in the SRV
    on a planet's surface), else None; why_not says what keeps it quiet when you are there (danger, the FSD, a screen
    the game has open), else None. Unsold data never does (the author always carries a lot)."""
    f, f2 = flags or 0, flags2 or 0
    if f2 & (F2_IN_TAXI | F2_IN_MULTICREW | F2_ON_FOOT_DOCKED) or f & F_DOCKED:
        return None, None
    if f & F_SUPERCRUISE and f & F_IN_MAIN_SHIP:
        place = "space"
    elif f2 & F2_ON_FOOT_ON_PLANET or (f & F_IN_SRV and f & F_HAS_LAT_LONG):
        place = "planet"
    else:
        return None, None
    if f & (F_IN_DANGER | F_INTERDICTED):
        return place, "danger"
    if f & F_OVERHEATING:
        return place, "heat"
    if f & F_LOW_FUEL:
        return place, "low fuel"
    if f & (F_FSD_CHARGING | F_FSD_JUMP) or f2 & F2_HYPERDRIVE_CHARGING:
        return place, "the FSD"
    # the suit's oxygen or health only: very cold and very hot are common on the worlds you sample, and once the
    # temperature hurts, low health says so (the author, 2026-10-16)
    if f2 & (F2_LOW_OXYGEN | F2_LOW_HEALTH):
        return place, "your suit"
    if (gui_focus or 0) in GUI_BUSY:
        return place, GUI_BUSY[gui_focus]
    return place, None


# ---- chattiness: the quiet before the first line and between lines (minutes; the page randomises N to 2N) ----
LEVELS = {"rare": 15, "normal": 7, "chatty": 4}
LEVEL_DEFAULT = "normal"
RARE_PER_HOUR = 3          # "rare" also caps it at this many an hour
GRACE_S = 60               # quiet after entering supercruise, or stepping out on a planet, before anyone talks
DIALOGUE_SHARE = 0.3       # with two roles that may talk, this share of the chatter is a dialogue
THIRD_BEAT_SHARE = 0.35    # and this share of dialogues ends with the asker's short reaction


# ---- the topics: (id, kind, who asks, who answers) ----
STATION, PERSONAL = "station", "personal"
EVERY_ROLE = ("xo", "navigator", "science", "exobiologist", "engineer", "quartermaster", "comms", "tactical", "mining")
TOPICS = (
    ("fuel", STATION, ("navigator", "xo"), ("engineer",)),
    ("route", STATION, ("xo", "engineer", "science"), ("navigator",)),
    ("drive", STATION, ("navigator", "tactical", "xo"), ("engineer",)),
    ("ship", STATION, ("xo", "quartermaster"), ("engineer",)),
    ("biology", STATION, ("science", "xo", "quartermaster"), ("exobiologist",)),
    ("stars", STATION, ("navigator", "exobiologist", "comms"), ("science",)),
    ("money", STATION, ("xo", "engineer", "mining", "comms"), ("quartermaster",)),
    ("mining", STATION, ("quartermaster", "engineer"), ("mining",)),
    ("threats", STATION, ("comms", "xo", "navigator"), ("tactical",)),
    ("traffic", STATION, ("tactical", "xo", "quartermaster"), ("comms",)),
    ("the_captain", STATION, EVERY_ROLE, ("xo",)),
    ("watch", STATION, EVERY_ROLE, EVERY_ROLE),
    ("family", PERSONAL, EVERY_ROLE, EVERY_ROLE),
    ("home", PERSONAL, EVERY_ROLE, EVERY_ROLE),
    ("food", PERSONAL, EVERY_ROLE, EVERY_ROLE),
    ("best_day", PERSONAL, EVERY_ROLE, EVERY_ROLE),
    ("fortune", PERSONAL, EVERY_ROLE, EVERY_ROLE),
    ("before", PERSONAL, EVERY_ROLE, EVERY_ROLE),
)
PERSONAL_SHARE = 0.25      # about a quarter of the dialogues are personal (the author: "should be mostly stations")
TOPIC_WORDS = {
    "fuel": "fuel, scooping, the tank", "route": "where we are heading, the route, the next jumps",
    "drive": "the frame shift drive, jump range, the ship's speed", "ship": "the ship's condition, repairs, modules",
    "biology": "exobiology, the life we sample", "stars": "stars, planets, the strange things out here",
    "money": "credits, the data we carry and what it will sell for", "mining": "mining, rigs, cargo of ore",
    "threats": "pirates, interdictions, keeping the ship safe", "traffic": "comms, station traffic, other commanders",
    "the_captain": "the captain's flying and decisions (affectionately or not)", "watch": "a quiet watch, boredom, time passing",
    "family": "what your family was like", "home": "where you grew up", "food": "the best (or worst) meal you ever had",
    "best_day": "the best day you remember", "fortune": "what you would do with a fortune",
    "before": "what you did before this ship",
}

# ---- the chatter lines' keys (outrider.speech.KEYS takes them in) and their placeholders ----
_CONTEXT = ("{system} (the system you are in), {minutes} (minutes in supercruise so far), and this session's {jumps} "
            "and {firsts} (systems first discovered); a line needing one that is not known is not said")
KEYS = {
    "chatter_space": "idle talk in quiet supercruise, nobody in particular addressed: " + _CONTEXT,
    "chatter_planet_orbit": "idle talk from the ship in orbit while you are on foot or in the SRV on {body}: {ship_dist} "
                            "(how far the ship is, if known)",
    "chatter_planet_landed": "idle talk from the ship landed near you while you are on foot or in the SRV on {body}: "
                             "{ship_dist} (how far the ship is)",
    "chatter_react": "a dialogue's short last word back from the one who asked, after the answer: {to} (the one who "
                     "answered: its name, else its station)",
}
for _id, _kind, _ask, _answer in TOPICS:
    KEYS[f"chat_{_id}_ask"] = (f"one crew member asks another about {TOPIC_WORDS[_id]}: {{to}} (the one asked: its name, "
                               f"else its station, e.g. \"Engineer\")")
    KEYS[f"chat_{_id}_answer"] = (f"the answer to a question about {TOPIC_WORDS[_id]}: {{to}} (the one who asked: its "
                                  f"name, else its station)")
SAMPLES = {
    "chatter_space": {"system": "Drojau LL-O b26-3", "minutes": 6, "jumps": 42, "firsts": 7},
    "chatter_planet_orbit": {"body": "B 7", "ship_dist": "1.2 km"},
    "chatter_planet_landed": {"body": "B 7", "ship_dist": "300 m"},
    "chatter_react": {"to": "Mira"},
    **{f"chat_{t[0]}_{w}": {"to": "Mira"} for t in TOPICS for w in ("ask", "answer")},
}
# The lines are in the speech files (written 2026-10-17 for all eleven personalities): the shipped-lines test asks for
# them, and a personality's coverage counts them. False again would make them optional (a key added before its lines).
LINES_WRITTEN = True


def page_info():
    """What the page needs to talk (sent with the lines): the topics with who asks and answers them, the timings, the
    sample values for the voice lab."""
    return {"topics": [{"id": t, "kind": k, "ask": list(a), "answer": list(b)} for t, k, a, b in TOPICS],
            "levels": dict(LEVELS), "rare_per_hour": RARE_PER_HOUR, "grace": GRACE_S, "dialogue": DIALOGUE_SHARE,
            "third": THIRD_BEAT_SHARE, "personal": PERSONAL_SHARE, "samples": SAMPLES, "written": LINES_WRITTEN}

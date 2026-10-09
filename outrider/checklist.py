"""The exobiology checklist: every species the rules know, by galactic region, with what you have done with it there.
Pure: the rules (outrider.bio's), your runs and your codex entries come in; the page's table goes out.

For each species and region:
  possible  "yes" when one of its rulesets lets it grow in the region, "parts" when every one that does also needs
            a place within it (near a Guardian site, in a tuber zone, by a nebula, one system), None when the rules
            rule it out ("not here": the rules' prediction, not proof nobody found it there)
  state     your best there: "sold" > "aboard" > "lost" > "logged" (in your codex, no finished run: a first sample, a
            composition scan) > None
  variants  its colours (ExploData's tables: by the star's class or by a material on the body), each with your best
            state there and what gives it ("F, G stars", "polonium"); a species with no colour table (anemones, brain
            trees, tubers...) is its own one variant
"""

STATES = ("sold", "aboard", "lost", "logged")   # best first
RANK = {s: i for i, s in enumerate(STATES)}
# a ruleset key that ties the species to a place inside a region, with the value that means "no such tie"
LOCAL = {"guardian": (None, False, "", [], {}), "tuber": (None, False, "", [], {}), "system": (None, ""),
         "nebula": (None, False, "", "none")}


def best(a, b):
    """The better of two states (None: nothing)."""
    if a is None:
        return b
    if b is None:
        return a
    return a if RANK[a] <= RANK[b] else b


def _local(ruleset):
    return any(k in ruleset and ruleset[k] not in empty for k, empty in LOCAL.items())


def possibility(species, region, region_ok):
    """"yes", "parts" or None for one species in region number `region`. `region_ok(ruleset, region)`: whether a
    ruleset lets it grow there (outrider.bio.ruleset_region_ok). A species with no rules at all is "yes": unknown is
    not "not here"."""
    if not species.get("rulesets"):
        return "yes"
    allowing = [r for r in species["rulesets"] if region_ok(r, region)]
    if not allowing:
        return None
    return "parts" if all(_local(r) for r in allowing) else "yes"


def colours(species):
    """[(colour, [conditions])] for a species, in the colour's first appearance in its table; [] when it has none."""
    c = species.get("colors") or {}
    table = c.get("star") or c.get("element") or {}
    out = {}
    for cond, colour in table.items():
        if isinstance(colour, str) and colour:
            out.setdefault(colour, []).append(cond)
    return list(out.items())


def colour_of(variant, species_name):
    """The colour in a journal or codex variant name ("Bacterium Aurasus - Teal" -> "teal"), lower-cased; None when
    it has none (a run from before the 2023 patch, or a species with no colours)."""
    v = (variant or "").strip()
    if " - " not in v:
        return None
    head, colour = v.rsplit(" - ", 1)
    return colour.strip().lower() or None if head.strip().lower() == (species_name or "").lower() else None


def merge_species(species_list):
    """The rules' species, one per game species id ($Codex_Ent_..._Name;), in their order, and {name lower-cased: id}
    for every name met (a duplicate under a misspelled name is merged into the one with rules: BioScan lists
    $Codex_Ent_Stratum_04_Name; as "Stratum Aranaemus" with none and "Stratum Araneamus" with its rules)."""
    by_id, names = {}, {}
    for sp in species_list:
        sid = sp.get("id") or sp["name"]
        names[sp["name"].lower()] = sid
        have = by_id.get(sid)
        if have is None or (not have.get("rulesets") and sp.get("rulesets")):
            by_id[sid] = sp
    return list(by_id.values()), names


def table(species_list, region, region_ok, runs, codex, region_count):
    """The checklist for region number `region` (None: All regions).

    species_list  the rules' species ({name, genus, value, rulesets, colors})
    region_ok     (ruleset, region) -> bool
    runs          your runs: [{species_id ($Codex_Ent_..._Name;), species (name), variant (name or None), region
                  (number or None), state}], state one of "sold", "aboard", "lost", "in progress"
    codex         your codex entries: [{name ("Bacterium Aurasus - Teal" or "Luteolum Anemone"), region (number)}]
    region_count  the number of regions (their numbers run 1..region_count)

    -> {"genera": [{genus, species: [row]}], "summary": {...}}; a row: {name, short, value, possible, state, runs,
    variants: {total, found, list: [{colour, where, state}]}}."""
    regions = range(1, region_count + 1) if region is None else (region,)
    here = lambda r: region is None or r == region   # noqa: E731

    species_list, names = merge_species(species_list)
    got, got_colour, n_runs = {}, {}, {}

    def note(key, colour, r, state):
        if key is None or not here(r):
            return
        got[key] = best(got.get(key), state)
        if colour:
            got_colour[(key, colour)] = best(got_colour.get((key, colour)), state)

    ids = {s.get("id") for s in species_list}
    for run in runs:
        name = run.get("species") or ""
        key = run.get("species_id") if run.get("species_id") in ids else names.get(name.lower())
        state = {"in progress": "logged"}.get(run.get("state"), run.get("state"))
        if state not in RANK or key is None:
            continue
        note(key, colour_of(run.get("variant"), name), run.get("region"), state)
        if here(run.get("region")):
            n_runs[key] = n_runs.get(key, 0) + 1
    for entry in codex:
        full = (entry.get("name") or "").strip()
        name = full.rsplit(" - ", 1)[0] if " - " in full else full
        note(names.get(name.lower()), colour_of(full, name), entry.get("region"), "logged")

    genera, totals = {}, {"possible": 0, "found": 0, "sold": 0, "aboard": 0, "lost": 0, "logged": 0,
                          "colours": 0, "colours_found": 0}
    for sp in species_list:
        key = sp.get("id") or sp["name"]
        poss = None
        for r in regions:
            p = possibility(sp, r, region_ok)
            poss = "yes" if "yes" in (poss, p) else (p or poss)
            if poss == "yes":
                break
        cols = colours(sp)
        state = got.get(key)
        if cols:
            vlist = [{"colour": c, "where": ", ".join(w), "state": got_colour.get((key, c.lower()))} for c, w in cols]
        else:   # its own one variant: found when the species is
            vlist = [{"colour": None, "where": None, "state": state}]
        found = sum(1 for v in vlist if v["state"])
        row = {"name": sp["name"], "short": short_name(sp), "value": sp.get("value"), "possible": poss, "state": state,
               "runs": n_runs.get(key, 0), "variants": {"total": len(vlist), "found": found, "list": vlist}}
        genera.setdefault(sp.get("genus") or "?", []).append(row)
        if poss or state:
            totals["possible"] += 1 if poss else 0
            totals["colours"] += len(vlist) if poss else 0
            totals["colours_found"] += found
            if state:
                totals["found"] += 1
                totals[state] += 1
    out = [{"genus": g, "species": sorted(rows, key=lambda x: x["short"])} for g, rows in sorted(genera.items())]
    return {"genera": out, "summary": totals}


def short_name(species):
    """A species' name inside its genus box: "Arcus" for Aleoida Arcus; a species named after its genus with a
    prefix ("Luteolum Anemone", "Roseum Brain Tree") keeps the prefix; one alone in its genus keeps its name."""
    name, genus = species["name"], species.get("genus") or ""
    if genus and name.lower().startswith(genus.lower() + " "):
        return name[len(genus) + 1:]
    if genus and name.lower().endswith(" " + genus.lower()):
        return name[: -len(genus) - 1]
    return name

// This fork's own page code, apart from upstream's page.js so the two merge without conflicts. Loaded before page.js:
// everything here is a definition, and uses page.js's helpers (esc, apiJson, plotBtn, copyText, CM, cmTable...) only
// when called.

// ---- Commander → Engineering, the fork's way (static/fork.js; GET /api/engineers*, outrider/engineers.py): upstream's
// cmdrEngineeringHtml hands the tab over to forkEngineeringHtml with one line. On upstream's blueprints (one row per
// kind of module and blueprint) and its search box and craft switch (CM.q, CM.craft, above the pane), it adds:
// parts and grades to pick (any of them), the Engineers list with each one's system and distance (Copy, Plot route),
// Load my ship, Clear filters and Plan the trip (outrider/engtour.py) ----
const FX = {parts: new Set(), grades: new Set(), ship: null, trip: null, tripNote: null, tripLocked: false, tripCarrier: false,
            eng: null, engKey: null, engOpen: true};
try { const t = JSON.parse(localStorage.getItem("fxTrip") || "null"); if (t && Array.isArray(t.stops)) FX.trip = t; } catch {}
const fxPlain = n => String(n || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const fxGradeKey = (b, g) => `${b.module}|${b.id}|${g.grade}`;
const fxRedraw = () => { if (typeof cmdrDrawBody === "function" && view === "cmdr" && CM.tab === "engineering") cmdrDrawBody(); };
// every engineer with their system, progress and distance (GET /api/engineers), asked when the tab is drawn and after a jump
async function fxEngLoad() {
  const key = typeof posId === "function" ? posId() : null;
  if (FX.engKey === key) return;
  FX.engKey = key;
  let d;
  try { d = await apiJson("api/engineers"); } catch (err) { d = {error: err.message}; }
  FX.eng = d && typeof d === "object" ? d : {error: "no answer"};
  fxRedraw();
}
// who does what of the picks: {name (fxPlain): Set of what, "Power plant" or "Overcharged G5"} for the picked parts
// (any grade) and, apart, the picked grades. Pure.
function fxSupports(blueprints, parts, grades) {
  const byPart = new Map(), byGrade = new Map();
  const add = (m, e, what) => { const k = fxPlain(e.name); if (!m.has(k)) m.set(k, new Set()); m.get(k).add(what); };
  for (const b of blueprints) for (const g of b.grades) {
    if (parts.has(b.module)) for (const e of g.engineers) add(byPart, e, b.module);
    if (grades.has(fxGradeKey(b, g))) for (const e of g.engineers) add(byGrade, e, `${b.name} G${g.grade}`);
  }
  return {byPart: parts.size ? byPart : null, byGrade: grades.size ? byGrade : null};
}
// one engineer's distance: the light years, else why there are none. Pure.
function fxDist(system, d) {
  if (!system) return "";
  if (!d) return `<span class="unk">…</span>`;
  const v = (d.distances || {})[system];
  if (v != null) return `${Number(v).toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 1})} ly`;
  return `<span class="unk" title="${esc(!d.from ? "no position yet: after your first jump" : d.error || "Spansh does not know this system")}">?</span>`;
}
// the Engineers section: every engineer (or those the search and the picks leave), where each works, how far. Pure.
function fxEngineersHtml(sup, q) {
  const d = FX.eng;
  if (!d) return `<div class="unk cmnote">Engineers: reading…</div>`;
  const all = d.engineers || [];
  if (!all.length) return d.error ? `<div class="unk cmnote">Engineers: ${esc(d.error)}</div>` : "";
  const keep = e => { const k = fxPlain(e.name);
    return (!q || [e.name, e.kind, e.system, e.region].filter(Boolean).join(" ").toLowerCase().includes(q))
      && (!sup.byPart || sup.byPart.has(k)) && (!sup.byGrade || sup.byGrade.has(k)); };
  const eng = all.filter(keep), picks = FX.parts.size || FX.grades.size;
  const what = e => { const k = fxPlain(e.name), w = new Set([...(sup.byPart && sup.byPart.get(k) || []), ...(sup.byGrade && sup.byGrade.get(k) || [])]);
    return w.size ? ` <span class="cmsupports">· ${esc([...w].sort((a, b) => a.localeCompare(b)).join(", "))}</span>` : ""; };
  const status = e => e.progress === "Unlocked" ? `<span class="ok">unlocked${e.rank != null ? `, grade ${e.rank}` : ""}</span>`
    : e.progress ? `<span class="warnc">${esc(e.progress.toLowerCase())}</span>` : `<span class="unk">not met</span>`;
  const row = e => `<tr><td><b>${esc(e.name)}</b>${what(e)}${e.kind && e.kind !== "ship" ? ` <span class="unk">${esc(e.kind)}</span>` : ""}</td><td>${status(e)}</td>` +
    `<td>${e.system ? `${esc(e.system)}${e.region === "Colonia" ? ` <span class="unk">Colonia</span>` : ""}` : `<span class="unk">not known</span>`}</td>` +
    `<td class="num">${fxDist(e.system, d)}</td>` +
    `<td class="num">${e.system ? `<button type="button" class="mini" data-fxcopy="${esc(e.system)}" title="copy ${esc(e.system)} for the galaxy map">Copy</button>${plotBtn(e.system)}` : ""}</td></tr>`;
  const open = q || picks ? true : FX.engOpen;
  return `<details class="cmengs"${open ? " open" : ""}><summary><b>Engineers</b> <span class="unk">where each works: copy the system or plot a route there</span>` +
    `${picks ? ` <span class="unk">· those who engineer the picks</span>` : ""}</summary>` +
    (eng.length ? `<table class="cmengtable"><thead><tr><th>Engineer</th><th>With you</th><th>System</th><th class="num" title="light years from where you are">Distance</th><th></th></tr></thead>` +
      `<tbody>${eng.map(row).join("")}</tbody></table>` : `<div class="unk cmnote">No engineer matches.</div>`) + `</details>`;
}
// the parts (each module of the table), Load my ship, Clear and Clear filters. Pure.
function fxPartsHtml(blueprints) {
  const all = [...new Set(blueprints.map(b => b.module))].sort((a, b) => a.localeCompare(b));
  const any = FX.parts.size || FX.grades.size, filters = any || CM.q || CM.craft || FX.ship;
  return `<div class="cmparts" role="group" aria-label="parts"><span class="unk">Parts:</span>` +
    all.map(p => `<button type="button" class="mini cmpart${FX.parts.has(p) ? " on" : ""}" data-fxpart="${esc(p)}" aria-pressed="${FX.parts.has(p)}">${esc(p)}</button>`).join("") +
    (any ? ` <button type="button" class="mini" data-fxclear title="every part and grade again">Clear</button>` : "") + `</div>` +
    `<div class="cmtripctl"><button type="button" class="mini" data-fxship title="pick the parts the ship you fly has, and the grade each engineered module is at">Load my ship</button>` +
    (filters ? ` <button type="button" class="mini" data-fxclearall title="the search, only what I can craft, the parts, the grades and the ship: all off">Clear filters</button>` : "") +
    (FX.grades.size ? ` <span class="unk">· ${FX.grades.size} grade${FX.grades.size === 1 ? "" : "s"} picked (click a grade below to pick or unpick it)</span>` : "") + `</div>`;
}
// "Load my ship" (GET /api/engineers/ship): the ship's parts and its engineered modules' grades picked
async function fxLoadShip() {
  let d;
  try { d = await apiJson("api/engineers/ship"); } catch (err) { d = {error: err.message}; }
  if (!d || d.error || !d.ship) { FX.ship = {error: (d && d.error) || "no ship yet: the game writes its Loadout when you log in"}; return fxRedraw(); }
  const rows = (CM.data.engineering || {}).blueprints || [];
  const have = new Set(rows.map(b => b.module)), keys = new Map();
  for (const b of rows) for (const g of b.grades) keys.set(fxGradeKey(b, g).toLowerCase(), fxGradeKey(b, g));
  FX.parts = new Set(d.parts.filter(p => have.has(p)));
  FX.grades = new Set(d.grades.map(k => keys.get(k.toLowerCase())).filter(Boolean));
  FX.ship = d;
  fxRedraw();
}
function fxShipHtml(sh) {
  if (!sh) return "";
  if (sh.error) return `<div class="unk cmnote">Load my ship: ${esc(sh.error)}</div>`;
  const done = sh.modules.filter(m => m.blueprint);
  const mod = m => `<span class="cmshipmod"><b>${esc(m.name)}</b> ${m.blueprint ? `${esc(m.blueprint)} G${m.level || "?"}` +
    (m.experimental ? ` <span class="unk">· ${esc(m.experimental)}</span>` : "") : `<span class="unk">stock</span>`}</span>`;
  return `<div class="cmship"><b>${esc(shipLabel(sh.ship.name, sh.ship.type))}</b> <span class="unk">${sh.modules.length} module${sh.modules.length === 1 ? "" : "s"} with blueprints, ` +
    `${done.length} engineered: their parts and grades picked (experimental effects are named, not picked)</span><div class="cmstats">${sh.modules.map(mod).join("")}</div></div>`;
}
// what the picks ask for: a picked grade is one requirement, a picked part with no picked grade "that part, any grade". Pure.
function fxTripRequirements(blueprints, parts, grades) {
  const reqs = [], graded = new Set();
  for (const b of blueprints) for (const g of b.grades) {
    if (!grades.has(fxGradeKey(b, g))) continue;
    graded.add(b.module);
    reqs.push({label: `${b.module}: ${b.name} G${g.grade}`, grade: g.grade, engineers: g.engineers.map(e => e.name)});
  }
  for (const p of [...parts].sort((a, b) => a.localeCompare(b))) {
    if (graded.has(p)) continue;
    const names = new Set();
    for (const b of blueprints) if (b.module === p) for (const g of b.grades) for (const e of g.engineers) names.add(e.name);
    reqs.push({label: `${p} (any grade)`, grade: null, engineers: [...names]});
  }
  return reqs;
}
// what the picked grades are short of, for one roll each. Pure.
function fxTripShort(blueprints, grades) {
  const out = [];
  for (const b of blueprints) for (const g of b.grades) {
    if (!grades.has(fxGradeKey(b, g))) continue;
    for (const m of g.materials) if (m.have < m.need) out.push({material: m.name, have: m.have, need: m.need, for: `${b.module}: ${b.name} G${g.grade}`});
  }
  return out;
}
function fxTripSave() { try { localStorage.setItem("fxTrip", JSON.stringify(FX.trip)); } catch {} }
async function fxPlanTrip() {
  const rows = (CM.data.engineering || {}).blueprints || [];
  const requirements = fxTripRequirements(rows, FX.parts, FX.grades);
  if (!requirements.length) { FX.tripNote = "pick a part or a grade first"; return fxRedraw(); }
  FX.tripNote = "planning…"; fxRedraw();
  let d;
  try {
    d = await apiJson("api/engineers/tour", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({requirements, include_locked: !!FX.tripLocked, return_carrier: !!FX.tripCarrier})});
  } catch (err) { d = {error: err.message}; }
  if (!d || d.error) { FX.tripNote = `could not plan it: ${(d && d.error) || "no answer"}`; return fxRedraw(); }
  FX.tripNote = null;
  FX.trip = Object.assign({}, d, {done: [], short: fxTripShort(rows, FX.grades), at: Date.now()});
  fxTripSave();
  fxRedraw();
}
// a stop is done once you are in its system (marked as the page draws, kept with the trip)
function fxTripTick(t) {
  const here = data && data.position && data.position.name;
  if (!t || !here) return;
  const i = t.stops.findIndex((s, k) => s.system === here && !t.done.includes(k));
  if (i >= 0 && t.stops.slice(0, i).every((s, k) => t.done.includes(k) || s.system === here)) { t.done.push(i); fxTripSave(); }
}
const fxTripText = t => t.stops.map((s, i) => `${i + 1}. ${s.engineer} — ${s.system} (${s.leg_ly} ly): ${s.covers.join(", ")}${s.locked ? ` [${s.locked}]` : ""}`)
  .concat(t.carrier && t.back_ly != null ? [`then your carrier ${t.carrier.name || ""} — ${t.carrier.system} (${t.back_ly} ly)`] : [])
  .concat([`${t.total_ly} ly in all, from ${t.from}`]).join("\n");
function fxTripHtml() {
  const picks = FX.parts.size || FX.grades.size, carrier = data && data.carrier;
  const ctl = !picks && !FX.trip ? "" : `<div class="cmtripctl">` +
    (picks ? `<button type="button" class="mini primary" data-fxplan title="the engineers who cover every pick for the fewest light years from where you are, in order">Plan the trip</button>` +
      ` <label title="also engineers you have not unlocked, or not far enough for the grade: each stop says what it still needs"><input type="checkbox" id="fxTripLocked"${FX.tripLocked ? " checked" : ""}> include engineers I have not unlocked</label>` +
      ` <label title="${carrier ? `end the trip at ${esc(carrier.name || "your carrier")} in ${esc(carrier.system || "?")}` : "no fleet carrier on record"}"><input type="checkbox" id="fxTripCarrier"${FX.tripCarrier && carrier ? " checked" : ""}${carrier ? "" : " disabled"}> end at my fleet carrier</label>` : "") +
    (FX.tripNote ? ` <span class="unk">${esc(FX.tripNote)}</span>` : "") + `</div>`;
  const t = FX.trip;
  if (!t) return ctl;
  fxTripTick(t);
  const next = t.stops.findIndex((s, i) => !t.done.includes(i));
  const row = (s, i) => `<tr class="${t.done.includes(i) ? "cmtripdone" : i === next ? "cmtripnext" : ""}"><td class="num">${t.done.includes(i) ? "✓" : i + 1}</td>` +
    `<td><b>${esc(s.engineer)}</b>${s.locked ? ` <span class="warnc" title="you would have to see to this first">${esc(s.locked)}</span>` : ""}</td><td>${esc(s.system || "?")}</td>` +
    `<td>${esc(s.covers.join(", "))}</td><td class="num">${cmNum(s.leg_ly)} ly</td>` +
    `<td class="num">${s.system ? `<button type="button" class="mini" data-fxcopy="${esc(s.system)}">Copy</button>${plotBtn(s.system)}` : ""}</td></tr>`;
  const back = t.carrier && t.back_ly != null ? `<tr class="cmtripback"><td class="num">⌂</td><td><b>${esc(t.carrier.name || "your carrier")}</b></td><td>${esc(t.carrier.system || "?")}</td>` +
    `<td class="unk">back to your carrier</td><td class="num">${cmNum(t.back_ly)} ly</td><td class="num">${t.carrier.system ? plotBtn(t.carrier.system) : ""}</td></tr>` : "";
  const short = (t.short || []).length ? `<div class="cmtripshort"><span class="warnc">Short for one roll:</span> ${t.short.map(m => `${esc(m.material)} ${cmNum(m.have)}/${cmNum(m.need)} <span class="unk">(${esc(m.for)})</span>`).join(", ")}</div>` : "";
  const missed = (t.uncovered || []).length ? `<div class="cmtripshort"><span class="warnc">Not covered:</span> ${t.uncovered.map(u => `${esc(u.label)} <span class="unk">(${esc(u.why)})</span>`).join(", ")}</div>` : "";
  return ctl + `<div class="cmtrip"><div class="hwyttl">Trip from ${esc(t.from || "?")}: ${t.stops.length} stop${t.stops.length === 1 ? "" : "s"}, ${cmNum(t.total_ly)} ly` +
    `${t.done.length ? ` <span class="unk">· ${t.done.length} done</span>` : ""}</div>` +
    `<div class="srow">${next >= 0 && t.stops[next].system ? `<button type="button" class="mini primary" data-plotto="${esc(t.stops[next].system)}">Plot next stop: ${esc(t.stops[next].system)}</button>` : t.stops.length ? `<span class="ok">every stop done</span>` : ""}` +
    ` <button type="button" class="mini" data-fxtripcopy>Copy itinerary</button> <button type="button" class="mini" data-fxtripforget>Forget the trip</button>` +
    ` <span class="unk">light years in straight lines: a guide to the jumps</span></div>` +
    (t.stops.length ? `<table class="cmengtable cmtriptable"><thead><tr><th class="num">#</th><th>Engineer</th><th>System</th><th>Covers</th><th class="num">Leg</th><th></th></tr></thead>` +
      `<tbody>${t.stops.map(row).join("")}${back}</tbody></table>` : `<div class="unk">No engineer you can use covers these picks.</div>`) + missed + short + `</div>`;
}
// the tab: upstream's note, the parts, the ship, the trip, the Engineers list, then the blueprints by module, each
// grade a toggle; the materials as upstream draws them (a short one links to the Materials tab, ⇄ its trader). Pure but
// for the asks it starts.
function forkEngineeringHtml(d) {
  fxEngLoad();
  if (d.unreadable) return `<div class="short">Blueprint table unreadable: resources/blueprints.json is missing or damaged (a fresh copy of Outrider brings it back).</div>`;
  const q = CM.q.trim().toLowerCase(), rows = d.blueprints || [];
  const eng = d.engineers || [], unlocked = eng.filter(e => e.progress === "Unlocked").length;
  const sup = fxSupports(rows, FX.parts, FX.grades);
  const gradeRow = (g, b) => {
    const key = fxGradeKey(b, g), on = FX.grades.has(key);
    const mats = g.materials.map(x => x.have >= x.need ? `<span class="cmmat ok" title="you hold ${cmNum(x.have)}">${esc(x.name)} ${cmNum(x.have)}/${cmNum(x.need)}</span>`
      : `<span class="cmshort"><span class="cmmat short cmlink" data-cmmat="${esc(x.name)}" role="link" tabindex="0" title="you hold ${cmNum(x.have)}: show it in the Materials tab">${esc(x.name)} ${cmNum(x.have)}/${cmNum(x.need)}</span>${typeof traderBtn === "function" ? traderBtn(x.category, true) : ""}</span>`).join("");
    const who = g.engineers.map(e => `<span class="${e.ready ? "ok" : "unk"}" title="${esc(e.progress ? `${e.progress}${e.rank != null ? `, crafts up to grade ${e.rank}` : ""}` : "not met yet")}">${esc(e.name)}</span>`).join(", ");
    return `<tr${on ? ` class="cmgradeon"` : ""}><td><button type="button" class="mini cmgrade${on ? " on" : ""}" data-fxgrade="${esc(key)}" aria-pressed="${on}" ` +
      `title="${on ? "unpick this grade" : "show only the engineers who do this grade"}"><b>G${cmNum(g.grade)}</b></button></td><td><div class="cmstats">${mats}</div></td>` +
      `<td class="num ${g.rolls ? "ok" : "unk"}" title="how many times you could craft this grade now">${g.rolls ? `×${cmNum(g.rolls)}` : "–"}</td><td>${who}</td></tr>`;
  };
  const groups = new Map();
  for (const b of rows) {
    if (q && !`${b.module} ${b.name} ${b.grades.map(g => g.materials.map(x => x.name).concat(g.engineers.map(e => e.name)).join(" ")).join(" ")}`.toLowerCase().includes(q)) continue;
    if (FX.parts.size && !FX.parts.has(b.module)) continue;
    const grades = CM.craft ? b.grades.filter(g => g.rolls > 0) : b.grades;
    if (!grades.length) continue;
    if (!groups.has(b.module)) groups.set(b.module, []);
    groups.get(b.module).push(`<h4 class="cmbp">${esc(b.name)}</h4>` + cmTable([["Grade"], ["Materials <span class=\"unk\">(held / one roll)</span>"], ["Rolls", 1], ["Engineers"]], grades.map(g => gradeRow(g, b))));
  }
  // collapsed unless you opened one (a search still opens what it found, as upstream's tab does); a pick shows in the title
  const open = k => q || CM.craft || CM.open[k];
  const picked = mod => rows.filter(b => b.module === mod).flatMap(b => b.grades.filter(g => FX.grades.has(fxGradeKey(b, g))).map(g => `${b.name} G${g.grade}`));
  return `<div class="unk cmnote">${eng.length ? `${unlocked} of ${eng.length} engineers unlocked` : "no engineer on record yet"} · ship modules only: no experimental effects, suits or weapons</div>` +
    fxPartsHtml(rows) + fxShipHtml(FX.ship) + fxTripHtml() + fxEngineersHtml(sup, q) +
    ([...groups].map(([mod, list]) => `<details class="cmmod" data-cmmod="${esc(mod)}"${open(mod) ? " open" : ""}><summary><b>${esc(mod)}</b> <span class="unk">${list.length} blueprint${list.length === 1 ? "" : "s"}</span>` +
      `${picked(mod).length ? ` <span class="cmsupports">· ${esc(picked(mod).join(", "))}</span>` : ""}</summary>${list.join("")}</details>`).join("")
      || `<div class="unk">Nothing matches.</div>`);
}
document.addEventListener("click", e => {
  const t = e.target.closest && e.target.closest("[data-fxpart], [data-fxgrade], [data-fxclear], [data-fxclearall], [data-fxship], [data-fxplan], [data-fxtripcopy], [data-fxtripforget], [data-fxcopy]");
  if (!t) return;
  const ds = t.dataset;
  if (ds.fxcopy) return copyText(ds.fxcopy);
  if (ds.fxpart) { if (FX.parts.has(ds.fxpart)) FX.parts.delete(ds.fxpart); else FX.parts.add(ds.fxpart); }
  else if (ds.fxgrade) { if (FX.grades.has(ds.fxgrade)) FX.grades.delete(ds.fxgrade); else FX.grades.add(ds.fxgrade); }
  else if ("fxclear" in ds) { FX.parts.clear(); FX.grades.clear(); FX.ship = null; }
  else if ("fxclearall" in ds) {
    FX.parts.clear(); FX.grades.clear(); FX.ship = null; CM.q = ""; CM.craft = false;
    const f = document.getElementById("cmFilter"), c = document.getElementById("cmCraft");
    if (f) f.value = ""; if (c) c.checked = false;
  }
  else if ("fxship" in ds) return fxLoadShip();
  else if ("fxplan" in ds) return fxPlanTrip();
  else if ("fxtripcopy" in ds) return FX.trip && copyText(fxTripText(FX.trip), "the itinerary");
  else if ("fxtripforget" in ds) { FX.trip = null; fxTripSave(); }
  fxRedraw();
});
document.addEventListener("change", e => {
  if (e.target.id === "fxTripLocked") FX.tripLocked = e.target.checked;
  if (e.target.id === "fxTripCarrier") FX.tripCarrier = e.target.checked;
});
document.addEventListener("toggle", e => { if (e.target.classList && e.target.classList.contains("cmengs")) FX.engOpen = e.target.open; }, true);

// ---- Route lists: who first discovered a system (this fork; EDSM's record, asked by the server in the background).
// Shown after the Known mark of a system somebody has been to. Pure ----
function hwyDiscovererHtml(name) {
  return name ? ` <span class="hwydisc" title="first discovered by CMDR ${esc(name)} (EDSM's record)">${esc(name)}</span>` : "";
}


// ---- Locate (this fork; GET /api/locate, outrider/locate.py): EDCoPilot's Location search, its tiles here. Each asks
// Spansh for the nearest places with what it names; Commodities (and where a mined mineral sells) hands over to the
// Materials view's Sell / Buy lookup (startLook). forkLocateShow is page.js's one-line hook in render() ----
const LC_TILES = [["factors", "Interstellar Factors", "pay off bounties and fines away from where you got them"],
  ["raw", "Raw material trader", "trade raw materials"], ["encoded", "Encoded material trader", "trade encoded data"],
  ["manufactured", "Manufactured material trader", "trade manufactured materials"],
  ["mining", "Mining", "ring hotspots of a mineral, nearest first, and where it sells"],
  ["commodities", "Commodities", "where to buy or sell a commodity (the Materials view's lookup)"],
  ["outfitting", "Ship outfitting", "stations with outfitting"], ["shipyard", "Shipyards", "stations with a shipyard"],
  ["repair", "Best local repair", "the nearest stations that repair"], ["black", "Black markets", "sell stolen goods"],
  ["guardian", "Guardian technology broker", "Guardian modules, weapons and fighters"], ["human", "Human technology broker", "human tech: AX weapons and the like"]];
const LC_MINERALS = ["Alexandrite", "Benitoite", "Bromellite", "Grandidierite", "Low Temperature Diamonds", "Monazite", "Musgravite",
  "Painite", "Platinum", "Rhodplumsite", "Serendibite", "Tritium", "Void Opals", "Osmium", "Gold", "Silver", "Palladium", "Samarium", "Praseodymium"];
const LC = {what: null, answer: null, busy: false, large: false, mineral: "Painite", commodity: ""};
try { const s = JSON.parse(localStorage.getItem("lcPrefs") || "null");
      if (s) { LC.large = !!s.large; if (LC_MINERALS.includes(s.mineral)) LC.mineral = s.mineral; } } catch {}
const lcSave = () => { try { localStorage.setItem("lcPrefs", JSON.stringify({large: LC.large, mineral: LC.mineral})); } catch {} };
function forkLocateShow(on) {
  const v = document.getElementById("locateView");
  if (!v) return;
  v.hidden = !on;
  if (on) lcRender();
}
// a report's age in words (Spansh's updated_at, as seconds): "40 min", "3 h", "12 d"
const lcAge = s => s == null ? "?" : s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : s < 172800 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d`;
const lcLy = v => v == null ? "?" : `${Number(v).toLocaleString("en-US", {maximumFractionDigits: 1, minimumFractionDigits: v < 100 ? 1 : 0})} ly`;
const lcLs = v => v == null ? "" : `${Number(v).toLocaleString("en-US")} ls`;
const lcActions = r => `<button type="button" class="mini" data-lccopy="${esc(r.system)}" title="copy the system's name">Copy</button>` +
  sysAimBtn(r.system, r.id64) + plotBtn(r.system);
function lcRowsHtml(a) {
  if (!a.rows.length) return `<div class="unk">Spansh knows none within reach (1,000 ly).</div>`;
  if (a.mineral) return `<table class="lctable"><thead><tr><th>Ring</th><th>System</th><th class="num">Distance</th><th class="num">From star</th><th>Hotspots</th><th></th></tr></thead><tbody>` +
    a.rows.map(r => `<tr><td><b>${esc(r.ring || r.body)}</b> <span class="unk">${esc(r.ring_type || "")}</span></td><td>${esc(r.system)}</td>` +
      `<td class="num">${lcLy(r.distance)}</td><td class="num">${lcLs(r.ls)}</td>` +
      `<td>${esc(a.mineral)} ×${r.count}${r.others.length ? ` <span class="unk">· ${esc(r.others.map(([n, c]) => `${n} ×${c}`).join(", "))}</span>` : ""}</td>` +
      `<td class="lcact">${lcActions(r)}</td></tr>`).join("") + `</tbody></table>`;
  return `<table class="lctable"><thead><tr><th>Station</th><th>System</th><th class="num">Distance</th><th class="num">From star</th><th>Pad</th><th class="num">Reported</th><th></th></tr></thead><tbody>` +
    a.rows.map(r => `<tr><td><b>${esc(r.name)}</b> <span class="unk">${esc(r.type || "")}</span></td><td>${esc(r.system)}</td>` +
      `<td class="num">${lcLy(r.distance)}</td><td class="num">${lcLs(r.ls)}</td><td>${esc(r.pad)}</td>` +
      `<td class="num" title="how long ago a player's game last reported the station to Spansh">${lcAge(r.age)} ago</td>` +
      `<td class="lcact">${lcActions(r)}</td></tr>`).join("") + `</tbody></table>`;
}
function lcRender() {
  const el = document.getElementById("locateBody");
  if (!el) return;
  const tiles = LC_TILES.map(([k, t, h]) => `<button type="button" class="lctile${LC.what === k ? " on" : ""}" data-lcwhat="${k}" title="${esc(h)}">${esc(t)}</button>`).join("");
  let ctl = "";
  if (LC.what === "mining") ctl = `<label>Mineral <select id="lcMineral">${LC_MINERALS.map(m => `<option${m === LC.mineral ? " selected" : ""}>${esc(m)}</option>`).join("")}</select></label>` +
    ` <button type="button" class="mini" data-lcgo>Find hotspots</button> <button type="button" class="mini" data-lcsell title="where ${esc(LC.mineral)} sells best near you (the Materials view's lookup)">Where it sells</button>`;
  else if (LC.what === "commodities") ctl = `<label>Commodity <input type="search" id="lcCommodity" value="${esc(LC.commodity)}" placeholder="e.g. Tritium" autocapitalize="off" spellcheck="false"></label>` +
    ` <button type="button" class="mini" data-lclook="buy">Where to buy</button> <button type="button" class="mini" data-lclook="sell">Where to sell</button>` +
    ` <span class="unk">opens the Materials view's lookup</span>`;
  const a = LC.answer;
  const res = LC.busy ? `<div class="unk">Asking Spansh…</div>` : !a || LC.what === "commodities" ? "" : a.error ? `<div class="short">${esc(a.error)}</div>` :
    `<div class="hwyttl">${esc(a.title)} <span class="unk">nearest ${esc(a.from || "you")} first · ${a.rows.length} found</span></div>` + lcRowsHtml(a);
  el.innerHTML = `<div class="srow"><b>Location search</b> <label class="unk" title="only stations with a large landing pad"><input type="checkbox" id="lcLarge"${LC.large ? " checked" : ""}> large pad only</label></div>` +
    `<div class="lctiles">${tiles}</div>${ctl ? `<div class="lcctl">${ctl}</div>` : ""}<div id="lcResults">${res}</div>`;
}
async function lcFind() {
  const what = LC.what;
  if (!what || what === "commodities") return;
  const q = new URLSearchParams({what, pad: LC.large ? "L" : "any"});
  if (what === "mining") q.set("mineral", LC.mineral);
  LC.busy = true; LC.answer = null; lcRender();
  const g = newRequest("locate");
  let r;
  try { r = await apiJson(`api/locate?${q}`); } catch (err) { r = {error: err.message}; }
  if (!isNewest("locate", g)) return;
  LC.busy = false; LC.answer = r; lcRender();
}
function lcLook(commodity, mode) {
  if (!commodity) { const i = document.getElementById("lcCommodity"); return i && i.focus(); }
  const v = document.querySelector('[data-view="mat"]');
  if (v && view !== "mat") v.click();
  startLook({commodity, label: commodity, mode, tons: 1, from: "here", key: null});
}
document.addEventListener("click", e => {
  const t = e.target.closest && e.target.closest("[data-lcwhat], [data-lcgo], [data-lcsell], [data-lclook], [data-lccopy]");
  if (!t) return;
  const ds = t.dataset;
  if (ds.lccopy) return copyText(ds.lccopy);
  if (ds.lcwhat) { LC.what = ds.lcwhat; LC.answer = null; lcRender(); return lcFind(); }
  if ("lcgo" in ds) return lcFind();
  if ("lcsell" in ds) return lcLook(LC.mineral, "sell");
  if (ds.lclook) { const i = document.getElementById("lcCommodity"); LC.commodity = i ? i.value.trim() : LC.commodity; return lcLook(LC.commodity, ds.lclook); }
});
document.addEventListener("change", e => {
  if (e.target.id === "lcLarge") { LC.large = e.target.checked; lcSave(); if (LC.what && LC.what !== "mining" && LC.what !== "commodities") lcFind(); }
  if (e.target.id === "lcMineral") { LC.mineral = e.target.value; lcSave(); if (LC.what === "mining") lcFind(); }
});
document.addEventListener("keydown", e => {
  if (e.key === "Enter" && e.target.id === "lcCommodity") { e.preventDefault(); LC.commodity = e.target.value.trim(); lcLook(LC.commodity, "buy"); }
});

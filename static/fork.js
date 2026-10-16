// This fork's own page code, apart from upstream's page.js so the two merge without conflicts. Loaded before page.js:
// everything here is a definition, and uses page.js's helpers (esc, apiJson, credits, shipLabel, view) only
// when called. page.js calls loadCmdr() from render() when the Commander view is shown.

// ---- The Commander view (GET /api/commander/<tab>, outrider/commander.py): who you are in the game (CMDR), what you own (Inventory),
// what engineering takes against your materials (Engineering), the missions you hold (Missions) and how your combat
// and mining sessions went (Sessions). Each tab is read from the journals when opened, and again when stale ----
// CM: tab (the one shown), data / error / at / loading per tab, q and craft (Engineering's filter), open (its modules)
const CM = {trip: null, tripNote: null, tripLocked: false, tripCarrier: false, ship: null, parts: new Set(), grades: new Set(), dist: null, distKey: null, tab: "profile", data: {}, error: {}, at: {}, loading: {}, q: "", craft: false, open: {}, wired: false};
const CM_TABS = [["profile", "CMDR", "your ranks and the way to the next, credits and assets, your fleet, your career"],
                 ["inventory", "Inventory", "your ships, stored modules, ship locker and suit loadouts"],
                 ["engineering", "Engineering", "every ship-module blueprint against the materials you hold"],
                 ["missions", "Missions", "the missions you hold, the soonest to expire first"],
                 ["sessions", "Sessions", "your combat and mining sessions of the last weeks"]];
const CM_STALE_MS = 30 * 1000;   // a tab opened again after this long asks again (the server reads only what changed)

async function loadCmdr(force = false) {
  cmdrWire();
  const tab = CM.tab;
  if (CM.loading[tab] || (!force && CM.at[tab] && Date.now() - CM.at[tab] < CM_STALE_MS)) return renderCmdr();
  CM.loading[tab] = true;
  renderCmdr();
  let d;
  try { d = await apiJson("api/commander/" + tab); } catch (err) { d = {error: err.message}; }
  CM.loading[tab] = false; CM.at[tab] = Date.now();
  if (!d || d.error) CM.error[tab] = (d && d.error) || "no answer"; else { CM.error[tab] = null; CM.data[tab] = d; }
  renderCmdr();
}
// the view's own clicks and typing, wired once (the section is in the page before any script runs)
function cmdrWire() {
  const el = document.getElementById("cmdrView");
  if (CM.wired || !el) return;
  CM.wired = true;
  el.addEventListener("click", e => {
    const t = e.target.closest("[data-cmtab]");
    if (t) { CM.tab = t.dataset.cmtab; try { localStorage.setItem("cmdrTab", CM.tab); } catch {} loadCmdr(); return; }
    if (e.target.closest("#cmRefresh")) loadCmdr(true);
    if (e.target.closest("#cmClearAll")) { CM.q = ""; CM.craft = false; CM.parts.clear(); CM.grades.clear(); CM.ship = null; cmdrDrawBody(); return; }
    if (e.target.closest("#cmLoadShip")) { cmdrLoadShip(); return; }
    if (e.target.closest("#cmPlanTrip")) { cmdrPlanTrip(); return; }
    if (e.target.closest("#cmTripCopy") && CM.trip) { copyText(cmdrTripText(CM.trip), "the itinerary"); return; }
    if (e.target.closest("#cmTripForget")) { CM.trip = null; cmdrTripSave(); cmdrDrawBody(); return; }
    const part = e.target.closest("[data-cmpart]"), clear = e.target.closest("[data-cmpart-clear]");
    if (part) { const p = part.dataset.cmpart; if (CM.parts.has(p)) CM.parts.delete(p); else CM.parts.add(p); cmdrDrawBody(); return; }
    if (clear) { CM.parts.clear(); CM.grades.clear(); CM.ship = null; cmdrDrawBody(); return; }
    const grade = e.target.closest("[data-cmgrade]");
    if (grade) { const k = grade.dataset.cmgrade; if (CM.grades.has(k)) CM.grades.delete(k); else CM.grades.add(k); cmdrDrawBody(); return; }
    const cp = e.target.closest("[data-cmcopy]");
    if (cp) copyText(cp.dataset.cmcopy);
  });
  el.addEventListener("input", e => { if (e.target.id === "cmFilter") { CM.q = e.target.value; cmdrDrawBody(); } });
  el.addEventListener("change", e => {
    if (e.target.id === "cmTripLocked") { CM.tripLocked = e.target.checked; return; }
    if (e.target.id === "cmTripCarrier") { CM.tripCarrier = e.target.checked; return; } if (e.target.id === "cmCraft") { CM.craft = e.target.checked; cmdrDrawBody(); } });
  el.addEventListener("toggle", e => { const k = e.target.dataset && e.target.dataset.cmmod; if (k) CM.open[k] = e.target.open; }, true);
  try { const t = localStorage.getItem("cmdrTab"); if (CM_TABS.some(x => x[0] === t)) CM.tab = t; } catch {}
  CM.trip = cmdrTripLoad();
}
// small pure helpers
const cmNum = v => v == null ? "" : Number(v).toLocaleString();
const cmCr = v => v == null || v === 0 ? "" : `${credits(v)} cr`;
const cmWhen = ts => ts ? esc(ts.slice(0, 16).replace("T", " ")) : "";
function cmSpan(s) {   // seconds as "2 d 3 h", "3 h 20 min", "12 min"
  if (s == null) return "";
  const m = Math.max(0, Math.round(s / 60)), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m % 60} min` : `${m} min`;
}
const cmAsOf = (ts, how) => ts ? `<span class="unk" title="${esc(how)}">as of ${cmWhen(ts)}</span>` : "";
const cmTable = (head, rows) => `<table class="cmtable"><thead><tr>${head.map(h => `<th${h[1] ? ` class="num"` : ""}>${h[0]}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
const cmCls = m => esc((m.size != null && m.size > 0 ? m.size : "") + (m.rating || ""));

// CMDR: who you are in the game: ranks with the way to the next, credits and assets, the fleet, the career. Pure.
function cmdrProfileHtml(d) {
  const p = d.profile;
  if (!p) return `<div class="hwyttl">No commander yet</div><div class="unk">Shown once the journals hold a login.</div>`;
  const tile = (k, v, title = "") => v == null || v === "" ? "" : `<span class="cmfig"${title ? ` title="${esc(title)}"` : ""}><span class="unk">${k}</span><b>${v}</b></span>`;
  const a = p.assets || {};
  const rank = r => `<tr><td class="unk">${esc(r.title)}</td><td><b>${esc(r.name)}</b></td>` +
    `<td class="cmbarcell">${r.progress == null ? "" : `<span class="cmbar" title="${r.progress}% of the way to ${esc(r.next || "")}"><span style="width:${Math.round(r.progress)}%"></span></span> <span class="unk">${Math.round(r.progress)}%</span>`}</td>` +
    `<td>${r.next ? `<span class="unk">next:</span> ${esc(r.next)}` : `<span class="ok">the top</span>`}` +
    `${r.to_next != null ? ` <span title="an estimate: about this much more ${esc(r.earned_by)} (what that rank's step takes, by the community's figures, times the share still to go)">in <b>${credits(r.to_next)} cr</b></span>` : ""}</td></tr>`;
  const rep = Object.entries(p.reputation || {}).map(([k, v]) => `${esc(k)} <b class="${v >= 35 ? "ok" : v <= -35 ? "noscoop" : ""}">${Math.round(v)}%</b>`).join(" · ");
  const ship = x => { const label = shipLabel(x.name, x.type), type = x.type_name || shipLabel(null, x.type);
    return `<tr><td><b>${esc(label)}</b>${type !== label ? ` <span class="unk">${esc(type)}</span>` : ""}</td>` +
      `<td>${x.current ? `<span class="ok">you fly it</span>` : x.in_transit ? `<span class="warnc">in transit</span>` : esc([x.system, x.station].filter(Boolean).join(" · ") || "?")}</td>` +
      `<td class="num">${cmCr(x.value)}</td></tr>`; };
  const fig = c => c.kind === "cr" ? `${credits(c.value)} cr` : c.kind === "ly" ? `${cmNum(Math.round(c.value))} ly`
    : c.kind === "time" ? `${cmNum(Math.round(c.value / 3600))} h` : cmNum(c.value);
  return `<div class="hwyttl">CMDR ${esc(p.commander || "?")}${p.squadron ? ` <span class="unk">· ${esc(p.squadron)}</span>` : ""}` +
    `${p.power ? ` <span class="unk">· pledged to ${esc(p.power.name)}${p.power.rank != null ? `, rank ${p.power.rank}` : ""}${p.power.merits != null ? `, ${cmNum(p.power.merits)} merits` : ""}</span>` : ""}` +
    ` ${cmAsOf(p.ts, "the login these figures are from: the game writes credits, ranks and statistics then")}</div>` +
    `<div class="cmfigs">${tile("Credits", cmCr(p.credits) || "0 cr", "at that login")}${p.loan ? tile("Loan", cmCr(p.loan)) : ""}` +
    `${tile("Net worth", cmCr(a.wealth), "the game's own total (Statistics: current wealth) at that login")}` +
    `${tile("Fleet", a.fleet ? `${cmCr(a.fleet)} · ${a.ships} ship${a.ships === 1 ? "" : "s"}` : a.ships ? `${a.ships} ship${a.ships === 1 ? "" : "s"}` : "", "hull and modules of every ship listed below")}` +
    `${tile("Stored modules", cmCr(a.modules))}${tile("Carrier balance", cmCr(a.carrier))}</div>` +
    `<h3 class="subhead">Ranks</h3>` + (p.ranks.length ? `<table class="cmtable cmranks"><tbody>${p.ranks.map(rank).join("")}</tbody></table>` : `<div class="unk">No ranks on record.</div>`) +
    (rep ? `<div class="cmrep"><span class="unk">Reputation:</span> ${rep}</div>` : "") +
    `<h3 class="subhead">Fleet <span class="cmcount">${p.fleet.length}</span></h3>` +
    (p.fleet.length ? cmTable([["Ship"], ["Where"], ["Value", 1]], p.fleet.map(ship)) : `<div class="unk">No ship on record yet.</div>`) +
    (p.carrier ? `<div class="cmrep"><span class="unk">Fleet carrier:</span> <b>${esc(p.carrier.name || "")}</b> ${esc(p.carrier.callsign)}` +
      `${p.carrier.balance != null ? ` · ${cmCr(p.carrier.balance) || "0 cr"}` : ""}${p.carrier.fuel != null ? ` · ${cmNum(p.carrier.fuel)} t tritium` : ""}</div>` : "") +
    (p.career.length ? `<h3 class="subhead">Career</h3><div class="cmfigs">${p.career.map(c => tile(esc(c.label), fig(c))).join("")}</div>` : "");
}

// Inventory. Pure.
function cmdrInventoryHtml(d) {
  const s = d.ships || {ships: []}, m = d.modules || {modules: []}, lk = d.locker || {kinds: []}, suits = d.suits || [];
  const shipRow = x => {
    const label = shipLabel(x.name, x.type), type = x.type_name || shipLabel(null, x.type);
    const where = x.current ? `<span class="ok">you fly it</span>` : x.in_transit ? `<span class="warnc">in transit</span>`
      : esc([x.system, x.station].filter(Boolean).join(" · ") || "?");
    const move = x.transfer_cost ? `${cmCr(x.transfer_cost)}${x.transfer_s ? ` · ${cmSpan(x.transfer_s)}` : ""}` : "";
    return `<tr><td><b>${esc(label)}</b>${type !== label ? ` <span class="unk">${esc(type)}</span>` : ""}${x.ident ? ` <span class="unk">${esc(x.ident)}</span>` : ""}` +
      `${x.hot ? ` <span class="warnc">hot</span>` : ""}</td><td>${where}</td><td class="num">${cmCr(x.value)}</td><td class="num">${move}</td></tr>`;
  };
  const modRow = x => `<tr><td><span class="cmcls">${cmCls(x)}</span> <b>${esc(x.name)}</b>${x.mount ? ` <span class="unk">${esc(x.mount)}</span>` : ""}` +
    `${x.hot ? ` <span class="warnc">hot</span>` : ""}</td>` +
    `<td>${x.blueprint ? `<b>${esc(x.blueprint)}</b>${x.level ? ` G${x.level}` : ""}` : `<span class="unk">stock</span>`}</td>` +
    `<td>${x.in_transit ? `<span class="warnc">in transit</span>` : esc(x.system || "?")}</td><td class="num">${cmCr(x.value)}</td>` +
    `<td class="num">${x.transfer_cost ? `${cmCr(x.transfer_cost)}${x.transfer_s ? ` · ${cmSpan(x.transfer_s)}` : ""}` : ""}</td></tr>`;
  const held = lk.kinds.filter(k => k.items.length);
  const suitRow = x => `<tr><td><b>${esc(x.loadout || "?")}</b></td><td>${esc(x.suit)}${x.class ? ` <span class="unk">G${x.class}</span>` : ""}` +
    `${x.mods.length ? `<div class="unk">${esc(x.mods.join(", "))}</div>` : ""}</td>` +
    `<td>${x.weapons.map(w => `<div>${esc(w.name)}${w.class ? ` <span class="unk">G${w.class}</span>` : ""}${w.mods.length ? ` <span class="unk">${esc(w.mods.join(", "))}</span>` : ""}</div>`).join("")}</td></tr>`;
  return `<h3 class="subhead">Ships <span class="cmcount">${s.ships.length}</span> ${cmAsOf(s.ts, "the stored ships as the last shipyard you opened listed them")}</h3>` +
    (s.ships.length ? cmTable([["Ship"], ["Where"], ["Value", 1], ["To bring it here", 1]], s.ships.map(shipRow)) : "") +
    (s.ts ? "" : `<div class="unk">Your stored ships are listed once you open a shipyard: the game writes the list then.</div>`) +
    `<h3 class="subhead">Stored modules <span class="cmcount">${m.modules.length}</span> ${cmAsOf(m.ts, "as the last outfitting you opened listed them")}</h3>` +
    (m.modules.length ? cmTable([["Module"], ["Engineering"], ["Where"], ["Value", 1], ["To bring it here", 1]], m.modules.map(modRow))
      : `<div class="unk">${m.ts ? "None stored." : "Listed once you open outfitting: the game writes the list then."}</div>`) +
    `<h3 class="subhead">Ship locker ${cmAsOf(lk.ts, "the locker as the game last wrote it whole (at login, and when it changes)")}</h3>` +
    (held.length ? `<div class="cmlocker">${held.map(k => `<div><b>${esc(k.name)}</b>${k.items.map(i =>
      `<div class="cmitem"><span>${esc(i.name)}${i.mission ? ` <span class="unk" title="a mission's own">mission</span>` : ""}</span><b>${cmNum(i.count)}</b></div>`).join("")}</div>`).join("")}</div>`
      : `<div class="unk">${lk.ts ? "Empty." : "Nothing on record (Odyssey writes it at login)."}</div>`) +
    `<h3 class="subhead">Suit loadouts <span class="cmcount">${suits.length}</span></h3>` +
    (suits.length ? cmTable([["Loadout"], ["Suit"], ["Weapons"]], suits.map(suitRow))
      : `<div class="unk">The journal names a loadout only when you put it on: those worn in the last year are listed.</div>`);
}

// how far each engineer's system is from you (GET /api/commander/engineer_distances): asked when the Engineering tab
// is drawn, again after a jump
async function cmdrLoadDistances() {
  const key = typeof posId === "function" ? posId() : null;
  if (CM.distKey === key) return;
  CM.distKey = key;
  let d;
  try { d = await apiJson("api/commander/engineer_distances"); } catch (err) { d = {error: err.message}; }
  CM.dist = d && typeof d === "object" ? d : {error: "no answer"};
  if (view === "cmdr" && CM.tab === "engineering") cmdrDrawBody();
}
// one engineer's distance cell: the light years, else why there are none. Pure.
function cmdrDistHtml(system, dist) {
  if (!system) return "";
  if (!dist) return `<span class="unk">…</span>`;
  const v = (dist.distances || {})[system];
  if (v != null) return `${Number(v).toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 1})} ly`;
  return `<span class="unk" title="${esc(!dist.from ? "no position yet: after your first jump" : dist.error || "Spansh does not know this system")}">?</span>`;
}
// the engineers: where each works, with Copy and Plot route (and how far you are with them). Pure.
function cmdrEngineersHtml(eng, q = "", supports = null) {
  if (!eng.length) return q ? `<div class="unk cmnote">No engineer matches.</div>` : "";
  const forParts = CM.parts.size || CM.grades.size ? ` <span class="unk">· those who engineer ${esc([...CM.parts].join(" or ") || "it")}` +
    `${CM.grades.size ? ` at a picked grade` : ""}</span>` : "";
  const status = e => e.progress === "Unlocked" ? `<span class="ok">unlocked${e.rank != null ? `, grade ${e.rank}` : ""}</span>`
    : e.progress ? `<span class="warnc">${esc(e.progress.toLowerCase())}</span>` : `<span class="unk">not met</span>`;
  // with parts picked: the picked parts this engineer engineers, after the name
  const parts = e => { const p = supports && supports.get(cmPlain(e.name)); return p && p.size ? ` <span class="cmsupports">· ${esc([...p].sort((a, b) => a.localeCompare(b)).join(", "))}</span>` : ""; };
  const row = e => `<tr><td><b>${esc(e.name)}</b>${parts(e)}${e.kind && e.kind !== "ship" ? ` <span class="unk">${esc(e.kind)}</span>` : ""}</td><td>${status(e)}</td>` +
    `<td>${e.system ? `${esc(e.system)}${e.region === "Colonia" ? ` <span class="unk">Colonia</span>` : ""}` : `<span class="unk">not known</span>`}</td>` +
    `<td class="num">${cmdrDistHtml(e.system, CM.dist)}</td>` +
    `<td class="num">${e.system ? `<button type="button" class="mini" data-cmcopy="${esc(e.system)}" title="copy ${esc(e.system)} for the galaxy map">Copy</button>${forkPlotBtn(e.system)}` : ""}</td></tr>`;
  const open = q ? true : CM.open.__engineers !== false;   // a search shows what it found
  return `<details class="cmengs" data-cmmod="__engineers"${open ? " open" : ""}><summary><b>Engineers</b> <span class="unk">where each works: copy the system or plot a route there</span>${forParts}</summary>` +
    `<table class="cmengtable"><thead><tr><th>Engineer</th><th>With you</th><th>System</th><th class="num" title="light years from where you are">Distance</th><th></th></tr></thead><tbody>${eng.map(row).join("")}</tbody></table></details>`;
}

// The parts the Engineering tab can narrow to: a blueprint's module, or for one shared by several kinds of module each
// kind it is for (missile racks, multi-cannons...). Pure.
const cmdrPartsOf = b => (b.for || []).length ? b.for : [b.module];
// a grade's engineers for the picked parts (all of them with none picked). Pure.
function cmdrGradeEngineers(g, b, parts) {
  if (!parts.size || !(b.for || []).length) return g.engineers;
  const names = new Set(Object.entries(g.by_kind || {}).filter(([k]) => parts.has(k)).flatMap(([, list]) => list.map(e => e.name)));
  return g.engineers.filter(e => names.has(e.name));
}
// the engineers who engineer any of the picked parts at any grade: {name (lower case, letters only): Set of the picked
// parts they engineer}. Pure.
const cmPlain = n => String(n || "").toLowerCase().replace(/[^a-z0-9]/g, "");
function cmdrPartEngineers(blueprints, parts) {
  const out = new Map();
  for (const b of blueprints) {
    for (const p of cmdrPartsOf(b)) {
      if (!parts.has(p)) continue;
      for (const g of b.grades) for (const e of cmdrGradeEngineers(g, b, new Set([p]))) {
        const k = cmPlain(e.name);
        if (!out.has(k)) out.set(k, new Set());
        out.get(k).add(p);
      }
    }
  }
  return out;
}
// the engineers who do any of the picked grades (`${blueprint id}|${grade}`, CM.grades), for the picked parts: {name (as
// cmPlain): Set of what they do of them, "Overcharged G5"}. Pure.
function cmdrGradeEngineersPicked(blueprints, picked, parts) {
  const out = new Map();
  for (const b of blueprints) for (const g of b.grades) {
    if (!picked.has(`${b.id}|${g.grade}`)) continue;
    for (const e of cmdrGradeEngineers(g, b, parts)) {
      const k = cmPlain(e.name);
      if (!out.has(k)) out.set(k, new Set());
      out.get(k).add(`${b.name} G${g.grade}`);
    }
  }
  return out;
}
// "Load my ship" (GET /api/commander/ship_parts): the parts the ship you fly has, and the grade each engineered module
// is at, picked; the modules listed under the buttons with their blueprints, levels and experimental effects
async function cmdrLoadShip() {
  let d;
  try { d = await apiJson("api/commander/ship_parts"); } catch (err) { d = {error: err.message}; }
  if (!d || d.error || !d.ship) { CM.ship = {error: (d && d.error) || "no ship yet: the game writes its Loadout when you log in"}; return cmdrDrawBody(); }
  const have = new Set(((CM.data.engineering || {}).blueprints || []).flatMap(cmdrPartsOf));
  const ids = new Map(((CM.data.engineering || {}).blueprints || []).map(b => [b.id.toLowerCase(), b]));
  CM.parts = new Set(d.parts.filter(p => have.has(p)));
  CM.grades = new Set(d.grades.map(k => { const [id, g] = k.split("|"), b = ids.get(id.toLowerCase());
    return b && b.grades.some(x => String(x.grade) === g) ? `${b.id}|${g}` : null; }).filter(Boolean));
  CM.ship = d;
  cmdrDrawBody();
}
// the loaded ship's modules: each with its blueprint, grade and experimental effect, stock ones by name. Pure.
function cmdrShipHtml(sh) {
  if (!sh) return "";
  if (sh.error) return `<div class="unk cmnote">Load my ship: ${esc(sh.error)}</div>`;
  const label = shipLabel(sh.ship.name, sh.ship.type), done = sh.modules.filter(m => m.blueprint);
  const mod = m => `<span class="cmshipmod"><b>${esc(m.name)}</b> ${m.blueprint ? `${esc(m.blueprint)} G${m.level || "?"}` +
    (m.experimental ? ` <span class="unk">· ${esc(m.experimental)}</span>` : "") : `<span class="unk">stock</span>`}</span>`;
  return `<div class="cmship"><b>${esc(label)}</b> <span class="unk">${sh.modules.length} module${sh.modules.length === 1 ? "" : "s"} with blueprints, ` +
    `${done.length} engineered: their parts and grades picked (experimental effects are named, not picked)</span><div class="cmstats">${sh.modules.map(mod).join("")}</div></div>`;
}

// ---- Engineering → Plan the trip (POST /api/commander/engineer_tour, outrider/engtour.py): the engineers who cover the
// picks for the fewest light years from where you are, in the order to visit them, ending at your carrier if asked ----
// what the picks ask for: a picked grade is one requirement (for a shared blueprint, one per picked part it is for),
// a picked part with no picked grade of its own is "that part, any grade". Pure.
function cmdrTripRequirements(blueprints, parts, grades) {
  const reqs = [], graded = new Set();
  for (const b of blueprints) for (const g of b.grades) {
    if (!grades.has(`${b.id}|${g.grade}`)) continue;
    const shared = (b.for || []).length, kinds = shared ? b.for.filter(p => parts.has(p)) : [];
    cmdrPartsOf(b).forEach(p => graded.add(p));
    if (shared && kinds.length) {
      for (const k of kinds) reqs.push({label: `${b.name} G${g.grade} (${k})`, grade: g.grade, engineers: ((g.by_kind || {})[k] || []).map(e => e.name)});
    } else reqs.push({label: `${shared ? "" : `${b.module}: `}${b.name} G${g.grade}`, grade: g.grade, engineers: g.engineers.map(e => e.name)});
  }
  for (const p of [...parts].sort((a, b) => a.localeCompare(b))) {
    if (graded.has(p)) continue;
    const names = new Set();
    for (const b of blueprints) if (cmdrPartsOf(b).includes(p)) for (const g of b.grades) for (const e of cmdrGradeEngineers(g, b, new Set([p]))) names.add(e.name);
    reqs.push({label: `${p} (any grade)`, grade: null, engineers: [...names]});
  }
  return reqs;
}
// what the picked grades are short of, for one roll each: [{material, have, need, for}]. Pure.
function cmdrTripShort(blueprints, grades) {
  const out = [];
  for (const b of blueprints) for (const g of b.grades) {
    if (!grades.has(`${b.id}|${g.grade}`)) continue;
    for (const m of g.materials) if (m.have < m.need) out.push({material: m.name, have: m.have, need: m.need, for: `${b.name} G${g.grade}`});
  }
  return out;
}
function cmdrTripSave() { try { localStorage.setItem("cmTrip", JSON.stringify(CM.trip)); } catch {} }
function cmdrTripLoad() { try { const t = JSON.parse(localStorage.getItem("cmTrip") || "null"); return t && Array.isArray(t.stops) ? t : null; } catch { return null; } }
async function cmdrPlanTrip() {
  const bps = (CM.data.engineering || {}).blueprints || [];
  const requirements = cmdrTripRequirements(bps, CM.parts, CM.grades);
  if (!requirements.length) { CM.tripNote = "pick a part or a grade first"; return cmdrDrawBody(); }
  CM.tripNote = "planning…"; cmdrDrawBody();
  let d;
  try {
    d = await apiJson("api/commander/engineer_tour", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({requirements, include_locked: !!CM.tripLocked, return_carrier: !!CM.tripCarrier})});
  } catch (err) { d = {error: err.message}; }
  if (!d || d.error) { CM.tripNote = `could not plan it: ${(d && d.error) || "no answer"}`; return cmdrDrawBody(); }
  CM.tripNote = null;
  CM.trip = Object.assign({}, d, {done: [], short: cmdrTripShort(bps, CM.grades), at: Date.now()});
  cmdrTripSave();
  cmdrDrawBody();
}
// a stop is done once you are in its system (marked as the page draws, kept with the trip). Pure but for that mark.
function cmdrTripTick(trip) {
  const here = data && data.position && data.position.name;
  if (!trip || !here) return;
  const i = trip.stops.findIndex((s, k) => s.system === here && !trip.done.includes(k));
  if (i >= 0 && trip.stops.slice(0, i).every((s, k) => trip.done.includes(k) || s.system === here)) { trip.done.push(i); cmdrTripSave(); }
}
// the trip as text, for the clipboard. Pure.
const cmdrTripText = t => t.stops.map((s, i) => `${i + 1}. ${s.engineer} — ${s.system} (${s.leg_ly} ly): ${s.covers.join(", ")}${s.locked ? ` [${s.locked}]` : ""}`)
  .concat(t.carrier && t.back_ly != null ? [`then your carrier ${t.carrier.name || ""} — ${t.carrier.system} (${t.back_ly} ly)`] : [])
  .concat([`${t.total_ly} ly in all, from ${t.from}`]).join("\n");
// the controls, and the trip once planned. Pure but for cmdrTripTick.
function cmdrTripHtml() {
  const picks = CM.parts.size || CM.grades.size, carrier = data && data.carrier;
  const ctl = !picks && !CM.trip ? "" : `<div class="cmtripctl">` +
    (picks ? `<button type="button" class="mini primary" id="cmPlanTrip" title="the engineers who cover every pick for the fewest light years from where you are, in order">Plan the trip</button>` +
      ` <label title="also engineers you have not unlocked, or not far enough for the grade: each stop says what it still needs"><input type="checkbox" id="cmTripLocked"${CM.tripLocked ? " checked" : ""}> include engineers I have not unlocked</label>` +
      ` <label title="${carrier ? `end the trip at ${esc(carrier.name || "your carrier")} in ${esc(carrier.system || "?")}` : "no fleet carrier on record"}"><input type="checkbox" id="cmTripCarrier"${CM.tripCarrier && carrier ? " checked" : ""}${carrier ? "" : " disabled"}> end at my fleet carrier</label>` : "") +
    (CM.tripNote ? ` <span class="unk">${esc(CM.tripNote)}</span>` : "") + `</div>`;
  const t = CM.trip;
  if (!t) return ctl;
  cmdrTripTick(t);
  const next = t.stops.findIndex((s, i) => !t.done.includes(i));
  const row = (s, i) => `<tr class="${t.done.includes(i) ? "cmtripdone" : i === next ? "cmtripnext" : ""}"><td class="num">${t.done.includes(i) ? "✓" : i + 1}</td>` +
    `<td><b>${esc(s.engineer)}</b>${s.locked ? ` <span class="warnc" title="you would have to see to this first">${esc(s.locked)}</span>` : ""}</td><td>${esc(s.system || "?")}</td>` +
    `<td>${esc(s.covers.join(", "))}</td><td class="num">${cmNum(s.leg_ly)} ly</td>` +
    `<td class="num">${s.system ? `<button type="button" class="mini" data-cmcopy="${esc(s.system)}">Copy</button>${forkPlotBtn(s.system)}` : ""}</td></tr>`;
  const back = t.carrier && t.back_ly != null ? `<tr class="cmtripback"><td class="num">⌂</td><td><b>${esc(t.carrier.name || "your carrier")}</b></td><td>${esc(t.carrier.system || "?")}</td>` +
    `<td class="unk">back to your carrier</td><td class="num">${cmNum(t.back_ly)} ly</td><td class="num">${t.carrier.system ? forkPlotBtn(t.carrier.system) : ""}</td></tr>` : "";
  const short = (t.short || []).length ? `<div class="cmtripshort"><span class="warnc">Short for one roll:</span> ${t.short.map(m => `${esc(m.material)} ${cmNum(m.have)}/${cmNum(m.need)} <span class="unk">(${esc(m.for)})</span>`).join(", ")}</div>` : "";
  const missed = (t.uncovered || []).length ? `<div class="cmtripshort"><span class="warnc">Not covered:</span> ${t.uncovered.map(u => `${esc(u.label)} <span class="unk">(${esc(u.why)})</span>`).join(", ")}</div>` : "";
  return ctl + `<div class="cmtrip"><div class="hwyttl">Trip from ${esc(t.from || "?")}: ${t.stops.length} stop${t.stops.length === 1 ? "" : "s"}, ${cmNum(t.total_ly)} ly` +
    `${t.done.length ? ` <span class="unk">· ${t.done.length} done</span>` : ""}</div>` +
    `<div class="srow">${next >= 0 && t.stops[next].system ? `<button type="button" class="mini primary" data-plotto="${esc(t.stops[next].system)}">Plot next stop: ${esc(t.stops[next].system)}</button>` : t.stops.length ? `<span class="ok">every stop done</span>` : ""}` +
    ` <button type="button" class="mini" id="cmTripCopy">Copy itinerary</button> <button type="button" class="mini" id="cmTripForget">Forget the trip</button>` +
    ` <span class="unk">light years in straight lines: a guide to the jumps</span></div>` +
    (t.stops.length ? `<table class="cmengtable cmtriptable"><thead><tr><th class="num">#</th><th>Engineer</th><th>System</th><th>Covers</th><th class="num">Leg</th><th></th></tr></thead>` +
      `<tbody>${t.stops.map(row).join("")}${back}</tbody></table>` : `<div class="unk">No engineer you can use covers these picks.</div>`) + missed + short + `</div>`;
}

// the part picker: every part as a toggle, the picked ones on; Clear when any part or grade is picked. Pure (CM.parts).
function cmdrPartsHtml(blueprints) {
  const all = [...new Set(blueprints.flatMap(cmdrPartsOf))].sort((a, b) => a.localeCompare(b));
  if (!all.length) return "";
  return `<div class="cmparts" role="group" aria-label="parts"><span class="unk">Parts:</span>` +
    all.map(p => `<button type="button" class="mini cmpart${CM.parts.has(p) ? " on" : ""}" data-cmpart="${esc(p)}" aria-pressed="${CM.parts.has(p)}">${esc(p)}</button>`).join("") +
    (CM.parts.size || CM.grades.size ? ` <button type="button" class="mini" data-cmpart-clear title="every part and grade again">Clear</button>` : "") +
    (CM.grades.size ? ` <span class="unk">· grades picked: ${CM.grades.size} (click a grade below to pick or unpick it)</span>` : "") + `</div>`;
}

// what the Engineering search looks in, lower case: a blueprint's module, name, the modules it is for (missile racks...),
// its materials and its engineers; an engineer's name, kind, system and region. Pure.
const cmdrBlueprintText = b => [b.module, b.name, ...(b.for || []), ...b.grades.flatMap(g => g.materials.map(x => x.name).concat(g.engineers.map(e => e.name)))]
  .join(" ").toLowerCase();
const cmdrEngineerText = e => [e.name, e.kind, e.system, e.region].filter(Boolean).join(" ").toLowerCase();
// Engineering: the blueprints by module, each grade's materials against what you hold. Pure (CM.q, CM.craft, CM.open).
function cmdrEngineeringHtml(d) {
  const q = CM.q.trim().toLowerCase();
  const all = d.engineers || [], eng = all.filter(e => e.progress), unlocked = eng.filter(e => e.progress === "Unlocked").length;
  const gradeRow = (g, b) => {
    const mats = g.materials.map(x => `<span class="cmmat ${x.have >= x.need ? "ok" : "noscoop"}" title="you hold ${cmNum(x.have)}">${esc(x.name)} ${cmNum(x.have)}/${x.need}</span>`).join("");
    const who = cmdrGradeEngineers(g, b, CM.parts).map(e => `<span class="${e.ready ? "ok" : "unk"}" title="${esc((e.progress ? `${e.progress}${e.rank != null ? `, rank ${e.rank}` : ""}` : "not met yet") + (e.system ? ` · in ${e.system}` : ""))}">${esc(e.name)}</span>`).join(", ");
    const key = `${b.id}|${g.grade}`, on = CM.grades.has(key);
    return `<tr${on ? ` class="cmgradeon"` : ""}><td><button type="button" class="mini cmgrade${on ? " on" : ""}" data-cmgrade="${esc(key)}" aria-pressed="${on}" ` +
      `title="${on ? "unpick this grade" : "show only the engineers who do this grade"}"><b>G${g.grade}</b></button></td><td><div class="cmstats">${mats}</div></td>` +
      `<td class="num ${g.rolls ? "ok" : "unk"}" title="how many times you could craft this grade now">${g.rolls ? `×${cmNum(g.rolls)}` : "–"}</td><td>${who}</td></tr>`;
  };
  const groups = new Map();
  for (const b of d.blueprints || []) {
    if (q && !cmdrBlueprintText(b).includes(q)) continue;
    if (CM.parts.size && !cmdrPartsOf(b).some(p => CM.parts.has(p))) continue;
    const grades = CM.craft ? b.grades.filter(g => g.rolls > 0) : b.grades;
    if (!grades.length) continue;
    if (!groups.has(b.module)) groups.set(b.module, []);
    groups.get(b.module).push(`<h4 class="cmbp">${esc(b.name)}</h4>` + ((b.for || []).length ? `<div class="unk cmfor">for: ${esc(b.for.join(", "))}</div>` : "") + cmTable([["Grade"], ["Materials <span class=\"unk\">(held / one roll)</span>"], ["Rolls", 1], ["Engineers"]], grades.map(g => gradeRow(g, b))));
  }
  const open = k => q || CM.craft || CM.parts.size || CM.grades.size || CM.open[k];   // a search or a pick shows what it found   // a filter shows what it found
  return `<div class="srow cmfilter"><input type="search" id="cmFilter" placeholder="search: module, weapon, blueprint, material or engineer" value="${esc(CM.q)}" size="34">` +
    ` <label title="only the grades you hold every material for"><input type="checkbox" id="cmCraft"${CM.craft ? " checked" : ""}> only what I can craft now</label>` +
    ` <button type="button" class="mini" id="cmLoadShip" title="pick the parts the ship you fly has, and the grade each engineered module is at">Load my ship</button>` +
    (CM.q || CM.craft || CM.parts.size || CM.grades.size
      ? ` <button type="button" class="mini" id="cmClearAll" title="the search, only what I can craft, the parts and the grades picked: all off">Clear filters</button>` : "") +
    ` <span class="unk">${eng.length ? `${unlocked} of ${eng.length} engineers unlocked` : "no engineer on record yet"} · ship modules only: no experimental effects, suits or weapons</span></div>` +
    cmdrPartsHtml(d.blueprints || []) + cmdrShipHtml(CM.ship) + cmdrTripHtml() +
    (cmdrLoadDistances(), "") + (() => {
      const bps = d.blueprints || [];
      const byPart = CM.parts.size ? cmdrPartEngineers(bps, CM.parts) : null;
      const byGrade = CM.grades.size ? cmdrGradeEngineersPicked(bps, CM.grades, CM.parts) : null;
      // a picked grade narrows further: the engineers who do it (and, with parts picked, those parts' engineers too)
      const keep = e => { const k = cmPlain(e.name); return (!byPart || byPart.has(k)) && (!byGrade || byGrade.has(k)); };
      const supports = byPart || byGrade ? new Map(all.map(e => [cmPlain(e.name), new Set([...(byPart && byPart.get(cmPlain(e.name)) || []),
                                                                                         ...(byGrade && byGrade.get(cmPlain(e.name)) || [])])])) : null;
      return cmdrEngineersHtml(all.filter(e => (!q || cmdrEngineerText(e).includes(q)) && keep(e)),
                               q || CM.parts.size || CM.grades.size ? [...CM.parts].join(", ") || q || "grades" : "", supports);
    })() +
    ([...groups].map(([mod, list]) => `<details class="cmmod" data-cmmod="${esc(mod)}"${open(mod) ? " open" : ""}><summary><b>${esc(mod)}</b> <span class="unk">${list.length} blueprint${list.length === 1 ? "" : "s"}</span></summary>${list.join("")}</details>`).join("")
      || `<div class="unk">Nothing matches.</div>`);
}

// Missions. Pure.
function cmdrMissionsHtml(d) {
  const rows = (d.missions || []).map(m => {
    const need = [m.commodity, m.target].filter(Boolean).map(esc).join(" · ") +
      (m.count != null ? ` <b>${m.delivered != null ? `${cmNum(m.delivered)}/` : ""}${cmNum(m.count)}</b>` : "");
    const exp = m.expires_in == null ? `<span class="unk">no limit</span>` : m.expired ? `<span class="noscoop">expired</span>`
      : `<span class="${m.soon ? "warnc" : ""}" title="${cmWhen(m.expiry)} UTC">${cmSpan(m.expires_in)}</span>`;
    return `<tr><td><b>${esc(m.name || "?")}</b>${m.wing ? ` <span class="unk">wing</span>` : ""}${m.passengers ? ` <span class="unk">passengers</span>` : ""}` +
      `${m.redirected ? ` <span class="ok" title="the game sent you on: usually back to hand it in">redirected</span>` : ""}</td>` +
      `<td>${esc(m.faction || "")}</td><td>${esc([m.system, m.station].filter(Boolean).join(" · "))}</td><td>${need}</td>` +
      `<td class="num">${cmCr(m.reward)}</td><td class="num">${exp}</td></tr>`;
  });
  const soon = (d.missions || []).filter(m => m.soon).length;
  return `<div class="hwyttl">${rows.length ? `${rows.length} mission${rows.length === 1 ? "" : "s"}` : "No missions"}` +
    `${soon ? ` <span class="warnc">· ${soon} expiring within half an hour</span>` : ""}</div>` +
    (rows.length ? cmTable([["Mission"], ["Faction"], ["Where"], ["What"], ["Reward", 1], ["Expires in", 1]], rows)
      : `<div class="unk">Missions you accept are listed here with where they go, what they ask and when they run out.</div>`);
}

// Sessions: the totals, then each combat and each mining session. Pure.
function cmdrSessionsHtml(d) {
  const all = d.sessions || [], t = d.totals || {combat: {}, mining: {}};
  const tile = (k, v) => v == null || v === "" ? "" : `<span class="cmfig"><span class="unk">${k}</span><b>${v}</b></span>`;
  const list = o => Object.entries(o || {}).map(([k, v]) => `${esc(k)} ${cmNum(v)}`).join(", ");
  const combat = all.filter(s => s.combat).map(s => { const c = s.combat; return `<tr><td>${cmWhen(s.start)}</td><td>${esc(s.ship || "")}</td>` +
    `<td class="num"><b>${cmNum(c.kills)}</b></td><td>${list(c.by_ship)}</td><td class="num">${cmCr(c.bounties)}</td><td class="num">${cmCr(c.bonds)}</td>` +
    `<td class="num">${c.per_hour != null ? c.per_hour : ""}</td><td class="num">${cmSpan(c.seconds)}</td><td class="num">${c.deaths ? `<span class="noscoop">${c.deaths}</span>` : ""}</td></tr>`; });
  const mining = all.filter(s => s.mining).map(s => { const m = s.mining; return `<tr><td>${cmWhen(s.start)}</td><td>${esc(s.ship || "")}</td>` +
    `<td class="num"><b>${cmNum(m.tons)} t</b></td><td>${list(m.refined)}</td><td class="num">${m.per_hour != null ? m.per_hour : ""}</td>` +
    `<td>${cmNum(m.prospected)}${m.prospected ? ` <span class="unk">${list(m.content)}${m.motherlodes ? ` · ${m.motherlodes} core${m.motherlodes === 1 ? "" : "s"}` : ""}</span>` : ""}</td>` +
    `<td class="num" title="prospector / collector limpets launched">${m.prospectors || m.collectors ? `${cmNum(m.prospectors)} / ${cmNum(m.collectors)}` : ""}</td>` +
    `<td class="num">${cmSpan(m.seconds)}</td><td class="num">${cmCr(m.sold)}</td></tr>`; });
  const c = t.combat, m = t.mining;
  return `<h3 class="subhead">Combat <span class="unk">the last ${d.days || 30} days</span></h3>` +
    (combat.length ? `<div class="cmfigs">${tile("Sessions", cmNum(c.sessions))}${tile("Kills", cmNum(c.kills))}${tile("Bounties", cmCr(c.bounties))}${tile("Combat bonds", cmCr(c.bonds))}${tile("Deaths", c.deaths ? cmNum(c.deaths) : "")}</div>` +
      cmTable([["Session"], ["Ship"], ["Kills", 1], ["Bounties by ship"], ["Bounties", 1], ["Bonds", 1], ["Kills/h", 1], ["Fighting", 1], ["Deaths", 1]], combat)
      : `<div class="unk">No fighting in these journals.</div>`) +
    `<h3 class="subhead">Mining <span class="unk">the last ${d.days || 30} days</span></h3>` +
    (mining.length ? `<div class="cmfigs">${tile("Sessions", cmNum(m.sessions))}${tile("Refined", `${cmNum(m.tons)} t`)}${tile("Asteroids prospected", cmNum(m.prospected))}${tile("Sold", cmCr(m.sold))}</div>` +
      cmTable([["Session"], ["Ship"], ["Refined", 1], ["What"], ["t/h", 1], ["Prospected"], ["Limpets", 1], ["Mining", 1], ["Sold", 1]], mining)
      : `<div class="unk">No mining in these journals.</div>`);
}

const CM_HTML = {profile: cmdrProfileHtml, inventory: cmdrInventoryHtml, engineering: cmdrEngineeringHtml, missions: cmdrMissionsHtml, sessions: cmdrSessionsHtml};
// the tab's own content: drawn apart from the tab row so typing in Engineering's filter keeps its place
function cmdrDrawBody() {
  const el = document.getElementById("cmdrBody");
  if (!el) return;
  const tab = CM.tab, d = CM.data[tab];
  const h = CM.error[tab] && !d ? `<div class="noscoop">Could not be read: ${esc(CM.error[tab])}</div>`
    : !d ? `<div class="unk">${CM.loading[tab] ? "Reading your journals…" : ""}</div>` : CM_HTML[tab](d);
  if (el.innerHTML === h) return;
  const typing = document.activeElement && document.activeElement.id === "cmFilter", at = typing ? document.activeElement.selectionStart : null;
  el.innerHTML = h;
  if (typing) { const f = document.getElementById("cmFilter"); if (f) { f.focus(); try { f.setSelectionRange(at, at); } catch {} } }
}
function renderCmdr() {
  const tabs = document.getElementById("cmdrTabs");
  if (!tabs) return;
  const h = `<span class="cmtabs">${CM_TABS.map(([k, name, title]) => `<button type="button" class="cmtab${k === CM.tab ? " on" : ""}" data-cmtab="${k}" title="${esc(title)}">${name}</button>`).join("")}</span>` +
    ` <button type="button" class="mini" id="cmRefresh" title="read the journals again now">Refresh</button>` +
    ` <span class="unk">${CM.loading[CM.tab] ? "reading…" : CM.error[CM.tab] && CM.data[CM.tab] ? `could not be read again: ${esc(CM.error[CM.tab])}` : "from your journals"}</span>`;
  if (tabs.innerHTML !== h) tabs.innerHTML = h;
  cmdrDrawBody();
}

// ---- Route lists: who first discovered a system (this fork; EDSM's record, asked by the server in the background).
// Shown after the Known mark of a system somebody has been to. Pure ----
function hwyDiscovererHtml(name) {
  return name ? ` <span class="hwydisc" title="first discovered by CMDR ${esc(name)} (EDSM's record)">${esc(name)}</span>` : "";
}


// This fork's own page code, apart from upstream's page.js so the two merge without conflicts. Loaded before page.js:
// everything here is a definition, and uses page.js's helpers (esc, apiJson, credits, shipLabel, view) only
// when called. page.js calls loadCmdr() from render() when the Commander view is shown.

// ---- The Commander view (GET /api/commander/<tab>, outrider/commander.py): who you are in the game (CMDR), what you own (Inventory),
// what engineering takes against your materials (Engineering), the missions you hold (Missions) and how your combat
// and mining sessions went (Sessions). Each tab is read from the journals when opened, and again when stale ----
// CM: tab (the one shown), data / error / at / loading per tab, q and craft (Engineering's filter), open (its modules)
const CM = {tab: "profile", data: {}, error: {}, at: {}, loading: {}, q: "", craft: false, open: {}, wired: false};
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
  });
  el.addEventListener("input", e => { if (e.target.id === "cmFilter") { CM.q = e.target.value; cmdrDrawBody(); } });
  el.addEventListener("change", e => { if (e.target.id === "cmCraft") { CM.craft = e.target.checked; cmdrDrawBody(); } });
  el.addEventListener("toggle", e => { const k = e.target.dataset && e.target.dataset.cmmod; if (k) CM.open[k] = e.target.open; }, true);
  try { const t = localStorage.getItem("cmdrTab"); if (CM_TABS.some(x => x[0] === t)) CM.tab = t; } catch {}
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

// Engineering: the blueprints by module, each grade's materials against what you hold. Pure (CM.q, CM.craft, CM.open).
function cmdrEngineeringHtml(d) {
  const q = CM.q.trim().toLowerCase();
  const eng = d.engineers || [], unlocked = eng.filter(e => e.progress === "Unlocked").length;
  const gradeRow = g => {
    const mats = g.materials.map(x => `<span class="cmmat ${x.have >= x.need ? "ok" : "noscoop"}" title="you hold ${cmNum(x.have)}">${esc(x.name)} ${cmNum(x.have)}/${x.need}</span>`).join("");
    const who = g.engineers.map(e => `<span class="${e.ready ? "ok" : "unk"}" title="${esc(e.progress ? `${e.progress}${e.rank != null ? `, rank ${e.rank}` : ""}` : "not met yet")}">${esc(e.name)}</span>`).join(", ");
    return `<tr><td><b>G${g.grade}</b></td><td><div class="cmstats">${mats}</div></td>` +
      `<td class="num ${g.rolls ? "ok" : "unk"}" title="how many times you could craft this grade now">${g.rolls ? `×${cmNum(g.rolls)}` : "–"}</td><td>${who}</td></tr>`;
  };
  const groups = new Map();
  for (const b of d.blueprints || []) {
    if (q && !`${b.module} ${b.name} ${b.grades.map(g => g.materials.map(x => x.name).join(" ")).join(" ")}`.toLowerCase().includes(q)) continue;
    const grades = CM.craft ? b.grades.filter(g => g.rolls > 0) : b.grades;
    if (!grades.length) continue;
    if (!groups.has(b.module)) groups.set(b.module, []);
    groups.get(b.module).push(`<h4 class="cmbp">${esc(b.name)}</h4>` + cmTable([["Grade"], ["Materials <span class=\"unk\">(held / one roll)</span>"], ["Rolls", 1], ["Engineers"]], grades.map(gradeRow)));
  }
  const open = k => q || CM.craft || CM.open[k];   // a filter shows what it found
  return `<div class="srow cmfilter"><input type="search" id="cmFilter" placeholder="filter: module, blueprint or material" value="${esc(CM.q)}" size="34">` +
    ` <label title="only the grades you hold every material for"><input type="checkbox" id="cmCraft"${CM.craft ? " checked" : ""}> only what I can craft now</label>` +
    ` <span class="unk">${eng.length ? `${unlocked} of ${eng.length} engineers unlocked` : "no engineer on record yet"} · ship modules only: no experimental effects, suits or weapons</span></div>` +
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

// ---- Space chatter (this fork; GET /api/chatter, outrider/chatter.py): with speech on and a personality that has
// chatter lines ticked (Rocky is the first), the co-pilot says something of its own when nothing was said for a while:
// at a random moment between `min` and `max` minutes after the last line, whoever said it. Never while the game is
// not running, the voice is hushed, another window speaks, or a line waits. Its settings are this browser's
// (localStorage "chatter": {on, min, max}; on unless switched off), in the voice dialog under Personality ----
// CH: lines {personality: [...]}, asked (when they were last asked for), quiet (since when nothing was said, or
// chatter could not have been), frac (where in the window this quiet's line falls), recent (lines said lately)
const CH = {lines: null, asked: 0, quiet: Date.now(), frac: Math.random(), recent: [], last: 0, wired: false};
const CH_DEFAULT = {on: true, min: 2, max: 10};
const CH_TICK_MS = 5000, CH_LINES_AGAIN_MS = 10 * 60 * 1000, CH_RECENT = 30;
// the settings, made sane: min 0.5 to 120 minutes, max from min to 240. Pure.
function chatterClean(c) {
  c = c && typeof c === "object" ? c : {};
  const min = Number(c.min), max = Number(c.max);
  const mn = min >= 0.5 && min <= 120 ? min : CH_DEFAULT.min, mx = max >= mn && max <= 240 ? max : Math.max(mn, CH_DEFAULT.max);
  return {on: c.on !== false, min: mn, max: mx};
}
function chatterCfg() { try { return chatterClean(JSON.parse(localStorage.getItem("chatter") || "null")); } catch { return chatterClean(null); } }
function chatterSave(c) { try { localStorage.setItem("chatter", JSON.stringify(chatterClean(c))); } catch {} CH.frac = Math.random(); chatterDraw(); }
// when this quiet's line is due: `frac` of the way from min to max minutes after the quiet began. Pure.
const chatterDue = (quiet, frac, cfg) => quiet + (cfg.min + Math.min(1, Math.max(0, frac)) * (cfg.max - cfg.min)) * 60000;
// the personalities that may chatter: ticked ones with lines; with one personality on shift, that one or none. Pure.
const chatterStyles = (lines, ticked, shift) => (ticked || []).filter(st => Array.isArray((lines || {})[st]) && lines[st].length && (!shift || st === shift));
// a line not said lately; with all of them said, any but the last one. Pure (rnd: 0..1).
function chatterPick(pool, recent, rnd = Math.random) {
  let fresh = pool.filter(x => !recent.includes(x));
  if (!fresh.length) fresh = pool.filter(x => x !== recent[recent.length - 1]);
  if (!fresh.length) fresh = pool;
  return fresh.length ? fresh[Math.min(fresh.length - 1, Math.floor(rnd() * fresh.length))] : null;
}
// what the page is doing, as the tick needs it: may chatter be said at all now, which personalities, since when quiet
function chatterEnv() {
  const cfg = chatterCfg();
  const ok = typeof speak === "function" && typeof data !== "undefined" && !!data;
  const can = ok && cfg.on && speechOn && speakerHere() && !hushed() && !!(data.freshness && data.freshness.live) && !speechBusy && !speechItems.length;
  return {cfg, can, lines: CH.lines || {}, ticked: ok ? speechStyles() : [], shift: ok && speechShift() ? shiftStyle : null,
          said: ok && captions.length ? captions[captions.length - 1].at : 0};
}
// One look: [personality, line] when a line is due and was handed to `say`, else null. A moment when chatter could
// not be said (speech off, the game closed, a line waiting) counts as not quiet: the window starts after it.
function chatterTick(now = Date.now(), env = chatterEnv(), say = chatterSay) {
  const styles = chatterStyles(env.lines, env.ticked, env.shift);
  if (!env.can || !styles.length) { CH.quiet = now; return null; }
  const quiet = Math.max(CH.quiet, env.said, CH.last);
  if (quiet !== CH.quiet) { CH.quiet = quiet; CH.frac = Math.random(); }
  if (now < chatterDue(CH.quiet, CH.frac, env.cfg)) return null;
  const style = styles[Math.floor(Math.random() * styles.length)], text = chatterPick(env.lines[style], CH.recent);
  if (!text) return null;
  CH.last = CH.quiet = now; CH.frac = Math.random();
  CH.recent.push(text); if (CH.recent.length > Math.min(CH_RECENT, env.lines[style].length - 1)) CH.recent.shift();
  say(style, text);
  return [style, text];
}
// said like any other line of that personality (its own voice when it has one), and shown in the caption strip
function chatterSay(style, text) { speak(text, {kind: "chatter", ...styleVoice(style)}); addCaption(text); }
// the settings row, put under the voice dialog's Personality line (made here: page.html stays upstream's)
function chatterWire() {
  const box = document.getElementById("speechStyles");
  if (CH.wired || !box) return;
  CH.wired = true;
  const row = document.createElement("div");
  row.className = "mod inlineopts"; row.id = "chatterRow";
  row.innerHTML = `<label title="with a personality that has chatter lines ticked, the voice says something of its own when it has been quiet for a while (never with speech off, the game closed, or the voice hushed)"><input type="checkbox" id="chatterOn"> Space chatter:</label>` +
    ` after <input type="number" id="chatterMin" min="0.5" max="120" step="0.5" inputmode="decimal" style="width:4.5em"> to <input type="number" id="chatterMax" min="0.5" max="240" step="0.5" inputmode="decimal" style="width:4.5em"> minutes of quiet <span id="chatterNote" class="unk"></span>`;
  box.closest(".mod").after(row);
  row.addEventListener("change", e => {
    const c = chatterCfg(), min = Number(document.getElementById("chatterMin").value), max = Number(document.getElementById("chatterMax").value);
    if (e.target.id === "chatterOn") c.on = e.target.checked;
    if (e.target.id === "chatterMin" && min >= 0.5 && min <= 120) { c.min = min; if (c.max < min) c.max = min; }
    if (e.target.id === "chatterMax" && max >= 0.5 && max <= 240) { c.max = Math.max(max, c.min); }
    chatterSave(c);
  });
  chatterDraw();
}
function chatterDraw() {
  const on = document.getElementById("chatterOn");
  if (!on) return;
  const c = chatterCfg(), mn = document.getElementById("chatterMin"), mx = document.getElementById("chatterMax");
  on.checked = c.on;
  if (document.activeElement !== mn) mn.value = c.min;
  if (document.activeElement !== mx) mx.value = c.max;
  const have = Object.keys(CH.lines || {}), lib = typeof speechLib !== "undefined" ? speechLib.styles || {} : {};
  const name = k => { const v = lib[k]; return typeof v === "string" ? v : (v && v.label) || k; };
  const ticked = typeof speechStyles === "function" ? chatterStyles(CH.lines, speechStyles(), null) : [];
  const note = !CH.lines ? "" : !have.length ? "no chatter lines found" : ticked.length ? `chatting: ${ticked.map(name).join(", ")}`
    : `tick ${have.map(name).join(" or ")} above to hear it`;
  const el = document.getElementById("chatterNote");
  if (el.textContent !== note) el.textContent = note;
}
// the lines, asked for once speech and chatter are both on (and again now and then: the file may be edited)
async function chatterLoad(now = Date.now()) {
  if (now - CH.asked < CH_LINES_AGAIN_MS && (CH.lines || CH.asked)) return;
  CH.asked = now;
  // fetch, not apiJson: a request nobody clicked for must not pass through what a caller may have put in its place
  try { const r = await fetch("api/chatter"), d = r.ok ? await r.json() : null; if (d && d.lines && typeof d.lines === "object") CH.lines = d.lines; } catch {}
  chatterDraw();
}
// The settings row once the page is there; then a look every few seconds, which does nothing at all while speech is
// off (the usual state of a window that is not the one speaking, and of the page under test)
document.addEventListener("DOMContentLoaded", () => { try { chatterWire(); } catch (e) { console.warn("chatter:", e); } });
setInterval(() => {
  try {
    if (typeof speechOn === "undefined" || !speechOn) { CH.quiet = Date.now(); return; }
    if (chatterCfg().on) chatterLoad();
    chatterTick();
  } catch (e) { console.warn("chatter:", e); }
}, CH_TICK_MS);

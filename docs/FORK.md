# This fork

`weidercs/ED-Outrider`, a personal fork of [weslocke/ED-Outrider](https://github.com/weslocke/ED-Outrider). Everything
about the fork is written here, not in upstream's documents: `CHANGELOG.md`, `AGENT_GUIDE.md`, `DESIGN_NOTES.md` and
`guide/settings.md` are upstream's word for word, so they merge without conflicts. Keep it that way: a fork change
gets its changelog entry, code-map row, design note and settings at the bottom of the matching section below.

## What the fork adds

- **Commander** tab: inventory, engineering blueprints against your materials, missions, combat and mining
  sessions (`outrider/commander.py`, `static/fork.js`); discoverer names in the route lists (EDSM).
- **Ship** tab: the ship you fly, its modules and engineering, with EDSY and Coriolis links (`outrider/shipinfo.py`).
- **GalNet** tab: Frontier's news, the systems an article mentions marked to copy or plot (`outrider/galnet.py`).
- **Plot Route**: the game's own route as a list and on the map (`outrider/navroute.py`); a Known column (already
  discovered?); "refuel at every fuel star"; the **Unscanned (bio)** plotter, which can favour one species
  (`outrider/biohunt.py`).
- **Auto honk** can then target the next route system (`[autohonk] target_next`, `target_delay`).
- **In-game overlay**: a Route panel (`[overlay] route_panel`).
- Sell / Buy results name the fleet carrier.
- `scripts/verify.sh` and the tests pass on Windows (Git Bash).

## Bringing upstream in

The remotes: `origin` is the fork (push here), `upstream` is weslocke's (fetch only).

    bash scripts/merge-upstream.sh

It fetches `upstream`, merges `upstream/main` into `main` with an ordinary merge (never a rebase or a force-push) and
runs `scripts/verify.sh`; with a PASS, `git push`. What to expect:

- **Conflicts** are kept small by where the fork's code sits. Keep both sides. `git rerere` is on in this checkout
  (`git config rerere.enabled true`), so a conflict resolved once is resolved the same way next time.
- **When upstream builds something the fork has**, upstream's wins and the fork's goes (EDDN, EDSM and Inara uploads
  went this way).
- **The Commander view is offered upstream** (branch `commander-view`, a pull request). If upstream takes it, its page
  code arrives in `page.js`: delete the Commander part of `static/fork.js` and the fork's own hooks and styles for it
  then, or the page declares `CM` twice and does not load.
- **A new upstream test that fails on Windows only**: a symlink (`@unittest.skipUnless(can_symlink(), ...)`), a file
  mode or a path Git Bash names its own way (`@unittest.skipIf(os.name == "nt", ...)`).
- `resources/bio_rules.json` is rewritten by Outrider at start-up and marked `--skip-worktree` in this checkout. If
  a merge stops over it: `git update-index --no-skip-worktree resources/bio_rules.json`, `git checkout --
  resources/bio_rules.json`, merge, then `--skip-worktree` again.

Where the fork still touches upstream's files (each a place a merge can conflict): `ed_outrider.py` (settings, State
methods, routes), `static/page.html`, `page.js` (new page code: `static/fork.js`) and `page.css`, `tests/page_smoke.js`,
`outrider/overlay.py`, `outrider/ask.py`, the guide's pages for the features above and Windows fixes in a few tests.
New fork code goes in its own module and its own test file wherever it can; in a shared file, add it as its own
block (a new line, not an edit in the middle of upstream's line).

## The Commander tab

What you own and what you have been doing, read from your journals when you open the tab (nothing is stored, and
nothing is asked of anyone):

- **CMDR**: who you are in the game, as of your last login (the game writes credits, ranks and statistics then):
  credits, net worth, the value of your fleet and stored modules, your carrier's balance; every rank with a bar
  to the next one and, for trade, exploration and exobiology, about how many credits it still takes (the
  community's figures for each rank's step: an estimate); reputation, Powerplay and squadron; your ships; and
  career figures (time played, systems visited, distance, profits by career).
- **Inventory**: your ships (where each is, its value, what bringing it here costs), your stored modules with their
  engineering, the ship locker, and the suit loadouts you have worn. The game writes the list of stored ships when
  you open a shipyard and of stored modules when you open outfitting: each is shown as of then.
- **Engineering**: every ship-module blueprint, grade by grade, with the materials one roll takes against what you
  hold (green: enough), how many rolls you could make now, and the engineers offering it (green: unlocked far
  enough). Filter by module, blueprint or material, or show only what you can craft now. Experimental effects and
  suit and weapon upgrades are not listed.
- **Missions**: the missions you hold, the soonest to expire first: where they go, what they ask (and how much is
  delivered), the reward, and the time left, marked when under half an hour.
- **Sessions**: your combat and mining sessions of the last 30 days, each from login to logout. Combat: kills, by
  ship, bounties and bonds, kills an hour, deaths. Mining: tons refined and of what, tons an hour, asteroids
  prospected and their content, limpets launched, and what the haul sold for.

In the route lists:

- **Discoverer**: after the Known mark of a system somebody has been to, the commander EDSM credits with its first
  discovery (this fork; asked in the background, 40 systems a pass, the main star's discoverer). No name: EDSM
  credits nobody, or does not know the system.

## Settings

Beside upstream's ([guide/settings.md](guide/settings.md)), all in `ed_outrider.toml.example`:

| Section | Keys |
|---|---|
| `[autohonk]` | `target_next` (false), `target_delay` (3.0 s, 0 to 60): after a successful auto honk, target the next system of the route you follow |
| `[overlay]` | `route_panel` (false): the Route panel |

## Code map

Beside upstream's ([AGENT_GUIDE.md](AGENT_GUIDE.md)):

| File | What |
|---|---|
| `outrider/commander.py` | This fork's Commander view, pure functions over journal events: `profile` (`rank_rows` with `RANKS` and `RANK_CREDITS`, the money, the fleet, `CAREER`), `ships`, `stored_modules`, `locker`, `suits` (`inventory`), `engineers` and `blueprints(counts, known, name)` (`engineering`; `load_blueprints` reads `resources/blueprints.json`, built by `scripts/build_blueprints.py`), `missions(events, now)` (the login's `Missions` line decides what is still held), `sessions(events)` and `totals` (a session: LoadGame to the next or Shutdown; only those with fighting or mining). `add_routes(app, state, dirs)` serves GET `/api/commander/<part>` in an executor (one line in `make_app`). The page: view `cmdr` in `static/fork.js` (`CM`, `loadCmdr`, `cmdr<Tab>Html`), hooked from page.js's `render()`. Tests: `tests/test_commander.py` |
| `outrider/jscan.py` | This fork's journal reader for the Commander view: `events(dirs, names, days)` (the files that can hold the window, by `outrider.log`'s `journal_files` / `window`; a line is parsed only when it names one of the events; a file that has not grown is read once: `_CACHE` by path, size and names) |
| `static/fork.js` | This fork's own page code, loaded before page.js (definitions only; page.js's helpers are used when called). New fork page code goes here, with a one-line hook in page.js where upstream's code must call it |
| `outrider/shipinfo.py` | This fork's Ship view: `summary(loadout event)` (the ship's figures, its modules by group with `module_name` (name, size, rating, mount from the journal symbol: `_NAMES` by prefix, an unknown family tidied), `slot_group`, `engineering` (blueprint, level, the Modifiers as {label, value, original, pct, good})), `links` (the Loadout gzipped and base64'd into EDSY's and Coriolis's import addresses, as EDMC does), `latest_loadout(dirs, ship_id)` (the newest Loadout in the last journals: nothing is stored). `State.ship_summary` and GET `/api/ship` (in an executor: it reads files). The page: view `ship` (`SH`, `loadShip`, `shipModuleHtml`, `shipStatHtml`, `shipFiguresHtml`). Tests: `tests/test_shipinfo.py`. No module database: a stock module's figures and ship totals are EDSY's to show |
| `outrider/biohunt.py` | This fork's Unscanned (bio) plotter, pure: `mass_code(name)`, `rates(counts)` (`PRIOR` blended with the player's own counts, `PRIOR_WEIGHT`), `odds`, `pick(candidates, here, reach, rate, start, toward, taken)` (the next hop: odds x how much of the range it uses; outward or towards a system; never twice), `rows` (highway_route rows). In ed_outrider.py: `Spansh.unscanned_near` (systems search, `estimated_scan_value` 0, the farthest first), `State.bio_mass_counts` (your own journals), `route_end`, `unscanned_start_plot` (the `unscanned` branch of `highway_start_plot`) and `_unscanned_plot` (one search per hop, `UNSCANNED_GAP_S` apart, `REACH_STEPS` when nothing is in reach; stored with `highway_store`, plotter `unscanned`). `highway_text(rows, i, plotter)` words its arrival line. Favouring one species: `biohunt.species_lean(found names, scanned names)` (each code's lift, the odds scaled to 1; `LEAN_MIN_FOUND` / `LEAN_MIN_SCANNED` or no lean) from `State.species_lean` (`Spansh.body_search` with the species' landmark, `Spansh.sphere` for the scanned systems around; `SPECIES_RADIUS`, `SPECIES_BASE_RADIUS`), kept in the route's options as `species` and `lean`; `State.bio_species_names` fills `/api/highway`'s `bio_species`. The page: the `unscanned` radio, `.hwy-uopt` (`#hwyStops`, `#hwyBioFor`), `unscannedHow`. Tests: `tests/test_biohunt.py` |
| `outrider/navroute.py` | This fork's game route for Plot Route, pure: `rows(hops, pos)` (each jump's ly and the total). In ed_outrider.py: `State.navroute_ahead` (meta `route`'s hops ahead of you) and `navroute_view` (GET `/api/navroute`: the rows with star, scoopable, visited, `route_known_state` and x / z; `from` and `start` for the map; it also starts `route_known_check`). The payload's `route.known_v` reloads it. The page, inside the Plot Route tab: `GR`, `loadNavRoute` (with `loadHwy`), `gameShown` (the device's `hwyGame` and a route), `gameSwitchHtml` (`#hwyGame`, outside `#hwyHead`), `gameHeadHtml`, `navRowHtml` (`#nrPane`), `gameMapRoute` (what `hwyMapRoute` gives the map). Route information only: nothing is followed, targeted or copied, and there is no fuel or refuel part (removed at the player's wish). The in-game overlay's Route panel (this fork: `overlay.route_panel`, `[overlay] route_panel`, off by default; `State.overlay_panels`) draws `route_summary` and `highway_summary`: a new overlay panel needs its id in `overlay.PANELS`, `PANEL_NAMES`, `DEFAULTS` (`<id>_panel`), `LAYOUT_DEFAULT`, `overlay_settings`' key list, `test_panels`, `config_text`, the example config and page.js's `OV_PANELS`. Tests: `tests/test_navroute.py`, `tests/test_overlay.py` (`RoutePanel`) |
| `outrider/galnet.py` | This fork's GalNet News, pure: `parse` (Frontier's feed, `URL`, as articles), `candidates` (what in a text may be a system's name: the capitalised words before "system", catalogue and sector names; each as the forms to try). In ed_outrider.py: `State.galnet_news` (meta `galnet`, live-only: the copy kept `MAX_AGE_S`, a failed read keeps it) and `galnet_systems` (each candidate confirmed by `find_local`, else `Spansh.system_record`; meta `galnet_systems`, live-only), GET `/api/galnet` and `/api/galnet/systems?id=`. The page: view `galnet` (`GN`, `loadGalnet`, `galnetBodyHtml`, `galnetSystemsHtml`); nothing is asked until the tab opens. Tests: `tests/test_galnet.py` (made-up articles, a fake session); verify.sh points `URL` at a closed port |

In `ed_outrider.py`:

- Plot Route's Known column: `route_known_state` (visited, else Spansh's explored / partial / no bodies from
  `route_known`, the sphere or the cache); `route_known_check` asks Spansh in the background for the listed rows,
  `ROUTE_KNOWN_GAP_S` apart, only when `route_known_on`, which `run()` sets; the summary's `known_v` reloads the list;
  `hwyKnownHtml` in page.js.
- Auto honk's "then target": a confirmed auto honk calls `State.honk_then_target` (`[autohonk] target_next`,
  `target_delay`; `start_autotarget_run("next", countdown)`), set by `State.set_honk_target` (meta `autohonk_target`);
  `tests/test_honk_target.py` fakes both the honker and the target run.
- Discoverer names in the route lists: `Spansh.edsm_discoverer(name)` (EDSM's bodies: the main star's discoverer, else
  the earliest; "" nobody credited, None unknown system), `State.route_discoverer_check(rows)` beside
  `route_known_check` (only "visited" / "explored" / "partial" systems, `ROUTE_DISCOVERER_MAX` a pass,
  `ROUTE_DISCOVERER_GAP_S` apart; `route_discoverers`, memory only), the rows' `discoverer`, `hwyDiscovererHtml` in
  fork.js. Tests: `tests/test_discoverer.py`.
- The tablet's page groups: the fork's views are added to `TB.groups` on their own line below it in page.js.

Testing on Windows: run `bash scripts/verify.sh` from Git Bash. It uses `.venv/Scripts/python.exe` and stops the
server through a stop file (Ctrl-C to it; there is no SIGTERM), and the tests of file modes, symlinks and `tzset` are
skipped. A test's database in a temporary folder: `temp_dir(self)` (`tests/support.py`), which removes the folder
after the database is closed. Do not add a view to the smoke test's desktop "every view" loop: it shifts the page's
long poll into a later batch's fast-clock window and that batch fails with "not connected".

## Design notes

Beside upstream's ([DESIGN_NOTES.md](DESIGN_NOTES.md)):

- **The Ship view shows what the journal states, no more** (this fork, `outrider/shipinfo.py`): the Loadout's own
  figures, and for an engineered module the stats the game lists with their stock values. It carries no module
  database, so a stock module has no figures and there are no ship totals (shields, speed, power, damage): the
  EDSY and Coriolis links carry the same Loadout to tools that do. Inara's API has no ship or module data to read.
- **The Unscanned (bio) plotter guesses, and says so** (this fork, `outrider/biohunt.py`). A system with no scan data
  gives away only its name and place, so "likely to have life" rests on the name's mass code alone, with odds counted
  from the player's own scans (a starting guess until then); "unscanned" means Spansh has no body of it, which is
  likely but not certainly undiscovered, and a system Spansh has never heard of cannot be routed to at all. It asks
  Spansh once per hop (up to three times where space is thin), half a second apart.
- **GalNet News is this fork's** (`outrider/galnet.py`): one more read-only lookup, Frontier's own feed, asked only
  when the tab is opened. A system is marked in an article only once confirmed (yours, or Spansh's by exact name):
  a marked name is never a guess, but a system the article names without "system" or a catalogue form is missed.
- **The Commander view stores nothing** (this fork, `outrider/commander.py`). Everything is read from the journal files
  when a tab is opened, so it is only as complete as the journal: stored ships and modules as of the last shipyard
  or outfitting you opened, suit loadouts only once worn, a mission accepted before the journals kept by its name
  alone. Credits, ranks and statistics are as of the last login (the game writes them then); what a rank still
  takes is an estimate from the community's credit figures per rank (Frontier publishes none), and combat,
  mercenary, CQC and navy ranks show their percentage only. The blueprint table is a copy of community data (EDCD), not the game's own: a recipe Frontier changes is
  wrong here until the table is rebuilt. No voice lines: a mission about to expire is marked on the page only.
- **Discoverer names are EDSM's, and best effort.** Spansh has no discoverer; EDSM credits whoever first uploaded
  a body there, which is not always who the game credits. Asked only for listed systems somebody has been to,
  slowly (EDSM limits requests), and kept for this run only.

## Changelog

Newest first. Upstream's is [CHANGELOG.md](CHANGELOG.md).

## 2026-10-14 · This fork: Commander → Engineering names each engineer's system
- **Engineers' systems** in Commander → Engineering: every engineer (ship, and suit and weapon) with the system of
  their workshop, Copy and Plot route; the grade rows say where on hover (`commander.ENGINEER_SYSTEMS`,
  `engineer_list`). The journal never says where an engineer is: the table is the fork's, as the workshops stand.
- A **Distance** column: light years from where you are to each engineer's system (GET
  `/api/commander/engineer_distances`, `commander.engineer_distances`): each system's place found once, here
  (`find_local`) or from Spansh, and kept (meta `engineer_places`); asked again after a jump.

## 2026-10-14 · This fork: Rocky removed
- The Rocky personality is gone at the player's wish: his lines (`resources/speech.fork.json`, `outrider/speech_fork.py`),
  the "Rocky" wake word and the AI layer's Rocky persona (`outrider/ask.py` is upstream's again), and space chatter,
  which had his lines alone (`outrider/chatter.py`, `resources/chatter.json`, its part of `static/fork.js`).
  `outrider/speech.py` and `docs/guide/voice-and-alerts.md` are upstream's again. A browser that had only Rocky
  ticked speaks the plain wording until another personality is ticked.
- The speech file and its bans are read again when their size changes too, not only their time (`outrider/speech.py`
  `_stamp`): two writes in one timestamp tick, common on Windows, kept the old bans (upstream's
  `test_a_ban_leaves_a_plain_line` failed one run in three). Test: `tests/test_fork_fixes.py`.

## 2026-10-14 · This fork: upstream's tweak-update merged in; Rocky in a file of his own
- Upstream up to its 2026.10.23 release (the `tweak-update` branch): the crew, a voice per personality, Find a
  setting, 🎯 anywhere, the fuel-short and last-scoop warnings, the overlay's Alerts and Target panels with
  analysis-only and hide-when-docked, EDSM flight log import, Outrider as a service, and more.
- The overlay keeps the fork's Route panel beside upstream's Alerts panel (both in the new per-panel options).
- Upstream's own `navroute_ahead` (the Map's: nothing off the route) took the name: the fork's is `navroute_left`
  and reads `journals.game_route` like upstream's (none while the game owes NavRoute.json).
- Rocky moved to `resources/speech.fork.json` (`outrider/speech_fork.py`), merged in as the lines load, with twelve
  lines for each of upstream's four new alerts. `resources/speech.json` is upstream's again; the fork's Rocky test is
  `tests/test_speech_fork.py`.
- The fork's game-route tests are `tests/test_game_route.py` (upstream's own `tests/test_navroute.py` took the name).
- Windows skips for upstream's new Linux-only tests (the systemd service, bash launcher paths, `time.tzset`, Linux
  network-error numbers); the backups smoke check accepts `launch_outrider.bat`.

## 2026-10-13 · Space chatter, starting with Rocky
- With speech on and **Rocky** ticked, the co-pilot now says something of its own when it has been quiet: at a
  random moment between two times after the last line said (2 and 10 minutes unless you change them), so never
  sooner than the first and never silent longer than the second. Any line counts as the last one, an alert's too.
- Never with speech off, the game not running, the voice hushed, another window speaking, or a line waiting; such a
  time does not count as quiet, so the window starts when it ends. A line is not repeated until the others were said.
- **Space chatter** under Personality in the voice dialog: the switch (on unless you switch it off) and the two
  times, kept in this browser (not part of the settings export). 60 lines for Rocky in `resources/chatter.json`:
  another personality chatters once it has a list there.
- `outrider/chatter.py` (GET `/api/chatter`), the scheduler in `static/fork.js` (`chatterTick`).

## 2026-10-12 · Commander: inventory, engineering, missions, sessions; discoverer names in the route lists
- A **Commander** tab with five parts, all read from the journals when opened (`outrider/commander.py`,
  `outrider/jscan.py`; nothing stored): **CMDR** (ranks with the way to the next and, for trade, exploration and
  exobiology, about how many credits it still takes; credits, net worth, the fleet's value, stored modules, the
  carrier's balance; reputation, Powerplay, squadron; every ship; career figures), **Inventory** (ships, stored modules, ship locker, suit loadouts worn),
  **Engineering** (every ship-module blueprint against your materials: what a roll takes, how many rolls you can
  make, which engineers offer the grade and whether yours are unlocked far enough), **Missions** (those you hold,
  the soonest to expire first) and **Sessions** (combat and mining, login to logout, the last 30 days).
- `resources/blueprints.json`: 80 blueprints, built by `scripts/build_blueprints.py` from EDCD's coriolis-data and
  FDevIDs tables; materials are by the journal's names, so they meet your counts.
- The route lists (Plot Route's and the game's) name the **first discoverer** after the Known mark, from EDSM's
  record of the system's bodies (`Spansh.edsm_discoverer`, `State.route_discoverer_check`: only systems somebody
  has been to, 40 a pass, 2 s apart, this run only).
- The fork's page code starts its own file, `static/fork.js` (loaded before page.js; verify.sh checks its syntax).
- GET `/api/commander/profile`, `/inventory`, `/engineering`, `/missions`, `/sessions`; the route rows carry `discoverer`.

## 2026-10-12 · Overlay: the Route panel lists the Plot Route stops ahead
- With a Plot Route route followed, the panel showed its systems only as far as the game's own route went:
  once a stop is targeted (Target next, auto-target, auto honk's "then target") that is the one jump to the next
  stop, so the systems along the route were gone. The panel now lists the stops after the next from the route
  itself (⚡ neutron, ⛽ refuel, the hop's length, known or not): as many as the game's jumps leave room for of
  six, three at least, the rest counted.
- `State.highway_ahead`, `overlay.route_panel`'s `stops` (`HIGHWAY_STOPS_MIN`).

## 2026-10-12 · This fork: its notes in one file, remotes renamed
- The fork's changelog, code map, design notes and settings moved out of upstream's documents into `docs/FORK.md`;
  `CHANGELOG.md`, `AGENT_GUIDE.md`, `DESIGN_NOTES.md` and `guide/settings.md` are upstream's again, word for word
  (the changelog conflicted at every merge: both sides write at its top).
- `scripts/merge-upstream.sh`: fetch, merge, verify. The remotes are now `origin` (the fork) and `upstream`.
- The tablet's page groups get the fork's views on their own line, not inside upstream's.

## 2026-10-12 · This fork: upstream merged in; upstream's Inara upload replaces the fork's
- Upstream's work up to its 2026-10-22 release is merged in (boxels, green gas giants, codex marks on body types,
  rare discoveries said once, the voice lab in the page, the Vorlon and Shadow themes and more), beside the fork's
  Ship view, Unscanned (bio) plotter, GalNet News, game route, Rocky, the overlay's Route panel and auto honk's
  "then target the next route system".
- Upstream now uploads to Inara itself (Settings → Uploads, a key per commander), so the fork's own Inara upload is
  gone, as planned: `[inara] enabled` is now the Uploads switch, and an `[inara] api_key` in the config file is no
  longer read: give the key again in Settings → Uploads.
## 2026-10-11 · This fork: auto honk can then target the next route system
- **Then target the next route system, N s after the honk** in ⚙ Settings → Auto honk (off by default; `[autohonk]
  target_next`, `target_delay`, 0 to 60 s, 3 by default). After an auto honk the journal confirms with its discovery
  scan, the next system of the route you follow in Plot Route is targeted that many seconds later, by the same run as
  Target next: it needs the keys auto-target needs, waits out a dangerous arrival, and clearing the route stops it.
- Only after a honk auto honk pressed and saw answered: not after your own honk, a skipped system or a missed one.
  With no route followed nothing happens and nothing is said; another refusal (a missing key binding, say) is shown
  beside the switch as "last time: ...". Switching it off stops a run that is counting down.
- `State.honk_then_target`, `State.set_honk_target` (meta `autohonk_target`); POST `/api/autohonk` takes
  `target_next` and `target_delay`, alone or with `enabled`; `autohonk_info` carries them and `target_note`.

## 2026-10-12 · This fork: the Unscanned (bio) plotter can favour one species
- **Favour** in the plot form (any life, or any species the rules know, the most valuable first): with a species
  chosen, the odds by mass code come from where players reported it. Spansh is asked for the 500 nearest bodies with
  that species on record and for the scanned systems around you; a mass code's weight is how much commoner it is
  among the systems with the species than among scanned systems at large (blended towards "no lean", so a handful of
  reports cannot swing it; a code with nothing known near you is left neutral). The route's line shows the lifts and
  how many reports they rest on.
- For Stratum Tectonicas the reports checked from two places both favoured mass code c, then b and d, and all but
  ruled out a. Too few reports near you (under 20 systems) or no answer from Spansh: the any-life odds, and the line
  says why. It says which kind of system to prefer, not that a system has the species: that cannot be known unscanned.
- `outrider.biohunt.species_lean`, `State.species_lean`; POST `/api/highway/plot` takes `species`; `/api/highway`
  carries `bio_species` for the list.

## 2026-10-12 · Plot Route: the map keeps its space with the game's route shown
- With **Game route** chosen in a window-filling layout, its list and its switch had no place in Plot Route's grid:
  they took cells of their own and squeezed the map. The list now sits in the Highway list's cell and the switch
  above the grid, so the map fills the right as with any other route.

## 2026-10-12 · This fork: Unscanned (bio), a plotter for systems nobody has scanned
- A sixth plotter in Plot Route: a chain of systems Spansh knows by name and place only (no body reported: nobody
  with an uploader has scanned anything there, so they are likely undiscovered), each hop as close to your jump range
  as there is such a system. From where you are (or From), for as many systems as you ask (20; up to 100), outward
  so it neither circles nor doubles back, or towards the system in To. A system you have been to is never picked.
- **Likely to have life** is judged by the one thing known of an unscanned system: its name's mass code (the letter
  before the last number, a to h: the heaviest star's mass class). The share of systems of each code that had a
  biological signal is counted from your own journals and blended with a starting guess until you have enough of
  your own; among the systems within a jump, odds times how much of the range the hop uses decides. The route's line
  says the odds it used. A guess about where to look, not a promise.
- With nothing unscanned within one jump it looks two, then four jump ranges out, and says how many jumps that hop
  takes. The route is a Highway route: followed, spoken ("Next unscanned system: ..."), targeted and drawn like one.
- `outrider/biohunt.py`, `Spansh.unscanned_near`, `State.unscanned_start_plot` (POST `/api/highway/plot` with
  `plotter: "unscanned"`, `range`, `stops`, an optional `to`).

## 2026-10-12 · This fork: a Rocky personality for the voice
- A fourth personality, **Rocky (Project Hail Mary)**: twelve lines for every alert in his way of talking (short plain
  sentences, no articles or contractions, a word three times for emphasis, questions ending ", question?", "Amaze!").
  Tick it in the alerts dialog's personalities, alone to hear only him; `[defaults] speech_styles = ["rocky"]` starts
  new browsers with it. No swearing versions.
- The assistant answers to "Rocky" as to "Vespa". With the AI layer on and Rocky the server's only default
  personality, its answers are worded his way too (`ask.system_prompt`); the facts still come from the tools.
- His voice is the Piper voice you chose: no voice imitates the character's own.

## 2026-10-12 · This fork: a Route panel for the in-game overlay
- A seventh overlay panel, optional (`[overlay] route_panel`, off by default; Settings → In-game overlay): the route
  ahead. The game's own route: jumps and light years left, how many jumps to the next scoopable star (or that there
  is none, and a long stretch without one), then the next six jumps with each star (⛽ scoopable in green), the jump,
  and ✓ you have been there / ● reported / ○ not reported to Spansh. Under it, a Highway route's next stop with jumps
  and light years left and the refuel coming up. It shows wherever you are while there is a route, and starts at the
  top right under the body panel; placed, sized and themed like the others (`outrider.overlay.route_panel`).

## 2026-10-12 · Ship: the rows' lines meet across the columns
- A module's Engineered stats cell was laid out as a flex box, so it stopped being a table cell and its line under
  the row sat higher than the Engineering column's. The stats now wrap inside a block of their own within the cell.

## 2026-10-12 · This fork: the game's own route moves into Plot Route, as a list and on the map
- While the game has a route plotted, Plot Route offers **Game route · N jumps** beside **Plotted here**. Chosen (per
  device), the tab shows the game's route in place of the routes plotted here: the heading, the list (each system,
  click to copy; the Known column; the star and whether it is scoopable; the jump and the light years flown) and the
  same map, from where you are.
- The Game Route tab is gone (a device that had it open lands on Plot Route), and with it the projected fuel and the
  places to refuel: `GET /api/navroute/refuel` is removed, `/api/navroute` gives the route only. Nothing of the
  game's route is followed, targeted or copied: the game already has it in its own computer.

## 2026-10-12 · This fork: Ship, the ship you fly with its modules and engineering
- A **Ship** tab (and tablet page): the ship's own figures (jump range, mass, cargo, fuel, hull, values, rebuy) and
  every module by group (hardpoints, utility mounts, core and optional internals) with its class and rating, mount,
  power priority, health and engineering: the blueprint and grade, the experimental effect, and each engineered stat
  with its value and the change from stock, green when for the better.
- From the journal's own Loadout, read when the tab opens (Inara's API has no ship data to read). What the journal
  does not state (a stock module's figures, shields, speed, power) is one click away: **open this ship in EDSY** /
  **Coriolis** carries the same Loadout to them.
- `outrider/shipinfo.py`, `GET /api/ship`.
## 2026-10-11 · This fork: Game Route, the game's own route as a list with its fuel
- A **Game Route** tab (and tablet page) lists the route plotted in the game's galaxy map jump by jump: the system
  (click to copy), the Known column of Plot Route's list, the star and whether it is scoopable, the jump and the
  light years flown by then.
- **Projected fuel:** what each jump burns and leaves, from the fuel aboard now with your ship's fuel model (each
  jump at the mass it is made at), without refuelling. It says whether the tank lasts the route, or after which jump
  it runs dry and how many scoopable stars come before then; the rows past that point are greyed.
- **Where to refuel:** when it would run dry, the stations your ship can land at and the fleet carriers that sell
  fuel nearest the last system the tank reaches (Spansh's station search, as the Nearest finder; your own carrier
  too), each with the route system it is closest to.
- `outrider/navroute.py`, `GET /api/navroute` and `/api/navroute/refuel`.

## 2026-10-11 · This fork: GalNet News, with the systems an article mentions
- A **GalNet** tab (and tablet page): the game's latest news article from Frontier's own feed, with the 30 latest
  listed beside it to pick from; Refresh asks again (the server keeps its copy half an hour, and the last one when
  the feed cannot be read).
- Star systems an article mentions are marked in its text: click one to copy its name, or use Copy / Plot route in
  the line under the title (Plot Route opens with it as the destination). A name is marked only once confirmed: a
  system you know, or one Spansh knows by exactly that name. Found by the words before "system" and by catalogue
  and sector names, so a system named with neither is not marked.
- `outrider/galnet.py`, `GET /api/galnet` and `/api/galnet/systems`; nothing is asked until the tab is opened.
## 2026-10-10 · Sell / Buy: a fleet carrier's name in the results
- A fleet carrier in the Sell / Buy lookup shows its own name with the callsign beside it ("Deep Space Relay (carrier
  G0B-W2J)"), from Spansh's `carrier_name`; a carrier Spansh has no name for shows its callsign as before.

## 2026-10-10 · This fork: an Inara upload (off by default); upstream's EDDN and EDSM uploads adopted
- Upstream now has its own EDDN and EDSM uploads (Settings → Uploads), which replace the ones this fork had built
  (`outrider/uplink.py`, `[uploads]`: both gone). What they did not cover is kept: `[inara]` (`enabled`, `api_key`)
  sends your travel, credits, ranks, reputation, ships, materials, missions and combat log to your Inara account,
  live play only, in batches. Off until switched on (Server settings → Inara upload; at the next start); never with
  --simulate, and not while EDMarketConnector on this PC sends to Inara itself.

## 2026-10-07 · Plot Route: a Known column in the route list
- The Highway's list says whether each system is already discovered: ✓ you have been there (your journal), ● every
  body reported to Spansh, ◐ some reported, ○ nobody has reported a body (it may be undiscovered); blank until
  looked up. Spansh is asked in the background for the listed systems only (the next 200), one a second, while the
  tab is open; a failed lookup pauses it for a minute. Kept in memory: asked again after a restart.

## 2026-10-07 · `scripts/verify.sh` passes on Windows (Git Bash)
- `verify.sh` finds a Windows venv (`.venv/Scripts/python.exe`), names its scratch folder the Windows way so the
  scratch config's paths mean something to Python, and stops the server through a stop file (Ctrl-C to the server:
  Windows has no SIGTERM to send).
- Fixed on Windows: all-time views asking for a date before 1970 (`iso_ts` reads it as 1970), `--help` and the log on a
  piped or redirected stdout (cp1252), a port in use reported as "forbidden" rather than "already in use", and two
  downloads of one voice at once failing with "Access is denied" (the move into place is tried again).
- Tests no longer assume Linux: absolute paths, TOML paths, the clipboard tools and key wording are pinned or asked of
  the platform, a database in a temporary folder is closed before the folder goes (`support.temp_dir`), and tests of
  file modes, symlinks and `tzset` are skipped where the system has none.

## 2026-10-07 · Refuel at every fuel star: a tick in Plot Route
- The exact plotter's options have **refuel at every fuel star** (off by default, remembered per browser): ticked,
  Spansh plans a top-up at every scoopable star (`refuel_every_scoopable`); left empty, only where the tank needs it,
  as since the entry below. The route's header says when it was plotted that way.

## 2026-10-07 · Exact plotter: no refuel at every scoopable star
- The exact plotter asks Spansh with `refuel_every_scoopable` off, so a route refuels only where the tank needs it
  rather than stopping to top up at every fuel star.

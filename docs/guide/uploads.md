[ED Outrider](../../README.md) · [Install and run](install.md) · [The views](views.md) · [Plot Route](plot-route.md) · [Cargo and trading](cargo-and-trading.md) · [Voice and alerts](voice-and-alerts.md) · [Automation](automation.md) · [On a tablet](tablet.md) · **Uploads** · [Settings and good to know](settings.md) · [For the curious](for-developers.md)

# Uploads: EDDN and EDSM

Outrider can send what your journals say to two community services, as EDMC does, so you need not run EDMC just to
upload. **Both are off unless you switch them on**, in Settings → Uploads: the switch applies at once and is kept in
the config file (`[eddn] enabled`, `[edsm] enabled`) for the next start. That is the only place to switch them: they
are not among the Server settings.

- **EDDN**, the Elite Dangerous Data Network: systems, scans, signals, codex entries, markets, sent as they happen.
  Spansh, EDSM, Inara and others read it. EDDN gets your commander name, hashed by EDDN itself; personal details
  (fines, fuel, your position on a planet) are taken out before anything is sent.
- **EDSM**, the Elite Dangerous Star Map: your flight log, scans, materials, ship and cargo, to your own EDSM account,
  in batches: each jump or docking sends what waited, and nothing waits more than five minutes. EDSM says which
  events it does not want, and those are not sent. It needs your EDSM commander name and API key
  ([edsm.net → Settings → API key](https://www.edsm.net/en/settings/api)), per in-game commander, set in Settings →
  Uploads. The key stays on this Outrider: the page never shows it again. A commander with no key sends nothing
  (Settings says so); a key EDSM refuses stops EDSM until you change it.

## Catching up, and what is never sent

Each upload remembers how far through your journals it has got. If Outrider was not running while you played (or
the server was down), the next start sends what you played meanwhile, up to a week back; anything older is skipped.
A journal re-read or a restore sends nothing twice, and switching an upload on starts from that moment: your history
is never uploaded. What cannot be caught up: markets, outfitting, shipyards and plotted routes come from files the
game rewrites each time, so for those Outrider sends only what it saw while running; a late codex entry has no body
name (that comes from the live Status.json).

- Anything older than a week, or from a legacy folder (journals imported once).
- Anything from the game's beta, or from the Legacy game (3.8): Settings says so ("unavailable: the Legacy game").
- Anything while you are crew in another commander's ship.
- Anything under `--simulate`.

## One uploader at a time

Two Outriders reading the same journals (the game PC's and a server's), or Outrider and EDMC, would send everything
twice: EDDN has no way to tell. So:

- Each uploading Outrider leaves a small note in your journal folder (`.outrider/uploads-<id>.json`, rewritten every
  minute). Another Outrider that sees a fresh note will not start the same upload ("Already uploading from erangel");
  if both started at once, both hold and say so until you switch one off. A note left by a crash goes stale after
  five minutes. When an Outrider stops, its note stays with how far it got: switch the upload on in another one and it
  starts there, with nothing missed and nothing sent twice.
- Catching up cannot know who else uploaded while it was down: if EDMC (or a read-only Outrider, which leaves no note)
  sent that time, it is sent again. Keep one uploader.
- An Outrider that cannot write in the journal folder (a read-only share) can still read the others' notes. If
  another one already uploads, it refuses ("Filesystem is read-only and another instance is set for upload");
  otherwise it asks first: "Is this the only Outrider uploading? Other instances can't see this one".
- **In Docker** the journals are mounted read-only. To give the server its note folder, create it on the share
  (`mkdir -p "$JOURNALS/.outrider"`, as the share's owner) and uncomment the `.outrider` line in `docker-compose.yml`.
  If the share itself is read-only on the server (an `ro` export or mount), leave that line commented: Docker cannot
  create the folder there and the container would not start. Outrider then works as a read-only instance: it sees
  the game PC's note, but the game PC cannot see its own, so if the server uploads, keep the game PC's uploads off
  yourself (that is what the "only Outrider" question is about).
- **EDMC on the same PC:** if it runs with its own EDDN or EDSM upload on, Outrider holds that upload and says so.
  Switch EDMC's off (its File → Settings → EDDN / EDSM tabs) before switching Outrider's on. EDMC on another computer
  cannot be seen: switch it off there yourself.

## Status

Settings → Uploads shows, per service: on or off, what is waiting, what was sent and refused in the last day, and why
nothing can be sent now (held by another uploader, a key EDSM refused, the beta or Legacy game).

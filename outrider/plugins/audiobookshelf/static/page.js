// Audiobookshelf's mini player (outrider/plugins/audiobookshelf/plugin.py): the book plays in the page you press ▶ in,
// its audio passed through Outrider; the position is synced back every SYNC_MS and at each pause. Outrider's own
// lines duck it (or pause it) while they are said; voice commands and the long-route watcher reach it as "command"
// events, acted on by the page playing (or, with none, the one that played last in this browser).
(() => {
  const O = window.Outrider;
  if (!O) return;
  const BASE = "api/plugins/audiobookshelf/", SYNC_MS = 15000, SKIP = 30;
  const rel = p => String(p || "").replace(/^\/+/, "");
  const store = {
    get(k, d) { try { const v = localStorage.getItem("abs." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("abs." + k, JSON.stringify(v)); } catch {} },
  };
  const ME = (() => { try { return sessionStorage.getItem("abs.me") || (sessionStorage.setItem("abs.me", Math.random().toString(36).slice(2, 10)), sessionStorage.getItem("abs.me")); } catch { return Math.random().toString(36).slice(2, 10); } })();

  const audio = new Audio();
  audio.preload = "auto";
  let book = null, track = 0, cfg = {}, ducked = null, lastSync = 0, listened = 0, tickAt = 0, picking = false;
  let volume = store.get("volume", 1);

  const box = document.createElement("div");
  box.id = "absPlayer";
  box.hidden = true;
  box.innerHTML = `<button class="absMin" title="Show / hide the player" aria-label="Show or hide the audiobook player">📖</button>
    <div class="absBody"><img class="absCover" alt=""><div class="absText"><div class="absTitle"></div><div class="absBy"></div>
    <div class="absCh"></div><div class="absBar"><div></div></div><div class="absTime"></div></div>
    <div class="absCtl"><button data-do="prev" title="Previous chapter">⏮</button><button data-do="back" title="Back ${SKIP} s">⟲</button>
    <button data-do="toggle" class="absPlay" title="Play / pause">▶</button><button data-do="forward" title="On ${SKIP} s">⟳</button>
    <button data-do="next" title="Next chapter">⏭</button><button data-do="pick" title="Pick a book">📚</button>
    <input type="range" class="absVol" min="0" max="1" step="0.05" title="Volume" aria-label="Audiobook volume"></div>
    <div class="absPick" hidden></div><div class="absErr"></div></div>`;
  document.body.appendChild(box);
  const $ = s => box.querySelector(s);
  box.classList.toggle("absCollapsed", !!store.get("collapsed", false));
  $(".absVol").value = volume;
  for (const img of [$(".absCover")]) {   // a cover that fails (none on the server) is not a broken picture
    img.addEventListener("error", () => img.classList.add("absNone"));
    img.addEventListener("load", () => img.classList.remove("absNone"));
  }

  const pos = () => book ? (book.tracks[track] ? book.tracks[track].start : 0) + (audio.currentTime || 0) : 0;
  const clock = s => { s = Math.max(0, Math.floor(s)); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
  const chapterAt = t => { const cs = (book && book.chapters) || []; let i = cs.findIndex(c => t >= c.start && t < c.end);
    if (i < 0 && cs.length && t >= cs[cs.length - 1].end) i = cs.length - 1; return i; };
  const applyVolume = () => { audio.volume = Math.max(0, Math.min(1, volume * (ducked === "duck" ? (cfg.duck_volume ?? 0.25) : 1))); };

  function seek(t) {
    if (!book || !book.tracks.length) return;
    t = Math.max(0, Math.min(t, book.duration || t));
    let i = book.tracks.findIndex(x => t >= x.start && t < x.start + x.duration);
    if (i < 0) i = book.tracks.length - 1;
    const playing = !audio.paused;
    if (i !== track || !audio.src) {
      track = i;
      audio.src = `${BASE}stream/${i}?s=${encodeURIComponent(book.session)}`;
    }
    const off = t - book.tracks[i].start;
    const go = () => { audio.currentTime = off; if (playing) audio.play().catch(() => {}); };
    if (audio.readyState >= 1) go(); else audio.addEventListener("loadedmetadata", go, {once: true});
  }

  function load(now) {
    if (!now) return;
    const same = book && book.session === now.session;
    book = now;
    if (!same) { track = -1; audio.removeAttribute("src"); seek(now.position || 0); }
    draw();
  }

  async function sync(force) {
    if (!book) return;
    const t = Date.now();
    if (!force && t - lastSync < SYNC_MS) return;
    lastSync = t;
    const got = await O.api(BASE + "sync", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({position: pos(), listened: Math.round(listened), playing: !audio.paused, player: ME})});
    listened = 0;
    if (got && got.error) $(".absErr").textContent = got.error;
  }

  async function play() {
    store.set("here", true);
    if (!book) {
      const got = await O.api(BASE + "play", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({player: ME})});
      if (!got || got.error) { O.toast(`Audiobookshelf: ${(got && got.error) || "no answer"}`); return; }
      load(got.now);
    }
    applyVolume();
    try { await audio.play(); } catch (e) { O.toast("Press ▶ on the audiobook player once: this browser wants a click before it plays sound"); }
    sync(true);
  }
  function pause() { audio.pause(); sync(true); }

  function act(what) {
    const t = pos(), i = chapterAt(t), cs = (book && book.chapters) || [];
    if (what === "play") return play();
    if (what === "pause") return pause();
    if (what === "toggle") return audio.paused ? play() : pause();
    if (!book) return;
    if (what === "back") seek(t - SKIP);
    else if (what === "forward") seek(t + SKIP);
    else if (what === "next" && i + 1 < cs.length) seek(cs[i + 1].start);
    else if (what === "prev" && i >= 0) seek(t - cs[i].start > 5 || i === 0 ? cs[i].start : cs[i - 1].start);
    setTimeout(() => sync(true), 500);
  }

  async function pick() {
    const list = $(".absPick");
    if (picking) { picking = false; list.hidden = true; return; }
    picking = true;
    list.hidden = false;
    list.textContent = "…";
    const got = await O.api(BASE + "library");
    if (!got || got.error) { list.textContent = (got && got.error) || "no answer"; return; }
    list.innerHTML = (got.books || []).map(b => `<button data-item="${O.esc(b.item)}"><img src="${O.esc(rel(b.cover))}?w=80" alt="">` +
      `<span>${O.esc(b.title)}<small>${O.esc(b.author || "")}</small></span></button>`).join("") || "Nothing in progress on Audiobookshelf";
  }

  box.addEventListener("click", async e => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.classList.contains("absMin")) { box.classList.toggle("absCollapsed"); store.set("collapsed", box.classList.contains("absCollapsed")); return; }
    if (b.dataset.item) {
      picking = false; $(".absPick").hidden = true;
      audio.pause();
      const got = await O.api(BASE + "play", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({item: b.dataset.item, player: ME})});
      if (!got || got.error) { O.toast(`Audiobookshelf: ${(got && got.error) || "no answer"}`); return; }
      book = null; load(got.now);
      play();
      return;
    }
    if (b.dataset.do === "pick") return pick();
    if (b.dataset.do) act(b.dataset.do);
  });
  $(".absVol").addEventListener("input", e => { volume = +e.target.value; store.set("volume", volume); applyVolume(); });

  audio.addEventListener("ended", () => {
    if (book && track + 1 < book.tracks.length) { track += 1; audio.src = `${BASE}stream/${track}?s=${encodeURIComponent(book.session)}`; audio.play().catch(() => {}); }
    else sync(true);
  });
  audio.addEventListener("play", draw);
  audio.addEventListener("pause", draw);
  audio.addEventListener("timeupdate", () => {
    const t = Date.now();
    if (!audio.paused && tickAt) listened += Math.min(5, (t - tickAt) / 1000);
    tickAt = t;
    if (!audio.paused) sync(false);
    draw();
  });

  function draw() {
    if (!book) { $(".absTitle").textContent = "Audiobookshelf"; $(".absBy").textContent = "▶ for the book you listened to last, 📚 to pick one"; return; }
    const t = pos(), i = chapterAt(t), ch = i >= 0 ? book.chapters[i] : null;
    const img = $(".absCover"), src = rel(book.cover) + "?w=200";
    if (img.getAttribute("src") !== src) img.setAttribute("src", src);
    $(".absTitle").textContent = book.title;
    $(".absBy").textContent = [book.author, book.narrator ? `read by ${book.narrator}` : ""].filter(Boolean).join(" · ");
    $(".absCh").textContent = ch ? `${i + 1}/${book.chapters.length} · ${ch.title}` : (book.series || "");
    $(".absBar > div").style.width = `${book.duration ? Math.min(100, 100 * t / book.duration) : 0}%`;
    $(".absTime").textContent = `${clock(t)} / ${clock(book.duration)}`;
    $(".absPlay").textContent = audio.paused ? "▶" : "⏸";
    box.classList.toggle("absPlaying", !audio.paused);
  }

  O.on("data", d => {
    const part = d && d.plugins && d.plugins.audiobookshelf;
    if (!part) return;
    const p = part.data || {};
    cfg = p;
    box.hidden = !p.configured;
    $(".absErr").textContent = p.error || "";
    // another page started a book: shown here, not played (it plays where ▶ was pressed)
    if (p.now && audio.paused && (!book || book.session !== p.now.session)) load(p.now);
    draw();
  });
  O.on("plugin:audiobookshelf", ev => {
    if (ev.kind !== "command") return;
    const d = ev.data || {}, mine = d.player ? d.player === ME : store.get("here", false);
    if (mine) { if (d.why) O.toast(`Audiobook: ${d.do === "play" ? "playing" : "paused"}: ${d.why}`); act(d.do); }
  });
  O.on("speech", s => {
    const mode = cfg.duck || "duck";
    if (mode === "off") return;
    if (s.state === "start" && !audio.paused && !ducked) {
      ducked = mode;
      if (mode === "pause") audio.pause(); else applyVolume();
    } else if (s.state === "end" && !s.more && ducked) {
      const was = ducked; ducked = null;
      if (was === "pause") audio.play().catch(() => {}); else applyVolume();
    }
  });
  addEventListener("pagehide", () => { if (book && !audio.paused) navigator.sendBeacon && navigator.sendBeacon(BASE + "sync",
    new Blob([JSON.stringify({position: pos(), listened: Math.round(listened), playing: false, player: ME})], {type: "application/json"})); });
})();

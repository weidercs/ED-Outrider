"""Audiobookshelf: your audiobooks in Outrider, from your own Audiobookshelf server.

Audiobookshelf's apps cannot be remote-controlled, so Outrider plays the book itself, in a page (the one you press ▶
in): the audio comes through Outrider (the API token never leaves it), and where you are is synced back to
Audiobookshelf, so the phone app carries on from there. The page's mini player shows the cover, the chapter and the
controls; Outrider's own lines duck the book (or pause it) while they are said; "pause the book", "resume the book",
"next chapter" and "what am I listening to" are answered by voice; on a long plotted route the book can start by
itself as you jump, and stop when you arrive; the in-game overlay's Plugins panel shows the cover and the chapter.

[plugins.audiobookshelf]
url = "http://abs.lan:13378"   # your Audiobookshelf server
token = "..."                  # an API token: Audiobookshelf -> Settings -> Users -> your user -> API token
duck = "duck"                  # while Outrider speaks: "duck" (quieter), "pause", or "off"
duck_volume = 0.25             # the book's volume while ducked (0 to 1)
long_route_jumps = 0           # start the book on a plotted route of at least this many jumps (0: never)
pause_on_arrival = true        # and pause it when that route ends
overlay = true                 # the cover and chapter in the overlay's Plugins panel while it plays
"""
import asyncio
import json
import re
import sys
import time

from aiohttp import ClientError, ClientSession, ClientTimeout, web

TITLE = "Audiobookshelf"
DESCRIPTION = "Your audiobooks from your Audiobookshelf server: a mini player, ducking, voice and long-route listening."

DEFAULTS = {"url": "", "token": "", "duck": "duck", "duck_volume": 0.25, "long_route_jumps": 0,
            "pause_on_arrival": True, "overlay": True}
DUCK = ("duck", "pause", "off")
ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
URL = re.compile(r"^https?://[^\s/?#]+(:\d+)?(/[^\s?#]*)?$")
TIMEOUT = ClientTimeout(total=15)
STREAM_TIMEOUT = ClientTimeout(total=None, sock_connect=10, sock_read=60)
SHOWN_AFTER_PAUSE = 30     # s: the overlay part stays this long after the book is paused
LONG_ROUTE_CHECK_S = 3     # s: how often the long-route watcher looks
RATE_MIN, RATE_MAX = 0.5, 3.0   # the page's playback speed, as the server counts it on between syncs
MIME = ["audio/flac", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/aac", "audio/webm", "audio/x-m4a"]

PHRASES = {
    "pause": ("pause the book", "pause the audiobook", "pause audiobook", "stop the book", "stop the audiobook",
              "pause my book"),
    "play": ("resume the book", "resume the audiobook", "resume audiobook", "play the audiobook", "play audiobook",
             "play the book", "continue the book", "play my book", "resume my book"),
    "next": ("next chapter", "skip chapter", "skip the chapter"),
    "prev": ("previous chapter", "last chapter", "chapter back"),
    "back": ("rewind the book", "rewind the audiobook", "go back thirty seconds", "back thirty seconds"),
    "what": ("what am i listening to", "what book is this", "what's playing", "what is playing", "which book is this"),
}


def _warn(msg):
    print(f"[plugins.audiobookshelf] {msg}", file=sys.stderr)


def settings(table):
    """[plugins.audiobookshelf] checked: a bad value said on stderr and the default kept."""
    out = dict(DEFAULTS)
    url = table.get("url", "")
    if isinstance(url, str) and (not url.strip() or URL.fullmatch(url.strip())):
        out["url"] = url.strip().rstrip("/")
    else:
        _warn(f"url = {url!r} must be http(s)://host[:port]")
    tok = table.get("token", "")
    if isinstance(tok, str):
        out["token"] = tok.strip()
    else:
        _warn("token must be text")
    duck = table.get("duck", out["duck"])
    if duck in DUCK:
        out["duck"] = duck
    else:
        _warn(f"duck = {duck!r} must be one of {', '.join(DUCK)}")
    for key, lo, hi, kind in (("duck_volume", 0.0, 1.0, float), ("long_route_jumps", 0, 500, int)):
        v = table.get(key, out[key])
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = kind(min(hi, max(lo, v)))
        else:
            _warn(f"{key} = {v!r} must be a number")
    for key in ("pause_on_arrival", "overlay"):
        v = table.get(key, out[key])
        if isinstance(v, bool):
            out[key] = v
        else:
            _warn(f"{key} = {v!r} must be true or false")
    for key in table:
        if key not in DEFAULTS:
            _warn(f"unknown setting {key!r}")
    return out


def clock(seconds):
    """3725 -> '1 h 2 m', 125 -> '2 m', 20 -> '20 s'."""
    s = max(0, int(seconds or 0))
    h, m = divmod(s // 60, 60)
    return f"{h} h {m} m" if h else f"{m} m" if m else f"{s} s"


def said_clock(seconds):
    """3725 -> '1 hour 2 minutes', 60 -> '1 minute': clock() for speech."""
    s = max(0, int(seconds or 0))
    h, m = divmod(s // 60, 60)
    unit = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")
    return " ".join(x for x in (unit(h, "hour") if h else "", unit(m, "minute") if m or not h else "") if x)


def chapter_at(chapters, t):
    """(index, chapter) of the chapter at `t` seconds, or (None, None)."""
    for i, c in enumerate(chapters or []):
        if c.get("start", 0) <= t < c.get("end", 0):
            return i, c
    return (len(chapters) - 1, chapters[-1]) if chapters and t >= chapters[-1].get("end", 0) else (None, None)


def names(xs):
    return ", ".join(x.get("name", "") if isinstance(x, dict) else str(x) for x in xs or [] if x)


def session_view(s):
    """What the page and the overlay need of an Audiobookshelf playback session (no URL that carries the token)."""
    meta = s.get("mediaMetadata") or {}
    series = (meta.get("series") or [None])[0]
    series = (f"{series.get('name')} #{series['sequence']}" if series.get("sequence") else series.get("name")) \
        if isinstance(series, dict) else None
    return {"session": s.get("id"), "item": s.get("libraryItemId"),
            "title": s.get("displayTitle") or meta.get("title") or "an audiobook",
            "author": s.get("displayAuthor") or meta.get("authorName") or names(meta.get("authors")),
            "narrator": meta.get("narratorName") or names(meta.get("narrators")), "series": series,
            "duration": float(s.get("duration") or 0), "position": float(s.get("currentTime") or 0),
            "chapters": [{"title": c.get("title") or f"Chapter {i + 1}", "start": float(c.get("start") or 0),
                          "end": float(c.get("end") or 0)} for i, c in enumerate(s.get("chapters") or [])],
            "tracks": [{"index": i, "start": float(t.get("startOffset") or 0), "duration": float(t.get("duration") or 0),
                        "mime": t.get("mimeType") or ""} for i, t in enumerate(s.get("audioTracks") or [])],
            "cover": f"/api/plugins/audiobookshelf/cover/{s.get('libraryItemId')}"}


def long_route_step(mem, remaining, jumping, playing, cfg, now):
    """The long-route watcher's one look: "play" while jumping on a plotted route of at least long_route_jumps jumps
    with the book not playing (once per route: paused by hand, it stays paused); "pause" when that route ended (nothing left, or under 2 jumps
    left and not jumping any more) and it was the watcher that started it. `mem` is kept between looks."""
    need = cfg.get("long_route_jumps") or 0
    if not need:
        return None
    if jumping and remaining and remaining >= need and not mem.get("started") and not playing:
        mem.update(started=True, at=now)
        return "play"
    if mem.get("started") and not jumping and (not remaining or remaining <= 1) and now - mem.get("at", now) > 20:
        mem.clear()
        return "pause" if cfg.get("pause_on_arrival") and playing else None
    return None


class Books:
    """The plugin's server side: the Audiobookshelf client, the session playing and what the pages are told."""

    def __init__(self, host):
        self.host, self.cfg = host, host.settings
        self.now = None          # session_view of the book loaded, with "playing" and "updated"
        self.error = None        # the last thing that went wrong, in words
        self.player = None       # the page playing it (its own random id)
        self._http = None
        self._track_urls = []    # the session's tracks' paths on Audiobookshelf (never sent to a page)
        self.route = {}

    @property
    def configured(self):
        return bool(self.cfg["url"] and self.cfg["token"])

    def http(self):
        if self._http is None or self._http.closed:
            self._http = ClientSession(headers={"Authorization": f"Bearer {self.cfg['token']}"})
        return self._http

    async def call(self, method, path, body=None):
        """JSON from Audiobookshelf; an error in words (RuntimeError) when it could not."""
        if not self.configured:
            raise RuntimeError("set url and token in [plugins.audiobookshelf]")
        try:
            async with self.http().request(method, self.cfg["url"] + path, json=body, timeout=TIMEOUT) as r:
                if r.status == 401 or r.status == 403:
                    raise RuntimeError("Audiobookshelf refused the API token")
                if r.status >= 400:
                    raise RuntimeError(f"Audiobookshelf answered HTTP {r.status} to {path.split('?')[0]}")
                text = await r.text()
        except (OSError, ClientError, asyncio.TimeoutError) as e:   # ClientError: a dropped connection, a bad answer
            raise RuntimeError(f"cannot reach Audiobookshelf at {self.cfg['url']} ({type(e).__name__})") from None
        try:   # some answers are plain text (sync and close say "OK")
            got = json.loads(text) if text.strip() else {}
        except ValueError:
            return {}
        return got if isinstance(got, dict) else {}

    # ---- what the page and the tools read ----

    def payload(self):
        return {"configured": self.configured, "error": self.error, "now": self.now, "player": self.player,
                "duck": self.cfg["duck"], "duck_volume": self.cfg["duck_volume"]}

    def position(self, now=None):
        """Where the book is now: the last synced position, moved on by the time since (at the page's speed) while it plays."""
        n = self.now or {}
        t = n.get("position", 0)
        if n.get("playing"):
            t += ((now or time.time()) - n.get("updated", now or time.time())) * n.get("rate", 1.0)
        return min(t, n.get("duration") or t)

    def brief(self, now=None):
        if not self.now:
            return None
        t, rate = self.position(now), self.now.get("rate", 1.0)
        i, ch = chapter_at(self.now["chapters"], t)
        left = max(0.0, self.now["duration"] - t) / rate   # listening time, at the page's speed
        return {"title": self.now["title"], "author": self.now["author"], "narrator": self.now["narrator"],
                "series": self.now["series"], "playing": bool(self.now.get("playing")), "rate": rate,
                "position": round(t), "duration": round(self.now["duration"]), "left": clock(left), "left_s": round(left),
                "chapter": ch["title"] if ch else None, "chapter_number": i + 1 if i is not None else None,
                "chapters": len(self.now["chapters"])}

    def overlay(self, now=None):
        """The overlay's Plugins panel part: while the book plays, and SHOWN_AFTER_PAUSE after."""
        now = now or time.time()
        n = self.now
        if not self.cfg["overlay"] or not n or not (n.get("playing") or now - n.get("updated", 0) < SHOWN_AFTER_PAUSE):
            return None
        b = self.brief(now)
        by = " · ".join(x for x in (b["author"], f"read by {b['narrator']}" if b["narrator"] else "") if x)
        where = (f"Chapter {b['chapter_number']}/{b['chapters']}: {b['chapter']}" if b["chapter"] else "") or b["series"] or ""
        return {"title": ("▶ " if b["playing"] else "⏸ ") + b["title"], "image": n["cover"] + "?w=200",
                "lines": [x for x in (by, [where, "text"] if where else None, f"{b['left']} left") if x],
                "progress": b["position"] / b["duration"] if b["duration"] else None}

    # ---- playing ----

    async def in_progress(self):
        got = await self.call("GET", "/api/me/items-in-progress?limit=12")
        out = []
        for it in got.get("libraryItems") or []:
            meta = (it.get("media") or {}).get("metadata") or {}
            if it.get("mediaType", "book") != "book":
                continue
            out.append({"item": it.get("id"), "title": meta.get("title"), "author": meta.get("authorName"),
                        "cover": f"/api/plugins/audiobookshelf/cover/{it.get('id')}"})
        return out

    async def start(self, item=None):
        """A playback session for `item` (None: the book you listened to last), loaded here: its view."""
        if not item:
            books = await self.in_progress()
            if not books:
                raise RuntimeError("nothing in progress on Audiobookshelf: start a book there, or pick one")
            item = books[0]["item"]
        if not ITEM_ID.fullmatch(str(item)):
            raise RuntimeError("not an Audiobookshelf item id")
        await self.close()
        s = await self.call("POST", f"/api/items/{item}/play", {
            "deviceInfo": {"clientName": "ED Outrider", "deviceId": "ed-outrider"}, "forceDirectPlay": True,
            "forceTranscode": False, "supportedMimeTypes": MIME, "mediaPlayer": "html5"})
        if not s.get("id") or not s.get("audioTracks"):
            raise RuntimeError("Audiobookshelf started no session for that item (is it an audiobook?)")
        self._track_urls = [t.get("contentUrl") or "" for t in s["audioTracks"]]
        self.now = dict(session_view(s), playing=False, updated=time.time(), rate=1.0)
        self.error = None
        self.host.emit("loaded", {"session": self.now["session"]})
        return self.now

    async def sync(self, position, listened, playing, player=None, rate=None):
        """The page's report (every 15 s while playing, at pause and at a change of speed): kept, and passed on to
        Audiobookshelf. `rate` is the page's playback speed (RATE_MIN to RATE_MAX; None keeps the last)."""
        if not self.now:
            return {"error": "no book loaded"}
        n = self.now
        n.update(position=max(0.0, min(float(position), n["duration"] or float(position))), playing=bool(playing),
                 updated=time.time())
        if player:
            self.player = str(player)[:40]
        if rate is not None:
            n["rate"] = min(RATE_MAX, max(RATE_MIN, float(rate)))
        self.host.state and self.host.state.bump()
        try:
            await self.call("POST", f"/api/session/{n['session']}/sync",
                            {"currentTime": n["position"], "timeListened": max(0.0, min(float(listened), 600.0)),
                             "duration": n["duration"]})
            self.error = None
        except RuntimeError as e:
            self.error = str(e)
        return {"ok": self.error is None, "error": self.error}

    async def close(self):
        n = self.now
        if not n:
            return
        try:
            await self.call("POST", f"/api/session/{n['session']}/close", {"currentTime": n["position"], "timeListened": 0})
        except RuntimeError:
            pass   # gone already (Audiobookshelf ends idle sessions): nothing to close

    def command(self, do, **extra):
        """A control for the page playing the book (or, with none playing, the one that played it last)."""
        self.host.emit("command", dict(extra, do=do, player=self.player))

    # ---- voice ----

    async def said(self, text):
        t = " " + re.sub(r"[^a-z0-9' ]+", " ", text.lower()) + " "
        kind = next((k for k, ps in PHRASES.items() if any(f" {p} " in t for p in ps)), None)
        b = self.brief()
        if kind == "what":
            if not b:
                return "No audiobook is loaded."
            return (f"{b['title']}, by {b['author']}" + (f", chapter {b['chapter_number']}" if b["chapter_number"] else "") +
                    f", {said_clock(b['left_s'])} left." + ("" if b["playing"] else " It is paused."))
        if kind == "play":
            if not self.now:
                try:
                    await self.start()
                except RuntimeError as e:
                    return f"I could not start the book: {e}."
            self.command("play")
            return f"Resuming {self.now['title']}."
        if not b:
            return "No audiobook is loaded."
        self.command(kind)
        return {"pause": "Book paused.", "next": "Next chapter.", "prev": "Previous chapter.", "back": "Back thirty seconds."}[kind]

    # ---- the long-route watcher ----

    async def watch_route(self):
        while True:
            await asyncio.sleep(LONG_ROUTE_CHECK_S)
            j = getattr(self.host.state, "journals", None)
            if j is None:
                continue
            st = j.status_json or {}
            remaining = (getattr(j, "target", None) or {}).get("remaining")
            jumping = bool((st.get("flags") or 0) & (1 << 30)) or bool((st.get("flags") or 0) & (1 << 17))   # FSD jump / charging
            act = long_route_step(self.route, remaining, jumping, bool(self.now and self.now.get("playing")), self.cfg,
                                  time.time())
            if act == "play":
                if not self.now:
                    try:
                        await self.start()
                    except RuntimeError as e:
                        self.error = str(e)
                        continue
                self.command("play", why=f"a {remaining}-jump route")
            elif act == "pause":
                self.command("pause", why="you have arrived")


def setup(host):
    books = Books(host)
    host.books = books   # for tests
    host.payload(books.payload)
    host.overlay(books.overlay)
    host.voice([p for ps in PHRASES.values() for p in ps], books.said)
    if books.cfg["long_route_jumps"]:
        host.task(books.watch_route)

    async def library(request):
        try:
            return web.json_response({"books": await books.in_progress()})
        except RuntimeError as e:
            return web.json_response({"error": str(e)}, status=502)

    async def now(request):
        return web.json_response({"now": books.brief(), "error": books.error, "configured": books.configured})

    async def play(request):
        body = await request.json() if request.can_read_body else {}
        try:
            v = await books.start((body or {}).get("item"))
        except RuntimeError as e:
            return web.json_response({"error": str(e)}, status=502)
        if body.get("player"):
            books.player = str(body["player"])[:40]
        return web.json_response({"now": v})

    async def sync(request):
        try:
            b = await request.json()
            position, listened = float(b.get("position", 0)), float(b.get("listened", 0))
            rate = float(b["rate"]) if b.get("rate") is not None else None
        except (TypeError, ValueError, AttributeError):
            return web.json_response({"error": "expected {position, listened, playing, rate}"}, status=400)
        if rate is not None and not rate > 0:   # NaN and nonsense too
            rate = None
        return web.json_response(await books.sync(position, listened, b.get("playing"), b.get("player"), rate))

    async def command(request):
        b = await request.json()
        if b.get("do") not in ("play", "pause", "toggle", "next", "prev", "back", "forward"):
            return web.json_response({"error": "do: play, pause, toggle, next, prev, back or forward"}, status=400)
        books.command(b["do"])
        return web.json_response({"ok": True})

    async def cover(request):
        item = request.match_info["item"]
        if not ITEM_ID.fullmatch(item):
            raise web.HTTPNotFound()
        w = request.query.get("w", "400")
        w = w if w.isdigit() and 16 <= int(w) <= 1200 else "400"
        try:
            async with books.http().get(f"{books.cfg['url']}/api/items/{item}/cover?width={w}&format=jpeg",
                                        timeout=TIMEOUT) as r:
                if r.status != 200:
                    raise web.HTTPNotFound()
                body = await r.read()
                return web.Response(body=body, content_type=r.content_type or "image/jpeg",
                                    headers={"Cache-Control": "max-age=86400"})
        except (OSError, ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway() from None

    async def stream(request):
        """The loaded session's track n, passed through from Audiobookshelf (Range and all, so the page can seek)."""
        try:
            n = int(request.match_info["n"])
            path = books._track_urls[n]
        except (ValueError, IndexError):
            raise web.HTTPNotFound() from None
        if not path.startswith("/"):
            raise web.HTTPNotFound()
        headers = {"Range": request.headers["Range"]} if "Range" in request.headers else {}
        try:
            async with books.http().get(books.cfg["url"] + path, headers=headers, timeout=STREAM_TIMEOUT) as r:
                if r.status not in (200, 206):
                    raise web.HTTPBadGateway(text=f"Audiobookshelf answered HTTP {r.status}")
                out = web.StreamResponse(status=r.status, headers={
                    k: r.headers[k] for k in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges")
                    if k in r.headers})
                await out.prepare(request)
                async for chunk in r.content.iter_chunked(64 << 10):
                    await out.write(chunk)
                await out.write_eof()
                return out
        except (OSError, ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway() from None

    host.route("GET", "/library", library)
    host.route("GET", "/now", now)
    host.route("POST", "/play", play)
    host.route("POST", "/sync", sync)
    host.route("POST", "/command", command)
    host.route("GET", "/cover/{item}", cover)
    host.route("GET", "/stream/{n}", stream)


def tools(tool):
    @tool("now_playing", "The audiobook loaded in Outrider's Audiobookshelf player: title, author, narrator, series, "
          "whether it is playing, the chapter, and the time left.")
    async def now_playing(get, args, rows):
        got = await get("/api/plugins/audiobookshelf/now")
        return got.get("now") or {"error": got.get("error") or "no audiobook loaded"}

    @tool("books_in_progress", "The audiobooks the commander has in progress on their Audiobookshelf server, the most "
          "recently listened first.")
    async def books_in_progress(get, args, rows):
        got = await get("/api/plugins/audiobookshelf/library")
        return {"books": [{k: b.get(k) for k in ("title", "author")} for b in got.get("books") or []][:rows]} \
            if "books" in got else got

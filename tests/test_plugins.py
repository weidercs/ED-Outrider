"""Plugins (outrider/plugins): discovery, the Manager and Host, [plugins] in the config, and the Audiobookshelf plugin
against a fake Audiobookshelf server on 127.0.0.1 (nothing leaves the machine)."""
import argparse
import asyncio
import contextlib
import io
import os
import tempfile
import tomllib
import unittest

from support import ed_outrider
import outrider.overlay as O
import outrider.overlay_window as W
import outrider.plugins as P
import outrider.tools

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ARGS = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
QUIET = dict(log=lambda *a, **k: None)

FAKE = '''
TITLE = "Fake"
from aiohttp import web

def settings(table):
    return {"greeting": str(table.get("greeting", "hello"))}

def setup(host):
    host.payload(lambda: {"greeting": host.settings["greeting"]})
    host.overlay(lambda: {"title": "Fake", "lines": ["a line"], "progress": 0.5})
    host.voice(["say hello"], lambda text: host.settings["greeting"] + ", commander")

    async def hi(request):
        host.emit("waved", {"n": 1})
        return web.json_response({"hi": host.settings["greeting"]})
    host.route("GET", "/hi", hi)

def tools(tool):
    @tool("hi", "Says hi.")
    async def hi(get, args, rows):
        return await get("/api/plugins/{name}/hi")
'''


def plugin_dir(tmp, name, body=FAKE):
    d = os.path.join(tmp, name)
    os.makedirs(os.path.join(d, "static"))
    with open(os.path.join(d, "plugin.py"), "w") as f:
        f.write(body.replace("{name}", name))
    with open(os.path.join(d, "static", "page.js"), "w") as f:
        f.write("// fake\n")
    return d


class Infrastructure(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def test_settings(self):
        names, tables, problems = P.enabled_settings({"plugins": {"enabled": ["fake", "Bad Name", "fake", 3],
                                                                   "fake": {"greeting": "yo"}}})
        self.assertEqual((names, tables), (["fake"], {"fake": {"greeting": "yo"}}))
        self.assertEqual(len(problems), 3)
        self.assertEqual(P.enabled_settings({})[:2], ([], {}))   # nothing enabled by default: nothing loads
        # set up but not switched on, e.g. `enabled` written under the plugin's own table: said, not silent
        _, _, problems = P.enabled_settings({"plugins": {"audiobookshelf": {"enabled": ["audiobookshelf"], "url": "x"}}})
        self.assertEqual(len(problems), 1)
        self.assertIn("put it under [plugins]", problems[0])
        with contextlib.redirect_stderr(io.StringIO()):
            st = ed_outrider.settings_from({"plugins": {"enabled": ["audiobookshelf"],
                                                        "audiobookshelf": {"url": "http://abs.lan", "token": "t"}}},
                                           ARGS, None, ([], []))
        back = tomllib.loads(ed_outrider.config_text(st))["plugins"]
        self.assertEqual((back["enabled"], back["audiobookshelf"]), (["audiobookshelf"], {"url": "http://abs.lan", "token": "t"}))
        self.assertTrue(ed_outrider.PLUGIN_SECRET.search("token") and ed_outrider.PLUGIN_SECRET.search("api_key"))

    def test_manager(self):
        plugin_dir(self.tmp, "fakeone")
        with open(os.path.join(plugin_dir(self.tmp, "broken"), "plugin.py"), "w") as f:
            f.write("def setup(host):\n    raise RuntimeError('no')\n")
        with contextlib.redirect_stderr(io.StringIO()):
            m = P.Manager(["fakeone", "broken", "missing"], {"fakeone": {"greeting": "hey"}}, dirs=[self.tmp],
                          data_root=self.tmp, **QUIET)
        self.assertEqual(list(m.hosts), ["fakeone"])
        self.assertEqual(set(m.failed), {"broken", "missing"})
        self.assertIn("RuntimeError", m.failed["broken"])
        self.assertEqual(m.payload()["fakeone"], {"events": [], "data": {"greeting": "hey"}})
        self.assertEqual(m.answer("Vespa, say hello please"), ("fakeone", "hey, commander"))
        self.assertIsNone(m.answer("say hellooo"))   # whole words only
        self.assertEqual(m.overlay_parts(), [{"title": "Fake", "lines": ["a line"], "progress": 0.5}])
        self.assertIn('src="plugins/fakeone/static/page.js?v=', m.page_tags())
        self.assertEqual([i["loaded"] for i in m.info()], [True, False, False])

        async def go():
            app = web.Application()
            m.mount(app)
            async with TestClient(TestServer(app)) as c:
                r = await c.get("/api/plugins/fakeone/hi")
                body = await r.json()
                js = await (await c.get("/plugins/fakeone/static/page.js")).text()
                return body, js
        body, js = asyncio.run(go())
        self.assertEqual((body, js), ({"hi": "hey"}, "// fake\n"))
        self.assertEqual([e["kind"] for e in m.payload()["fakeone"]["events"]], ["waved"])

    def test_tools_registered_with_the_plugins_name(self):
        plugin_dir(self.tmp, "faketools")
        self.assertEqual(P.register_tools(["faketools"], dirs=[self.tmp], **QUIET), ["faketools"])
        self.addCleanup(outrider.tools.TOOLS.pop, "faketools_hi", None)
        self.assertIn("faketools_hi", outrider.tools.TOOLS)
        self.assertIn("/api/plugins/faketools/", outrider.tools.READ_ROUTES)

    def test_host_rejects_a_bad_path(self):
        h = P.Host("x", {}, data_root=self.tmp)
        with self.assertRaises(ValueError):
            h.route("GET", "../escape", None)


class OverlayPanel(unittest.TestCase):
    def test_panel(self):
        pal = O.palette()
        self.assertIsNone(O.plugins_panel([], pal))
        p = O.plugins_panel([{"title": "The Martian", "image": "/api/plugins/abs/cover/x", "lines": ["Andy Weir", ["Ch 7", "text"]],
                              "progress": 0.4}, {"title": "Other"}], pal)
        self.assertEqual(p["id"], "plugins")
        images = [i for i in p["items"] if i["t"] == "image"]
        self.assertEqual([i["src"] for i in images], ["/api/plugins/abs/cover/x"])
        self.assertGreaterEqual(p["h"], O.PLUGIN_IMAGE)
        # a picture from anywhere else is not drawn
        q = O.plugins_panel([{"title": "x", "image": "http://evil/x.png"}], pal)
        self.assertFalse([i for i in q["items"] if i["t"] == "image"])

    def test_window_fetches_the_pictures_once(self):
        asked = []

        class Client:
            url = "http://x"

            def view(self, *a):
                return {"version": "1", "panels": [{"id": "plugins", "items": [O.image(0, 0, 10, 10, "/api/plugins/a/c")]}]}

            def raw(self, path):
                asked.append(path)
                return b"PNG"
        f = W.Feed(Client())
        f.fetch_once()
        f.fetch_once()
        self.assertEqual((asked, f.images), (["/api/plugins/a/c"], {"/api/plugins/a/c": b"PNG"}))

    def test_render_with_a_picture(self):
        import importlib.util
        if importlib.util.find_spec("PyQt6") is None:
            self.skipTest("PyQt6 not installed")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtCore import QBuffer, QByteArray
        from PyQt6.QtGui import QColor, QImage
        red = QImage(8, 8, QImage.Format.Format_ARGB32)
        red.fill(QColor(255, 0, 0))
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        red.save(buf, "PNG")
        panel = O.plugins_panel([{"title": "Book", "image": "/api/plugins/a/c"}], O.palette())
        data = {"layout": O.clean_layout(None), "panels": [panel]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.png")
            self.assertTrue(W.render_png(data, path, 1280, 720, images={"/api/plugins/a/c": bytes(ba)}))
            x, y, w, h = W.panel_rect(data["layout"]["plugins"], panel["w"], panel["h"], 1280, 720)
            s = w / panel["w"]
            c = QImage(path).pixelColor(int(x + (O.PAD + O.PLUGIN_IMAGE / 2) * s), int(y + (O.PAD + O.PLUGIN_IMAGE / 2) * s))
            self.assertEqual((c.red(), c.green(), c.blue()), (255, 0, 0))   # the cover, where the panel puts it


SESSION = {"id": "sess1", "libraryItemId": "li_1", "displayTitle": "The Martian", "displayAuthor": "Andy Weir",
           "duration": 3600, "currentTime": 120, "mediaMetadata": {"narratorName": "R. C. Bray"},
           "chapters": [{"start": 0, "end": 1800, "title": "Sol 6"}, {"start": 1800, "end": 3600, "title": "Sol 7"}],
           "audioTracks": [{"startOffset": 0, "duration": 3600, "contentUrl": "/api/items/li_1/file/9", "mimeType": "audio/mpeg"}]}
AUDIO = bytes(range(256)) * 4


def fake_abs(seen):
    def auth(r):
        seen.append((r.method, r.path, r.headers.get("Authorization"), r.headers.get("Range")))
        if r.headers.get("Authorization") != "Bearer tok":
            raise web.HTTPUnauthorized()

    async def progress(r):
        auth(r)
        return web.json_response({"libraryItems": [{"id": "li_1", "mediaType": "book",
                                                    "media": {"metadata": {"title": "The Martian", "authorName": "Andy Weir"}}}]})

    async def play(r):
        auth(r)
        return web.json_response(SESSION)

    async def ok(r):
        auth(r)
        seen.append(await r.json())
        return web.json_response({})

    async def audio(r):
        auth(r)
        if r.headers.get("Range") == "bytes=10-19":
            return web.Response(status=206, body=AUDIO[10:20], headers={"Content-Range": f"bytes 10-19/{len(AUDIO)}"},
                                content_type="audio/mpeg")
        return web.Response(body=AUDIO, content_type="audio/mpeg")

    async def cover(r):
        auth(r)
        return web.Response(body=b"\xff\xd8jpeg", content_type="image/jpeg")
    app = web.Application()
    app.add_routes([web.get("/api/me/items-in-progress", progress), web.post("/api/items/{i}/play", play),
                    web.post("/api/session/{s}/sync", ok), web.post("/api/session/{s}/close", ok),
                    web.get("/api/items/{i}/file/{n}", audio), web.get("/api/items/{i}/cover", cover)])
    return app


class Audiobookshelf(unittest.TestCase):
    def setUp(self):
        self.mod = P.load_module("audiobookshelf", P.discover()["audiobookshelf"])

    def test_settings(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            s = self.mod.settings({"url": "ftp://x", "duck": "loud", "duck_volume": 3, "long_route_jumps": "ten", "nope": 1})
        self.assertEqual((s["url"], s["duck"], s["duck_volume"], s["long_route_jumps"]), ("", "duck", 1.0, 0))
        self.assertEqual(err.getvalue().count("[plugins.audiobookshelf]"), 4)   # url, duck, long_route_jumps, nope (3 is clamped)
        s = self.mod.settings({"url": "http://abs.lan:13378/", "token": " t ", "duck": "pause"})
        self.assertEqual((s["url"], s["token"], s["duck"]), ("http://abs.lan:13378", "t", "pause"))

    def test_words(self):
        self.assertEqual((self.mod.clock(3725), self.mod.clock(125), self.mod.clock(20)), ("1 h 2 m", "2 m", "20 s"))
        self.assertEqual((self.mod.said_clock(3725), self.mod.said_clock(60), self.mod.said_clock(7200)),
                         ("1 hour 2 minutes", "1 minute", "2 hours"))
        v = self.mod.session_view(SESSION)
        self.assertEqual((v["title"], v["narrator"], len(v["chapters"]), v["tracks"][0]["mime"]),
                         ("The Martian", "R. C. Bray", 2, "audio/mpeg"))
        self.assertNotIn("contentUrl", str(v))   # Audiobookshelf's paths stay on the server

    def test_long_route(self):
        cfg, mem, step = {"long_route_jumps": 10, "pause_on_arrival": True}, {}, self.mod.long_route_step
        self.assertIsNone(step(mem, 4, True, False, cfg, 0))     # a short route: no
        self.assertEqual(step(mem, 12, True, False, cfg, 1), "play")
        self.assertIsNone(step(mem, 11, True, True, cfg, 60))    # once per route
        self.assertIsNone(step(mem, 11, True, False, cfg, 90))   # paused by hand mid-route: it stays paused
        self.assertIsNone(step(mem, 5, False, False, cfg, 200))  # between jumps
        self.assertIsNone(step(mem, 1, False, False, cfg, 300))  # arrived, already paused: nothing to do
        self.assertEqual(mem, {})
        mem = {}
        step(mem, 12, True, False, cfg, 1)
        self.assertEqual(step(mem, None, False, True, cfg, 400), "pause")
        self.assertIsNone(step({}, 50, True, False, {"long_route_jumps": 0}, 1))   # off

    def run_with(self, go, cfg=None):
        seen = []

        async def main():
            async with TestServer(fake_abs(seen)) as abs_srv:
                table = {"url": str(abs_srv.make_url("")).rstrip("/"), "token": "tok", **(cfg or {})}
                with contextlib.redirect_stderr(io.StringIO()):
                    m = P.Manager(["audiobookshelf"], {"audiobookshelf": table}, **QUIET)
                app = web.Application()
                m.mount(app)
                async with TestClient(TestServer(app)) as c:
                    try:
                        return await go(c, m, m.hosts["audiobookshelf"].books), seen
                    finally:
                        await m.hosts["audiobookshelf"].books.http().close()
        return asyncio.run(main())

    def test_playing_through_outrider(self):
        async def go(c, m, books):
            out = {"library": await (await c.get("/api/plugins/audiobookshelf/library")).json()}
            r = await c.post("/api/plugins/audiobookshelf/play", json={"player": "p1"})
            out["play"] = (await r.json())["now"]
            r = await c.get("/api/plugins/audiobookshelf/stream/0", headers={"Range": "bytes=10-19"})
            out["range"] = (r.status, await r.read(), r.headers.get("Content-Range"))
            out["whole"] = await (await c.get("/api/plugins/audiobookshelf/stream/0")).read()
            out["missing"] = (await c.get("/api/plugins/audiobookshelf/stream/5")).status
            out["cover"] = (await c.get("/api/plugins/audiobookshelf/cover/li_1")).status
            out["bad_cover"] = (await c.get("/api/plugins/audiobookshelf/cover/..%2Fx")).status
            r = await c.post("/api/plugins/audiobookshelf/sync", json={"position": 1900, "listened": 15, "playing": True})
            out["sync"] = await r.json()
            out["now"] = (await (await c.get("/api/plugins/audiobookshelf/now")).json())["now"]
            out["payload"] = m.payload()["audiobookshelf"]
            out["overlay"] = m.overlay_parts()
            out["what"] = await m.answer("what am I listening to")[1]
            out["pause"] = await m.answer("Vespa, pause the book")[1]
            out["events"] = [e["kind"] for e in m.hosts["audiobookshelf"].events]
            return out
        out, seen = self.run_with(go)
        self.assertEqual(out["library"]["books"][0]["title"], "The Martian")
        self.assertEqual((out["play"]["title"], out["play"]["position"]), ("The Martian", 120.0))
        self.assertEqual(out["range"], (206, AUDIO[10:20], f"bytes 10-19/{len(AUDIO)}"))
        self.assertEqual(out["whole"], AUDIO)
        self.assertEqual((out["missing"], out["cover"], out["bad_cover"]), (404, 200, 404))
        self.assertEqual(out["sync"], {"ok": True, "error": None})
        self.assertIn({"currentTime": 1900.0, "timeListened": 15.0, "duration": 3600.0}, seen)
        self.assertEqual((out["now"]["chapter"], out["now"]["chapter_number"]), ("Sol 7", 2))
        self.assertNotIn("tok", str(out["payload"]))   # the token never reaches a page
        self.assertEqual(out["overlay"][0]["image"], "/api/plugins/audiobookshelf/cover/li_1?w=200")
        self.assertTrue(out["what"].startswith("The Martian, by Andy Weir, chapter 2, 28 minutes left"))
        self.assertEqual(out["pause"], "Book paused.")
        self.assertEqual(out["events"], ["loaded", "command"])
        self.assertTrue(all(s[2] == "Bearer tok" for s in seen if isinstance(s, tuple)))

    def test_a_refused_token_is_said(self):
        async def go(c, m, books):
            return await (await c.get("/api/plugins/audiobookshelf/library")).json()
        out, _ = self.run_with(go, {"token": "wrong"})
        self.assertEqual(out, {"error": "Audiobookshelf refused the API token"})


if __name__ == "__main__":
    unittest.main()

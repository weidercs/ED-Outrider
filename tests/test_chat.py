"""Chat read aloud by Comms (NEXT-VERSION #17, the author 2026-10-17): ReceiveText kept for the page in memory only
(live, never an NPC's or your own, mentions of you marked), and the voice never caching nor logging it (api/say's
private). The page's pacing and settings: tests/page_smoke.js ("chat read aloud")."""
import contextlib
import io
import time
import types
import unittest

from support import ed_outrider  # also puts the repository root on sys.path

import outrider.tts  # noqa: E402


def now_ts(ago=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - ago))


def text(channel, sender, message, ago=0):
    return {"timestamp": now_ts(ago), "event": "ReceiveText", "From": sender, "Message": message, "Channel": channel}


class Chat(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.j.commander = {"name": "Hefay"}

    def test_kept_live_only_not_npc_not_yours(self):
        j = self.j
        for ev in (text("squadron", "Kurbo26", "o7 all"),
                   text("npc", "$npc_name_decorate:#name=Pirate;", "Your cargo or your life"),
                   text("squadron", "Hefay", "my own line"),                       # yours (the game echoes it): never
                   text("squadron", "Old Timer", "from a journal caught up on", ago=3600),   # not live: never
                   text("local", "$cmdr_decorate:#name=Bob Smith;", "anyone near Sol?"),
                   text("player", "CMDR Alice", "hello Hefay, got a minute?"),
                   text("wing", "", "no sender")):
            j.handle(ev)
        got = [(m["channel"], m["sender"], m["text"], m["mention"]) for m in j.chat]
        self.assertEqual(got, [("squadron", "Kurbo26", "o7 all", False), ("local", "Bob Smith", "anyone near Sol?", False),
                               ("player", "Alice", "hello Hefay, got a minute?", True)])
        self.assertEqual([m["seq"] for m in j.chat], [1, 2, 3])
        # in memory only: nothing about it in the database
        dump = "\n".join(self.db.iterdump())
        self.assertNotIn("o7 all", dump)
        self.assertNotIn("got a minute", dump)

    def test_mention_long_and_whitespace(self):
        j = self.j
        j.handle(text("squadron", "Kurbo26", "hefay\tare you   there"))           # case and spacing
        j.handle(text("squadron", "Kurbo26", "Hefayson is someone else"))         # a longer name: no mention
        j.handle(text("squadron", "Kurbo26", "x" * 400))
        a, b, c = j.chat
        self.assertEqual((a["text"], a["mention"], b["mention"]), ("hefay are you there", True, False))
        self.assertEqual((len(c["text"]), c["more"]), (ed_outrider.CHAT_MAX, True))

    def test_rolled_back_tick_says_it_once(self):
        """A failed tick is retried: its chat must not come twice (the checkpoint keeps the chat too)."""
        j = self.j
        cp = j.checkpoint()
        j.handle(text("squadron", "Kurbo26", "first try"))
        j.restore(cp)
        j.handle(text("squadron", "Kurbo26", "first try"))
        self.assertEqual([(m["seq"], m["text"]) for m in j.chat], [(1, "first try")])

    def test_in_the_payload(self):
        state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.j.handle(text("wing", "Kurbo26", "on my way"))
        self.assertEqual([(m["channel"], m["text"]) for m in state.payload()["chat"]], [("wing", "on my way")])

    def test_sender_names(self):
        self.assertEqual([ed_outrider.chat_sender(x) for x in ("$cmdr_decorate:#name=Bob;", "CMDR Alice", "cmdr  Zed", "$npc_x;", "", None)],
                         ["Bob", "Alice", "Zed", None, None, None])


class PrivateSpeech(unittest.TestCase):
    """Another player's chat is never kept in the voice's cache, nor its words printed to the log on a failure."""

    def test_speaker_keeps_nothing(self):
        sp = outrider.tts.Speaker.__new__(outrider.tts.Speaker)
        sp._cache, sp._lock, sp._voice, sp.voice_name = __import__("collections").OrderedDict(), __import__("threading").Lock(), object(), "v"
        sp.extra_voice = lambda name: None
        sp.voice_speakers = lambda name: []
        sp.speaker_for = lambda name: None
        sp._synth = lambda voice, text, speed, speaker: b"RIFF" + text.encode()
        self.assertEqual(sp.say("chat words", keep=False), b"RIFFchat words")
        self.assertEqual(len(sp._cache), 0)
        sp.say("an alert")
        self.assertEqual(len(sp._cache), 1)

    def test_say_route_private(self):
        from aiohttp.test_utils import TestClient, TestServer
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        state = ed_outrider.State(db, ed_outrider.Journals(db), types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        calls = []

        def say(text, speed=1.0, voice=None, speaker=None, keep=True):
            calls.append((text, keep))
            if text.startswith("boom"):
                raise RuntimeError("piper fell over")
            return b"RIFF...."
        state.speaker = types.SimpleNamespace(ready=True, say=say, installed=lambda: [], voice_name="v")
        err = io.StringIO()

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(state))) as c:
                a = await c.get("/api/say", params={"text": "Kurbo: o7", "private": "1"})
                b = await c.get("/api/say", params={"text": "Tank full."})
                with contextlib.redirect_stderr(err):
                    e = await c.get("/api/say", params={"text": "boom secret words", "private": "1"})
                return a.status, b.status, e.status
        self.assertEqual(asyncio_run(go()), (200, 200, 503))
        self.assertEqual(calls[:2], [("Kurbo: o7", False), ("Tank full.", True)])
        self.assertIn("could not speak a chat message", err.getvalue())
        self.assertNotIn("secret", err.getvalue())


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()

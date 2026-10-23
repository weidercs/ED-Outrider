"""[speech] tts_server: spoken alerts from a Wyoming voice server on the network (outrider/wyoming.py, Speaker's remote).
A fake server on 127.0.0.1 answers here; nothing leaves the machine."""
import argparse
import contextlib
import io
import json
import socket
import socketserver
import threading
import tomllib
import unittest
import wave

from support import ed_outrider
import outrider.tts
import outrider.wyoming as W

ARGS = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)


class FakeServer:
    """A Wyoming text-to-speech server: `describe` lists two voices; `synthesize` answers 0.1 s of 16-bit silence per
    word at 22050 Hz, in the voice asked for (recorded in `asked`). `split`: data as a separate block (data_length),
    else inline. `refuse`: answer an error event instead."""

    def __init__(self, split=True, refuse=None):
        self.split, self.refuse, self.asked = split, refuse, []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def send(self, kind, data=None, payload=b""):
                head = {"type": kind}
                body = json.dumps(data).encode() if data else b""
                if data and not outer.split:
                    head["data"] = data
                    body = b""
                if body:
                    head["data_length"] = len(body)
                if payload:
                    head["payload_length"] = len(payload)
                self.wfile.write(json.dumps(head).encode() + b"\n" + body + payload)

            def handle(self):
                ev = json.loads(self.rfile.readline())
                if ev["type"] == "describe":
                    self.send("info", {"tts": [{"name": "fake", "voices": [{"name": "bm_lewis", "languages": ["en_GB"]},
                                                                         {"name": "af_heart", "languages": ["en_US"]}]}]})
                    return
                outer.asked.append(ev["data"])
                if outer.refuse:
                    self.send("error", {"text": outer.refuse})
                    return
                fmt = {"rate": 22050, "width": 2, "channels": 1}
                self.send("audio-start", fmt)
                for _ in ev["data"]["text"].split():
                    self.send("audio-chunk", fmt, b"\0\0" * 2205)
                self.send("audio-stop")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def wav_seconds(audio):
    with wave.open(io.BytesIO(audio)) as w:
        return w.getnframes() / w.getframerate()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Protocol(unittest.TestCase):
    def serve(self, **kw):
        srv = FakeServer(**kw)
        self.addCleanup(srv.close)
        return srv

    def test_parse_server(self):
        self.assertIsNone(W.parse_server(""))
        self.assertEqual(W.parse_server(" voice.lan:10210 "), ("voice.lan", 10210))
        self.assertEqual(W.parse_server("10.0.0.5:10200"), ("10.0.0.5", 10200))
        self.assertEqual(W.parse_server("[fe80::1]:10200"), ("fe80::1", 10200))
        for bad in ("voice.lan", "voice.lan:0", "voice.lan:70000", "http://voice.lan:10200", "a b:1"):
            with self.assertRaises(ValueError):
                W.parse_server(bad)

    def test_synthesize_both_data_forms(self):
        for split in (True, False):
            srv = self.serve(split=split)
            audio = W.synthesize("127.0.0.1", srv.port, "good evening sir", "bm_lewis")
            self.assertAlmostEqual(wav_seconds(audio), 0.3, places=2)
            self.assertEqual(srv.asked, [{"text": "good evening sir", "voice": {"name": "bm_lewis"}}])
        srv = self.serve()
        W.synthesize("127.0.0.1", srv.port, "hello")
        self.assertEqual(srv.asked, [{"text": "hello"}])   # no voice: the server's default

    def test_describe_and_errors(self):
        srv = self.serve()
        self.assertEqual([v["name"] for v in W.describe("127.0.0.1", srv.port)], ["bm_lewis", "af_heart"])
        with self.assertRaisesRegex(W.WyomingError, "refused: no such voice"):
            W.synthesize("127.0.0.1", self.serve(refuse="no such voice").port, "hi")
        with self.assertRaisesRegex(W.WyomingError, "cannot reach"):
            W.synthesize("127.0.0.1", free_port(), "hi", timeout=2)
        # something that is not a Wyoming server (an HTTP answer)
        with socket.socket() as ls:
            ls.bind(("127.0.0.1", 0))
            ls.listen()
            port = ls.getsockname()[1]

            def answer():
                c, _ = ls.accept()
                c.recv(1024)
                c.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                c.close()
            threading.Thread(target=answer, daemon=True).start()
            with self.assertRaisesRegex(W.WyomingError, "does not speak Wyoming"):
                W.synthesize("127.0.0.1", port, "hi", timeout=2)

    def test_remote_records_its_state(self):
        srv = self.serve()
        r = W.Remote("127.0.0.1", srv.port, "bm_lewis")
        self.assertTrue(r.check())
        self.assertEqual((r.voices, r.error), (["bm_lewis", "af_heart"], None))
        r.voice = "nobody"
        r.check()
        self.assertEqual(r.error, "the server has no voice nobody")
        dead = W.Remote("127.0.0.1", free_port())
        self.assertFalse(dead.check())
        self.assertIn("cannot reach", dead.error)


class SpeakerRemote(unittest.TestCase):
    """Speaker with a voice server and no Piper (the case of a PC without it, or a Docker install)."""

    def speaker(self, port, voice="bm_lewis"):
        sp = outrider.tts.Speaker.__new__(outrider.tts.Speaker)
        outrider.tts.Speaker.__init__(sp, voices_dir="/nonexistent")
        sp.PiperVoice = None   # this test machine's Piper, if any, is left out
        sp._voice = None
        sp.remote = W.Remote("127.0.0.1", port, voice)
        return sp

    def test_says_through_the_server_and_caches(self):
        srv = FakeServer()
        self.addCleanup(srv.close)
        sp = self.speaker(srv.port)
        self.assertTrue(sp.available and sp.ready)
        self.assertEqual(sp.engine(), "wyoming")
        a = sp.say("all systems online", voice="en_GB-cori-medium")   # a personality voice not installed here: the server's
        self.assertAlmostEqual(wav_seconds(a), 0.3, places=2)
        self.assertEqual(sp.say("all systems online"), a)
        self.assertEqual(len(srv.asked), 1)                           # the second came from the cache
        sp.say("private line", keep=False)
        sp.say("private line", keep=False)
        self.assertEqual(len(srv.asked), 3)                           # keep=False (another player's chat) is never cached
        info = sp.info()
        self.assertEqual((info["engine"], info["server"]["address"], info["server"]["voice"], info["server"]["error"]),
                         ("wyoming", f"127.0.0.1:{srv.port}", "bm_lewis", None))

    def test_server_down_without_piper_means_the_browser_voice(self):
        sp = self.speaker(free_port())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(sp.say("hello"))
            self.assertIsNone(sp.say("hello again"))
        self.assertEqual(err.getvalue().count("cannot reach"), 1)   # said once while it stays down
        self.assertIn("cannot reach", sp.info()["server"]["error"])
        self.assertEqual(sp.engine(), "wyoming")   # still the server's to say (no Piper here to fall back on)

    def test_without_a_server_nothing_changes(self):
        sp = outrider.tts.Speaker.__new__(outrider.tts.Speaker)
        outrider.tts.Speaker.__init__(sp, voices_dir="/nonexistent")
        sp.PiperVoice, sp._voice = None, None
        self.assertEqual((sp.remote, sp.available, sp.ready, sp.engine(), sp.info()["server"]), (None, False, False, None, None))


class Settings(unittest.TestCase):
    def settings(self, cfg):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            return ed_outrider.settings_from(cfg, ARGS, None, ([], [])), err.getvalue()

    def test_config(self):
        st, _ = self.settings({})
        self.assertEqual((st["tts_server"], st["tts_server_voice"]), ("", ""))   # off by default: nothing is sent
        st, _ = self.settings({"speech": {"tts_server": "voice.lan:10210", "tts_server_voice": "bm_lewis"}})
        self.assertEqual((st["tts_server"], st["tts_server_voice"]), ("voice.lan:10210", "bm_lewis"))
        back = tomllib.loads(ed_outrider.config_text(st))["speech"]
        self.assertEqual((back["tts_server"], back["tts_server_voice"]), ("voice.lan:10210", "bm_lewis"))
        st, err = self.settings({"speech": {"tts_server": "http://voice.lan", "tts_server_voice": 5}})
        self.assertEqual((st["tts_server"], st["tts_server_voice"]), ("", ""))
        self.assertIn("tts_server", err)


if __name__ == "__main__":
    unittest.main()

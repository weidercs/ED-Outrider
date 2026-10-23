"""Spoken alerts from a voice server on your network ([speech] tts_server): the Wyoming protocol, the one Home
Assistant uses for Piper, Kokoro and other local voices. Plain sockets, no dependency: one connection per line.

An event is one JSON line ({"type", "data"?, "data_length"?, "payload_length"?}), then data_length bytes of JSON
(merged into "data") and payload_length bytes of payload (the audio). A line is spoken by sending "synthesize"
{text, voice?: {name}} and reading "audio-start" {rate, width, channels}, "audio-chunk"s and "audio-stop"; the voice
is asked for by its name ("describe" lists the server's).
"""
import io
import json
import re
import socket
import wave

TIMEOUT = 15.0          # s: a whole line, connect to the last chunk
AUDIO_MAX = 32 << 20    # bytes of audio a line may bring (about 6 minutes at 24 kHz): more is a broken server
HEADER_MAX = 1 << 20    # bytes in one event's header line or data
SERVER = re.compile(r"^\[?([A-Za-z0-9.\-:]+?)\]?:(\d{1,5})$")   # host:port, [IPv6]:port


class WyomingError(Exception):
    """The server could not be reached or answered something that is not speech (the reason, in words)."""


def parse_server(text):
    """'voice.lan:10210' -> ('voice.lan', 10210); '' -> None; ValueError for anything else."""
    text = str(text or "").strip()
    if not text:
        return None
    m = SERVER.fullmatch(text)
    if not m or not 1 <= int(m.group(2)) <= 65535:
        raise ValueError("not host:port (e.g. voice.lan:10200)")
    return m.group(1), int(m.group(2))


def _send(sock, kind, data=None):
    sock.sendall((json.dumps({"type": kind, **({"data": data} if data else {})}) + "\n").encode())


def _read_exact(f, n):
    out = f.read(n)
    if len(out) != n:
        raise WyomingError("the server closed the connection mid-line")
    return out


def read_event(f):
    """(type, data, payload) of the next event on the binary file `f`."""
    line = f.readline(HEADER_MAX + 1)
    if not line:
        raise WyomingError("the server closed the connection")
    if len(line) > HEADER_MAX:
        raise WyomingError("the server sent an event header over 1 MB")
    try:
        head = json.loads(line)
    except ValueError:
        raise WyomingError("the server does not speak Wyoming") from None
    if not isinstance(head, dict) or not isinstance(head.get("type"), str):
        raise WyomingError("the server does not speak Wyoming")
    data = head.get("data") if isinstance(head.get("data"), dict) else {}
    dlen, plen = head.get("data_length") or 0, head.get("payload_length") or 0
    if not all(isinstance(n, int) and 0 <= n for n in (dlen, plen)) or dlen > HEADER_MAX or plen > AUDIO_MAX:
        raise WyomingError("the server sent an event of an impossible size")
    if dlen:
        try:
            extra = json.loads(_read_exact(f, dlen))
        except ValueError:
            raise WyomingError("the server sent unreadable event data") from None
        if isinstance(extra, dict):
            data = {**data, **extra}
    return head["type"], data, _read_exact(f, plen) if plen else b""


def synthesize(host, port, text, voice=None, timeout=TIMEOUT, connect=socket.create_connection):
    """WAV bytes of `text` spoken by the server (in `voice`, a name it knows; None: its default). WyomingError when
    it cannot be reached or does not answer with audio."""
    try:
        with connect((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            _send(sock, "synthesize", {"text": text, **({"voice": {"name": voice}} if voice else {})})
            f = sock.makefile("rb")
            fmt, audio = None, bytearray()
            while True:
                kind, data, payload = read_event(f)
                if kind == "audio-start":
                    fmt = data
                elif kind == "audio-chunk":
                    fmt = fmt or data   # some servers send no audio-start: every chunk carries the format
                    audio += payload
                    if len(audio) > AUDIO_MAX:
                        raise WyomingError("the server sent more audio than a line can be")
                elif kind == "audio-stop":
                    break
                elif kind == "error":
                    raise WyomingError(f"the server refused: {data.get('text') or 'no reason given'}")
    except OSError as e:
        raise WyomingError(f"cannot reach {host}:{port} ({e.strerror or type(e).__name__})") from None
    try:
        rate, width, channels = int(fmt["rate"]), int(fmt["width"]), int(fmt["channels"])
    except (TypeError, KeyError, ValueError):
        raise WyomingError("the server sent audio without its format") from None
    if not audio:
        return None   # nothing to say (a line of punctuation): as Piper's None
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setframerate(rate)
        w.setsampwidth(width)
        w.setnchannels(channels)
        w.writeframes(bytes(audio))
    return buf.getvalue()


def describe(host, port, timeout=5.0, connect=socket.create_connection):
    """The server's text-to-speech voices, [{name, languages}] (empty when it offers none). WyomingError when it cannot
    be reached or does not answer."""
    try:
        with connect((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            _send(sock, "describe")
            f = sock.makefile("rb")
            while True:
                kind, data, _ = read_event(f)
                if kind == "info":
                    break
    except OSError as e:
        raise WyomingError(f"cannot reach {host}:{port} ({e.strerror or type(e).__name__})") from None
    voices = []
    for prog in data.get("tts") or []:
        for v in (prog.get("voices") if isinstance(prog, dict) else None) or []:
            if isinstance(v, dict) and isinstance(v.get("name"), str):
                voices.append({"name": v["name"], "languages": [x for x in v.get("languages") or [] if isinstance(x, str)]})
    return voices


class Remote:
    """A voice server from the config: where it is, the voice asked for (None: its default) and how the last line
    went (`error`: None after a line it spoke). Speaker holds one."""

    def __init__(self, host, port, voice=None):
        self.host, self.port, self.voice = host, int(port), (voice or None)
        self.error = None
        self.voices = None   # its voices' names, once describe() answered

    @property
    def label(self):
        return f"{self.host}:{self.port}"

    def check(self):
        """Ask the server what it offers (at start, off the event loop). True when it answered."""
        try:
            self.voices = [v["name"] for v in describe(self.host, self.port)]
        except WyomingError as e:
            self.error = str(e)
            return False
        self.error = (f"the server has no voice {self.voice}" if self.voice and self.voices and self.voice not in self.voices
                      else None)
        return True

    def say(self, text):
        """WAV bytes, or None (nothing to say). WyomingError, recorded in `error`, when it could not."""
        try:
            audio = synthesize(self.host, self.port, text, self.voice)
        except WyomingError as e:
            self.error = str(e)
            raise
        self.error = None
        return audio

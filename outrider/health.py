"""What kind of failure a call to an outside service met (the uploads' Recent list and outage alert, S3/S16; the
read-only lookups' health later, S42). Pure: no network, no state.

`classify(exc, status, text)` -> (kind, user_fix): kind is one of KINDS, user_fix True when the player can fix it on
their side (no DNS, no network at all). `HttpError` is a sender's own "the service answered HTTP <status>", a
ConnectionError (so the upload loop backs off as for any network failure) that keeps the status for classify.
"""
import asyncio
import errno
import re
import socket
import ssl

# dns: the name not found; offline: no route to it (this machine's network down); refused: nothing listening there;
# timeout: no answer in time; tls: the secure connection failed; http5xx: the service failing; rate: asked to slow
# down; http4xx: a request it refused; bad_answer: an answer that is not what the service answers; other: anything else
KINDS = ("dns", "offline", "refused", "timeout", "tls", "http5xx", "rate", "http4xx", "bad_answer", "other")
USER_FIX = frozenset({"dns", "offline"})
# words in a 4xx answer that mean "too many requests" (Inara says it in its header's text, with a 400: inara.RATE_WORDS)
RATE_WORDS = ("slow down", "too many", "too much", "rate limit", "revoked", "temporarily")
_OFFLINE = {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN}
_CODE = re.compile(r"^\s*(\d{3})\b")


class HttpError(ConnectionError):
    """A service answered with an HTTP status that is not an answer to read (EDSM's or Inara's non-200)."""

    def __init__(self, status, text):
        super().__init__(text)
        self.status = status


def _by_status(status, text=""):
    if 500 <= status <= 599:
        return "http5xx"
    if 400 <= status <= 499:
        return "rate" if status == 429 or any(w in (text or "").lower() for w in RATE_WORDS) else "http4xx"
    return "bad_answer"


def _chain(exc):
    """The exception and what it wraps (__cause__, __context__, aiohttp's os_error), each once."""
    seen = []
    while exc is not None and exc not in seen and len(seen) < 8:
        seen.append(exc)
        exc = getattr(exc, "os_error", None) or exc.__cause__ or exc.__context__
    return seen


def classify(exc=None, status=None, text=None):
    """(kind, user_fix) for a failure: a raised exception, an HTTP status, or a service's answer text that starts
    with its code ("503 busy", "400 Too much requests, slow down")."""
    kind = None
    if exc is not None:
        if isinstance(exc, HttpError) or (status is None and isinstance(getattr(exc, "status", None), int)):
            kind = _by_status(status or exc.status, str(exc))   # aiohttp's ClientResponseError carries one too
        for e in () if kind else _chain(exc):
            name = type(e).__name__
            if isinstance(e, socket.gaierror) or name == "ClientConnectorDNSError":
                kind = "dns"
            elif isinstance(e, ssl.SSLError | ssl.CertificateError) or "SSL" in name or "Certificate" in name:
                kind = "tls"
            elif isinstance(e, asyncio.TimeoutError | TimeoutError) or "Timeout" in name:
                kind = "timeout"
            elif isinstance(e, ConnectionRefusedError) or name == "ServerDisconnectedError":
                kind = "refused"
            elif isinstance(e, OSError) and e.errno in _OFFLINE:
                kind = "offline"
            elif isinstance(e, ValueError) or name in ("ContentTypeError", "ClientPayloadError"):
                kind = "bad_answer"   # JSONDecodeError is a ValueError; so is our own "no msgnum"
            elif isinstance(e, ConnectionError):
                kind = "refused"      # reset, aborted, or a sender's own "unreachable"
            if kind:
                break
    elif status is not None:
        kind = _by_status(status, text or "")
    elif text:
        m = _CODE.match(text)
        # a retry answer with no code of its own: the service is having trouble
        kind = _by_status(int(m.group(1)), text) if m else "http5xx"
    kind = kind or "other"
    return kind, kind in USER_FIX

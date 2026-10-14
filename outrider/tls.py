"""The one TLS context every outgoing HTTPS connection uses (issue #9), and the plain words for a certificate failure.

`client_context()`: the system's certificate store (ssl.create_default_context: on Windows the Windows store, so a
corporate or self-added root keeps working) PLUS certifi's bundle when certifi is installed (requirements.txt). Windows
only fetches a new or renewed root when something asks it to (a browser does, Python does not), so a site that moved to
a root the store has not fetched yet fails there with "certificate has expired" or "unable to get local issuer
certificate"; certifi's bundle has it. Without certifi: the system store alone, said once in the log. Created once.

`connector()`: an aiohttp TCPConnector on that context (every ClientSession is given one); `urlopen(url, timeout)`:
urllib's urlopen with it, a certificate failure raised as `CertificateFailed` (an OSError, so the callers' handlers
still catch it) whose text is `cert_text`'s. tests/test_tls.py walks the source: a ClientSession or urlopen without the
shared context fails it.

`cert_failure(exc)`: the certificate verification error in an exception's chain (aiohttp's
ClientConnectorCertificateError, urllib's URLError around one), or None; `cert_text(exc, host)`: "couldn't verify
spansh.co.uk's certificate (expired): check this PC's date and time; if they are right, update Outrider" (a clock that
is wrong gives the same error, so that is the first thing to look at). outrider.health.classify's "certificate" kind.
"""
import functools
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

# OpenSSL's verify codes in a few words (X509_V_ERR_*); any other: its own message
REASONS = {10: "expired", 9: "not valid yet", 2: "its issuer is not known here", 20: "its issuer is not known here",
           18: "self-signed", 19: "self-signed", 62: "made out to another name"}
ADVICE = "check this PC's date and time; if they are right, update Outrider"


@functools.lru_cache(maxsize=None)
def client_context():
    """The shared client SSLContext: the system store plus certifi's bundle when certifi is importable."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        where = certifi.where()
    except ImportError:
        print("TLS: certifi is not installed: only this PC's certificate store is used (pip install -r "
              "requirements.txt adds it)", file=sys.stderr)
        return ctx
    try:
        ctx.load_verify_locations(cafile=where)
    except (OSError, ssl.SSLError) as e:   # a broken install: the system store still works
        print(f"TLS: certifi's bundle could not be read ({e}): only this PC's certificate store is used", file=sys.stderr)
    return ctx


def connector(**kw):
    """An aiohttp TCPConnector on the shared context (ClientSession(connector=...); the session closes it)."""
    from aiohttp import TCPConnector
    return TCPConnector(ssl=client_context(), **kw)


class CertificateFailed(OSError):
    """urlopen met a certificate it could not verify; the text is cert_text's, the cause the original error."""


def urlopen(url, timeout, data=None):
    """urllib.request.urlopen(url, data, timeout) on the shared context; a certificate failure as CertificateFailed."""
    try:
        return urllib.request.urlopen(url, data=data, timeout=timeout, context=client_context())
    except urllib.error.URLError as e:
        if cert_failure(e) is None:
            raise
        full = url.full_url if isinstance(url, urllib.request.Request) else str(url)
        raise CertificateFailed(cert_text(e, urllib.parse.urlsplit(full).hostname)) from e


def _chain(exc):
    """The exception and what it wraps (urllib's reason, aiohttp's certificate_error/os_error, __cause__, __context__)."""
    seen, todo = [], [exc]
    while todo and len(seen) < 12:
        e = todo.pop(0)
        if not isinstance(e, BaseException) or e in seen:
            continue
        seen.append(e)
        todo += [getattr(e, "reason", None), getattr(e, "certificate_error", None), getattr(e, "os_error", None),
                 e.__cause__, e.__context__]
    return seen


def cert_failure(exc):
    """The certificate verification failure in `exc`'s chain (an ssl.SSLCertVerificationError, aiohttp's
    ClientConnectorCertificateError, an SSLError saying CERTIFICATE_VERIFY_FAILED, a CertificateFailed), or None."""
    for e in _chain(exc):
        if isinstance(e, ssl.SSLCertVerificationError | CertificateFailed) or \
                type(e).__name__ == "ClientConnectorCertificateError" or \
                (isinstance(e, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(e)):
            return e
    return None


def cert_reason(exc):
    """What was wrong with the certificate in a few words ("expired"), or None when the error does not say."""
    for e in _chain(exc):
        code, message = getattr(e, "verify_code", None), getattr(e, "verify_message", None)
        if code in REASONS:
            return REASONS[code]
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def cert_host(exc):
    """The host the failed connection was to, when the error carries it (aiohttp's does)."""
    for e in _chain(exc):
        host = getattr(e, "host", None)
        if isinstance(host, str) and host:
            return host
    return None


def cert_text(exc, host=None):
    """The words for a certificate failure: "couldn't verify spansh.co.uk's certificate (expired): check this PC's
    date and time; if they are right, update Outrider". A CertificateFailed's own text is already that."""
    for e in _chain(exc):
        if isinstance(e, CertificateFailed):
            return str(e)
    host = host or cert_host(exc)
    reason = cert_reason(exc)
    whose = f"{host}'s certificate" if host else "the certificate"
    return f"couldn't verify {whose}{f' ({reason})' if reason else ''}: {ADVICE}"

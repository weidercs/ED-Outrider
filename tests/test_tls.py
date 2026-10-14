"""Unit tests: outrider/tls.py, the one TLS context of every outgoing HTTPS connection (issue #9: Windows' certificate
store without a root it has not fetched yet, so "certificate has expired" for spansh.co.uk), and the plain words for a
certificate failure (outrider.health's "certificate" kind, the Data tile, the banner, the uploads' Recent list).
Nothing here touches the network: certifi is a fake module pointing at a test root in tests/fixtures, urlopen a fake.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import ast
import contextlib
import io
import os
import ssl
import sys
import types
import unittest
import unittest.mock
import urllib.error
import urllib.request

from support import ed_outrider  # also puts the repository root on sys.path
import outrider.health as H  # noqa: E402
import outrider.tls as tls  # noqa: E402
import outrider.uploads  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "tls_test_root.pem")
TEST_CN = "ED Outrider test root (tests only)"
ADVICE = "check this PC's date and time; if they are right, update Outrider"


def expired(code=10, message="certificate has expired"):
    """An ssl.SSLCertVerificationError as OpenSSL raises it (its verify code and message set)."""
    e = ssl.SSLCertVerificationError(1, f"[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: {message} (_ssl.c:1006)")
    e.verify_code, e.verify_message = code, message
    return e


def aiohttp_expired(host="spansh.co.uk"):
    """aiohttp's error for it, as issue #9's log has it."""
    from aiohttp import ClientConnectorCertificateError
    key = types.SimpleNamespace(host=host, port=443, is_ssl=True, ssl=True)
    return ClientConnectorCertificateError(key, expired())


def subjects(ctx):
    return {v for c in ctx.get_ca_certs() for rdn in c.get("subject", ()) for k, v in rdn if k == "commonName"}


class ContextTests(unittest.TestCase):

    def setUp(self):
        tls.client_context.cache_clear()
        self.addCleanup(tls.client_context.cache_clear)

    def made(self, certifi):
        """client_context() with `certifi` in sys.modules (None: not installed), the system store's own context
        recorded: (context, the contexts create_default_context made, stderr)."""
        real, made = ssl.create_default_context, []

        def system(*a, **k):
            made.append(real(*a, **k))
            return made[-1]
        err = io.StringIO()
        with unittest.mock.patch.dict(sys.modules, {"certifi": certifi}), \
                unittest.mock.patch.object(tls.ssl, "create_default_context", system), contextlib.redirect_stderr(err):
            ctx = tls.client_context()
            again = tls.client_context()
        self.assertIs(ctx, again)   # created once
        return ctx, made, err.getvalue()

    def test_system_store_plus_certifi(self):
        ctx, made, err = self.made(types.SimpleNamespace(where=lambda: TEST_ROOT))
        self.assertEqual(made, [ctx])                 # the system store's context (corporate roots keep working) ...
        self.assertIn(TEST_CN, subjects(ctx))         # ... with certifi's bundle loaded into it
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(err, "")

    def test_without_certifi_the_system_store_alone(self):
        ctx, made, err = self.made(None)              # None in sys.modules: import certifi raises ImportError
        self.assertEqual(made, [ctx])
        self.assertNotIn(TEST_CN, subjects(ctx))
        self.assertEqual(err.count("\n"), 1)          # said once, though asked twice
        self.assertIn("certifi is not installed", err)

    def test_an_unreadable_bundle_keeps_the_system_store(self):
        ctx, made, err = self.made(types.SimpleNamespace(where=lambda: os.path.join(REPO, "no-such-bundle.pem")))
        self.assertEqual(made, [ctx])
        self.assertIn("certifi's bundle could not be read", err)

    def test_connector_uses_it(self):
        import asyncio

        async def go():
            c = tls.connector()
            try:
                return c._ssl
            finally:
                await c.close()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIs(asyncio.run(go()), tls.client_context())


class UrlopenTests(unittest.TestCase):

    def test_context_given_and_a_certificate_failure_said(self):
        seen = []

        def fake(url, data=None, timeout=None, context=None):
            seen.append(context)
            raise urllib.error.URLError(expired())
        with unittest.mock.patch.object(tls.urllib.request, "urlopen", fake), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(tls.CertificateFailed) as cm:
                tls.urlopen("https://huggingface.co/rhasspy/piper-voices/x.json", timeout=5)
            self.assertIs(seen[0], tls.client_context())
        self.assertIsInstance(cm.exception, OSError)   # the callers' "except OSError" still catches it
        self.assertEqual(str(cm.exception), f"couldn't verify huggingface.co's certificate (expired): {ADVICE}")
        self.assertEqual(H.classify(cm.exception), ("certificate", False))

    def test_other_failures_pass_unchanged(self):
        boom = urllib.error.URLError(ConnectionRefusedError(111, "refused"))

        def fake(url, data=None, timeout=None, context=None):
            raise boom
        with unittest.mock.patch.object(tls.urllib.request, "urlopen", fake), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(urllib.error.URLError) as cm:
                tls.urlopen(urllib.request.Request("https://api.github.com/x"), timeout=5)
        self.assertIs(cm.exception, boom)


class ClassifyTests(unittest.TestCase):

    def test_certificate_errors(self):
        for exc in (expired(), aiohttp_expired(), urllib.error.URLError(expired())):
            self.assertEqual(H.classify(exc), ("certificate", False), exc)
        # any other TLS trouble stays "tls"
        self.assertEqual(H.classify(ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")), ("tls", False))

    def test_words(self):
        self.assertEqual(tls.cert_text(aiohttp_expired()), f"couldn't verify spansh.co.uk's certificate (expired): {ADVICE}")
        self.assertEqual(tls.cert_text(expired(9, "certificate is not yet valid"), "www.edsm.net"),
                         f"couldn't verify www.edsm.net's certificate (not valid yet): {ADVICE}")
        self.assertEqual(tls.cert_text(expired(20, "unable to get local issuer certificate"), "eddn.edcd.io"),
                         f"couldn't verify eddn.edcd.io's certificate (its issuer is not known here): {ADVICE}")
        self.assertEqual(tls.cert_text(expired(99, "something new")), f"couldn't verify the certificate (something new): {ADVICE}")
        self.assertEqual(tls.cert_text(ssl.SSLError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] x")), f"couldn't verify the certificate: {ADVICE}")


class HealthTests(unittest.TestCase):
    """The lookups' health keeps the words; the banner's one card; the uploads' Recent list."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def cards(self):
        return {n["key"]: n["text"] for n in self.state.notices.active()}

    def test_tile_and_banner(self):
        st, changes = self.state, []
        h = st.health
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            h.failed("spansh", TimeoutError())
            self.assertEqual(self.cards(), {})                      # a timeout: the tile only, for now
            h.failed("spansh", aiohttp_expired(), host="spansh.co.uk")   # the kind turned: a card at once
            down = st.payload()["health"]["down"]
            self.assertEqual([(d["kind"], d["text"]) for d in down],
                             [("certificate", f"couldn't verify spansh.co.uk's certificate (expired): {ADVICE}")])
            self.assertEqual(self.cards(), {"lookup_down:certificate":
                                            f"Spansh unavailable: couldn't verify spansh.co.uk's certificate (expired): {ADVICE}. "
                                            "Meanwhile Nearby and Search show what was kept from earlier."})
            h.on_change = lambda: changes.append(1) or st.health_changed()
            h.failed("edsm", aiohttp_expired("www.edsm.net"))          # its host from the error itself
            self.assertEqual(list(self.cards()), ["lookup_down:certificate"])   # one card for both
            self.assertTrue(self.cards()["lookup_down:certificate"].startswith("Spansh and EDSM unavailable: couldn't verify "
                                                                               "spansh.co.uk's certificate (expired)"))
            st.check_lookup_outages(1e12 - 1)   # never the "unavailable for over 10 minutes" card too
            h.ok("spansh")
            h.ok("edsm")
            self.assertEqual(self.cards(), {})
        self.assertIn(f"lookups: Spansh unavailable: couldn't verify spansh.co.uk's certificate (expired): {ADVICE}",
                      log.getvalue())   # Show log has it
        self.assertTrue(changes)

    def test_uploads_recent(self):
        r = outrider.uploads.Recent()
        r.add("eddn", {"at": 100, "raised": aiohttp_expired("eddn.edcd.io"), "error": str(aiohttp_expired("eddn.edcd.io")),
                       "results": [], "wait": 60})
        e = r.recent("eddn")[0]
        self.assertEqual((e["state"], e["kind"], e["say"]),
                         ("fail", "certificate", f"couldn't verify eddn.edcd.io's certificate (expired): {ADVICE}"))
        r.add("edsm", {"at": 100, "raised": TimeoutError(), "error": "timeout", "results": [], "wait": 60})
        self.assertIsNone(r.recent("edsm")[0]["say"])
        self.assertIn("certificate could not be verified", ed_outrider.State.DOWN_WORDS["certificate"])


class SourceWalkTests(unittest.TestCase):
    """Every outgoing connection goes through the shared context: a ClientSession is given connector=tls.connector(),
    a urlopen is outrider.tls's (or passes context=), a TCPConnector passes ssl=. A new one that forgets fails here."""

    # local connections only (the overlay window to this PC's own Outrider over http): nothing to verify
    EXEMPT = {("outrider/overlay_window.py", "build_opener")}

    def calls(self):
        files = ["ed_outrider.py"] + sorted(os.path.join("outrider", f) for f in os.listdir(os.path.join(REPO, "outrider"))
                                            if f.endswith(".py"))
        for rel in files:
            with open(os.path.join(REPO, rel), encoding="utf-8") as f:
                tree = ast.parse(f.read(), rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
                    yield rel, name, ast.unparse(func), node

    def test_every_session_and_urlopen_uses_the_shared_context(self):
        bad, counted = [], {"ClientSession": 0, "urlopen": 0}
        for rel, name, full, node in self.calls():
            kw = {k.arg: ast.unparse(k.value) for k in node.keywords if k.arg}
            if name == "ClientSession":
                counted[name] += 1
                if "tls.connector()" not in kw.get("connector", ""):
                    bad.append(f"{rel}:{node.lineno} ClientSession without connector=tls.connector()")
            elif name == "TCPConnector" and rel != "outrider/tls.py" and "ssl" not in kw:
                bad.append(f"{rel}:{node.lineno} TCPConnector without ssl=")
            elif name == "urlopen":
                counted[name] += 1
                ours = full in ("tls.urlopen", "outrider.tls.urlopen", "urlopen") and rel != "outrider/tls.py"
                if not ours and "context" not in kw:
                    bad.append(f"{rel}:{node.lineno} {full} without the shared context")
            elif name in ("build_opener", "HTTPSConnection") and (rel, name) not in self.EXEMPT:
                bad.append(f"{rel}:{node.lineno} {full}: give it the shared context (outrider.tls.client_context())")
        self.assertEqual(bad, [])
        self.assertGreaterEqual(counted["ClientSession"], 4)   # the walk sees them (main, assistant, uploads, MCP)
        self.assertGreaterEqual(counted["urlopen"], 4)         # tls's own, bio, tts twice

    def test_bare_urlopen_names_are_tls(self):
        """A bare `urlopen(...)` is allowed above only when the module took it from outrider.tls."""
        for rel, name, full, node in self.calls():
            if full == "urlopen":
                with open(os.path.join(REPO, rel), encoding="utf-8") as f:
                    src = f.read()
                self.assertIn("from .tls import urlopen", src, rel)
                self.assertNotIn("from urllib.request import urlopen", src, rel)


if __name__ == "__main__":
    unittest.main()

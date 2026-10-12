"""Auto-target's game window (outrider/game_window.py, S74): finding Elite's window by its own title, bringing it to the
front, saying whether it is in front. Every desktop here is a fake (support.FakeDesktop, a fake user32): no real
window is activated and no key is pressed."""
import types
import unittest

from support import FakeClock, FakeDesktop  # also puts the repository root on sys.path

import outrider.game_window as G  # noqa: E402
import outrider.overlay_tracking  # noqa: E402


class GameWindowLinux(unittest.TestCase):

    def window(self, desk, **kw):
        clock = FakeClock()
        return desk.window(clock=clock, sleep=clock.sleep, **kw), clock

    def test_brings_the_game_forward_from_the_browser(self):
        desk = FakeDesktop()
        gw, _ = self.window(desk)
        self.assertIsNone(gw.why_not())
        got = gw.bring_forward()
        self.assertEqual(got, {"front": True, "checked": True, "why": None})
        self.assertEqual(desk.activations(), ["0x03c00007"])   # the game's id, from wmctrl -lGx
        self.assertEqual(desk.active, FakeDesktop.GAME)
        self.assertIsNone(gw.front_why())
        self.assertEqual(gw.status(), {"front": True, "why": None})
        desk.active = FakeDesktop.BROWSER   # you clicked away: the check before the next key says so
        self.assertEqual(gw.front_why(), G.NOT_FRONT)

    def test_already_in_front_is_not_activated_again(self):
        desk = FakeDesktop(active=FakeDesktop.GAME)
        gw, _ = self.window(desk)
        self.assertEqual(gw.bring_forward()["front"], True)
        self.assertEqual(desk.activations(), [])

    def test_an_ignored_activation_is_seen(self):
        """A compositor that ignores X11 activation (Sway, Hyprland, focus-stealing prevention): the tracker never
        reports the game in front, so it is a no after FRONT_WAIT_S, not a guess."""
        desk = FakeDesktop(obeys=False)
        gw, clock = self.window(desk)
        t0 = clock()
        got = gw.bring_forward()
        self.assertEqual(got, {"front": False, "checked": True, "why": G.NOT_FRONT})
        self.assertGreaterEqual(clock() - t0, G.FRONT_WAIT_S)
        self.assertEqual(desk.activations(), ["0x03c00007"])
        self.assertEqual(gw.front_why(), G.NOT_FRONT)

    def test_only_the_games_own_title_counts(self):
        """A browser tab about the game (in front, so the overlay's looser match would pick it) is never the game."""
        desk = FakeDesktop(windows={0x2a00003: "Elite - Dangerous wiki — Mozilla Firefox"}, active=0x2a00003)
        gw, _ = self.window(desk)
        self.assertEqual(gw.bring_forward(), {"front": False, "checked": False, "why": G.NOT_FOUND})
        self.assertEqual(desk.activations(), [])
        self.assertEqual(gw.status(), {"front": False, "why": "no game window found"})
        self.assertEqual(gw.front_why(), G.NOT_FRONT)
        self.assertTrue(G.is_game_title(" Elite - Dangerous (CLIENT) "))
        self.assertFalse(G.is_game_title("Elite - Dangerous (CLIENT) - Mozilla Firefox"))
        # the overlay's own matching is unchanged: any title naming the game
        self.assertTrue(outrider.overlay_tracking.matches_window_title("Elite - Dangerous wiki"))
        # the game found again later: the status line follows
        desk.windows[FakeDesktop.GAME] = "Elite - Dangerous (CLIENT)"
        self.assertTrue(gw.bring_forward()["front"])
        self.assertEqual(gw.status(), {"front": True, "why": None})

    def test_no_wmctrl_or_no_display_checks_nothing(self):
        for kw, why in (({"tools": ("xprop",)}, "wmctrl is not installed"), ({"tools": ("wmctrl",)}, "xprop is not installed")):
            desk = FakeDesktop()
            gw, _ = self.window(desk, **kw)
            self.assertEqual(gw.why_not(), why)
            self.assertEqual(gw.bring_forward(), {"front": False, "checked": False, "why": why})
            self.assertEqual(desk.calls, [])   # nothing run at all
            self.assertEqual(gw.status(), {"front": False, "why": why})
        gw = G.GameWindow(platform="linux", run=FakeDesktop().run, environ={}, which=lambda t: "/usr/bin/" + t)
        self.assertEqual(gw.why_not(), "no X display (DISPLAY is not set)")
        self.assertEqual(G.GameWindow(platform="darwin").why_not(), "not on this system (darwin)")


class FakeUser32:
    """Win32's user32 as far as activation needs: the window in front changes only through SetForegroundWindow, and
    only while attached to the thread in front (what Windows asks of a background process)."""

    def __init__(self, front, iconic=False):
        self.front, self.iconic, self.calls, self.attached = front, iconic, [], False

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, *args))
            if name == "GetForegroundWindow":
                return self.front
            if name == "GetWindowThreadProcessId":
                return 77
            if name == "AttachThreadInput":
                self.attached = bool(args[2])
                return 1
            if name == "IsIconic":
                return self.iconic
            if name == "SetForegroundWindow" and self.attached:
                self.front = args[0]
            return 1
        return call


class GameWindowWindows(unittest.TestCase):
    """The Windows path (untried against the game): a fake tracker and a fake user32, never the real API."""

    def test_attaches_to_the_thread_in_front_and_never_presses_alt(self):
        user32, game = FakeUser32(front=0x500, iconic=True), 0x1234
        tracker = types.SimpleNamespace(missing=False, active_window_id=lambda: user32.front,
                                        poll=lambda: outrider.overlay_tracking.WindowState(
                                            0, 0, 1920, 1080, user32.front == game, True, identifier=hex(game)))
        clock = FakeClock()
        gw = G.GameWindow(platform="win32", tracker=tracker, user32=user32,
                          kernel32=types.SimpleNamespace(GetCurrentThreadId=lambda: 5), clock=clock, sleep=clock.sleep)
        self.assertIsNone(gw.why_not())
        self.assertEqual(gw.bring_forward(), {"front": True, "checked": True, "why": None})
        names = [c[0] for c in user32.calls]
        self.assertIn(("ShowWindow", game, G.SW_RESTORE), user32.calls)   # minimised: restored first
        self.assertIn(("AttachThreadInput", 5, 77, True), user32.calls)
        self.assertEqual(user32.calls[-1], ("AttachThreadInput", 5, 77, False))   # always let go
        self.assertLess(names.index("SetForegroundWindow"), len(names) - 1)
        self.assertFalse(any(n in ("keybd_event", "SendInput") for n in names))   # no Alt-key trick: no key at all
        self.assertIsNone(gw.front_why())
        user32.front = 0x500
        self.assertEqual(gw.front_why(), G.NOT_FRONT)


if __name__ == "__main__":
    unittest.main()

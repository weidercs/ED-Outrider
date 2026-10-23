"""Plugins: optional add-ons, each switched on by name in [plugins] enabled and configured in its own [plugins.<name>]
table. Nothing loads unless it is listed there.

A plugin is a folder holding plugin.py: shipped ones in outrider/plugins/<name>/, your own in data/plugins/<name>/ (a
shipped name wins). plugin.py may define:

- TITLE, DESCRIPTION: what Settings shows.
- settings(table) -> dict: its [plugins.<name>] table checked (a bad value reported on stderr, the default kept).
  Without it the table is passed as it is.
- tools(tool): read-only tools for the AI and the MCP bridge, registered as `@tool(name, description, params,
  required)` on an async fn(get, args, rows) like outrider/tools.py's own. Their names get the plugin's name in front;
  `get` may read the plugin's own GET routes (/api/plugins/<name>/<one segment>) besides Outrider's READ_ROUTES.
- setup(host): the server side, given a Host (below). A plugin that raises here is left out, said once.
- static/page.js, static/page.css: loaded into the page after page.js. The page API is window.Outrider: on(event, fn)
  for "data" (each payload), "speech" ({state: "start" | "end"}: Outrider is about to speak a line / has finished)
  and "plugin:<name>" (the Host's emit), plus api(path, options), esc(text) and toast(text).

The Host gives a plugin: route(method, path, handler) under /api/plugins/<name> (behind the same guards as every
route: Host names, other sites, the password), payload(fn) (its part of the page's payload, under plugins.<name>),
task(coroutine function) (started with Outrider, cancelled when it stops), voice(phrases, handler) (spoken questions
answered before the AI layer: handler(text) -> words), emit(kind, data) (an event every page receives), overlay(fn) (its part of the in-game overlay's Plugins panel: fn() ->
{title, lines, image, progress} or None, see outrider.overlay.plugins_panel), settings,
data_dir (data/plugins-data/<name>, made on first use) and state (Outrider's State, read with care).
"""
import asyncio
import importlib.util
import json
import os
import re
import sys
import time
import traceback
from collections import deque

from outrider import DATA_DIR

BUILTIN_DIR = os.path.dirname(os.path.abspath(__file__))
USER_DIR = os.path.join(DATA_DIR, "plugins")
DATA_ROOT = os.path.join(DATA_DIR, "plugins-data")
NAME = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
EVENTS_KEPT = 20   # a plugin's latest events in the payload (the page acts on those newer than it has seen)


def discover(dirs=None):
    """{name: folder} of every plugin found (a folder named like NAME holding plugin.py), the first directory winning."""
    found = {}
    for d in dirs if dirs is not None else (BUILTIN_DIR, USER_DIR):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            path = os.path.join(d, n)
            if NAME.fullmatch(n) and n not in found and os.path.isfile(os.path.join(path, "plugin.py")):
                found[n] = path
    return found


def load_module(name, folder):
    """plugin.py imported as outrider_plugin_<name> (its folder importable as a package for its own modules)."""
    mod_name = f"outrider_plugin_{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(folder, "plugin.py"),
                                                  submodule_search_locations=[folder])
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[mod_name]
        raise
    return module


def enabled_settings(cfg):
    """[plugins] enabled from a parsed config: (names, {name: its table}, problems). A name that is not one is left out,
    with the reason."""
    p = cfg.get("plugins") if isinstance(cfg.get("plugins"), dict) else {}
    raw, problems, names = p.get("enabled", []), [], []
    if not isinstance(raw, list):
        problems.append(f"[plugins] enabled = {raw!r} must be a list of plugin names, e.g. [\"audiobookshelf\"]")
        raw = []
    for n in raw:
        if isinstance(n, str) and NAME.fullmatch(n.strip()) and n.strip() not in names:
            names.append(n.strip())
        else:
            problems.append(f"[plugins] enabled: {n!r} is not a plugin name (lower case, digits, _)")
    tables = {n: dict(p[n]) for n in names if isinstance(p.get(n), dict)}
    return names, tables, problems


def tool_registrar(name, register):
    """The `tool` decorator a plugin's tools() gets: outrider.tools.tool with the plugin's name in front."""
    def tool(tool_name, description, params=None, required=()):
        return register(f"{name}_{tool_name}", description, params, required)
    return tool


def register_tools(names, tables=None, dirs=None, log=print):
    """For the MCP bridge (and the server): the enabled plugins' tools() into outrider.tools, their GET routes allowed.
    The plugins' names whose tools are in."""
    import outrider.tools as tools
    found, done = discover(dirs), []
    for n in names:
        if n not in found:
            continue
        try:
            module = load_module(n, found[n])
            if callable(getattr(module, "tools", None)):
                module.tools(tool_registrar(n, tools.tool))
                prefix = f"/api/plugins/{n}/"
                if prefix not in tools.READ_ROUTES:
                    tools.READ_ROUTES = tools.READ_ROUTES + (prefix,)
                done.append(n)
        except Exception as e:  # noqa: BLE001 -- a broken plugin leaves Outrider's own tools working
            log(f"plugin {n}: its tools could not load: {type(e).__name__}: {e}", file=sys.stderr)
    return done


class Host:
    """What one plugin is given (see the module's docstring)."""

    def __init__(self, name, settings, state=None, data_root=DATA_ROOT, bump=lambda: None):
        self.name, self.settings, self.state = name, settings, state
        self._data_root, self._bump = data_root, bump
        self.routes, self.tasks, self.voices = [], [], []
        self.payload_fn = self.overlay_fn = None
        self.events = deque(maxlen=EVENTS_KEPT)
        self._seq = 0

    @property
    def data_dir(self):
        d = os.path.join(self._data_root, self.name)
        os.makedirs(d, exist_ok=True)
        return d

    def route(self, method, path, handler):
        if not path.startswith("/") or ".." in path:
            raise ValueError(f"route path {path!r} must start with / ")
        self.routes.append((method.upper(), f"/api/plugins/{self.name}{path}", handler))

    def payload(self, fn):
        self.payload_fn = fn
        return fn

    def overlay(self, fn):
        self.overlay_fn = fn
        return fn

    def task(self, fn):
        self.tasks.append(fn)
        return fn

    def voice(self, phrases, handler):
        """Phrases (lower case, matched as whole words in what was asked) answered by handler(text) -> words."""
        self.voices.append(([str(p).lower().strip() for p in phrases if str(p).strip()], handler))

    def emit(self, kind, data=None):
        """An event every page receives once (window.Outrider.on("plugin:<name>")), newest EVENTS_KEPT kept."""
        self._seq += 1
        self.events.append({"seq": self._seq, "kind": str(kind), "data": data, "ts": time.time()})
        self._bump()


class Manager:
    """The enabled plugins of a running Outrider: loaded at start, their routes on the app, their parts of the payload,
    their tasks and voice phrases. `failed` {name: why} for the ones left out."""

    def __init__(self, names, tables, state=None, dirs=None, data_root=DATA_ROOT, bump=lambda: None, log=print):
        self.hosts, self.modules, self.failed = {}, {}, {}
        self._tasks = []
        self.log = log
        found = discover(dirs)
        for n in names:
            if n not in found:
                self.failed[n] = "not found (outrider/plugins or data/plugins)"
                continue
            try:
                module = load_module(n, found[n])
                table = tables.get(n, {})
                settings = module.settings(table) if callable(getattr(module, "settings", None)) else dict(table)
                host = Host(n, settings, state, data_root, bump)
                if callable(getattr(module, "setup", None)):
                    module.setup(host)
            except Exception as e:  # noqa: BLE001 -- a broken plugin is left out; Outrider runs without it
                self.failed[n] = f"{type(e).__name__}: {e}"
                traceback.print_exc()
                continue
            self.hosts[n], self.modules[n] = host, (module, found[n])
        for n, why in self.failed.items():
            log(f"plugin {n}: left out: {why}", file=sys.stderr)
        if self.hosts:
            log("plugins: " + ", ".join(self.hosts))

    def mount(self, app):
        """Their routes, and their static/ folders at /plugins/<name>/static/."""
        for n, host in self.hosts.items():
            for method, path, handler in host.routes:
                app.router.add_route(method, path, handler)
            static = os.path.join(self.modules[n][1], "static")
            if os.path.isdir(static):
                app.router.add_static(f"/plugins/{n}/static/", static, show_index=False)

    def page_tags(self):
        """<link>/<script> tags for the plugins' page.css/page.js, stamped by modification time like page.js."""
        out = []
        for n in self.hosts:
            static = os.path.join(self.modules[n][1], "static")
            for f, tag in (("page.css", '<link rel="stylesheet" href="plugins/{n}/static/page.css?v={v}">'),
                           ("page.js", '<script src="plugins/{n}/static/page.js?v={v}"></script>')):
                try:
                    v = int(os.path.getmtime(os.path.join(static, f)))
                except OSError:
                    continue
                out.append(tag.format(n=n, v=v))
        return "".join(out)

    def payload(self):
        """{name: {data, events}} for the page; a payload function that raises gives {error} instead."""
        out = {}
        for n, host in self.hosts.items():
            part = {"events": list(host.events)}
            if host.payload_fn:
                try:
                    part["data"] = host.payload_fn()
                except Exception as e:  # noqa: BLE001 -- one plugin must not break the payload
                    part["error"] = f"{type(e).__name__}: {e}"
            out[n] = part
        return out

    def overlay_parts(self):
        """The in-game overlay's Plugins panel: each plugin's part that has one now (one that raises is left out)."""
        out = []
        for host in self.hosts.values():
            if host.overlay_fn:
                try:
                    part = host.overlay_fn()
                except Exception:  # noqa: BLE001 -- one plugin must not break the overlay
                    continue
                if isinstance(part, dict):
                    out.append(part)
        return out

    def info(self):
        """For Settings: every enabled plugin, loaded or not, and why not."""
        return [{"name": n, "title": getattr(self.modules[n][0], "TITLE", n), "loaded": True} for n in self.hosts] + \
            [{"name": n, "title": n, "loaded": False, "why": why} for n, why in self.failed.items()]

    def answer(self, text):
        """A spoken question one of the plugins' phrases matches: (plugin name, words), else None."""
        said = " " + re.sub(r"[^a-z0-9' ]+", " ", str(text).lower()) + " "
        said = re.sub(r"\s+", " ", said)
        for n, host in self.hosts.items():
            for phrases, handler in host.voices:
                if any(f" {p} " in said for p in phrases):
                    return n, handler(text)
        return None

    def start(self):
        """Their tasks, on the running loop."""
        loop = asyncio.get_running_loop()
        for n, host in self.hosts.items():
            for fn in host.tasks:
                self._tasks.append(loop.create_task(self._guard(n, fn)))

    async def _guard(self, name, fn):
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 -- said, and that task stops; the plugin's routes stay
            self.log(f"plugin {name}: a task stopped: {type(e).__name__}: {e}", file=sys.stderr)

    def tasks(self):
        return list(self._tasks)


def json_safe(value):
    """`value` if JSON can carry it, else its str (a plugin's payload must never break the page's)."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)

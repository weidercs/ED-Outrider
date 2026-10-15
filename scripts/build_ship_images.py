#!/usr/bin/env python3
"""Build static/ships/<symbol>.webp (the CMDR tab's Inventory: a ship's picture on a hover) from Elite Dangerous
Almanac's ship illustrations, fetched at a pinned commit: assets/ships/<Symbol>/illustration.svg for each hull (the
directories are the journal's ship symbols in their CamelCase: Explorer_NX, MediumTransport01, Krait_Light...).

Each SVG is drawn from the ship's 3D model and is large (up to about 2 MB, some 50 MB in all), so none is shipped:
each is rendered once with PyQt6's QSvgRenderer, offscreen, onto a transparent background at WIDTH x HEIGHT (the
SVGs' own 3:2) and saved as WebP under the journal's lower-case symbol (the page's SHIP_NAMES keys). Only the
illustrations are taken, never Almanac's data files. The pictures are Frontier's: static/ships/CREDITS.txt.

    .venv/bin/python scripts/build_ship_images.py            (48 downloads, about 50 MB; PyQt6 from requirements-overlay.txt)

To move to a newer Almanac, set COMMIT and COMMIT_DATE to its commit and run it again; a hull it adds is listed as
having no name in the page (add it to page.js's SHIP_NAMES). It writes only into static/ships/.
"""
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "https://github.com/Elite-Dangerous-Almanac/Almanac-Core"
COMMIT = "5da3bfca20aba4bb39332628e220ea2acb5dbcd9"   # main's head when built (2026-10-15)
COMMIT_DATE = "2026-09-26"
LIST_URL = "https://api.github.com/repos/Elite-Dangerous-Almanac/Almanac-Core/contents/assets/ships?ref={commit}"
URL = "https://raw.githubusercontent.com/Elite-Dangerous-Almanac/Almanac-Core/{commit}/assets/ships/{symbol}/illustration.svg"
OUT = os.path.join(ROOT, "static", "ships")
HEADERS = {"User-Agent": "ED-Outrider ship pictures build"}
WIDTH, HEIGHT = 600, 400   # the illustrations' viewBox is 1200 x 800
QUALITY = 80               # WebP quality: about 25-60 kB a hull, some 2 MB in all


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as r:
        return r.read()


def symbols():
    """The hulls at COMMIT: assets/ships' directory names, as Almanac spells them."""
    return sorted(x["name"] for x in json.loads(get(LIST_URL.format(commit=COMMIT))) if x.get("type") == "dir")


def render(svg):
    """One illustration as WebP bytes: WIDTH x HEIGHT, transparent around the ship."""
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QImage, QImageWriter, QPainter
    from PyQt6.QtSvg import QSvgRenderer
    r = QSvgRenderer(QByteArray(svg))
    if not r.isValid():
        raise ValueError("not a drawable SVG")
    img = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)   # transparent
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    w = QImageWriter(buf, b"webp")
    w.setQuality(QUALITY)
    if not w.write(img):
        raise ValueError(f"WebP not written: {w.errorString()}")
    buf.close()
    return bytes(data)


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # never a window on the display
    from PyQt6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv[:1])   # noqa: F841 (the QImage painting needs one)
    os.makedirs(OUT, exist_ok=True)
    total, done = 0, []
    for symbol in symbols():
        out = os.path.join(OUT, symbol.lower() + ".webp")
        webp = render(get(URL.format(commit=COMMIT, symbol=symbol)))
        with open(out + ".tmp", "wb") as f:
            f.write(webp)
        os.replace(out + ".tmp", out)
        total += len(webp)
        done.append(symbol.lower())
        print(f"{symbol.lower():28} {len(webp) / 1024:6.1f} kB")
    with open(os.path.join(ROOT, "static", "page.js"), encoding="utf-8") as f:
        page = f.read()
    named = page[page.index("const SHIP_NAMES"):]
    named = named[:named.index("};")]
    missing = [s for s in done if not re.search(rf"\b{s}:", named)]
    print(f"{len(done)} pictures, {total / 1024:.0f} kB in all, into {os.path.relpath(OUT, ROOT)}/ "
          f"(Almanac-Core {COMMIT[:12]}, {COMMIT_DATE})")
    if missing:
        print("not in page.js's SHIP_NAMES (no name for them there): " + ", ".join(missing))


if __name__ == "__main__":
    main()

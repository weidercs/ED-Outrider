"""Unit tests: the documentation's links. The README is a front page and the user guide is docs/guide/ (2026-10-07):
every relative link and image must reach a file, every #anchor a heading (or an explicit <a id>) of its page, the
README must index every guide page, and each page's nav bar must link all the others.

Run all: python3 -m unittest discover tests (or scripts/verify.sh).
"""
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slug(heading):
    """GitHub's anchor for a heading: lower case, punctuation and emoji gone, spaces to hyphens."""
    t = re.sub(r"[^\w\- ]", "", heading.lstrip("#").strip().lower())
    return t.replace(" ", "-")


def text_of(path):
    with open(path, encoding="utf-8") as f:
        return re.sub(r"```.*?```", "", f.read(), flags=re.S)   # code blocks hold no links


def anchors(path):
    s = text_of(path)
    return {slug(line) for line in s.split("\n") if line.startswith("#")} | set(re.findall(r'<a id="([^"]+)"', s))


def doc_files():
    return [os.path.join(ROOT, "README.md")] + sorted(glob.glob(os.path.join(ROOT, "docs", "guide", "*.md"))) + \
        sorted(glob.glob(os.path.join(ROOT, "docs", "*.md")))


class DocLinks(unittest.TestCase):

    def test_relative_links_and_anchors(self):
        bad = []
        for path in doc_files():
            s = text_of(path)
            for t in re.findall(r"\]\(([^)\s]+)\)", s) + re.findall(r'(?:href|src)="([^"]+)"', s):
                if re.match(r"(https?:|mailto:)", t) or t.startswith("<"):
                    continue
                target, _, frag = t.partition("#")
                dest = os.path.normpath(os.path.join(os.path.dirname(path), target)) if target else path
                where = os.path.relpath(path, ROOT)
                if not os.path.exists(dest):
                    bad.append(f"{where}: no file {t}")
                elif frag and dest.endswith(".md") and frag not in anchors(dest):
                    bad.append(f"{where}: no anchor {t}")
        self.assertEqual(bad, [])

    def test_guide_index_and_nav(self):
        pages = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "docs", "guide", "*.md")))
        self.assertGreater(len(pages), 5)
        readme = text_of(os.path.join(ROOT, "README.md"))
        for p in pages:
            self.assertIn(f"](docs/guide/{p})", readme, p)
        for p in pages:
            nav = text_of(os.path.join(ROOT, "docs", "guide", p)).split("\n", 1)[0]
            self.assertIn("](../../README.md)", nav, p)
            for other in pages:
                self.assertIn(f"]({other})" if other != p else "**", nav, (p, other))

    def test_old_readme_anchors_kept(self):
        """Links into the old single README (release notes, posts) still land: its sections' anchors stay."""
        kept = anchors(os.path.join(ROOT, "README.md"))
        for old in ("-running-as-a-server-docker", "-other-devices-on-your-network", "-the-neutron-highway", "-trading",
                    "-cargo-and-your-carrier", "-auto-honk", "-on-a-tablet", "-settings", "-the-voice", "-getting-started"):
            self.assertIn(old, kept)


if __name__ == "__main__":
    unittest.main()

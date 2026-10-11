"""GalNet News (this fork): Frontier's own feed of the game's news articles, read only, and the star systems an
article mentions. Pure: `parse` (the feed's answer as articles), `candidates` (what in an article's text may be a
system's name; ed_outrider.State.galnet_systems confirms each against your own records and Spansh before the page
marks it, so nothing is marked on a guess).

The feed is Frontier's community site's JSON:API (the one their GalNet pages read): newest first, a page at a time.
"""
import re

URL = "https://cms.zaonce.net/en-GB/jsonapi/node/galnet_article"
ARTICLES = 30           # how many of the latest are kept and listed
MAX_AGE_S = 1800        # s a copy is served before the feed is asked again (a Refresh asks at once)
TEXT_MAX = 20000        # characters of one article kept (they run to a few thousand)
ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")


def query(limit=ARTICLES):
    """The feed's request parameters: the latest `limit` articles, newest first."""
    return {"sort": "-published_at", "page[limit]": str(limit)}


def parse(answer, limit=ARTICLES):
    """The feed's answer as [{id, title, date (the in-game date as written, "08 OCT 3312"), published (ISO), text}],
    newest first, each article once. Raises ValueError for an answer of another shape (an error page, a notice)."""
    data = answer.get("data") if isinstance(answer, dict) else None
    if not isinstance(data, list):
        raise ValueError("it answered in an unexpected shape")
    out, seen = [], set()
    for item in data:
        at = item.get("attributes") if isinstance(item, dict) else None
        if not isinstance(at, dict):
            continue
        body = at.get("body")
        text = body.get("value") if isinstance(body, dict) else None
        title, ident = at.get("title"), at.get("field_galnet_guid") or item.get("id")
        if not (isinstance(title, str) and title.strip() and isinstance(text, str) and isinstance(ident, str)
                and ID_RE.fullmatch(ident)) or ident in seen:
            continue
        seen.add(ident)
        lines = [" ".join(ln.split()) for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        out.append({"id": ident, "title": " ".join(title.split()),
                    "date": at["field_galnet_date"].strip() if isinstance(at.get("field_galnet_date"), str) else None,
                    "published": at["published_at"] if isinstance(at.get("published_at"), str) else None,
                    "text": "\n".join(ln for ln in lines if ln)[:TEXT_MAX]})
    out.sort(key=lambda a: a["published"] or "", reverse=True)
    return out[:limit]


# ---- the systems an article mentions ----

# a word of a system's name as GalNet writes one: capitalised, a number, or a catalogue's letters ("HIP 22460",
# "Col 285 Sector KM-V d2-106", "LP 98-132")
_W = r"(?:[A-Z][\w'’+.-]*|\d[\w+.-]*|[a-h]\d+(?:-\d+)?)"
_NAME = rf"{_W}(?: {_W}){{0,6}}"
# "the Redonesses system", "the Sol and Achenar systems", "the LHS 20, Wolf 359 and Sol systems"
_BEFORE_SYSTEM = re.compile(rf"((?:{_NAME}(?:, | and |, and ))*{_NAME}) [Ss]ystems?\b")
_SPLIT = re.compile(r", and | and |, ")
# names that say what they are without the word: catalogue stars and the galaxy's sectors
_CATALOGUE = re.compile(r"\b(?:HIP|HD|HR|LHS|LTT|LFT|LP|GJ|Gliese|Wolf|Ross|NLTT|Lalande|Luyten|Groombridge) \d[\w.-]*\b")
_SECTOR = re.compile(r"\b[A-Z][a-z]+(?: [A-Z][a-z0-9]+| \d+){0,3} (?:Sector )?[A-Z]{2}-[A-Z] [a-h]\d+(?:-\d+)?\b")
# words a sentence puts before "system" that are no part of a name: dropped from the front of a candidate
_LEAD = frozenset("the a an in at of to from for and both near around within across throughout into via with by on "
                  "as its their his her our this that these those each every several many multiple other another "
                  "nearby neighbouring neighboring local home core entire whole same new old".split())
# and words that are never a system's name by themselves, whatever a name search may answer
NOT_NAMES = frozenset("federal imperial alliance independent solar star stellar planetary political legal judicial "
                      "security defence defense weapons life support navigation communications transport banking "
                      "economic financial caste class monitoring operating control tracking".split())
OPTIONS = 4             # how many forms of one mention are worth asking about


def candidates(text):
    """What in an article may be a system's name, in order, each as the forms to try from the longest: the
    capitalised words before "system" ("Imperial capital Achenar system": that run, then "Achenar"), and catalogue
    and sector names anywhere. [[form, shorter form, ...], ...], every form as written in the text; no mention
    twice."""
    found, seen = [], set()

    def add(forms):
        forms = [f for f in forms if len(f) >= 2 and f.lower() not in NOT_NAMES and re.search(r"[A-Za-z]{2}", f)][:OPTIONS]
        if forms and forms[0].lower() not in seen:
            seen.add(forms[0].lower())
            found.append(forms)

    spans = []   # (position, forms): kept in the article's order
    for m in _BEFORE_SYSTEM.finditer(text or ""):
        at = m.start(1)
        for part in _SPLIT.split(m.group(1)):
            words = part.split(" ")
            while words and words[0].lower() in _LEAD:   # "The Sol system": a sentence's first word
                words = words[1:]
            # the name may be only the last words of the run (a headline capitalises every word): the whole run
            # first, then its last three words, two, one
            spans.append((at, [" ".join(words)] + [" ".join(words[-k:]) for k in (3, 2, 1) if k < len(words)]))
            at += len(part) + 1
    for rx in (_CATALOGUE, _SECTOR):
        spans += [(m.start(), [m.group(0)]) for m in rx.finditer(text or "")]
    for _, forms in sorted(spans, key=lambda s: s[0]):
        add(forms)
    return found

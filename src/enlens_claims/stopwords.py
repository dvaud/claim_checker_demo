"""The common words of each language (0.17), for the glossary and the key terms of themes only.

Search keeps its own word rule (`textutil.STOPWORDS`, mostly English). The glossary needs more: in a project with
Dutch interviews "dan", "wel", "maar" and "ja" occur in two documents often enough to become terms, and a theme of the
interviews' passages was named after them and, when themes were found by words, held together by them. So the
glossary now reads each passage by the common words of its own language:

- Lists for 58 languages come with ENLENS (stopwords-iso 1.1.0, MIT licence: data/stopwords.json and
  data/stopwords-iso-LICENSE.txt). English and Dutch are ENLENS's own: stopwords-iso's English list leaves out
  "research", "world" and "zero" ("net zero"), and its Dutch list lacks the words of speech ("nou", "oké", "denk").
- A passage's language is the one whose common words it uses most: at least two different ones, and half as many
  again as its English common words (those it writes too, such as "in" and "is" in Dutch, speak for neither). A word that is also an English word ("care", "global", "door": `english_too`,
  made by tools/make_stopwords.py) tells nothing, so a heading or a table of an English report ("Net zero care
  homes") is never read as Romanian; one-letter words and numbers tell nothing either (some lists hold them). A
  passage that does not tell ("Ja.") takes the language of the passage before it in its document (the first ones: of
  the first passage that tells); a document that never tells is English.
- A term may not start or end with a common word of its passage's language, and English common words count in every
  passage (they are search's own). So a word that is also English ("die", "met", "net", "door") is a common word
  only in a passage of its own language, and "net zero" stays a term of an English report.
- A project can switch a language off (its passages are then read by the English rule) and list words of its own that
  are never a term, such as a speaker label ("Interviewer", "R1"); a phrase there leaves out that term only.
- A typed name or a key term is read by the English rule and the project's own words (`terms._key_of`): a term never
  starts or ends with a common word of any language that is not English, so this finds it whatever its language.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .textutil import STOPWORDS, STOPWORDS_V1, token_spans

NAMES = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali", "br": "Breton", "ca": "Catalan",
    "cs": "Czech", "da": "Danish", "de": "German", "el": "Greek", "en": "English", "eo": "Esperanto", "es": "Spanish",
    "et": "Estonian", "eu": "Basque", "fa": "Persian", "fi": "Finnish", "fr": "French", "ga": "Irish",
    "gl": "Galician", "gu": "Gujarati", "ha": "Hausa", "he": "Hebrew", "hi": "Hindi", "hr": "Croatian",
    "hu": "Hungarian", "hy": "Armenian", "id": "Indonesian", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "ku": "Kurdish", "la": "Latin", "lt": "Lithuanian", "lv": "Latvian", "mr": "Marathi", "ms": "Malay",
    "nl": "Dutch", "no": "Norwegian", "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
    "sk": "Slovak", "sl": "Slovenian", "so": "Somali", "st": "Sotho", "sv": "Swedish", "sw": "Swahili", "th": "Thai",
    "tl": "Tagalog", "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu", "vi": "Vietnamese", "yo": "Yoruba",
    "zh": "Chinese", "zu": "Zulu",
}
# a tie between two languages goes to the first of these (then to the code)
PRIORITY = {c: i for i, c in enumerate(("en", "nl", "de", "fr", "es", "pt", "it", "hu"))}

# English common words beyond search's: words that never start or end a term ("because", "themselves", "yeah"). Not
# "us" (the US), "down" (Down syndrome), "up" or "out" ("scale up", "phase out": see terms.GENERAL), "oh" (OH radicals).
ENGLISH = frozenset("""
about against because although though whereas whilst unless whether hence thereby furthermore nevertheless
nonetheless additionally besides myself yourself yourselves himself herself itself ourselves themselves theirs hers
yours anybody anyone anything everybody everyone everything nobody nothing somebody someone whoever whatever whenever
wherever yeah yep okay ok um uh uhm hmm erm isn aren wasn weren don doesn didn hasn haven hadn wouldn couldn shouldn
ll ve
""".split())

# Dutch: stopwords-iso's list without the words that start or end real terms ("eigen regie", "samen spelen", "vrije
# tijd"), and with the words of speech an interview is full of, Flemish ones included ("allee", "efkes").
DUTCH_TERMS = frozenset("eigen vrij klaar samen gelijk weg vol recent onzeker".split())
DUTCH_SPEECH = frozenset("""
nou nouja oké oke okee hè hoor allee awel efkes gij ofzo enzo enzovoort ehm eh uhm hm hmm ah oh joh jawel sowieso
trouwens best echt natuurlijk bijvoorbeeld belangrijk soms keer manier goed goede beter
zeg zegt zeggen zei denk denkt denken dacht weet weten wist gaan ga gaat ging gingen zien zie ziet zag kijken kijk
kijkt komen kom komt kwam vinden vind vindt vond zit zitten zat zet zetten laat laten geven geef geeft gaf krijgen
krijg krijgt kreeg staan sta staat stond blijft blijven bleef hangt hangen terug gedaan gebruik gebruikt gebruiken
leuk leuke fijn mooi lekker makkelijk makkelijker moeilijk moeilijker duidelijk groot grote hele helemaal dingen
ding volgende vast vaste houdt houden lang langer lastig horen hoort sneller qua gebeuren gebeurt gebeurde
""".split())

_DATA = Path(__file__).parent / "data" / "stopwords.json"
_EN_DETECT = frozenset(STOPWORDS_V1 | ENGLISH)   # English alone (search's list also holds other languages' words)
META = "glossary_words"
MAX_OWN = 500          # own words a project may list
MAX_OWN_CHARS = 80     # and the length of one


def _code_digest() -> str:
    """This file and its lists, as imported: a change to either reads the documents again."""
    try:
        data = Path(__file__).read_bytes() + _DATA.read_bytes()
    except OSError:   # installed without its source
        from . import __version__

        data = __version__.encode()
    return hashlib.sha1(data).hexdigest()[:16]


_CODE = _code_digest()


def _word(w: str) -> str | None:
    """A list's word as the word rule reads it (normalised, lower case), or None when it is not one word of two letters
    or more (some lists hold single letters, numbers, "aujourd'hui")."""
    w = w.strip()
    toks = token_spans(w, keep_stop=True)
    if len(toks) != 1 or toks[0][0] != 0 or toks[0][1] != len(w):
        return None
    word = toks[0][3]
    return word if len(word) > 1 and not word.isdigit() else None


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(_DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # a broken install: the English rule alone
        return {}


@lru_cache(maxsize=1)
def lists() -> dict[str, frozenset[str]]:
    """{language: its common words}; English is search's list with ENGLISH."""
    raw = _data().get("languages") or {}
    out: dict[str, frozenset[str]] = {}
    for code, words in raw.items():
        if code == "en" or code not in NAMES:
            continue
        s = {x for x in (_word(w) for w in words) if x}
        if code == "nl":
            s = (s - DUTCH_TERMS) | {x for x in (_word(w) for w in DUTCH_SPEECH) if x}
        out[code] = frozenset(s)
    out["en"] = frozenset(STOPWORDS | ENGLISH)
    return out


@lru_cache(maxsize=1)
def _index() -> dict[str, tuple[str, ...]]:
    """{word: the languages other than English that list it}, for the words that are no English word."""
    english = _EN_DETECT | {x for x in (_word(w) for w in _data().get("english_too") or ()) if x}
    idx: dict[str, list[str]] = defaultdict(list)
    for code, words in lists().items():
        if code == "en":
            continue
        for w in words:
            if w not in english and w.isalpha():
                idx[w].append(code)
    return {w: tuple(v) for w, v in idx.items()}


def detect(words: Iterable[str]) -> str | None:
    """The language of a passage from its (normalised) words, or None when it does not tell."""
    idx = _index()
    en: list[str] = []
    hits: Counter[str] = Counter()
    seen: dict[str, set[str]] = defaultdict(set)
    for w in words:
        if len(w) < 2 or not w.isalpha():
            continue
        if w in _EN_DETECT:
            en.append(w)
            continue
        for code in idx.get(w, ()):
            hits[code] += 1
            seen[code].add(w)
    told = [c for c in hits if len(seen[c]) >= 2]
    if told:
        best = min(told, key=lambda c: (-hits[c], -len(seen[c]), PRIORITY.get(c, len(PRIORITY)), c))
        # English words the language writes too ("in", "is" in Dutch) speak for neither
        theirs = lists().get(best, frozenset())
        if hits[best] > 1.5 * sum(1 for w in en if w not in theirs):
            return best
    return "en" if len(en) >= 2 else None


def fill(found: list[str | None]) -> list[str]:
    """Each passage's language, the ones that do not tell taking the one before them (the first ones: the first that
    tells; English when none does)."""
    first = next((c for c in found if c), "en")
    out, last = [], None
    for c in found:
        last = c or last
        out.append(last or first)
    return out


class Rules:
    """What a project's glossary leaves out: the common words of each language found (but those switched off) and
    the project's own words and phrases."""

    def __init__(self, off: Iterable[str] = (), own: Iterable[str] = ()):
        self.off = frozenset(c for c in off if c in NAMES and c != "en")
        self.own = tuple(own)
        english = lists()["en"]
        words: set[str] = set()
        phrases: set[str] = set()
        for entry in self.own:
            toks = token_spans(entry, keep_stop=True)
            # as a term is written: without English common words at its ends ("the care home" is "care home")
            while toks and (len(toks[0][3]) <= 1 or toks[0][3] in english):
                toks = toks[1:]
            while toks and (len(toks[-1][3]) <= 1 or toks[-1][3] in english):
                toks = toks[:-1]
            if len(toks) == 1:
                words.add(toks[0][3])
            elif toks:
                phrases.add(" ".join(t[2] for t in toks))
        self.words = frozenset(words)       # never at the start or end of a term
        self.phrases = frozenset(phrases)   # term keys (stems) left out
        self._stops: dict[str, frozenset[str]] = {}
        # what a document's reading depends on (a phrase only drops a term afterwards: no reading again for it) ...
        self.reading_digest = hashlib.sha1(json.dumps([_CODE, sorted(self.off), sorted(self.words)])
                                           .encode()).hexdigest()[:16]
        # ... and the whole of what the glossary leaves out
        self.digest = hashlib.sha1(json.dumps([self.reading_digest, sorted(self.phrases)]).encode()).hexdigest()[:16]

    def stops(self, code: str) -> frozenset[str]:
        """The words no term of a passage in that language starts or ends with."""
        s = self._stops.get(code)
        if s is None:
            ls = lists()
            s = ls["en"] | self.words
            if code != "en" and code not in self.off:
                s = s | ls.get(code, frozenset())
            s = self._stops[code] = frozenset(s)
        return s


DEFAULT = Rules()


def clean_own(own: Iterable) -> list[str]:
    """A person's own words as kept: trimmed, one space between words, without repeats (ignoring case)."""
    out: list[str] = []
    seen: set[str] = set()
    for e in own:
        if not isinstance(e, str):
            raise ValueError("List your own words as text, one word or phrase each.")
        e = re.sub(r"\s+", " ", e).strip()
        if not e or not token_spans(e, keep_stop=True):
            continue
        if len(e) > MAX_OWN_CHARS:
            raise ValueError(f"“{e[:30]}…” is longer than {MAX_OWN_CHARS} characters: list words or short phrases.")
        if e.lower() not in seen:
            seen.add(e.lower())
            out.append(e)
    if len(out) > MAX_OWN:
        raise ValueError(f"List at most {MAX_OWN} words of your own.")
    return out


def settings(ws) -> dict:
    """{"off": languages switched off, "own": the project's own words}."""
    v = ws.meta(META) or {}
    if not isinstance(v, dict):
        v = {}
    off = [c for c in (v.get("off") or []) if isinstance(c, str) and c in NAMES and c != "en"]
    own = [e for e in (v.get("own") or []) if isinstance(e, str)]
    return {"off": sorted(set(off)), "own": own}


def rules(ws) -> Rules:
    s = settings(ws)
    return Rules(s["off"], s["own"])


def found(ws) -> list[dict]:
    """The languages the glossary found, most passages first: {code, name, passages, on}. Empty before a glossary
    made by 0.17 or later."""
    counts = ws.meta("terms_languages") or {}
    off = set(settings(ws)["off"])
    rows = [{"code": c, "name": NAMES.get(c, c), "passages": int(n), "on": c not in off}
            for c, n in counts.items() if c in NAMES and int(n or 0) > 0]
    return sorted(rows, key=lambda r: (-r["passages"], r["name"]))


def save(ws, off: Iterable[str] | None = None, own: Iterable | None = None) -> dict:
    """Keep a project's choice (languages switched off, its own words); the glossary is made again when next needed.
    Only what is given changes (read and written in one transaction, so another window's change is kept). Returns the
    settings as kept. Like the glossary, they belong to this copy of the project (not synced)."""
    if off is not None:
        off = list(off)
        bad = [c for c in off if not isinstance(c, str) or c not in NAMES]
        if bad:
            raise ValueError(f"Unknown language: {bad[0]!r}.")
        if "en" in off:
            raise ValueError("English common words are always left out: search leaves them out too.")
    if own is not None:
        own = clean_own(own.splitlines() if isinstance(own, str) else own)
    from . import researchlog

    with ws.connect() as cx:
        before = settings(ws)
        cur = {"off": sorted(set(off)) if off is not None else before["off"],
               "own": own if own is not None else before["own"]}
        if before != cur:
            ws.set_meta(META, cur, cx)
            off_names = ", ".join(NAMES[c] for c in cur["off"]) or "none"
            researchlog.record(cx, "glossary-words", "Changed what the glossary and key terms leave out, in this copy "
                               f"of the project. Languages switched off: {off_names}. Own words: "
                               f"{', '.join(cur['own']) or 'none'}.", data={"before": before, "after": cur})
    return cur

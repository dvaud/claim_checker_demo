"""Text helpers: normalisation, exact quote matching with offsets, sentences, tokens."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# Characters that PDF extraction and language models swap freely. Mapping them to one form
# keeps the quote check strict about words while tolerant of typography.
_CHAR_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "​": "",
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
}

STOPWORDS = frozenset(
    "a an the of in on for and or to with by this that these those is are was were be been being it its "
    "as at from into than then there their they them which who whom whose what when where while also can "
    "could will would may might must shall should do does did has have had not no nor but if so such very "
    "more most other some any each all both few many much own same just only over under again further once "
    "here why how our ours we you your he she his her him i me my et al use used using between within "
    "however therefore thus via per".split()
)

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)


def clean_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d)
    d = d.rstrip(".,;:)]}>'\"")
    return d or None


def find_dois(text: str) -> list[str]:
    seen: list[str] = []
    for m in DOI_RE.finditer(text):
        d = clean_doi(m.group(1))
        if d and d not in seen:
            seen.append(d)
    return seen


def _norm_char(ch: str) -> str:
    if ch in _CHAR_MAP:
        return _CHAR_MAP[ch]
    if ch.isspace():
        return " "
    return ch


def normalise_with_map(text: str, drop_spaces: bool = False) -> tuple[str, list[int]]:
    """Return (normalised text, index map) where map[i] is the offset in `text` of normalised char i.

    Normalisation: NFKC per character, typographic quotes/dashes/ligatures unified, whitespace runs
    collapsed to one space (or removed when drop_spaces), lower case.
    """
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        rep = _norm_char(unicodedata.normalize("NFKC", ch) if ch not in _CHAR_MAP else ch)
        for r in rep:
            if r == " ":
                if drop_spaces or prev_space:
                    continue
                prev_space = True
            else:
                prev_space = False
            out.append(r.lower())
            idx.append(i)
    # strip a trailing space
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def normalise(text: str) -> str:
    return normalise_with_map(text)[0]


def find_quote(haystack: str, quote: str) -> tuple[int, int, str] | None:
    """Locate `quote` in `haystack`. Returns (start, end, match_type) in haystack offsets, or None.

    match_type "exact": equal after typography/whitespace/case normalisation.
    match_type "spacing": equal once all whitespace is ignored (PDF text often splits or joins words).
    Nothing looser is accepted: a paraphrase or an added word fails.
    """
    q = quote.strip()
    if len(normalise(q)) < 3:
        return None
    for drop, kind in ((False, "exact"), (True, "spacing")):
        nh, hmap = normalise_with_map(haystack, drop_spaces=drop)
        nq, _ = normalise_with_map(q, drop_spaces=drop)
        if not nq:
            continue
        pos = nh.find(nq)
        if pos >= 0:
            start = hmap[pos]
            end = hmap[pos + len(nq) - 1] + 1
            return start, end, kind
    return None


_ABBREV = re.compile(
    r"(?:\b(?:e\.g|i\.e|et al|etc|fig|figs|no|vs|approx|ca|cf|eq|ref|refs|dr|prof|mr|ms|st|vol|pp|resp|incl|esp|al)\.|\b[A-Z]\.)$",
    re.I,
)


def split_sentences(text: str, offset: int = 0) -> list[tuple[int, int]]:
    """Split into sentences; returns (start, end) spans (shifted by offset). Rule-based, abbreviation aware."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in re.finditer(r"[.!?](?:[\"'”’)\]]+)?(\s+)(?=[\"'“‘(\[]?[A-Z0-9])", text):
        end = m.start(1)  # just after the punctuation and any closing quote or bracket
        head = text[start:end]
        if _ABBREV.search(head):
            continue
        if re.fullmatch(r"\s*\d+\.", head):  # list numbering such as "3."
            continue
        if head.strip():
            s = start + (len(head) - len(head.lstrip()))
            spans.append((offset + s, offset + end))
        start = m.end()
    tail = text[start:]
    if tail.strip():
        s = start + (len(tail) - len(tail.lstrip()))
        spans.append((offset + s, offset + start + len(tail.rstrip())))
    return spans


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def stem(tok: str) -> str:
    for suf in ("ization", "isation", "ations", "ation", "ments", "ment", "ities", "ity", "ings", "ing", "ies", "ed", "es", "s"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            if suf == "ies":
                return tok[: -3] + "y"
            return tok[: -len(suf)]
    return tok


def tokens(text: str, keep_stop: bool = False) -> list[str]:
    toks = _TOKEN_RE.findall(normalise(text))
    if not keep_stop:
        toks = [t for t in toks if t not in STOPWORDS and len(t) > 1]
    return [stem(t) for t in toks]


def content_words(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(normalise(text)) if t not in STOPWORDS and len(t) > 3}


def overlap(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa:
        return 0.0
    return len(sa & sb) / len(sa)

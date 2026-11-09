"""Text helpers: normalisation, exact quote matching with offsets, sentences, tokens."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable

# Characters that PDF extraction and language models swap freely. Mapping them to one form
# keeps the quote check strict about words while tolerant of typography.
_CHAR_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ",
    "​": "", "­": "", "﻿": "",  # zero-width space, soft hyphen, byte-order mark
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
}
_TRANSLATE = str.maketrans(_CHAR_MAP)

STOPWORDS_V1 = frozenset(
    "a an the of in on for and or to with by this that these those is are was were be been being it its "
    "as at from into than then there their they them which who whom whose what when where while also can "
    "could will would may might must shall should do does did has have had not no nor but if so such very "
    "more most other some any each all both few many much own same just only over under again further once "
    "here why how our ours we you your he she his her him i me my et al use used using between within "
    "however therefore thus via per".split()
)

STOPWORDS = frozenset(
    "a an the of in on for and or to with by this that these those is are was were be been being it its "
    "as at from into than then there their they them which who whom whose what when where while also can "
    "could will would may might must shall should do does did has have had not no nor but if so such very "
    "more most other some any each all both few many much own same just only over under again further once "
    "here why how our ours we you your he she his her him i me my et al use used using between within "
    "however therefore thus via per "
    # frequent function words of other languages a corpus may hold (Dutch, German, French, Spanish, Portuguese)
    "de het een van voor op te zijn niet en dat ook als bij naar om aan "
    "der das und von mit dem ist im zu ein eine nicht auch auf sich "
    "la le les et des du en une est sur dans qui que "
    "el los las y del por para una es se "
    "da do dos das em os ao".split()
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


def _norm_cluster(cluster: str) -> str:
    """One base character with its combining marks, in normalised form (possibly empty or several characters)."""
    if len(cluster) == 1 and cluster < "\x80":
        return " " if cluster.isspace() else cluster.lower()
    if cluster in _CHAR_MAP:
        return _CHAR_MAP[cluster]
    rep = unicodedata.normalize("NFKC", cluster)
    if rep in _CHAR_MAP:
        return _CHAR_MAP[rep]
    # lower() may lengthen a character ('İ' -> 'i' + combining dot); every resulting character gets its own map entry
    return "".join(" " if c.isspace() else _CHAR_MAP.get(c, c) for c in rep).lower()


def _normalise_spans(text: str, drop_spaces: bool = False) -> tuple[str, list[int], list[int]]:
    """Normalised text with, for each of its characters, the start and end offset of its source in `text`.

    Combining marks are read together with the character before them, so 'e' + U+0301 matches 'é'.
    """
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    prev_space = True
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        for r in _norm_cluster(text[i:j]):
            if r == " ":
                if drop_spaces or prev_space:
                    continue
                prev_space = True
            else:
                prev_space = False
            out.append(r)
            starts.append(i)
            ends.append(j)
        i = j
    if out and out[-1] == " ":  # strip a trailing space
        out.pop()
        starts.pop()
        ends.pop()
    return "".join(out), starts, ends


def normalise_with_map(text: str, drop_spaces: bool = False) -> tuple[str, list[int]]:
    """Return (normalised text, index map) where map[i] is the offset in `text` of normalised char i.

    Normalisation: NFKC per character cluster, typographic quotes/dashes/ligatures unified, soft hyphens and
    zero-width characters removed, whitespace runs collapsed to one space (or removed when drop_spaces),
    lower case. The map always has one entry per normalised character.
    """
    norm, starts, _ends = _normalise_spans(text, drop_spaces)
    return norm, starts


def normalise(text: str) -> str:
    return _normalise_spans(text)[0]


def fast_normalise(text: str) -> str:
    """The same folding as `normalise` for searching (no offset map): much faster on long texts."""
    t = unicodedata.normalize("NFKC", text.translate(_TRANSLATE)).translate(_TRANSLATE)
    return " ".join(t.split()).lower()


_UNSPACED = ((0x0E00, 0x0EFF), (0x1000, 0x109F), (0x1780, 0x17FF), (0x2E80, 0x31FF), (0x3400, 0x4DBF),
             (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x3FFFF))  # Thai, Lao, Myanmar, Khmer, Chinese, Japanese


def _unspaced(c: str) -> bool:
    """A character of a script written without spaces between words: any place between two of them can be an edge."""
    o = ord(c)
    return any(a <= o <= b for a, b in _UNSPACED)


def _year_before(chars: str, j: int) -> bool:
    """Whether the digits just before index `j` of `chars` are a year (four digits, 1900 to 2099), not part of a
    longer number."""
    k = j
    while k > 0 and chars[k - 1].isdigit():
        k -= 1
    if j - k != 4 or chars[k:k + 2] not in ("19", "20"):
        return False
    return k == 0 or not (chars[k - 1].isdigit() or (chars[k - 1] in ".," and k >= 2 and chars[k - 2].isdigit()))


def _word_edge(orig: str, chars: str, starts: list[int], i: int, start: bool = False) -> bool:
    """Whether a word ends or begins before normalised character `i` of `chars` (`starts`: each one's offset in
    `orig`). Besides spaces and punctuation, PDF text glues some words together that are still separate words: a
    footnote number or a figure ("projects44", "2050expected") and a bullet before a capital ("rRenewables",
    "°CFading"). Two letters (or two digits) of one word are not an edge, nor the point or comma inside a number: a
    quote may not begin or end inside one ("5 percent" is not a quote of "2.5 percent", "rose by 2" not of "rose by
    2,500 tonnes"). One exception: a year followed by a full stop and digits, where the digits are a footnote number
    in PDF text ("by 2030.106 But": a quote may end with "by 2030")."""
    if i <= 0 or i >= len(chars):
        return True
    a, b = chars[i - 1], chars[i]
    if a in ".," and b.isdigit() and i >= 2 and chars[i - 2].isdigit():  # between "2." and "5"
        return not start and a == "." and _year_before(chars, i - 1)
    if b in ".," and a.isdigit() and i + 1 < len(chars) and chars[i + 1].isdigit():  # between "2" and ".5"
        return not start and b == "." and _year_before(chars, i)
    if not (a.isalnum() and b.isalnum()) or _unspaced(a) or _unspaced(b):
        return True
    if a.isdigit() != b.isdigit():
        return True
    oa, ob = orig[starts[i - 1]], orig[starts[i]]
    if oa.islower() and ob.isupper():
        return True
    return (oa.isupper() and ob.isupper() and i + 1 < len(chars) and starts[i + 1] != starts[i]
            and orig[starts[i + 1]].islower())


def find_quote(haystack: str, quote: str, whole_words: bool = True) -> tuple[int, int, str] | None:
    """Locate `quote` in `haystack`. Returns (start, end, match_type) in haystack offsets, or None.

    match_type "exact": equal after typography/whitespace/case normalisation.
    match_type "spacing": equal once whitespace is ignored where the text has more of it than the quote (PDF text
    often splits a word: "wi ll", "addition al").
    Nothing looser is accepted: a paraphrase or an added word fails.

    0.14.3: a quote is found only as whole words: it may not start or end inside a word of the text ("not" is not
    found in "another", "legal" not in "illegal"), and the spacing pass may not join two words the quote keeps apart
    ("now here" is not "nowhere"). `whole_words=False` keeps the looser search of before (to place a quote stored
    before 0.14.3); a person's own selection is found with `find_selection`.
    """
    q = (quote or "").strip()
    if len(normalise(q)) < 3:
        return None
    nh, hstart, hend = _normalise_spans(haystack)
    nq = _normalise_spans(q)[0]
    pos = nh.find(nq) if nq else -1
    while pos >= 0:
        end = pos + len(nq)
        if not whole_words or (_word_edge(haystack, nh, hstart, pos, True) and _word_edge(haystack, nh, hstart, end)):
            return hstart[pos], hend[end - 1], "exact"
        pos = nh.find(nq, pos + 1)
    # the spacing pass: every space is left out, and it is noted where the text had one before each character
    chars, starts, ends, gap = [], [], [], []
    prev = False
    for c, a, b in zip(nh, hstart, hend):
        if c == " ":
            prev = True
            continue
        chars.append(c)
        starts.append(a)
        ends.append(b)
        gap.append(prev)
        prev = False
    sh = "".join(chars)
    qc, qgap = [], []
    prev = False
    for c in nq:
        if c == " ":
            prev = True
            continue
        qc.append(c)
        qgap.append(prev)
        prev = False
    sq = "".join(qc)
    if not sq:
        return None

    def edge(i: int, start: bool = False) -> bool:
        return i <= 0 or i >= len(sh) or gap[i] or _word_edge(haystack, sh, starts, i, start)

    pos = sh.find(sq)
    while pos >= 0:
        end = pos + len(sq)
        # a space the quote puts between two words must be in the text too (or the text must have an edge there)
        if not whole_words or (edge(pos, True) and edge(end)
                               and all(edge(pos + k) for k in range(1, len(sq)) if qgap[k])):
            return starts[pos], ends[end - 1], "spacing"
        pos = sh.find(sq, pos + 1)
    return None


def find_selection(haystack: str, quote: str) -> tuple[int, int, str] | None:
    """A person's own selection in a text (0.14.3), found as a quote is; one that starts or ends inside a word (a
    selection dragged a little short) is widened to the whole words, so it is kept as whole words like every quote
    and found again wherever quotes are placed (highlights, the original file)."""
    hit = find_quote(haystack, quote)
    if hit:
        return hit
    hit = find_quote(haystack, quote, whole_words=False)
    if not hit:
        return None
    a, b, kind = hit

    def inside(c: str) -> bool:  # part of a word: a letter or digit, or a combining mark on one (not Chinese etc.)
        return (c.isalnum() or bool(unicodedata.combining(c))) and not _unspaced(c)

    while a > 0 and inside(haystack[a - 1]) and inside(haystack[a]):
        a -= 1
    while b < len(haystack) and inside(haystack[b - 1]) and inside(haystack[b]):
        b += 1
    return a, b, kind


MIN_GRADE_WORDS, MIN_GRADE_CHARS = 3, 15


def grade_quote_problem(quote: str | None) -> str | None:
    """0.14.3: what is wrong with the quote of a judgement (supports, partly supports, contradicts), or None. A quote
    shows a judgement only with a few words of context: "not" or "no effect" alone can be found almost anywhere."""
    q = " ".join((quote or "").split())
    words = 0
    for tok in q.split():  # in Chinese or Thai, written without spaces, a character is about a word
        u = sum(1 for c in tok if _unspaced(c))
        words += u + any(c.isalnum() and not _unspaced(c) for c in tok) if u else 1
    if words >= MIN_GRADE_WORDS or len(q) >= MIN_GRADE_CHARS:
        return None
    return (f"the quote {q[:80]!r} is too short to show the judgement: quote at least {MIN_GRADE_WORDS} words (or "
            f"{MIN_GRADE_CHARS} characters), copied exactly")


def partial_word_hint(haystack: str, quote: str) -> str:
    """When a quote is in the text only as part of a word (see `find_quote`), the words to say so; otherwise ""."""
    if find_quote(haystack, quote, whole_words=False):
        return (" (it is there only as part of a word, or with words the text writes together: quote whole words, "
                "exactly as written)")
    return ""


_ABBREV = re.compile(
    r"(?:\b(?:e\.g|i\.e|et al|etc|fig|figs|no|vs|approx|ca|cf|eq|ref|refs|dr|prof|mr|ms|st|vol|pp|resp|incl|esp|al)\.|\b[A-Z]\.)$",
    re.I,
)
# sentence ends exactly as in 0.4: passage boundaries (and so the SDG pack's tasks) stay the same on re-ingest
_SENT_END = re.compile(r"[.!?](?:[\"'”’)\]]+)?(\s+)(?=[\"'“‘(\[]?[A-Z0-9])")


def split_sentences(text: str, offset: int = 0) -> list[tuple[int, int]]:
    """Split into sentences; returns (start, end) spans (shifted by offset). Rule-based, abbreviation aware."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_END.finditer(text):
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


# Letters and digits of any script (the old [a-z0-9]+ split "économie" into "conomie" and dropped Greek, Cyrillic...)
_TOKEN_RE = re.compile(r"[^\W_]+")
_SUFFIXES = ("ization", "isation", "ations", "ation", "ments", "ment", "ities", "ity", "ings", "ing", "ies", "ed",
             "es", "s")


@lru_cache(maxsize=262144)
def stem(tok: str) -> str:
    """A light English suffix stripper: 'increase', 'increases', 'increased', 'increasing' all become 'increas'."""
    if len(tok) <= 3 or tok.isdigit():
        return tok
    for suf in _SUFFIXES:
        if len(tok) - len(suf) >= 3 and tok.endswith(suf):
            if suf == "s" and tok.endswith(("ss", "us", "is")):
                break  # 'stress', 'status', 'analysis'
            if suf == "ies":
                tok = tok[:-3] + "y"
            elif suf == "es" and tok[-3] not in "sxz" and not tok.endswith(("ches", "shes")):
                tok = tok[:-1]  # 'prices' -> 'price', but 'taxes' -> 'tax'
            else:
                tok = tok[: -len(suf)]
            break
    if len(tok) > 4 and tok.endswith("e"):
        tok = tok[:-1]
    return tok


def tokens(text: str, keep_stop: bool = False) -> list[str]:
    toks = _TOKEN_RE.findall(fast_normalise(text))
    if not keep_stop:
        toks = [t for t in toks if len(t) > 1 and t not in STOPWORDS]
    return [stem(t) for t in toks]


def token_spans(text: str, keep_stop: bool = False) -> list[tuple[int, int, str, str]]:
    """The words of `text` as `tokens` finds them, each with its place: (start, end, stem, word).

    One rule for both (`[^\\W_]+` on the normalised text, the same stop words and stemmer), so a search for "prices"
    finds "price" exactly as the checker's ranking does. `word` is the normalised (lower-case) surface form; `start`
    and `end` are offsets in `text`. With `keep_stop`, stop words and one-letter words are kept (for phrases).
    """
    out: list[tuple[int, int, str, str]] = []
    flat = text.lower() if text.isascii() else _one_to_one(text)
    if flat is not None:  # every character normalises to one character: offsets are unchanged
        for m in _TOKEN_RE.finditer(flat):
            w = m.group()
            if not keep_stop and (len(w) <= 1 or w in STOPWORDS):
                continue
            out.append((m.start(), m.end(), stem(w), w))
        return out
    norm, starts, ends = _normalise_spans(text)
    for m in _TOKEN_RE.finditer(norm):
        w = m.group()
        if not keep_stop and (len(w) <= 1 or w in STOPWORDS):
            continue
        out.append((starts[m.start()], ends[m.end() - 1], stem(w), w))
    return out


_ONE: dict[str, str | None] = {}


def _one_to_one(text: str) -> str | None:
    """`text` normalised character by character when every character becomes exactly one (most PDF text: accents,
    typographic quotes and dashes); None when one does not (ligatures, soft hyphens, combining marks), which then
    takes the exact but slower way."""
    out = []
    for ch in text:
        if ch < "\x80":
            out.append(ch.lower() if not ch.isspace() else " ")
            continue
        rep = _ONE.get(ch, "")
        if rep == "":
            if unicodedata.combining(ch):
                rep = None
            else:
                r = _norm_cluster(ch)
                rep = r if len(r) == 1 else None
            _ONE[ch] = rep
        if rep is None:
            return None
        out.append(rep)
    return "".join(out)


def surface_words(text: str) -> dict[str, str]:
    """{stem: the first word of the text with that stem}, for showing matched stems as the text writes them."""
    out: dict[str, str] = {}
    for w in _TOKEN_RE.findall(fast_normalise(text)):
        if len(w) > 1 and w not in STOPWORDS:
            out.setdefault(stem(w), w)
    return out


def is_stop(word: str) -> bool:
    """Whether `tokens` leaves this (normalised) word out."""
    return len(word) <= 1 or word in STOPWORDS


def content_words(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(fast_normalise(text)) if t not in STOPWORDS and len(t) > 3}


def overlap(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa:
        return 0.0
    return len(sa & sb) / len(sa)


# ---------------------------------------------------------------------------------------------
# The 0.4 tokenizer, kept for the SDG / value chain pack: its passage selections (screen, extraction per target,
# VCA verification sets) stay as they were, so re-running make-tasks on an older workspace queues no new work.
# Only the speed changed (it shares fast_normalise).
# ---------------------------------------------------------------------------------------------
_TOKEN_RE_V1 = re.compile(r"[a-z0-9]+")


@lru_cache(maxsize=262144)
def stem_v1(tok: str) -> str:
    for suf in ("ization", "isation", "ations", "ation", "ments", "ment", "ities", "ity", "ings", "ing", "ies", "ed", "es", "s"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            if suf == "ies":
                return tok[: -3] + "y"
            return tok[: -len(suf)]
    return tok


# 0.4's character map (without the soft hyphen and byte-order mark added in 0.5)
_CHAR_MAP_V1 = {k: v for k, v in _CHAR_MAP.items() if k not in ("\u00ad", "\ufeff")}


class _V1Table(dict):
    """0.4's per-character normalisation as a str.translate table, filled on first sight of each character."""

    def __missing__(self, code: int) -> str:
        ch = chr(code)
        rep = _CHAR_MAP_V1[ch] if ch in _CHAR_MAP_V1 else unicodedata.normalize("NFKC", ch)
        if rep in _CHAR_MAP_V1:
            rep = _CHAR_MAP_V1[rep]
        elif rep.isspace():
            rep = " "
        self[code] = rep
        return rep


_V1 = _V1Table()
_SPACES = re.compile(" {2,}")


def normalise_v1(text: str) -> str:
    """Exactly 0.4's `normalise`: per character NFKC and the 0.4 map, whitespace collapsed, lower case."""
    t = _SPACES.sub(" ", text.translate(_V1)).strip(" ")
    return t.lower() if t.isascii() else "".join(c.lower() for c in t)


def tokens_v1(text: str, keep_stop: bool = False) -> list[str]:
    toks = _TOKEN_RE_V1.findall(normalise_v1(text))
    if not keep_stop:
        toks = [t for t in toks if t not in STOPWORDS_V1 and len(t) > 1]
    return [stem_v1(t) for t in toks]


def _rule_digest() -> str:
    """0.16: the word rule as this program uses it, for the caches that keep words split by it (the keyword index,
    the glossary): this file's code as it was imported (an update replaces it on disk, not in a program already
    running), and the Unicode data that normalising and the word pattern follow (a newer Python may bring other)."""
    import hashlib
    import sys
    from pathlib import Path

    try:
        code = Path(__file__).read_bytes()
    except OSError:   # installed without its source: the version stands for it
        from . import __version__

        code = __version__.encode()
    extra = f"|{unicodedata.unidata_version}|{sys.version_info[0]}.{sys.version_info[1]}".encode()
    return hashlib.sha1(code + extra).hexdigest()[:16]


RULE_DIGEST = _rule_digest()

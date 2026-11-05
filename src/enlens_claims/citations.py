"""0.13.7: check the citations of a text against the sources they cite.

A text is the researcher's own draft (pasted, or read from a file without becoming one of the project's documents)
or one of the project's documents. ENLENS finds its citations, in the author-year styles ("(Smith & Jones, 2020)",
"Smith et al. (2020a) found…") and, with the text's numbered reference list, the numeric ones ("[3]", "[2–4]"); for
each it takes the claim in front of it and the sentences around it. Each cited work is looked up in the project's
bibliography (bibliography.py), and each work with a document in the project gets a check of its own: the claim,
against that document only, with the claim's context given to the AI as context (never as evidence). The check is an
ordinary check (claimcheck.py) with `origin="citation"` and the reference's id as `origin_id`, so every answer goes
through the quote check, a person can overrule it on the result page, and the result records how it was made.

Nothing here uses the AI: finding citations, their claims and their works runs on this computer. Only the checks do,
and they send what every check sends (the claim, here with its sentences, and the excerpts of the cited source), to
the route of Settings, within the AI settings of the text and of the source's document (access.citing_level).
"""
from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .store import Workspace, now
from .textutil import STOPWORDS, find_dois

MAX_REFS = 500             # citations checked from one text, as for Check several
MAX_CHARS = 2_000_000      # the longest text read
CONTEXT_CHARS = 600        # the sentences before a citation given as its context
SOURCES = {"paste": "Pasted text", "file": "File", "document": "Document of the project"}

# the answer about a citation, from its check's status: (group, words)
VERDICT = {
    "supported": ("accurate", "Source accurate"),
    "partially_supported": ("partly", "Only partly supported by the source"),
    "contradicted": ("contradicted", "The source says otherwise"),
    "contested": ("mixed", "The source says both"),
    "unsupported": ("not_found", "Not found in the source"),
    "no_passages": ("not_found", "Not found in the source"),
    "uncertain": ("unsure", "Unsure: read the excerpts"),
    "failed": ("failed", "The check did not work"),
    "waiting": ("checking", "Being checked"),
    "not_checked": ("checking", "Being checked"),
}
VERDICT_HELP = {
    "accurate": "An excerpt of the source says what your sentence says, and none says the opposite.",
    "partly": "The source says part of it (a narrower finding, another group or period, a weaker version), not all of "
              "it. Read the excerpts, then reword the sentence or add a source for the rest.",
    "contradicted": "An excerpt of the source says the opposite, and none supports it.",
    "mixed": "Some excerpts of the source support the sentence and others say the opposite.",
    "not_found": "None of the excerpts read says it. The source may say it in words the search missed: open the "
                 "excerpts and look for more evidence, or check that the right work is cited.",
    "unsure": "The AI was not sure enough about any excerpt for your strictness setting.",
    "failed": "The AI's answers could not be used. Open it to try again.",
    "checking": "The excerpts are being read.",
}
STATE_TEXT = {
    "no_work": "Not in your bibliography",
    "ambiguous": "Which work is it?",
    "no_document": "Its source is not in the project",
    "to_confirm": "Its document waits for your confirmation",
    "same_document": "It cites the text itself",
    "no_ai": "No AI may read it",
    "ready": "Not checked yet",
    "ignored": "Left out",
    "contrast": "Cited for another view (“but see”)",
}
NOTICE_GROUPS = ("contradicted", "partly", "mixed", "not_found", "unsure", "failed")


class CitationError(ValueError):
    pass


def _new_id() -> str:
    return "t" + uuid.uuid4().hex[:9]


# ------------------------------------------------------------------------------------------------------------------
# reading a text: names, years, citations
# ------------------------------------------------------------------------------------------------------------------
_UPPER = "".join(c for c in map(chr, range(0x41, 0x2B0)) if c.isupper())
_PARTICLE = r"(?:van|von|de|der|den|del|della|di|da|du|dos|das|le|la|ten|ter|op|zu|al|el|bin|ibn|mac|st\.?)"
_YEAR = r"(?:1[6-9]\d\d|20\d\d)[a-z]?"
_YEARISH = rf"(?:{_YEAR}|n\.\s?d\.|in\s+press|forthcoming)"
_LOCATOR = r"(?:\s*[,:]\s*(?:pp?\.\s*|pages?\s+|chapter\s+|ch\.\s*|section\s+|§\s*)?[\divxlcIVXLC]+(?:\s*[-–—]\s*[\divxlc]+)?)"
_YEARS_ONLY = re.compile(rf"\(\s*({_YEARISH}(?:\s*[,;]\s*{_YEARISH})*){_LOCATOR}?\s*\)")
_PAREN = re.compile(r"[(\[]([^()\[\]]{3,500})[)\]]")
_NUMERIC = re.compile(r"\[(\s*\d{1,3}(?:\s*[-–—,]\s*\d{1,3}){0,12}\s*)\]")
_YEAR_IN = re.compile(rf"(?<![\w-])({_YEARISH})(?![\w-])", re.I)
_LEADING = re.compile(r"^(?:(?:see(?:\s+also)?|e\.\s?g\.|eg\.?|cf\.|cf|i\.\s?e\.|for\s+(?:example|instance|a\s+review)|"
                      r"as\s+reviewed\s+(?:in|by)|reviewed\s+in|but\s+see|compare|also|and|or|in|by|from|after|"
                      r"quoted\s+in|cited\s+in)[,:]?\s+)+", re.I)
_HEADINGS = re.compile(
    r"^[ \t]*(?:\d+\.?\s*)?(references|reference\s+list|bibliography|works\s+cited|literature\s+cited|cited\s+literature|"
    r"literature|sources|literatur(?:verzeichnis)?|irodalom(?:jegyzék)?|felhasznált\s+irodalom|bronnen|literatuurlijst|"
    r"literatuur|références|bibliographie|referencias|bibliografía|riferimenti\s+bibliografici)[ \t]*:?[ \t]*$",
    re.I | re.M)
_ABBREV = {"al", "e.g", "eg", "i.e", "ie", "cf", "vs", "p", "pp", "fig", "figs", "no", "nos", "vol", "vols", "ed", "eds",
           "dr", "mr", "mrs", "ms", "prof", "st", "jr", "sr", "inc", "ltd", "co", "approx", "ca", "resp", "sec", "ch",
           "eq", "ref", "refs", "op", "cit", "ibid", "viz", "etc", "u.s", "u.k", "e.u", "n.d", "chap", "tab"}
_REPORTING = (r"(?:(?:have|has|had|also|further|recently|previously|similarly)\s+)*(?:found|find|finds|showed|shown|show|"
              r"shows|demonstrated|demonstrates|demonstrate|reported|reports|report|argued|argues|argue|noted|notes|"
              r"note|suggested|suggests|suggest|concluded|concludes|conclude|observed|observes|observe|stated|states|"
              r"state|claimed|claims|claim|estimated|estimates|estimate|indicated|indicates|indicate|revealed|reveals|"
              r"reveal|confirmed|confirms|confirm|documented|documents|document|explained|explains|explain|emphasised|"
              r"emphasized|emphasises|emphasizes|highlighted|highlights|highlight|pointed\s+out|points\s+out|wrote|"
              r"writes|write|proposed|proposes|propose|described|describes|describe|showed\s+us)")
_FRAME_AFTER = re.compile(
    rf"^[\s,;:]*(?:(?:in\s+(?:their|his|her|its)\s+)?(?:study|survey|review|analysis|paper|work|research|report|"
    rf"meta-analysis|experiment|findings?|results?|data|book|article|trial)\s+)?(?:,\s*)?(?:{_REPORTING}\s+)?(?:that\s+)?",
    re.I)
_FRAME_BEFORE = re.compile(
    r"[\s,;:]*(?:\b(?:(?:but\s+)?see(?:\s+also)?|contra|as\s+(?:shown|found|reported|argued|noted|described|discussed|suggested|demonstrated|"
    r"documented|observed)\s+(?:by|in)|according\s+to|see(?:\s+also)?|cf\.?|e\.\s?g\.,?|following|for\s+example|"
    r"for\s+instance|as\s+in|by|in))?[\s,;:(]*$", re.I)
_LEAD_WORDS = re.compile(r"^(?:and|but|while|whereas|although|though|which|or|so|yet|as|with)\s+", re.I)


def _fold(s: str) -> str:
    from .bibliography import _fold as fold

    return fold(s)


def _tokens(s: str) -> list[str]:
    return re.findall(r"[^\W_]+", _fold(s))


def _names(author: str) -> tuple[list[list[str]], bool, str | None]:
    """'Smith, Jones & Lee' → the surnames' words [['smith'], ['jones'], ['lee']]; 'Smith et al.' → et al. True;
    'World Health Organization [WHO]' → one name, and the abbreviation 'who' it stands for."""
    a = re.sub(r"\s+", " ", author).strip(" ,;:.")
    alias = None
    m = re.search(r"\s*\[([^\]]{2,15})\]\s*$", a) or re.search(r"\s*\(([A-Z][A-Z&.\- ]{1,14})\)\s*$", a)
    if m:
        alias, a = m.group(1), a[:m.start()].strip(" ,")
    a = re.sub(r"['’]s?$", "", a)  # Smith's
    etal = bool(re.search(r"\bet\.?\s*al\b\.?|\band\s+(?:colleagues|others|co-?workers)\b", a, re.I))
    a = re.sub(r",?\s*\bet\.?\s*al\b\.?|\s+and\s+(?:colleagues|others|co-?workers)\b", "", a, flags=re.I).strip(" ,")
    parts = [p for p in re.split(r"\s*(?:,\s*(?:and|&)\s+|\s+and\s+|\s*&\s*|,\s*)", a) if p and p.strip()]
    names = []
    for p in parts:
        toks = _tokens(p)
        if toks:
            names.append(toks)
    return names, etal, (_fold(alias).replace(".", "").replace(" ", "") if alias else None)


_NOT_NAMES = {"according", "moreover", "furthermore", "similarly", "recently", "notably", "importantly", "indeed",
              "likewise", "finally", "first", "second", "third", "here", "these", "those", "such", "our", "we", "they",
              "unlike", "like", "following", "both", "neither", "either", "each", "every", "some", "many", "most",
              "several", "previous", "prior", "earlier", "later", "recent", "early", "studies", "study", "research",
              "work", "evidence", "data", "authors", "researchers", "scholars", "table", "figure", "fig", "section",
              "chapter", "appendix", "see", "cf", "ibid", "since", "until", "during", "after", "before", "when",
              "where", "although", "though", "because", "therefore", "hence", "still", "today", "yesterday",
              "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
              "november", "december", "spring", "summer", "autumn", "winter", "fall"}
_AUTH_TOKEN = re.compile(r"et\s+al\.?|&|,|\[[^\]\s]{2,12}\]|[^\W\d_][\w'’\-]*\.?")
_CONTRAST = re.compile(r"(?:\bbut\s+(?:see|cf\.?)|\bcontra|\bcontrary\s+to|\bunlike|\bin\s+contrast\s+to|"
                       r"\bas\s+opposed\s+to)\s*$", re.I)


def _is_name(w: str) -> bool:
    lw = w.lower().rstrip(".")
    if w[:1] not in _UPPER:
        return False
    if w.rstrip(".").isupper() and len(w.rstrip(".")) >= 2:
        return True  # WHO, OECD
    return lw not in STOPWORDS and lw not in _NOT_NAMES


def _looks_like_author(author: str) -> bool:
    """Whether the words before a year can name an author: a capitalised word that is not a common word, no digits
    (Figure 3, COVID-19), not too long."""
    a = author.strip(" ,;:")
    if not a or len(a) > 160 or re.search(r"\d", a) or not re.search(rf"[{_UPPER}]", a):
        return False
    words = re.findall(r"[^\W\d_][\w'’\-]*", a)
    return bool(words) and len(words) <= 14 and any(_is_name(w) for w in words)


def _author_before(text: str, pos: int, floor: int) -> int | None:
    """Where the author words of a narrative citation begin, looking back from `pos` (the '(' before the year):
    names (several words: 'World Health Organization', 'J. Smith'), name particles ('van der Berg'), and between
    names ',' '&' 'and'; just before the year also 'et al.', a possessive or an abbreviation ('[WHO]'). None when
    no name stands there."""
    toks = [(m.start() + floor, m.end() + floor, m.group(0)) for m in _AUTH_TOKEN.finditer(text[floor:pos])]
    start, names, expect, end = None, 0, "first", pos
    for a, b, w in reversed(toks):
        if text[b:end].strip():
            break  # something else stands between (a digit, a bracket): the author words end here
        lw = w.lower().rstrip(".")
        if re.fullmatch(r"et\s+al", lw):
            kind = "etal"
        elif lw in ("&", "and", ","):
            kind = "join"
        elif w.startswith("["):
            kind = "alias"
        elif re.fullmatch(_PARTICLE, lw, re.I):
            kind = "particle"
        elif _is_name(w):
            kind = "name"
        else:
            break
        allowed = {"first": ("name", "alias", "etal"), "name": ("name",), "any": ("name", "particle", "join"),
                   "particle": ("particle", "name", "join")}[expect]
        if kind not in allowed or names >= 8:
            break
        if kind in ("name", "particle"):
            start = a
            names += kind == "name"
            expect = "any" if kind == "name" else "particle"
        else:
            expect = "name"  # a joiner, 'et al.' or an abbreviation: a name must come before it
        end = a
    if not names or start is None:
        return None
    if not _is_name(text[start:pos].split()[0]) and not re.fullmatch(_PARTICLE, text[start:pos].split()[0], re.I):
        return None
    return start


def _blocks(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Paragraphs: a blank line, or a line break after the end of a sentence or after a short line (a heading). A
    line break inside a sentence (a PDF's wrapped line) is not one."""
    out = []
    b = start
    for m in re.finditer(r"\n", text[start:end]):
        i = start + m.start()
        before = text[b:i].rstrip()
        line = before[before.rfind("\n") + 1:]
        nxt = text[i + 1:i + 3]
        blank = nxt.strip() == "" and "\n" in text[i + 1:i + 4]
        if blank or (before and before[-1] in ".!?:”\"") or len(line.strip()) < 60 or re.match(r"\s*[•\-–*]\s", nxt):
            if before.strip():
                out.append((b, i))
            b = i + 1
    if text[b:end].strip():
        out.append((b, end))
    return out


def _sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """The sentences of one paragraph, never split inside brackets, after an abbreviation or an initial."""
    out = []
    s = start
    depth = 0
    i = start
    while i < end:
        c = text[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        elif c in ".!?…" and depth == 0:
            j = i + 1
            while j < end and text[j] in "\"”’')]":
                j += 1
            k = j
            while k < end and text[k] in " \t\n":
                k += 1
            if k > j and k < end and (text[k] in _UPPER or text[k].isdigit() or text[k] in "\"“‘(["):
                word = re.search(r"([\w.]+)$", text[s:i])
                w = (word.group(1) if word else "").lower()
                if c == "." and (w in _ABBREV or w.rstrip(".") in _ABBREV or (len(w) == 1 and w.isalpha())):
                    i += 1
                    continue
                out.append((s, j))
                s = k
                i = k
                continue
        i += 1
    if text[s:end].strip():
        out.append((s, end))
    return out


def references_start(text: str) -> int | None:
    """Where the text's reference list begins (its heading), when it has one in its second half or later."""
    found = None
    for m in _HEADINGS.finditer(text):
        if m.start() >= len(text) * 0.3:
            found = m
    return found.start() if found else None


def numbered_list(text: str, start: int | None) -> dict[int, str]:
    """The entries of a numbered reference list ('[3] Smith J…', '3. Smith J…'), by number."""
    if start is None:
        return {}
    out: dict[int, str] = {}
    cur: int | None = None
    for line in text[start:].splitlines()[1:]:
        m = re.match(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})[.)])\s+(\S.*)$", line)
        if m:
            cur = int(m.group(1) or m.group(2))
            out[cur] = m.group(3).strip()
        elif cur is not None and line.strip():
            out[cur] += " " + line.strip()
        elif not line.strip():
            continue
    return out if len(out) >= 2 else {}


def _numbers(spec: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"\s*,\s*", spec.strip()):
        m = re.fullmatch(r"(\d{1,3})\s*[-–—]\s*(\d{1,3})", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b and b - a <= 30:
                out.extend(range(a, b + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def find_markers(text: str, end: int | None = None, entries: dict[int, str] | None = None) -> list[dict]:
    """Every citation in text[:end]: {start, end, kind (paren | narrative | numeric), refs: [{raw, author, year} or
    {raw, number, entry}], author_start (narrative)}, in reading order."""
    end = len(text) if end is None else end
    body = text[:end]
    found: list[dict] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    # narrative: Smith (2020), Smith and Jones (2019, p. 4), Smith et al.'s (2020a)
    for m in _YEARS_ONLY.finditer(body):
        a = _author_before(body, m.start(), max(0, m.start() - 160))
        if a is None:
            continue
        author = body[a:m.start()].strip()
        if not _looks_like_author(author):
            continue
        years = [y for y in re.split(r"\s*[,;]\s*", m.group(1)) if y.strip()]
        signal = "contrast" if _CONTRAST.search(body[max(0, a - 40):a]) else None
        found.append({"start": a, "end": m.end(), "kind": "narrative", "author_start": a,
                      "refs": [{"raw": f"{author} ({y.strip()})", "author": author, "year": y.strip(), "signal": signal}
                               for y in years]})
        taken.append((a, m.end()))
    # parenthetical: (Smith, 2020; Lee & Kim 2019a, p. 4), [Smith 2020]
    for m in _PAREN.finditer(body):
        if not free(m.start(), m.end()):
            continue
        inner = m.group(1)
        if not _YEAR_IN.search(inner) or _YEARS_ONLY.fullmatch(m.group(0)):
            continue
        refs = []
        last_author = None
        for item in re.split(r"\s*;\s*", inner):
            signal = "contrast" if re.match(r"(?:but\s+(?:see|cf\.?)|contra)\b", item.strip(), re.I) else None
            item = _LEADING.sub("", re.sub(r"^(?:but\s+(?:see|cf\.?)|contra)\s+", "", item.strip(), flags=re.I))
            ys = list(_YEAR_IN.finditer(item))
            if not ys:
                continue
            author = item[:ys[0].start()].strip(" ,")
            if not author and last_author:
                author = last_author
            if not _looks_like_author(author):
                continue
            last_author = author
            # several years for one author ("Smith 2019, 2020"), each its own work; a page after a year is not one
            years = [ys[0].group(1)]
            for y in ys[1:]:
                gap = item[ys[0].end():y.start()]
                if re.fullmatch(r"[\s,a-z0-9]*", gap, re.I) and not re.search(r"p\.|pp\.|page", gap, re.I):
                    years.append(y.group(1))
            for y in dict.fromkeys(years):
                refs.append({"raw": f"{author}, {y}", "author": author, "year": y, "signal": signal})
        if refs:
            found.append({"start": m.start(), "end": m.end(), "kind": "paren", "refs": refs})
            taken.append((m.start(), m.end()))
    # numeric: [3], [2, 5–7], read with the text's numbered reference list
    if entries:
        for m in _NUMERIC.finditer(body):
            if not free(m.start(), m.end()):
                continue
            nums = [n for n in _numbers(m.group(1)) if n in entries]
            if nums:
                found.append({"start": m.start(), "end": m.end(), "kind": "numeric",
                              "refs": [{"raw": f"[{n}] {entries[n][:160]}", "number": n, "entry": entries[n]}
                                       for n in nums]})
                taken.append((m.start(), m.end()))
    found.sort(key=lambda f: f["start"])
    return found


def _clean_claim(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"\(\s*\)|\[\s*\]|\s*\[[^\]\s]{2,12}\]", "", s)
    s = re.sub(r"^[\s,;:.\-–—]+", "", s)
    s = _LEAD_WORDS.sub("", s)
    s = re.sub(r"[\s,;:\-–—(]+$", "", s)
    s = re.sub(r"[\s,;:]+(?:and|but|or|while|whereas|as|see|yet)$", "", s, flags=re.I)
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    if s and s[-1] not in ".!?":
        s += "."
    return s


def _strip_markers(text: str, a: int, b: int, markers: list[dict]) -> str:
    """text[a:b] without the citations in it (a narrative citation keeps its author: 'Smith (2020)' → 'Smith')."""
    out = []
    i = a
    for mk in markers:
        if mk["end"] <= a or mk["start"] >= b:
            continue
        s, e = max(a, mk["start"]), min(b, mk["end"])
        out.append(text[i:s])
        if mk["kind"] == "narrative":
            par = text.find("(", mk["start"], mk["end"])
            if par > s:
                out.append(text[s:par])
        i = e
    out.append(text[i:b])
    return "".join(out)


def _words(s: str) -> int:
    return len(re.findall(r"[^\W_]{2,}", s))


def claim_span(text: str, sent: tuple[int, int], mk: dict, markers: list[dict]) -> tuple[int, int]:
    """The part of a sentence a citation stands for: before a parenthetical citation (from the citation before it in
    the sentence, else the sentence's start), after a narrative one ('Smith (2020) found that …' → what follows,
    to the next citation)."""
    s0, s1 = sent
    inside = [m for m in markers if s0 <= m["start"] < s1]
    i = inside.index(mk)
    nxt = inside[i + 1]["start"] if i + 1 < len(inside) else s1
    if mk["kind"] == "narrative":
        a, b = mk["end"], nxt
        frame = _FRAME_AFTER.match(text[a:b])
        least = 4
        if re.match(r"\s*[,;:]", text[a:b]) or re.search(r"\bthat\s*$", frame.group(0), re.I):
            a += frame.end()  # 'According to Smith (2020), X' and 'Smith (2020) found that X': X
            least = 2  # a clause of its own ('pay gaps widen')
        else:
            a = mk["start"]  # 'WHO (2019) warned about X': the author is the claim's subject
        if b < s1:  # '… reduce sick leave, but see Van der Berg (2022)': not part of the claim
            b = a + _FRAME_BEFORE.search(text[a:b]).start()
        if _words(_strip_markers(text, a, b, markers)) >= least:
            return a, b
        before = _FRAME_BEFORE.search(text[s0:mk["start"]])
        b2 = s0 + (before.start() if before else mk["start"] - s0)
        if _words(_strip_markers(text, s0, b2, markers)) >= 4:
            return s0, b2
        return s0, s1
    prev = inside[i - 1]["end"] if i > 0 else s0
    clause = _LEAD_WORDS.sub("", _strip_markers(text, prev, mk["start"], markers).strip(" ,;:"))
    a = prev if i > 0 and _words(clause) >= 2 else s0  # ', while productivity doubles (B)': its own clause
    if i > 0 and inside[i - 1]["kind"] == "narrative":
        a = s0  # 'WHO (2019) warned about X (see also WHO, 2021)': the whole statement
    b = a + _FRAME_BEFORE.search(text[a:mk["start"]]).start()
    if _words(_strip_markers(text, a, b, markers)) >= 3:
        return a, b
    return mk["end"], nxt if _words(_strip_markers(text, mk["end"], nxt, markers)) >= 3 else s1


def find_citations(text: str, limit: int = MAX_REFS) -> dict:
    """The citations of a text, each with its claim and context: {citations: [...], numeric_unread, refs_start}.
    Nothing is stored; `add_text` stores them."""
    ref_at = references_start(text)
    entries = numbered_list(text, ref_at)
    body_end = ref_at if ref_at is not None else len(text)
    markers = find_markers(text, body_end, entries)
    unread = 0
    if not entries:
        unread = sum(1 for m in _NUMERIC.finditer(text[:body_end]) if _numbers(m.group(1)))
    sents: list[tuple[int, int, int]] = []  # (start, end, paragraph start)
    for b0, b1 in _blocks(text, 0, body_end):
        for s0, s1 in _sentences(text, b0, b1):
            sents.append((s0, s1, b0))
    starts = [s[0] for s in sents]
    import bisect

    out = []
    n_refs = 0
    for mk in markers:
        j = bisect.bisect_right(starts, mk["start"]) - 1
        if j < 0:
            continue
        s0, s1, p0 = sents[j]
        # a citation just after the end of a sentence ("… rose.[3]", "… rose. (Smith, 2020)") belongs to it
        if (mk["kind"] != "narrative" and j > 0 and sents[j - 1][2] == p0
                and not _strip_markers(text, s0, mk["start"], markers).strip(" ,;:.")):
            s0, _e, p0 = sents[j - 1]
            s1 = max(s1, mk["end"])
        sentence_markers = [m for m in markers if s0 <= m["start"] < s1]
        if mk not in sentence_markers:
            sentence_markers = sorted(sentence_markers + [mk], key=lambda m: m["start"])
        a, b = claim_span(text, (s0, s1), mk, sentence_markers)
        lead = re.match(r"[\s,;:.\-–—]*(?:(?:and|but|while|whereas|although|though|or|so|yet)\b[\s,]*)?", text[a:b], re.I)
        a += lead.end() if lead and lead.end() < b - a else 0
        while b > a and text[b - 1] in " \t\n,;:(–—-":
            b -= 1
        claim = _clean_claim(_strip_markers(text, a, b, markers))
        if _words(claim) < 2:
            claim = _clean_claim(_strip_markers(text, s0, s1, markers))
        if len(claim) < 10:
            continue
        claim = claim[:1500]
        before = ""
        k = j - 1
        while k >= 0 and sents[k][2] == p0 and len(before) < CONTEXT_CHARS:
            before = text[sents[k][0]:sents[k][1]].strip() + (" " + before if before else "")
            k -= 1
        refs = mk["refs"][:max(0, limit - n_refs)]
        if not refs:
            break
        n_refs += len(refs)
        out.append({"start": mk["start"], "end": mk["end"], "kind": mk["kind"], "marker": text[mk["start"]:mk["end"]],
                    "sentence": re.sub(r"\s", " ", text[s0:s1]).rstrip(), "sentence_start": s0,
                    "claim": claim, "claim_start": a, "claim_end": b,
                    "before": re.sub(r"\s+", " ", before)[-CONTEXT_CHARS:].strip(), "refs": refs})
    return {"citations": out, "numeric_unread": unread, "refs_start": ref_at,
            "cut": n_refs >= limit and sum(len(m["refs"]) for m in markers) > limit}


# ------------------------------------------------------------------------------------------------------------------
# which work of the bibliography a citation names
# ------------------------------------------------------------------------------------------------------------------
class BibIndex:
    """The works of the project's bibliography, by their authors' surnames, for matching citations."""

    def __init__(self, ws: Workspace):
        self.items: dict[str, dict] = {}
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.by_doi: dict[str, str] = {}
        for r in ws.query("SELECT item_key, title, creators_json, year, doi, seq FROM bib_items ORDER BY seq"):
            creators = json.loads(r["creators_json"] or "[]")
            authors = [c for c in creators if c.get("role") in (None, "author")] or creators
            names = [_tokens(c.get("last") or c.get("name") or "") for c in authors]
            names = [n for n in names if n]
            orgs = {"".join(t[0] for t in n if t not in STOPWORDS) for c, n in zip(authors, names) if c.get("name")}
            it = {"key": r["item_key"], "title": r["title"] or "", "year": (r["year"] or "")[:4] or None,
                  "names": names, "orgs": orgs, "doi": (r["doi"] or "").lower()}
            self.items[r["item_key"]] = it
            if names:
                self.by_name[names[0][-1]].append(r["item_key"])
            for o in orgs:
                if len(o) >= 2:
                    self.by_name["~" + o].append(r["item_key"])
            if it["doi"]:
                self.by_doi[it["doi"]] = r["item_key"]

    def __len__(self) -> int:
        return len(self.items)

    @staticmethod
    def _same(cited: list[str], have: list[str]) -> bool:
        """The same name: the same last word (the surname), and the words of one inside the other's ('Berg' and
        'van den Berg', 'J. Smith' and 'Smith'), not two organisations sharing a word."""
        if not cited or not have or cited[-1] != have[-1]:
            return False
        c, h = set(cited), set(have)
        return c <= h or h <= c

    def _named(self, first: list[str], alias: str | None) -> list[str]:
        keys = [k for k in self.by_name.get(first[-1], []) if self._same(first, self.items[k]["names"][0])]
        if not keys and len(first) >= 2:  # an organisation spelt out: compare every word
            keys = [k for k, it in self.items.items() if it["names"] and self._same(first, it["names"][0])]
        if not keys and len(first) == 1 and 2 <= len(first[0]) <= 8:  # 'WHO' for World Health Organization
            keys = list(self.by_name.get("~" + first[0], []))
        if not keys and alias:
            keys = list(self.by_name.get("~" + alias, []))
        return list(dict.fromkeys(keys))

    def match(self, author: str, year: str | None) -> dict:
        """{state: auto | ambiguous | none, key, candidates}: the work an author-year citation names."""
        names, etal, alias = _names(author)
        if not names:
            return {"state": "none", "key": None, "candidates": []}
        y = suffix = None
        m = re.match(r"(\d{4})([a-z]?)", (year or "").strip())
        if m:
            y, suffix = m.group(1), m.group(2) or None
        same_name = self._named(names[0], alias)
        if not same_name and len(names) > 1:  # 'Sweden, Lindqvist (2025)': a word before the author's name
            names = names[1:]
            same_name = self._named(names[0], None)
        cands = [k for k in same_name if self.items[k]["year"] == y]
        if len(cands) > 1 and len(names) >= 2:
            second = [k for k in cands if len(self.items[k]["names"]) > 1 and self._same(names[1], self.items[k]["names"][1])]
            cands = second or cands
        if len(cands) > 1:
            if etal:
                more = [k for k in cands if len(self.items[k]["names"]) >= 2]
                cands = more or cands
            elif len(names) == 1:
                one = [k for k in cands if len(self.items[k]["names"]) == 1]
                cands = one or cands
        if len(cands) > 1 and suffix:  # 2020a, 2020b: in the order of their titles, as APA lists them
            ordered = sorted(cands, key=lambda k: _fold(self.items[k]["title"]))
            i = ord(suffix) - ord("a")
            if 0 <= i < len(ordered):
                return {"state": "auto", "key": ordered[i], "candidates": ordered}
        if len(cands) == 1:
            return {"state": "auto", "key": cands[0], "candidates": []}
        if cands:
            return {"state": "ambiguous", "key": None, "candidates": cands[:8]}
        # the author is there with another year: a wrong year is worth a look, so the person decides
        near = sorted(same_name, key=lambda k: abs(int(self.items[k]["year"] or 0) - int(y or 0)))
        return {"state": "none", "key": None, "candidates": near[:5]}

    def match_entry(self, entry: str) -> dict:
        """The work an entry of a numbered reference list is: its DOI, else its title with its first author, else
        its first author and year."""
        for d in find_dois(entry):
            k = self.by_doi.get(d.lower())
            if k:
                return {"state": "auto", "key": k, "candidates": []}
        toks = set(_tokens(entry))
        best = []
        for k, it in self.items.items():
            sig = [t for t in _tokens(it["title"]) if (len(t) > 2 or t.isdigit()) and t not in STOPWORDS]
            if len(sig) >= 2 and sum(t in toks for t in sig) >= 0.85 * len(sig):
                if not it["names"] or it["names"][0][-1] in toks:
                    best.append(k)
        if len(best) == 1:
            return {"state": "auto", "key": best[0], "candidates": []}
        if best:
            return {"state": "ambiguous", "key": None, "candidates": best[:8]}
        m = re.match(r"\s*([^,.(]{2,60})", entry)
        y = _YEAR_IN.search(entry)
        if m and y:
            return self.match(m.group(1), y.group(1))
        return {"state": "none", "key": None, "candidates": []}


# ------------------------------------------------------------------------------------------------------------------
# storing a text and its citations
# ------------------------------------------------------------------------------------------------------------------
def read_draft(path: Path) -> tuple[str, list[int], str]:
    """The text of a draft file (as ENLENS reads documents, without adding it): (text, the start of each page, its
    title)."""
    from .ingest import SUPPORTED, read_file

    if path.suffix.lower() not in SUPPORTED:
        raise CitationError("ENLENS reads PDF, Word (.docx), text, Markdown and web pages (.html).")
    try:
        raw = read_file(path)
    except Exception as e:  # noqa: BLE001 - a broken or protected file
        raise CitationError(f"This file could not be read ({e}).") from None
    starts, parts, at = [], [], 0
    for page in raw.pages:
        starts.append(at)
        parts.append(page)
        at += len(page) + 2
    text = "\n\n".join(parts)
    if not text.strip():
        raise CitationError("No text could be read from this file (a scanned PDF needs OCR: add it as a document).")
    return text, (starts if raw.paginated and len(starts) > 1 else []), (raw.meta_title or path.stem)


def _page_at(starts: list[int], offset: int) -> int | None:
    import bisect

    return bisect.bisect_right(starts, offset) if starts else None


def add_text(ws: Workspace, text: str | None = None, title: str | None = None, doc_id: str | None = None,
             ai_access: str | None = None, file_name: str | None = None, page_starts: list[int] | None = None) -> str:
    """Store a text and the citations found in it; returns its id. `doc_id`: one of the project's documents (its own
    AI setting applies); otherwise `text` is the person's draft (pasted, or read from `file_name`) with `ai_access`
    (cloud, local, none; the project's default when None)."""
    from . import access

    source = "paste"
    if doc_id:
        row = ws.query("SELECT title, text FROM documents WHERE doc_id=?", (doc_id,))
        if not row:
            raise KeyError("No such document.")
        text, source, title = row[0]["text"] or "", "document", title or row[0]["title"]
        page_starts = [r["start"] for r in ws.query("SELECT start FROM pages WHERE doc_id=? ORDER BY page", (doc_id,))]
        ai_access = None
    else:
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
        if file_name:
            source = "file"
        lv = access.clean(ai_access) if ai_access else None
        ai_access = lv or access.default(ws)
    if len(text.strip()) < 20:
        raise CitationError("Paste or choose a text with at least one sentence.")
    if len(text) > MAX_CHARS:
        raise CitationError("This text is too long (more than two million characters).")
    found = find_citations(text)
    if not found["citations"] and not found["numeric_unread"]:
        raise CitationError("No citations were found in this text. ENLENS reads author-year citations such as "
                            "(Smith, 2020) and Smith et al. (2020), and numbered ones such as [3] when the text "
                            "ends with its numbered reference list.")
    tid = _new_id()
    title = re.sub(r"\s+", " ", title or "").strip()[:200] or (file_name or "Pasted text")
    index = BibIndex(ws)
    with ws.connect() as cx:
        cx.execute("INSERT INTO cite_texts(text_id, title, source, doc_id, file_name, body, pages_json, ai_access, "
                   "numeric_unread, cut, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (tid, title, source, doc_id, file_name, None if doc_id else text,
                    json.dumps(page_starts or []), ai_access, found["numeric_unread"], int(bool(found["cut"])), now()))
        for n, c in enumerate(found["citations"], 1):
            cid = f"{tid}-{n}"
            cx.execute("INSERT INTO citations(cite_id, text_id, n, start, end, kind, marker, sentence, claim, claim_start, "
                       "claim_end, before, page) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (cid, tid, n, c["start"], c["end"], c["kind"], c["marker"], c["sentence"], c["claim"],
                        c["claim_start"] - c["sentence_start"], c["claim_end"] - c["sentence_start"], c["before"],
                        _page_at(page_starts or [], c["start"])))
            for m, r in enumerate(c["refs"], 1):
                got = (index.match_entry(r["entry"]) if "entry" in r else index.match(r["author"], r.get("year")))
                cx.execute("INSERT INTO cite_refs(ref_id, cite_id, text_id, n, raw, author, year, number, item_key, how, "
                           "candidates_json, ignored, signal) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (f"{cid}-{m}", cid, tid, m, r["raw"][:300], r.get("author"), r.get("year"),
                            r.get("number"), got["key"], got["state"], json.dumps(got["candidates"]),
                            int(r.get("signal") == "contrast"), r.get("signal")))
    return tid


def rematch(ws: Workspace, text_id: str) -> int:
    """Match again the references not checked yet and not decided by a person (the bibliography may have changed
    since the text was added). Returns how many changed."""
    index = BibIndex(ws)
    checked = set(_checks(ws, text_id))
    n = 0
    rows = ws.query("SELECT * FROM cite_refs WHERE text_id=? AND how != 'person'", (text_id,))
    entries: dict[int, str] | None = None
    with ws.connect() as cx:
        for r in rows:
            if r["ref_id"] in checked:
                continue
            if r["number"] is not None:
                if entries is None:
                    t = _body(ws, text_id)
                    entries = numbered_list(t, references_start(t))
                got = index.match_entry(entries.get(r["number"], "")) if entries.get(r["number"]) else None
                if got is None:
                    continue
            else:
                got = index.match(r["author"] or "", r["year"])
            if got["key"] != r["item_key"] or got["state"] != r["how"]:
                cx.execute("UPDATE cite_refs SET item_key=?, how=?, candidates_json=? WHERE ref_id=?",
                           (got["key"], got["state"], json.dumps(got["candidates"]), r["ref_id"]))
                n += 1
    return n


def _body(ws: Workspace, text_id: str) -> str:
    r = ws.query("SELECT body, doc_id FROM cite_texts WHERE text_id=?", (text_id,))
    if not r:
        raise KeyError("No such text.")
    if r[0]["doc_id"]:
        return ws.scalar("SELECT text FROM documents WHERE doc_id=?", (r[0]["doc_id"],)) or ""
    return r[0]["body"] or ""


def choose_work(ws: Workspace, ref_id: str, item_key: str | None) -> None:
    """A person's word on which work a citation names (None: back to what the matching finds). A check already made
    against another work is removed: it answered another question."""
    r = ws.query("SELECT text_id, item_key FROM cite_refs WHERE ref_id=?", (ref_id,))
    if not r:
        raise KeyError("No such citation.")
    if item_key and not ws.scalar("SELECT 1 FROM bib_items WHERE item_key=?", (item_key,)):
        raise KeyError("No such work in the bibliography.")
    if item_key != r[0]["item_key"]:
        _drop_checks(ws, [ref_id])
    with ws.connect() as cx:
        if item_key:
            cx.execute("UPDATE cite_refs SET item_key=?, how='person', ignored=0 WHERE ref_id=?", (item_key, ref_id))
        else:
            cx.execute("UPDATE cite_refs SET item_key=NULL, how='none' WHERE ref_id=?", (ref_id,))
    if not item_key:
        rematch(ws, r[0]["text_id"])


def set_ignored(ws: Workspace, ref_id: str, ignored: bool) -> None:
    """'Not a citation' (a year in brackets that is not one) and 'Put back'."""
    if not ws.scalar("SELECT 1 FROM cite_refs WHERE ref_id=?", (ref_id,)):
        raise KeyError("No such citation.")
    with ws.connect() as cx:
        cx.execute("UPDATE cite_refs SET ignored=? WHERE ref_id=?", (int(bool(ignored)), ref_id))


def set_text(ws: Workspace, text_id: str, title: str | None = None, ai_access: str | None = None) -> None:
    """Rename a text, or change who may read a draft with AI (a document keeps its own setting). Tasks not answered
    yet take the new setting at once."""
    from . import access

    r = ws.query("SELECT doc_id FROM cite_texts WHERE text_id=?", (text_id,))
    if not r:
        raise KeyError("No such text.")
    with ws.connect() as cx:
        if title is not None and title.strip():
            cx.execute("UPDATE cite_texts SET title=? WHERE text_id=?", (re.sub(r"\s+", " ", title).strip()[:200], text_id))
        if ai_access is not None:
            if r[0]["doc_id"]:
                raise CitationError("A document of the project keeps its own AI setting (Documents page).")
            lv = access.clean(ai_access)
            if lv is None:
                raise CitationError("ai_access must be cloud, local or none.")
            cx.execute("UPDATE cite_texts SET ai_access=? WHERE text_id=?", (lv, text_id))
            access.relabel(cx)


def remove_text(ws: Workspace, text_id: str) -> None:
    """A text, its citations and their checks."""
    if not ws.scalar("SELECT 1 FROM cite_texts WHERE text_id=?", (text_id,)):
        raise KeyError("No such text.")
    _drop_checks(ws, [r[0] for r in ws.query("SELECT ref_id FROM cite_refs WHERE text_id=?", (text_id,))])
    with ws.connect() as cx:
        cx.execute("DELETE FROM cite_refs WHERE text_id=?", (text_id,))
        cx.execute("DELETE FROM citations WHERE text_id=?", (text_id,))
        cx.execute("DELETE FROM cite_texts WHERE text_id=?", (text_id,))


def remove_document(ws: Workspace, doc_id: str) -> None:
    """A document removed from the project takes the texts read from it along."""
    for (tid,) in ws.query("SELECT text_id FROM cite_texts WHERE doc_id=?", (doc_id,)):
        remove_text(ws, tid)


def _drop_checks(ws: Workspace, ref_ids: list[str]) -> None:
    from .claimcheck import delete_hypothesis

    if not ref_ids:
        return
    marks = ",".join("?" * len(ref_ids))
    for (hid,) in ws.query(f"SELECT hyp_id FROM hypotheses WHERE origin='citation' AND origin_id IN ({marks})", ref_ids):
        delete_hypothesis(ws, hid)


def _checks(ws: Workspace, text_id: str | None = None) -> dict[str, str]:
    """{ref_id: its latest check's hypothesis id}."""
    sql = "SELECT origin_id, hyp_id FROM hypotheses WHERE origin='citation'"
    args: tuple = ()
    if text_id:
        sql += " AND origin_id LIKE ?"
        args = (text_id + "-%",)
    out: dict[str, str] = {}
    for r in ws.query(sql + " ORDER BY created_at, rowid", args):
        out[r["origin_id"]] = r["hyp_id"]
    return out


# ------------------------------------------------------------------------------------------------------------------
# who may read a text with AI
# ------------------------------------------------------------------------------------------------------------------
def level_of(cx, text_id: str | None, dflt: str | None = None) -> str:
    """How far a text's claims may go: a document's own setting, else the draft's. A text removed since: none."""
    from . import access

    r = cx.execute("SELECT doc_id, ai_access FROM cite_texts WHERE text_id=?", (text_id or "",)).fetchone()
    if r is None:
        return "none"
    if r[0]:
        return access.levels(cx, [r[0]], dflt=dflt).get(r[0], "none")
    lv = r[1] if r[1] in access.LEVELS else (dflt or access._default_from_cx(cx))
    return "local" if lv == "cloud" and access._local_only() else lv


def hidden(ws: Workspace) -> set[str]:
    """The checks of claims whose text Claude may not read: never shown to a Claude chat through the connector."""
    out: set[str] = set()
    try:
        rows = ws.query("SELECT hyp_id, options_json FROM hypotheses WHERE origin='citation'")
    except Exception:  # noqa: BLE001 - an older project without the column
        return out
    levels: dict[str, str] = {}
    cx = ws._conn()
    for r in rows:
        tid = (json.loads(r["options_json"] or "{}").get("citation") or {}).get("text_id")
        if tid not in levels:
            levels[tid] = level_of(cx, tid)
        if levels[tid] != "cloud":
            out.add(r["hyp_id"])
    return out


# ------------------------------------------------------------------------------------------------------------------
# what the page shows
# ------------------------------------------------------------------------------------------------------------------
def _works(ws: Workspace) -> dict[str, dict]:
    from .bibliography import _work_view

    return {r["item_key"]: _work_view(r) for r in ws.query("SELECT * FROM bib_items ORDER BY seq")}


def _docs_of(ws: Workspace) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """{work: its documents (linked)}, {work: documents proposed for it (waiting for a person)}."""
    linked: dict[str, list[str]] = defaultdict(list)
    proposed: dict[str, list[str]] = defaultdict(list)
    for r in ws.query("SELECT l.item_key, l.doc_id, l.status FROM bib_links l JOIN documents d ON d.doc_id=l.doc_id "
                      "WHERE l.status IN ('auto', 'confirmed', 'probable') ORDER BY l.doc_id"):
        (proposed if r["status"] == "probable" else linked)[r["item_key"]].append(r["doc_id"])
    return linked, proposed


def _best_quotes(ws: Workspace, hyp_ids: list[str], threshold: float) -> dict[str, dict]:
    """The excerpt that shows each check's answer best: its quote, page and document."""
    from .claimcheck import effective

    if not hyp_ids:
        return {}
    marks = ",".join("?" * len(hyp_ids))
    rank = {"refutes": 0, "supports": 1, "partially_supports": 2}
    out: dict[str, dict] = {}
    for v in ws.query("SELECT v.subject_id, v.verdict, v.user_verdict, v.confidence, v.quote, v.page, v.doc_id, "
                      f"d.title FROM verifications v LEFT JOIN documents d ON d.doc_id=v.doc_id WHERE "
                      f"v.subject_kind='user_claim' AND v.subject_id IN ({marks})", hyp_ids):
        e = effective(v)
        if e["verdict"] not in rank or not e.get("quote") or (e["confidence"] or 0) < threshold:
            continue
        cur = out.get(v["subject_id"])
        key = (rank[e["verdict"]], -(e["confidence"] or 0))
        if cur is None or key < cur["_key"]:
            out[v["subject_id"]] = {"_key": key, "verdict": e["verdict"], "quote": e["quote"], "page": v["page"],
                                    "doc_id": v["doc_id"], "title": v["title"]}
    for d in out.values():
        d.pop("_key", None)
    return out


def view(ws: Workspace, text_id: str, threshold: float | None = None) -> dict:
    """A text with its citations, each reference with its work, its document and its answer, grouped for the page."""
    from .claimcheck import _threshold, history

    t = ws.query("SELECT * FROM cite_texts WHERE text_id=?", (text_id,))
    if not t:
        raise KeyError("No such text.")
    t = dict(t[0])
    rematch(ws, text_id)
    thr = _threshold(ws, threshold)
    works = _works(ws)
    linked, proposed = _docs_of(ws)
    checks = _checks(ws, text_id)
    status = {h["hyp_id"]: h for h in history(ws, thr, citations=True) if h.get("origin") == "citation"}
    quotes = _best_quotes(ws, [hid for hid in checks.values() if hid in status], thr)
    level = level_of(ws._conn(), text_id)
    cites = {r["cite_id"]: dict(r) for r in ws.query("SELECT * FROM citations WHERE text_id=? ORDER BY n", (text_id,))}
    titles = {r[0]: r[1] for r in ws.query("SELECT doc_id, title FROM documents")}
    refs = []
    counts: dict[str, int] = defaultdict(int)
    for r in ws.query("SELECT * FROM cite_refs WHERE text_id=? ORDER BY rowid", (text_id,)):
        c = cites.get(r["cite_id"])
        if c is None:
            continue
        w = works.get(r["item_key"]) if r["item_key"] else None
        docs = [d for d in linked.get(r["item_key"], []) if d != t["doc_id"]] if w else []
        hid = checks.get(r["ref_id"])
        h = status.get(hid) if hid else None
        if r["ignored"]:
            state = "contrast" if r["signal"] == "contrast" else "ignored"
        elif h is not None:
            state = "checked"
        elif w is None:
            state = "ambiguous" if r["how"] == "ambiguous" else "no_work"
        elif not docs:
            state = ("same_document" if t["doc_id"] in linked.get(r["item_key"], [])
                     else "to_confirm" if proposed.get(r["item_key"]) else "no_document")
        else:
            state = "ready"
        verdict, words = VERDICT.get(h["status"], ("checking", "Being checked")) if h else (None, None)
        group = verdict if state == "checked" else state
        counts[group] += 1
        cands = [works[k] for k in json.loads(r["candidates_json"] or "[]") if k in works]
        rel_a, rel_b = c["claim_start"], c["claim_end"]
        refs.append({
            "ref_id": r["ref_id"], "cite_id": r["cite_id"], "n": c["n"], "raw": r["raw"], "marker": c["marker"],
            "kind": c["kind"], "page": c["page"], "sentence": c["sentence"], "claim": c["claim"],
            "claim_at": [rel_a, rel_b] if 0 <= rel_a < rel_b <= len(c["sentence"]) else None,
            "before": c["before"], "state": state, "state_text": STATE_TEXT.get(state),
            "work": w, "how": r["how"], "candidates": cands,
            "documents": [{"doc_id": d, "title": titles.get(d) or d} for d in docs],
            "proposed": [{"doc_id": d, "title": titles.get(d) or d} for d in proposed.get(r["item_key"], [])] if w else [],
            "hyp_id": hid if h else None, "status": h["status"] if h else None, "verdict": verdict,
            "verdict_text": words, "verdict_help": VERDICT_HELP.get(verdict) if verdict else None,
            "quote": quotes.get(hid) if h else None,
            "reviewed": bool(h and h.get("reviewed")), "corrected": bool(h and h.get("corrected")),
        })
    notices = sum(counts[g] for g in NOTICE_GROUPS)
    return {"text": {"text_id": t["text_id"], "title": t["title"], "source": t["source"],
                     "source_text": SOURCES.get(t["source"], t["source"]), "doc_id": t["doc_id"],
                     "file_name": t["file_name"], "ai_access": t["ai_access"], "level": level,
                     "created_at": t["created_at"], "numeric_unread": t["numeric_unread"] or 0, "cut": bool(t["cut"])},
            "refs": refs, "counts": dict(counts), "notices": notices, "citations": len(cites),
            "works": len({r["work"]["key"] for r in refs if r["work"]}),
            "ready": counts.get("ready", 0), "accurate": counts.get("accurate", 0),
            "checking": counts.get("checking", 0), "has_bibliography": bool(len(works)),
            "bibliography_works": [{"key": k, "cite": w["cite"], "title": w["title"]} for k, w in works.items()]}


def texts(ws: Workspace, threshold: float | None = None) -> list[dict]:
    """The project's texts, newest first, each with its counts (for the list and the Overview)."""
    out = []
    for t in ws.query("SELECT text_id FROM cite_texts ORDER BY created_at DESC, rowid DESC"):
        v = view(ws, t["text_id"], threshold)
        out.append({**v["text"], "citations": v["citations"], "works": v["works"], "counts": v["counts"],
                    "notices": v["notices"], "ready": v["ready"], "accurate": v["accurate"], "checking": v["checking"]})
    return out


def counts(ws: Workspace) -> dict:
    """Cheap counts for the Overview: texts, references, checked."""
    try:
        n_texts = int(ws.scalar("SELECT COUNT(*) FROM cite_texts") or 0)
        n_refs = int(ws.scalar("SELECT COUNT(*) FROM cite_refs WHERE ignored=0") or 0)
        checked = int(ws.scalar("SELECT COUNT(DISTINCT origin_id) FROM hypotheses WHERE origin='citation'") or 0)
    except Exception:  # noqa: BLE001 - an older project
        return {"texts": 0, "refs": 0, "checked": 0}
    return {"texts": n_texts, "refs": n_refs, "checked": checked}


def export_rows(ws: Workspace, text_id: str, threshold: float | None = None) -> list[dict]:
    """One row per cited work of each citation, for Excel."""
    v = view(ws, text_id, threshold)
    rows = []
    for r in v["refs"]:
        q = r["quote"] or {}
        rows.append({
            "#": r["n"], "Page of your text": r["page"] or "", "Sentence": r["sentence"], "Claim checked": r["claim"],
            "Citation": r["raw"], "Work": (r["work"] or {}).get("cite") or "", "Title": (r["work"] or {}).get("title") or "",
            "Answer": r["verdict_text"] or r["state_text"] or "",
            "Quote from the source": q.get("quote") or "", "Page in the source": q.get("page") or "",
            "Document": q.get("title") or ", ".join(d["title"] for d in r["documents"]),
        })
    return rows


# ------------------------------------------------------------------------------------------------------------------
# checking
# ------------------------------------------------------------------------------------------------------------------
def plan(ws: Workspace, text_id: str, ref_ids: list[str] | None = None, again: bool = False) -> list[dict]:
    """The references to check now: those ready (a work with a document, not checked yet), or `ref_ids` among
    them. With `again`, the given references are checked again (their earlier check is replaced)."""
    v = view(ws, text_id)
    want = set(ref_ids) if ref_ids is not None else None
    out = []
    for r in v["refs"]:
        if want is not None and r["ref_id"] not in want:
            continue
        if r["state"] == "checked" and not (again and want is not None):
            continue
        if r["state"] not in ("ready", "checked") or not r["documents"]:
            continue
        w = r["work"]
        out.append({"ref_id": r["ref_id"], "claim": r["claim"], "doc_ids": [d["doc_id"] for d in r["documents"]],
                    "again": r["state"] == "checked",
                    "citation": {"text_id": text_id, "ref_id": r["ref_id"], "sentence": r["sentence"],
                                 "before": r["before"], "marker": r["marker"],
                                 "work": f"{w['cite']}, {w['title']}" if w.get("cite") else w["title"]}})
    return out


def _expand_ok(ws: Workspace, text_id: str, levels: set[str]) -> bool:
    """Search words are proposed by the AI only when the text's claims may go to the model that proposes them."""
    return level_of(ws._conn(), text_id) in levels


def check(ws: Workspace, items: list[dict], backend, model: str, progress: Callable | None = None,
          should_stop: Callable[[], bool] | None = None, expand: bool = True, **options: Any) -> dict:
    """Check the references of `plan`, one after the other, each against its work's documents only. A problem with
    one is recorded and the next is checked; a problem with the model service stops (what was done is kept)."""
    from . import access, claimcheck
    from .llm import BackendError

    say = claimcheck._adapt(progress)
    done, errors, stopped = [], [], None
    levels = set(access.Readers(backend, model).main_levels)
    for i, it in enumerate(items, 1):
        if should_stop and should_stop():
            stopped = "Stopped."
            break
        say("item", f"Citation {i} of {len(items)}", {"index": i, "total": len(items), "text": it["claim"]})
        if it.get("again"):
            _drop_checks(ws, [it["ref_id"]])
        try:
            hid = claimcheck.check_hypothesis(
                ws, it["claim"], backend, model, decompose=False, doc_ids=it["doc_ids"],
                expand=expand and _expand_ok(ws, it["citation"]["text_id"], levels), should_stop=should_stop,
                progress=lambda s, m, info=None, _i=i: say(s, m, {**(info or {}), "index": _i}),
                origin="citation", origin_id=it["ref_id"], extra={"citation": it["citation"]}, **options)
            done.append(hid)
        except BackendError as e:
            stopped = str(e)
            break
        except ValueError as e:
            errors.append({"index": i, "text": it["claim"], "error": str(e)})
    return {"checked": done, "errors": errors, "stopped": stopped, "total": len(items)}


def queue(ws: Workspace, items: list[dict], router, expand: bool = True, **options: Any) -> tuple[list[str], list[dict]]:
    """The same by queue: every check prepared at once; Claude Code reads them in turn. Returns (hypothesis ids,
    errors)."""
    from . import claimcheck

    done, errors = [], []
    for i, it in enumerate(items, 1):
        if it.get("again"):
            _drop_checks(ws, [it["ref_id"]])
        try:
            done.append(claimcheck.queue_check(
                ws, it["claim"], router, decompose=False, doc_ids=it["doc_ids"],
                expand=expand and _expand_ok(ws, it["citation"]["text_id"], {"cloud"}),
                origin="citation", origin_id=it["ref_id"], extra={"citation": it["citation"]}, **options))
        except ValueError as e:
            errors.append({"index": i, "text": it["claim"], "error": str(e)})
    return done, errors


def context_of(ws: Workspace, claim_id: str) -> dict | None:
    """The citation a check's claim comes from (its hypothesis's options), or None for an ordinary check."""
    raw = ws.scalar("SELECT h.options_json FROM user_claims u JOIN hypotheses h ON h.hyp_id=u.hyp_id "
                    "WHERE u.claim_id=? AND h.origin='citation'", (claim_id,))
    if not raw:
        return None
    return json.loads(raw).get("citation") or None

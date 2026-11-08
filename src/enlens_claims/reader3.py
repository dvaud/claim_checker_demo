"""Reader 3 (ENLENS 0.15.1): reader 2 (`reader.py`), and what it adds for text-only files and for books.

Reader 2 finds running heads, page numbers and the front and back matter of a PDF from where its lines stand on the
page and from their type. A text file has neither. Many text files are text copied out of a PDF (a `.md` or `.txt` a
converter made): every running head and page number is still in the text, while the pages, the headings and often the
spaces between words are lost. Books add a table of contents, an index, endnotes and pages of publishing details.
Reader 3 adds these rules, on the text alone (no model), and `reader.read_blocks(raw, version=3)` calls them:

1. **Running heads and footers by repetition** (`text_furniture`, lines without positions): a line that comes back at
   least four times in the same shape (its numbers and roman numerals aside, text printed twice read once), about once
   a page (12 to 150 lines apart), and either next to a page break or a blank line most times, or at regular
   intervals. Interview answers ("[P] Ja.") come back too, but irregularly and in mid-text: they stay.
2. **Page numbers** (`text_furniture`): lines that are only a number, counting up through the text a page apart.
3. **Text printed twice** (`undouble_lines`): "TTIISS ffiinnaall" (a PDF that draws each letter twice) is "TIS final".
4. **Paragraphs in hard-wrapped text** (`paragraph_breaks`): a line clearly shorter than the text's usual line that ends
   a sentence ends its paragraph, and a short line standing on its own (a heading) is a block of its own.
5. **Headings by rule** in a Markdown file, web page or Word file that marks fewer than three (reader 2 then found
   none), and **publishing details** at the start of a text file that looks published (`looks_published`).
6. **Books and theses** (`book_parts`): the table of contents (lines ending in page numbers that go up) is set aside,
   its entries find the chapter headings in the text, what comes before the first chapter is front matter (an abstract,
   summary or preface stays), and Notes, the bibliography, the index, About the author and acknowledgements found from
   it are end matter. An index is also known by its shape ("archetypes, 112–116, 191").
7. **Words that ran together** (`split_runs`), only in a document whose text lost many of its spaces: a long token is
   split where all its pieces are words the document itself uses, and never into word endings ("require ment").
8. **The reading report** (`report_warnings`) says when a text file looks copied out of a PDF, when a PDF was read
   without its layout (pdfminer missing), and when many words still run together.

Everything here depends on the file alone, so the same file reads the same on every computer.
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict

# ------------------------------------------------------------------------------------------------------------------
# lines: text printed twice, running heads and page numbers by repetition
# ------------------------------------------------------------------------------------------------------------------
_ROMAN_TOKEN = re.compile(r"\b[ivxlc]{1,7}\b")
_DIGITS = re.compile(r"\d+")


def _doubled_word(w: str) -> bool:
    return len(w) >= 2 and len(w) % 2 == 0 and w[0::2] == w[1::2]


def undouble(text: str) -> str | None:
    """The text of a line drawn twice letter by letter ("TTIISS ffiinnaall ppggss" -> "TIS final pgs"); None when the
    line is not such a line."""
    words = text.split()
    letters = sum(len(w) for w in words)
    if letters < 6 or len(words) < 1:
        return None
    doubled = sum(len(w) for w in words if _doubled_word(w))
    if doubled < 0.85 * letters or not any(c.isalpha() for c in text):
        return None
    return " ".join(w[0::2] if _doubled_word(w) else w for w in words)


def undouble_lines(pages, counts: Counter) -> None:
    for p in pages:
        for ln in p:
            u = undouble(ln.text.strip())
            if u is not None:
                ln.text = u
                counts["doubled"] += 1


def shape(text: str) -> str:
    """A line's shape: lower case, numbers and roman numerals as '#', so a running head with its page number is the
    same line on every page."""
    t = " ".join(text.lower().split())
    return _ROMAN_TOKEN.sub("#", _DIGITS.sub("#", t))


_CAPTION_SHAPE = re.compile(r"^(fig\.?|figure|table|tab\.?|box|chart|graph|map|plate|exhibit|scheme|photo|image|"
                            r"diagram|appendix|annex|bijlage)\s+#")
_ENDS_SENTENCE = re.compile(r"[.!?:;][\"'”’)\]]*$")
_LONE_NUMBER = re.compile(r"^(?:page\s+)?(\d{1,4}|[ivxlc]{1,7})$", re.I)
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


def _roman(s: str) -> int | None:
    s = s.lower()
    if not s or any(c not in _ROMAN_VALUES for c in s):
        return None
    total = 0
    for i, c in enumerate(s):
        v = _ROMAN_VALUES[c]
        total += -v if i + 1 < len(s) and _ROMAN_VALUES[s[i + 1]] > v else v
    return total


def text_furniture(pages) -> dict:
    """Mark running heads, footers and page numbers among the lines without positions (text files, OCR, pypdf without
    line positions): `Line.furniture` 'head' or 'number'. Returns counts."""
    seq = [ln for p in pages for ln in p if ln.top is None]
    n = len(seq)
    out = {"heads": 0, "numbers": 0}
    if n < 40:
        return out
    # a line next to a page break or a blank line (where a page of copied text begins or ends)
    edge = [bool(ln.blank_before) or (i + 1 >= n) or bool(seq[i + 1].blank_before) or seq[i + 1].page != ln.page
            for i, ln in enumerate(seq)]

    def in_flow(i: int) -> bool:
        """The line goes on from the line before or into the line after, as a sentence does."""
        t = seq[i].text.strip()
        before = i > 0 and not edge[i] and not _ENDS_SENTENCE.search(seq[i - 1].text.strip()) and t[:1].islower()
        after = i + 1 < n and not edge[i] and not _ENDS_SENTENCE.search(t) and seq[i + 1].text.strip()[:1].islower() \
            and not seq[i + 1].blank_before
        return before or after

    where: dict[str, list[int]] = defaultdict(list)
    for i, ln in enumerate(seq):
        k = shape(ln.text)
        if 4 <= len(k) <= 140 and sum(c.isalpha() for c in k) >= 3:
            where[k].append(i)
    marked: set[int] = set()
    for k in [k for k in where if _CAPTION_SHAPE.match(k)]:
        del where[k]  # "FIGURE 1" comes back too, as the label of each figure
    for _round in range(2):  # a footer stacked under another is next to a page break once the other is set aside
        for k, idx in where.items():
            if len(idx) < 4 or idx[0] in marked:
                continue
            gaps = [b - a for a, b in zip(idx, idx[1:])]
            med = statistics.median(gaps)
            if med < 12 or med > 150:
                continue
            near = sum(1 for i in idx if edge[i] or (i > 0 and (i - 1) in marked) or (i + 1) in marked) / len(idx)
            mean = statistics.mean(gaps)
            cv = statistics.pstdev(gaps) / mean if mean else 9.0
            words = len(k.split())
            regular = cv <= 0.5 and ("#" in k or words >= 3)
            if not (near >= 0.6 or regular):
                continue
            if sum(1 for i in idx if in_flow(i)) > 0.5 * len(idx):
                continue
            marked.update(idx)
    # a running head that comes back only a few times (a short chapter: "2 INTRODUCTION", "THE SYSTEM LENS 3",
    # "XII A NOTE FROM THE EDITOR" and "A NOTE FROM THE EDITOR XIII"): set in capitals with a page number at one
    # end, always at a page break, never twice in a row
    numbered: dict[str, list[int]] = defaultdict(list)
    for k, idx in where.items():
        if len(k) <= 70 and re.match(r"^#\s\S|.*\S\s#$", k) and idx[0] not in marked:
            numbered[k.strip("# ")].extend(idx)
    # the titles in a table of contents near the start ("Introduction: The Systems Lens | 1"): a recto running head
    # repeats one with the page number after it ("THE SYSTEMS LENS 3")
    toc_titles: set[str] = set()
    for ln in seq[: max(1, int(0.3 * n))]:
        e = _toc_entry(ln.text)
        if e:
            toc_titles.add(_norm(e[0]))
            toc_titles.update(p for p in (_norm(x) for x in e[0].split(":")) if len(p) >= 6)

    def capitals(t: str) -> bool:
        letters = [c for c in t if c.isalpha()]
        return bool(letters) and sum(c.isupper() for c in letters) >= 0.7 * len(letters)

    for k, idx in numbered.items():
        # the same words in the table of contents ("A Note from the Editor xi") are not at a page break: not counted
        idx = sorted(i for i in idx if (edge[i] or (i > 0 and (i - 1) in marked) or (i + 1) in marked)
                     and capitals(seq[i].text))
        if len(k) < 3 or any(b - a < 12 for a, b in zip(idx, idx[1:])):
            continue
        if len(idx) == 1:
            # once only: a page number after the title of a chapter in the contents, or a line in the middle of a
            # sentence that runs on over the page turn
            i = idx[0]
            if re.match(r".*\S\s#$", shape(seq[i].text)) and _norm(k) in toc_titles:
                marked.add(i)
                continue
            j = i - 1
            while j >= 0 and (j in marked or seq[j].furniture):
                j -= 1
            if not (j >= 0 and i + 1 < n and not _ENDS_SENTENCE.search(seq[j].text.strip())
                    and seq[i + 1].text.strip()[:1].islower()):
                continue
        marked.update(idx)
    for i in marked:
        seq[i].furniture = "head"
    out["heads"] = len(marked)
    # page numbers: lone numbers counting up, a page apart (a number in a list or a chart counts on every line)
    nums = []
    for i, ln in enumerate(seq):
        m = _LONE_NUMBER.match(ln.text.strip())
        if m and i not in marked:
            s = m.group(1)
            v = int(s) if s.isdigit() else _roman(s)
            if v is not None:
                nums.append((i, v, s.isdigit()))
    chain: list[int] = []
    found: set[int] = set()
    for (i, v, d), nxt in zip(nums, nums[1:] + [None]):
        chain.append(i)
        if nxt is not None:
            j, w, d2 = nxt
            if d == d2 and 1 <= w - v <= 3 and 8 <= j - i <= 200:
                continue
        if len(chain) >= 3:
            found.update(chain)
        chain = []
    for i in found:
        seq[i].furniture = "number"
    out["numbers"] = len(found)
    return out


# ------------------------------------------------------------------------------------------------------------------
# ligatures a converter broke with a space ("fi nd", "infl uenced", "Sufi s")
# ------------------------------------------------------------------------------------------------------------------
_LIG_GAP = re.compile(r"(?<![^\W\d_])([^\W\d_]*?(?:ffi|ffl|fi|fl|ff)) ([a-z][^\W\d_]*)")


def ligature_words(lines) -> Counter | None:
    """The words a document uses on their own (not right after a lone "fi", "fl" or "ff"), when the document has
    ligatures broken by a space (at least five); None when it has not."""
    standalone: Counter = Counter()
    gaps = 0
    for ln in lines:
        t = ln.text
        for m in re.finditer(r"[^\W\d_]+", t):
            standalone[m.group(0).lower()] += 1
        for m in _LIG_GAP.finditer(t):
            standalone[m.group(2).lower()] -= 1
            gaps += 1
    # and the pieces after a ligature broken at a line's end ("artifi" / "cially") or a word hyphenated there
    # ("espe-" / "cially"): ends of words, not words
    for a, b in zip(lines, lines[1:]):
        if re.search(r"(?<![^\W\d_])[^\W\d_]*?(?:ffi|ffl|fi|fl|ff)$|[^\W\d_][-‐\u00ad]$", a.text.rstrip()):
            n = re.match(r"([a-z][^\W\d_]*)", b.text.lstrip())
            if n:
                standalone[n.group(1).lower()] -= 1
    if gaps < 5:
        return None
    rest_words = Counter()
    for ln in lines:
        for m in _LIG_GAP.finditer(ln.text):
            if standalone[m.group(2).lower()] < 2:
                rest_words[m.group(2).lower()] += 1
    return standalone if sum(rest_words.values()) >= 5 else None


def join_ligature_gaps(text: str, standalone: Counter, counts: Counter) -> str:
    """"fi nd" -> "find": a word ending in fi, fl or ff joined to what follows when that is not a word of its own. A
    bare "fi" or "fl" is never a word, so it always joins; "off the", "staff members" and "Sufi teaching" stay."""
    cut: list[int] = []   # the spaces to take out
    for m in re.finditer(r"(?=(?<![^\W\d_])([^\W\d_]*?(?:ffi|ffl|fi|fl|ff)) ([a-z][^\W\d_]*))", text):
        left, rest = m.group(1).lower(), m.group(2).lower()
        word = rest in _SHORT_WORDS or (len(rest) >= 3 and standalone[rest] >= 2 and rest not in _ENDINGS)
        if left in ("fi", "fl", "ff", "ffi", "ffl"):
            pass                                   # "fl own", "fi r", "fi nal"
        elif left.endswith("ff") and left not in ("ffi", "ffl"):
            # "off", "staff", "stuff" end words: joined only to what cannot begin one ("off ered", "diff erent")
            if word or rest[0] not in "aeiouy" or standalone[left] >= 2 and len(rest) >= 4 and standalone[rest] >= 1:
                continue
        elif word and len(rest) >= 3:
            continue                               # "Sufi teaching"
        cut.append(m.start(1) + len(m.group(1)))
    if not cut:
        return text
    counts["ligatures"] += len(cut)
    out, last = [], 0
    for i in cut:
        out.append(text[last:i])
        last = i + 1
    out.append(text[last:])
    return "".join(out)


def not_a_heading(t: str, next_text: str | None) -> bool:
    """A line without positions that the heading rules took for a heading, but which is a piece of a sentence: it
    ends one, holds one, introduces a list, or goes on in the next block."""
    s = t.rstrip("\"'”’)] ")
    if s[-1:] in ".!?" and not re.fullmatch(r"(\d+\.)+", s.split()[0] if s.split() else ""):
        return True
    if re.search(r"[.!?][\"'”’]?\s+[A-Z“\"]", t):
        return True
    words = re.findall(r"[^\W\d_]+", t.lower())
    if s.endswith(":") and len(words) >= 6 and sum(w in ("the", "of", "a", "to", "that", "and", "is", "about", "for",
                                                         "this", "with", "in") for w in words) >= 2:
        return True
    return bool(next_text and next_text[:1].islower() and not _ENDS_SENTENCE.search(t))


def join_ligature_breaks(pages, standalone: Counter, counts: Counter) -> None:
    """A ligature broken at a line's end ("suffi" + "cient by itself"): the rest of the word moves up to its line."""
    for p in pages:
        for a, b in zip(p, p[1:]):
            if b.blank_before or a.furniture or b.furniture:
                continue
            m = re.search(r"(?<![^\W\d_])([^\W\d_]*?(?:ffi|ffl|fi|fl|ff))$", a.text.rstrip())
            n = re.match(r"([a-z][^\W\d_]*)(.*)$", b.text.lstrip(), re.S)
            if not m or not n:
                continue
            joined = join_ligature_gaps(f"{m.group(1)} {n.group(1)}", standalone, counts)
            if " " not in joined:
                a.text = a.text.rstrip()[: m.start(1)] + joined
                b.text = n.group(2).lstrip()
    for p in pages:
        p[:] = [ln for ln in p if ln.text.strip() or ln.furniture]


# ------------------------------------------------------------------------------------------------------------------
# paragraphs in hard-wrapped text
# ------------------------------------------------------------------------------------------------------------------
_STARTS_UPPER = re.compile(r"[\"'“‘(\[]*[A-ZÀ-ÖØ-Þ0-9]")
_NO_END = re.compile(r"[,;\-–‐/&]$")


def wrap_width(lines) -> float | None:
    """The usual length of a full line in text broken into lines of about one width (a PDF's lines kept in a text
    file); None when the text is not wrapped like that."""
    lens = sorted(len(ln.text.strip()) for ln in lines if len(ln.text.strip()) >= 20)
    if len(lens) < 20:
        return None
    wrap = lens[int(0.9 * (len(lens) - 1))]
    med = lens[len(lens) // 2]
    if wrap > 130 or med < 0.55 * wrap:
        return None
    return float(wrap)


def paragraph_breaks(pages) -> float | None:
    """In hard-wrapped lines without positions, mark where paragraphs begin (`Line.blank_before`): after a short line
    that ends a sentence, and around a short line that stands on its own (a heading). Returns the wrap width."""
    lines = [ln for p in pages for ln in p if ln.top is None]
    wrap = wrap_width([ln for ln in lines if not ln.furniture])
    if wrap is None:
        return None
    short = 0.6 * wrap
    for i, ln in enumerate(lines):
        if ln.furniture:
            continue
        t = ln.text.strip()
        prev = lines[i - 1] if i else None
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if prev is not None and not prev.furniture and not ln.blank_before:
            pt = prev.text.strip()
            if _ENDS_SENTENCE.search(pt) and len(pt) < 0.85 * wrap and _STARTS_UPPER.match(t):
                ln.blank_before = True
        # a short line on its own: it does not end a sentence or run on, it starts upper case, and so does the next
        if (len(t) < short and len(t.split()) <= 12 and _STARTS_UPPER.match(t) and not _NO_END.search(t)
                and not _ENDS_SENTENCE.search(t.rstrip(":")) and nxt is not None and not nxt.furniture
                and (_STARTS_UPPER.match(nxt.text.strip()) or nxt.blank_before)
                and (prev is None or prev.furniture or ln.blank_before or _ENDS_SENTENCE.search(prev.text.strip())
                     or len(prev.text.strip()) < short)):
            ln.blank_before = True
            nxt.blank_before = True
    return wrap


# ------------------------------------------------------------------------------------------------------------------
# what looks published, publishing details, more names of end matter
# ------------------------------------------------------------------------------------------------------------------
BOOK_FRONT = re.compile(r"\bisbn\b|all rights reserved|library of congress|british library|catalogu?ing[- ]in[- ]"
                        r"publication|\bprinted (in|by|and bound)\b|\btypeset (by|in)\b|\bcover (design|image|photo|"
                        r"illustration)|\bfirst published\b|\bpublished by\b|\bthis edition\b|\breprinted\b|^tel[.:]|"
                        r"^fax[.:]|^e-?mail:|^web:|©|\bcopyright\b|other books by|^also by|by the same author", re.I)
# section names that end a document's text (with the reader-2 names in `reader._BACK_HEAD`)
END_NOTES = re.compile(r"^(\d+\.?\s*)?(notes|endnotes|end notes|notes and references)\s*:?$", re.I)
INDEX_HEAD = re.compile(r"^(\d+\.?\s*)?((subject|author|name|general) )?index( of [a-z ]+)?\s*:?$|^register$", re.I)


def looks_published(blocks, front_cue) -> bool:
    """A text file whose first part has publishing details (a copyright line, an ISBN, a DOI, e-mail addresses, an
    affiliation...): its front matter is set aside as a PDF's is."""
    seen: set[str] = set()
    total = sum(len(" ".join(ln.text for ln in b.lines)) for b in blocks) or 1
    done = 0
    for b in blocks:
        t = " ".join(ln.text.strip() for ln in b.lines)
        if done > 0.08 * total and done > 3000:
            break
        done += len(t)
        for m in front_cue.finditer(t):
            seen.add(m.group(0).lower()[:12])
        for m in BOOK_FRONT.finditer(t):
            seen.add(m.group(0).lower()[:12])
        if len(seen) >= 2:
            return True
    return False


# ------------------------------------------------------------------------------------------------------------------
# books and theses: the contents, front and end matter, the index
# ------------------------------------------------------------------------------------------------------------------
_TOC_HEAD = re.compile(r"^(table of )?contents?\.?$|^inhoud(sopgave)?$|^inhaltsverzeichnis$|^inhalt$|^sommaire$|"
                       r"^table des mati[eè]res$|^[íi]ndice$|^tartalom(jegyz[eé]k)?$", re.I)
_TOC_LINE = re.compile(r"^(?P<title>.*?[^\W\d_].*?)(?P<lead>\s*[.·…_]{2,}\s*|\s*\|\s*|\s+)(?P<num>\d{1,4}|[ivxlc]{1,7})$",
                       re.I)
_INDEX_LINE = re.compile(r"[^\W\d_].*?,\s*(?:\d{1,4}(?:n\d+)?(?:[–-]\d{1,4})?(?:,\s*)?)+\.?$|"
                         r"^[^\W\d_][^,]{1,60}\s\d{1,4}(?:[–-]\d{1,4})?(?:,\s*\d{1,4}(?:[–-]\d{1,4})?)+$")
_NUMBER_WORDS = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
                 "seventeen|eighteen|nineteen|twenty")
_LEAD_NUMBER = re.compile(rf"^(?:(?:chapter|part|section|appendix|hoofdstuk|deel|bijlage|kapitel|chapitre)\s+"
                          rf"(?:\d+|[ivxlc]+|{_NUMBER_WORDS}|[a-z])\b\.?:?\s*|(?:{_NUMBER_WORDS})\b\s*[.:—–-]\s*|"
                          rf"\d+(?:\.\d+)*\.?\s+|[ivxlc]{{1,5}}\.\s+|[a-z]\.\s+)", re.I)
# entries of a table of contents that are not the document's own text
_ENTRY_REFS = re.compile(r"^(bibliography|references|reference list|works cited|literature( cited)?|sources|"
                         r"bibliografie|literatuur(lijst)?|literatur|irodalom|further reading)\b", re.I)
_ENTRY_INDEX = re.compile(r"^((subject|author|name|general) )?index\b|^register$", re.I)
_ENTRY_BACK = re.compile(r"^(notes|endnotes|end notes|acknowledge?ments|editor s acknowledge?ments|"
                         r"author s acknowledge?ments|about the (author|authors|editor|editors|contributors)|"
                         r"notes on contributors|permissions|credits|dankwoord|curriculum vitae|about this book)\b", re.I)
_ENTRY_FRONT = re.compile(r"^(list of (figures|tables|illustrations|abbreviations|boxes)|abbreviations|acronyms)\b",
                          re.I)
# sections before a book's contents that are its own text
_KEEP_BEFORE = re.compile(r"^(abstract|summary|samenvatting|executive summary|preface|foreword|voorwoord|"
                          r"zusammenfassung|r[ée]sum[ée]|összefoglal[óo])\b", re.I)


def _norm(t: str) -> str:
    t = " ".join(t.split())
    for _ in range(2):
        t = _LEAD_NUMBER.sub("", t)
    t = re.sub(r"[^\w\s]", " ", t.lower().replace("’", "'").replace("'", " "))
    return " ".join(t.split())


def _stems(t: str) -> set[str]:
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in t.split() if len(w) > 1}


def _same_title(block: str, entry: str) -> bool:
    if not block or not entry:
        return False
    if block == entry:
        return True
    if len(entry) >= 8 and len(block) >= 8 and (block.startswith(entry) and len(block) <= len(entry) + 40
                                                  or entry.startswith(block) and len(block) >= 0.45 * len(entry)):
        return True
    a, b = _stems(block), _stems(entry)
    return len(a) >= 2 and len(b) >= 2 and len(a & b) / len(a | b) >= 0.75


def _toc_entry(line: str):
    m = _TOC_LINE.match(line.strip())
    if not m:
        return None
    num = m.group("num")
    if num.isdigit():
        v = int(num)
        if v > 1500 and not m.group("lead").strip():
            return None  # a year at the end of a sentence
    else:
        v = _roman(num)
        if v is None or (not m.group("lead").strip() and m.group("title").rstrip()[-1:] in ",;"):
            return None
    title = m.group("title").strip(" .·…_|:-–")
    if len(title) < 2 or len(title) > 140 or _ENDS_SENTENCE.search(title) and not title.endswith(":"):
        return None
    return title, v, num.isdigit()


def _prose(t: str) -> bool:
    words = re.findall(r"[^\W\d_]+", t.lower())
    return len(words) >= 40 and sum(1 for w in words if w in ("the", "of", "and", "to", "in", "is", "that", "a", "we",
                                                              "this", "it", "for", "with", "are", "was")) >= 0.12 * len(words)


def _text(b) -> str:
    return " ".join(ln.text.strip() for ln in b.lines).strip()


def find_contents(blocks, fracs) -> tuple[int, int, list[str]] | None:
    """The table of contents near the start: (first block, block after the last, entry titles in order)."""
    n = len(blocks)
    i = 0
    while i < n and fracs[i] < 0.25:
        b = blocks[i]
        if b.kind in ("furniture", "table", "figure"):
            i += 1
            continue
        head = _TOC_HEAD.match(_text(b))
        start = i + 1 if head else i
        entries: list[tuple[str, int, bool]] = []
        last_hit = None
        misses = 0
        j = start
        while j < n:
            bj = blocks[j]
            if bj.kind == "furniture":
                j += 1
                continue
            lines = [ln.text.strip() for ln in bj.lines if ln.text.strip()]
            got = [e for e in (_toc_entry(t) for t in lines) if e]
            if lines and len(got) >= max(1, 0.6 * len(lines)):
                entries.extend(got)
                last_hit = j
                misses = 0
            elif lines and len(lines) <= 2 and len(_text(bj)) <= 100 and misses < 2 and entries:
                entries.append((_text(bj), -1, True))  # a part's heading without a page number
                misses += 1
            else:
                break
            j += 1
        numbered = [e for e in entries if e[1] >= 0]
        need = 3 if head else 5
        if last_hit is not None and len(numbered) >= need:
            ups = [(a[1], b_[1]) for a, b_ in zip(numbered, numbered[1:]) if a[2] == b_[2]]
            if not ups or sum(1 for a, z in ups if z >= a) >= 0.7 * len(ups):
                return (i if head else start), last_hit + 1, [e[0] for e in entries]
        i = (last_hit + 1) if last_hit is not None and last_hit >= i else i + 1
    return None


def book_parts(blocks, fracs: list[float]) -> dict:
    """Set the kinds of a book's or thesis's parts from its table of contents (`contents`, `front`, `back`,
    `references`, `index`), and an index known by its shape. Returns what was found, for the reading report."""
    out = {"contents": 0, "chapters": 0}
    found = find_contents(blocks, fracs)
    n = len(blocks)
    if found is not None:
        c0, c1, titles = found
        for b in blocks[c0:c1]:
            if b.kind != "furniture":
                b.kind = "contents"
        out["contents"] = 1
        # the entries' headings in the text, in order
        entries = [(t, _norm(t)) for t in titles]
        matches: list[tuple[int, str]] = []    # (block index, entry title)
        e = 0
        k = c1
        while k < n and e < len(entries):
            b = blocks[k]
            if b.kind in ("furniture", "table", "figure", "contents") or len(_text(b)) > 200:
                k += 1
                continue
            mine = _norm(_text(b))
            nxt = next((blocks[x] for x in range(k + 1, min(n, k + 3)) if blocks[x].kind != "furniture"), None)
            both = _norm(_text(b) + " " + _text(nxt)) if nxt is not None and len(_text(nxt)) <= 80 else None
            hit = None
            for x in range(e, len(entries)):
                t, ne = entries[x]
                if not ne:
                    continue
                late = bool(_ENTRY_REFS.match(ne) or _ENTRY_INDEX.match(ne) or _ENTRY_BACK.match(ne))
                if late and fracs[k] < 0.5:
                    continue  # end matter is at the end: a "Notes" heading inside a chapter is not it
                parts = [ne] + ([p for p in (_norm(s) for s in t.split(":")) if len(p) >= 6] if ":" in t else [])
                if any(_same_title(mine, p) for p in parts) or (both and _same_title(both, ne)):
                    hit = x
                    break
            if hit is not None:
                matches.append((k, entries[hit][0]))
                e = hit + 1
            k += 1
        out["chapters"] = len(matches)
        # front matter: before the contents (an abstract, summary or preface stays), and between the contents and
        # the first entry found
        keep = False
        for b in blocks[:c0]:
            t = _text(b)
            if b.kind in ("heading", "title") and len(t) <= 80:
                keep = bool(_KEEP_BEFORE.match(_norm(t)) or _KEEP_BEFORE.match(t))
            if b.kind in ("body", "heading", "caption", "title") and not keep:
                b.kind = "front"
        if matches and fracs[matches[0][0]] - fracs[min(c1, n - 1)] < 0.15:
            # between the contents and the first chapter found: lists of figures, a dedication, blank pages; but
            # where a paragraph of text comes first, the text has begun there (its heading was not found)
            stop = matches[0][0]
            for x in range(c1, stop):
                t = _text(blocks[x])
                if blocks[x].kind in ("body", "abstract") and len(t) >= 300 and _prose(t):
                    stop = x
                    while stop > c1 and blocks[stop - 1].kind in ("heading", "title", "furniture"):
                        stop -= 1
                    break
            keep = False
            for b in blocks[c1:stop]:
                t = _text(b)
                if b.kind in ("heading", "title") and len(t) <= 80:
                    keep = bool(_KEEP_BEFORE.match(_norm(t)) or _KEEP_BEFORE.match(t))
                if b.kind in ("body", "heading", "caption") and not keep:
                    b.kind = "front"
        # the entries' parts: chapters are text (their heading a heading); end matter by name
        for x, (k, title) in enumerate(matches):
            end = matches[x + 1][0] if x + 1 < len(matches) else n
            ne = _norm(title)
            kind = ("references" if _ENTRY_REFS.match(ne) else "index" if _ENTRY_INDEX.match(ne)
                    else "back" if _ENTRY_BACK.match(ne) else "front" if _ENTRY_FRONT.match(ne) else None)
            if kind is None:
                if blocks[k].kind in ("body", "front"):
                    blocks[k].kind = "heading"
                continue
            for b in blocks[k:end]:
                if b.kind not in ("furniture", "table", "figure", "contents"):
                    b.kind = kind
    # an index known by its shape: near the end, a run of lines like "archetypes, 112–116, 191"
    _index_by_shape(blocks, fracs)
    out["index"] = sum(1 for b in blocks if b.kind == "index")
    return out


def _index_by_shape(blocks, fracs) -> None:
    n = len(blocks)
    run: list[int] = []
    lines_in = 0

    def close():
        nonlocal run, lines_in
        if lines_in >= 12:
            for x in run:
                if blocks[x].kind not in ("furniture",):
                    blocks[x].kind = "index"
        run, lines_in = [], 0

    for i in range(n):
        b = blocks[i]
        if fracs[i] < 0.6:
            continue
        if b.kind == "furniture":
            continue
        if b.kind in ("table", "figure"):
            close()
            continue
        lines = [ln.text.strip() for ln in b.lines if ln.text.strip()]
        hits = sum(1 for t in lines if _INDEX_LINE.search(t) and len(t) <= 160)
        if lines and hits >= max(1, 0.6 * len(lines)):
            run.append(i)
            lines_in += hits
        elif lines and len(lines) == 1 and len(lines[0]) <= 40 and run:
            run.append(i)  # a letter of the index ("A"), a term over two lines
        elif INDEX_HEAD.match(_text(b)) and not run:
            run.append(i)
        else:
            close()
    close()


# ------------------------------------------------------------------------------------------------------------------
# words that ran together
# ------------------------------------------------------------------------------------------------------------------
_LETTERS = re.compile(r"[^\W\d_]+")
_SHORT_WORDS = frozenset("a an am as at be by do go he if in is it me my no of on or so to up us we".split())
# pieces that are only the end of a word: never a word of their own when a token is split
_ENDINGS = frozenset("""al ally ance ances ence ences ed er ers est ful ic ical ically ing ings ion ions ise ised ism
ist ists ity ities ive ives ization isation istics ize ized less ly ment ments ness ous ship sion sions tion tions ture
tures able ible ary ory ial ian ians ency ancy ure led ted ting ening ies ied cient ciency""".split())


def damaged_spacing(text: str) -> bool:
    """Whether the text lost many of its spaces: words of 15 letters and more are rare in English (about 0.3%)."""
    toks = _LETTERS.findall(text)
    long = sum(1 for t in toks if len(t) >= 15)
    return len(toks) >= 200 and long >= 20 and long >= 0.02 * len(toks)


def split_runs(text: str, vocab: Counter, bigrams: Counter, common: set, counts: Counter) -> str:
    """Split long tokens that are words run together ("peoplelivingwithdementia" -> "people living with dementia"):
    the pieces are words the document uses on their own (at least twice) or short function words; never word
    endings. A token the document uses more than once as it is splits only where it reads as words the document puts
    side by side elsewhere ("ofthe": "of the"), so a word like "background" stays whole."""

    def valid(w: str) -> bool:
        if w in _SHORT_WORDS:
            return True
        return 3 <= len(w) <= 14 and w not in _ENDINGS and (vocab.get(w, 0) >= 2 or w in common)

    def cost(w: str) -> float:
        f = vocab.get(w, 0) + (40 if w in _SHORT_WORDS or w in common else 0)
        return 1.0 + 1.0 / math.log(f + 2.0)

    def fix(m: re.Match) -> str:
        tok = m.group(0)
        low = tok.lower()
        if len(low) < 9 or low in common:
            return tok
        n = len(low)
        best: list = [None] * (n + 1)
        best[0] = (0.0, [])
        for i in range(1, n + 1):
            for j in range(max(0, i - 14), i):
                if best[j] is None:
                    continue
                w = low[j:i]
                if not valid(w):
                    continue
                c = best[j][0] + cost(w)
                if best[i] is None or c < best[i][0]:
                    best[i] = (c, best[j][1] + [i])
        if best[n] is None or len(best[n][1]) < 2:
            return tok
        cuts = [0] + best[n][1]
        pieces = [low[a:z] for a, z in zip(cuts, cuts[1:])]
        if vocab.get(low, 0) >= 2 and not all(
                bigrams.get(f"{a} {b}", 0) >= 1 or a in _SHORT_WORDS or b in _SHORT_WORDS for a, b in zip(pieces, pieces[1:])):
            return tok
        if len(low) < 12 and not any(bigrams.get(f"{a} {b}", 0) >= 1 for a, b in zip(pieces, pieces[1:])):
            return tok  # a short token splits only where the document has the words side by side
        counts["words_split"] += 1
        return " ".join(tok[a:z] for a, z in zip(cuts, cuts[1:]))

    return _LETTERS.sub(fix, text)


# ------------------------------------------------------------------------------------------------------------------
# the reading report
# ------------------------------------------------------------------------------------------------------------------
def report_warnings(report: dict, raw_kind: str, text: str) -> list[str]:
    out: list[str] = []
    found = report.get("text_layout") or {}
    if raw_kind == "text" and (found.get("heads", 0) >= 4 or found.get("numbers", 0) >= 3 or (
            found.get("wrapped") and (report.get("repairs") or {}).get("hyphens_joined", 0) >= 20)):
        out.append("This file looks like text copied out of a PDF: its pages and layout were lost, and with them what "
                   "tells a heading from the text. If you have the PDF, add it instead: it reads better.")
    if report.get("engine") == "pypdf":
        out.append("This PDF was read from its text alone, without its layout: columns, headings and tables are found "
                   "less well. ENLENS reads layout with pdfminer, which the one-line install brings.")
    if damaged_spacing(text):
        out.append("Many words in this file run together (its spaces were lost when it was made), so searches can miss "
                   "them. The PDF, if you have it, reads better.")
    return out


def publishing_details(t: str) -> bool:
    """A short block of publishing details near the start (a copyright line, an ISBN, a printer, the publisher's
    address); a paragraph that only mentions copyright is text."""
    cues = {m.group(0).lower() for m in BOOK_FRONT.finditer(t)}
    if not cues:
        return False
    words = re.findall(r"[^\W\d_]+", t.lower())
    function = sum(1 for w in words if w in ("the", "of", "and", "to", "in", "is", "that", "we", "this", "it", "for"))
    return len(t) < 250 or len(cues) >= 2 or function < 0.12 * max(1, len(words))

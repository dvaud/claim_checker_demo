"""Reader 2 (ENLENS 0.15): a file read into blocks that know what they are, in reading order.

Reader 1 (`ingest._build_document_1`, ENLENS 0.5 to 0.14) took the text of each page as pypdf gave it, joined its lines
and cut it into passages by sentences. Two columns came out interleaved, running heads and page numbers sat in the
middle of sentences, tables came out as a stream of numbers, and "long-\\nterm" became "longterm". This reader:

1. **Lines with positions.** PDFs are read with pdfminer when it is installed (the one-line install has it): each line
   with its box, font size and boldness, text inside figures marked as such. Without pdfminer, pypdf's page text with
   where each line starts. Scanned pages read by OCR, Word, web pages and text files: their lines, without positions.
2. **Page furniture** (`furniture`): lines in the top or bottom margin that repeat on other pages (running heads,
   footers, "Downloaded from ..."), page numbers, and line numbers in the margin.
3. **Columns and reading order**: a vertical gap no line crosses splits a page into columns; what spans the columns
   (a title, an abstract, a wide figure) cuts the page into bands, read top to bottom, each band column by column.
4. **Blocks**: lines grouped into paragraphs by vertical gaps, indents, short last lines, font size and bold type.
5. **Tables** (A3): three or more rows whose pieces line up in two or more columns are kept as rows and cells.
6. **What each block is** (A2): heading, title, abstract, body, caption, footnote, front matter (authors,
   affiliations, e-mails, dates), back matter (acknowledgements, funding, conflicts of interest, data availability,
   licence), references, table, figure text, furniture. Rules from position, font, repetition and keywords; no model.
7. **Text repair** (A1): ligatures, odd and zero-width spaces, soft hyphens, accents set as separate marks, words
   hyphenated across lines (joined unless both halves are words, so "long-term" stays), and words that ran together
   ("ofthe"), split only when the document itself uses the two words apart more often than together.
8. **Passages** from the blocks: body text, headings, the abstract and captions are what features read (section
   'body'); everything else is kept in the text, searchable on request, as passages with section 'left_out' (or
   'references'), so a person's *Restore* or *Leave out* only changes a passage's section, never its text or id.

The text, its passages and the reading report depend on the file alone (never on the rest of the project), so the same
file reads the same on every computer with the same reader and engine.

Reader 3 (ENLENS 0.15.1) is this reader with the rules of `reader3.py` added: running heads, page numbers and paragraphs
in text-only files, headings where a file marks none, the parts of books and theses from their table of contents, an
index, and words run together. `read_blocks(raw, version=2)` still reads exactly as reader 2 did.
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .textutil import split_sentences

READER = 3   # 2: ENLENS 0.15.0; 3: ENLENS 0.15.1 (reader3.py)
INCLUDED = ("body", "heading", "title", "abstract", "caption")
KINDS = ("title", "heading", "abstract", "body", "caption", "table", "footnote", "front", "back", "references",
         "figure", "furniture", "contents", "index")
# what a person reads for each kind (the reading view, the reading report)
KIND_TEXT = {"title": "title", "heading": "heading", "abstract": "abstract", "body": "paragraph", "caption": "caption",
             "table": "table", "footnote": "footnote",
             "front": "front matter (authors, article and publishing details)",
             "back": "end notes (acknowledgements, funding, licence)", "references": "reference list",
             "figure": "text inside a figure", "furniture": "running head or page number",
             "contents": "table of contents", "index": "index"}
# the same, short, where a block left out is named beside it in the reading view
KIND_LABEL = {"table": "Table", "footnote": "Footnote", "front": "Front matter", "back": "End notes",
              "references": "Reference list", "figure": "Text in a figure", "furniture": "Running head",
              "contents": "Contents", "index": "Index"}


def furniture_label(text: str) -> str:
    """What a block of page furniture is, for the person: a page number, line numbers, or a running head."""
    t = " ".join(text.split())
    if re.fullmatch(r"(\d{1,4}\s+){4,}\d{1,4}", t):
        return "Line numbers"
    if _PAGE_NO.match(t):
        return "Page number"
    if len(t.replace(" ", "")) <= 2 or (len(t) > 20 and t.count(" ") > 0.6 * len(t.replace(" ", ""))):
        return "Text up the margin"   # turned text, a letter at a time
    return "Running head"


# ------------------------------------------------------------------------------------------------------------------
# lines
# ------------------------------------------------------------------------------------------------------------------
@dataclass
class Line:
    page: int                      # 0-based
    text: str
    x0: float | None = None        # points from the left edge
    top: float | None = None       # points from the top of the page to the top of the line
    x1: float | None = None
    bottom: float | None = None
    size: float | None = None      # font size (median over the line's characters)
    bold: bool = False
    figure: bool = False           # inside a figure (chart labels, a diagram's words)
    blank_before: bool = False     # a blank line before it (lines without positions)
    furniture: str = ""            # 'head' | 'number' | 'line-number' | 'turned' | '' (content)
    col: int = 0                   # the column it is in (-1: spans the columns)


@dataclass
class Block:
    page: int
    lines: list[Line]
    kind: str = "body"
    text: str = ""
    start: int = 0
    end: int = 0
    continues: bool = False        # its sentence goes on in the next content block (a column or page turned)
    rows: list[list[str]] | None = None   # a table's rows of cells
    caption: str | None = None     # a table's caption
    n: int = 0

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        xs = [ln for ln in self.lines if ln.x0 is not None and ln.top is not None]
        if not xs:
            return None
        return (min(ln.x0 for ln in xs), min(ln.top for ln in xs), max((ln.x1 or ln.x0) for ln in xs),
                max((ln.bottom or ln.top) for ln in xs))

    @property
    def included(self) -> bool:
        return self.kind in INCLUDED


_BOLD = re.compile(r"bold|black|heavy|semibold|demi|\.b$|-b$|,b$", re.I)


def pdfminer_available() -> bool:
    try:
        import pdfminer.high_level  # noqa: F401
    except Exception:  # noqa: BLE001 - missing or broken: read with pypdf
        return False
    return True


def _pdfminer_pages(path) -> tuple[list[list[Line]], list[tuple[float, float]]]:
    """Every horizontal line of text of each page with its box, size and boldness (pdfminer)."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar, LTFigure, LTTextLineHorizontal

    params = LAParams(line_margin=0.3, char_margin=1.6, word_margin=0.12, all_texts=True, detect_vertical=False)
    pages: list[list[Line]] = []
    dims: list[tuple[float, float]] = []
    for pno, pg in enumerate(extract_pages(str(path), laparams=params)):
        height = float(pg.height)
        out: list[Line] = []

        def walk(obj, in_fig: bool) -> None:
            if isinstance(obj, LTTextLineHorizontal):
                text = obj.get_text().replace("\n", " ").rstrip()
                if not text.strip():
                    return
                chars = [c for c in obj if isinstance(c, LTChar)]
                if chars and sum(1 for c in chars if not getattr(c, "upright", True)) > 0.5 * len(chars):
                    # turned text (arXiv's stamp up the margin, a rotated label) comes out a letter per line
                    out.append(Line(pno, text, float(obj.x0), height - float(obj.y1), float(obj.x1),
                                    height - float(obj.y0), None, False, in_fig, furniture="turned"))
                    return
                sizes = [round(c.size, 1) for c in chars if c.get_text().strip()]
                bold = sum(1 for c in chars if _BOLD.search(c.fontname or "")) > 0.6 * max(1, len(chars))
                out.append(Line(pno, text, float(obj.x0), height - float(obj.y1), float(obj.x1), height - float(obj.y0),
                                statistics.median(sizes) if sizes else None, bold, in_fig))
                return
            if isinstance(obj, LTChar):
                return
            try:
                children = list(obj)
            except TypeError:
                return
            for c in children:
                walk(c, in_fig or isinstance(obj, LTFigure))

        walk(pg, False)
        # a page whose text is all inside one figure (some PDF makers wrap the whole page in a form): it is the page
        if out and sum(len(ln.text) for ln in out if ln.figure) > 0.7 * sum(len(ln.text) for ln in out):
            for ln in out:
                ln.figure = False
        pages.append(out)
        dims.append((float(pg.width), height))
    return pages, dims


def _text_lines(page_text: str, pno: int, spots=None, height: float | None = None) -> list[Line]:
    """Lines of a page read without boxes: pypdf's text (with where each line starts, when known), OCR, text files."""
    out: list[Line] = []
    blank = True
    raw = page_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, t in enumerate(raw):
        if not t.strip():
            blank = True
            continue
        x = top = None
        if spots and len(spots) == len(raw) and spots[i] is not None and height:
            x, y = spots[i]
            top = height - y
        out.append(Line(pno, t.strip(), x, top, blank_before=blank))
        blank = False
    return out


# ------------------------------------------------------------------------------------------------------------------
# text repair
# ------------------------------------------------------------------------------------------------------------------
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st",
             "ﬆ": "st", "ꜳ": "aa", "Ĳ": "IJ", "ĳ": "ij"}
_SPACES = re.compile("[  -   　]")
_ZERO = re.compile("[​‌‍⁠﻿]")
# accents set as separate characters before their letter ("´e"), as TeX's fonts often come out
_SPACING_MARKS = {"´": "́", "`": "̀", "¨": "̈", "ˆ": "̂", "˜": "̃",
                  "¸": "̧", "ˇ": "̌", "˘": "̆", "˚": "̊", "˝": "̋"}
_MARK_LETTER = re.compile("([" + "".join(_SPACING_MARKS) + "]) ?([A-Za-z])")


def repair(text: str, counts: Counter) -> str:
    """The text of one line with ligatures, odd spaces, zero-width characters and separate accents put right."""
    if any(c in text for c in LIGATURES):
        for k, v in LIGATURES.items():
            if k in text:
                counts["ligatures"] += text.count(k)
                text = text.replace(k, v)
    t2 = _SPACES.sub(" ", text)
    if t2 != text:
        counts["spaces"] += sum(1 for a, b in zip(text, t2) if a != b)
        text = t2
    t2 = _ZERO.sub("", text)
    if t2 != text:
        counts["spaces"] += len(text) - len(t2)
        text = t2

    def accent(m: re.Match) -> str:
        composed = unicodedata.normalize("NFC", m.group(2) + _SPACING_MARKS[m.group(1)])
        if len(composed) == 1:
            counts["accents"] += 1
            return composed
        return m.group(0)

    if any(c in text for c in _SPACING_MARKS):
        text = _MARK_LETTER.sub(accent, text)
    if not text.isascii():
        text = unicodedata.normalize("NFC", text)
    return text


# Common English words: a word list for deciding whether a hyphen at a line end joins two words ("long-term") or
# splits one ("exam-ple"); a document's own words count too.
_COMMON = set("""
a able about above across act action active actual after again against age ago agreed air all almost alone along
already also always among amount an analysis and annual another any applied apply approach area areas around as
ask assessed at available average away back bad base based basic be became because become been before being below
best better between beyond big both bottom brief broad build built business but by call called can capacity care
carbon case cases cause central certain chain change changes child children city class clear close co cold common
community company complete complex control cost costs could country course cross current cut data day days deal
decision demand design designed developed development did different direct do does down drawn driven due during
each early economic economy effect effects either end energy enough even ever every evidence example far fast few
field final first fixed follow following for form formal formation found free from front full fuel further future
gas general given go good great green ground group groups growth half hand hard has have he health heat her here
high higher his home house how however human i if impact in income increase independent individual industry
information inside into is it its just key kind known labour land large last late later lead led left less level
levels life light like line little local long low lower made main major make making man management many market
may me mean means measure medium might mid model more most much multi must my national natural near need needs
net new next no non not now number of off often old on one only open or order other our out over own part
particular people per period place plan point policy political poor post power practice present pressure price
private process production public quality question range rate rather real reduced related report research
resource result results right risk role rural said same scale school second sector see self set several she short
should side since single size small so social some source specific stage state step still structure study such
supply support system take taken technical term than that the their them then there these they third this those
three through time to top total trade two type under up upon urban use used user very view was water way we
well were what when where which while white who whole wide will with within without women work world would year
years yet you young zero
""".split())
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
_FUNCTION = frozenset("a an and are as at be by for from in into is it of on or than that the their this to was "
                      "were which with".split())


def _vocabulary(lines: list[Line]) -> Counter:
    """How often each word (lower case) stands on its own in the document's lines, before any repair."""
    vocab: Counter = Counter()
    for ln in lines:
        for w in _WORD.findall(ln.text):
            vocab[w.lower()] += 1
    return vocab


def _bigrams(lines: list[Line]) -> Counter:
    out: Counter = Counter()
    for ln in lines:
        ws = [w.lower() for w in _WORD.findall(ln.text)]
        out.update(f"{a} {b}" for a, b in zip(ws, ws[1:]))
    return out


def _is_word(w: str, vocab: Counter) -> bool:
    w = w.lower()
    return len(w) >= 2 and (w in _COMMON or vocab.get(w, 0) >= 2)


# words English writes as one, though both their halves are words too (a line-end hyphen in them is typesetting)
_CLOSED = frozenset("""
another anybody anyone anything anywhere became become becomes because before behind below beside between beyond
cannot everybody everyone everything everywhere furthermore hereby herein however indeed inside into itself
meanwhile moreover nevertheless nobody nothing nowhere onto otherwise ourselves outcome outcomes output outside
overall somebody someone something sometimes somewhat somewhere therefore thereby throughout together toward towards
underlying understand understanding understood undertake undertaken upon whatever whenever whereas wherever whether
whichever whoever within without workplace workforce worldwide yourself themselves himself herself landscape
framework frameworks network networks feedback database databases household households stakeholder stakeholders
""".split())
# first halves that keep their hyphen ("non-fiction", "self-reported")
_HYPHEN_PREFIX = frozenset("non self mid well cross half quasi semi anti ex".split())
# a second piece that is only the end of a word ("forma-tion", "manage-ment")
_SUFFIX_PIECE = re.compile(r"[a-z]{0,4}(tion|tions|sion|sions|ment|ments|ness|ity|ities|ance|ances|ence|ences|ical|"
                           r"ically|ally|ture|tures|able|ible|ous|ive|ives|ing|ings|ism|ist|ists|ize|ise|ized|ised|"
                           r"ary|ory|ial|ian|ians|ency|ancy|ure)")
_TAIL = re.compile(r"([^\W\d_]+)[-‐]$")
_HEAD = re.compile(r"^([^\W\d_]+)")


def join_lines(texts: list[str], vocab: Counter, counts: Counter) -> str:
    """The lines of one block joined into one paragraph: a hyphen at a line end joins a word broken by typesetting
    ("exam-" + "ple") and stays in a compound ("long-" + "term", "COVID-" + "19"); other line ends become a space."""
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if not out:
            out = t
            continue
        if out.endswith("­"):  # a soft hyphen: the word goes on
            out = out[:-1] + t
            counts["hyphens_joined"] += 1
            continue
        m = _TAIL.search(out)
        nxt = _HEAD.match(t)
        if m and out[-1] in "-‐" and nxt and t[0].islower():
            left, right = m.group(1), nxt.group(1)
            whole = (left + right).lower()
            hyph = vocab.get(f"{left}-{right}".lower(), 0)
            if whole in _CLOSED or (vocab.get(whole, 0) >= 1 and vocab.get(whole, 0) >= hyph):
                join = True       # the document (or English) writes it as one word
            elif hyph:
                join = False      # the document writes it with a hyphen elsewhere
            elif left.lower() in _HYPHEN_PREFIX:
                join = False      # "non-fiction", "self-reported", "mid-century"
            elif _SUFFIX_PIECE.fullmatch(right.lower()):
                join = True       # "for-mation", "applica-tion": the second piece is the end of a word
            elif _is_word(left, vocab) and len(left) >= 3 and len(right) >= 3:
                join = False      # "long-term", "well-known", "short-lived", "clay-rich"
            else:
                join = True       # "exam-ple", "re-search", "be-tween"
            if join:
                out = out[:-1] + t
                counts["hyphens_joined"] += 1
            else:
                out = out + t
                counts["hyphens_kept"] += 1
            continue
        if out[-1] in "-‐–/" and not out.endswith(" -") and not out.endswith(" –"):
            out = out + t  # "COVID-" + "19", "2010–" + "2020", "and/" + "or"
            continue
        out = out + " " + t
    return out.replace("­", "")


_RUN = re.compile(r"\b[a-z]{5,}\b")


def split_run_together(text: str, vocab: Counter, bigrams: Counter, counts: Counter) -> str:
    """Words that ran together because a space was lost ("ofthe", "climatechange"): split only where the document
    itself has the two words apart more often than this joined form (so "income", "another" and "greenhouse",
    never written apart, stay as they are)."""
    def fix(m: re.Match) -> str:
        tok = m.group(0)
        if tok in _COMMON:
            return tok
        seen = vocab.get(tok, 0)
        best, best_n = None, 0
        for i in range(2, len(tok) - 1):
            a, b = tok[:i], tok[i:]
            if len(a) < 2 or len(b) < 2:
                continue
            n = bigrams.get(f"{a} {b}", 0)
            if n >= 2 and n > seen and n > best_n and (a in _FUNCTION or b in _FUNCTION or (len(a) >= 4 and len(b) >= 4)):
                best, best_n = (a, b), n
        if best is None:
            return tok
        counts["words_split"] += 1
        return f"{best[0]} {best[1]}"

    return _RUN.sub(fix, text)


# ------------------------------------------------------------------------------------------------------------------
# page furniture
# ------------------------------------------------------------------------------------------------------------------
_PAGE_NO = re.compile(r"^(page\s*)?[\divxlc]{1,6}(\s*(of|/)\s*\d+)?\.?$|^[-–—]\s*\d{1,4}\s*[-–—]$", re.I)
_DIGITS = re.compile(r"\d+")


def _key(text: str) -> str:
    return _DIGITS.sub("#", " ".join(text.lower().split()))


_SECNUM = re.compile(r"^(\d{1,2}(\.\d{1,2}){0,3}\.?|[IVX]{1,5}\.?|[A-Z]\.?)$")


def join_section_numbers(lines: list[Line]) -> list[Line]:
    """A section number set apart from its heading on the same line ("2.1" and "Data", far apart) is one line."""
    out: list[Line] = []
    rest = sorted(lines, key=lambda x: (round(x.top or 0), x.x0 or 0)) if all(
        ln.top is not None and ln.x0 is not None for ln in lines) else None
    if rest is None:
        return lines
    used: set[int] = set()
    for i, ln in enumerate(rest):
        if i in used:
            continue
        if _SECNUM.match(ln.text.strip()) and not ln.furniture:
            for j in range(i + 1, min(i + 4, len(rest))):
                o = rest[j]
                if j not in used and abs((o.top or 0) - (ln.top or 0)) < 0.4 * (ln.size or 8) and o.x0 > (ln.x1 or ln.x0) \
                        and o.x0 - (ln.x1 or ln.x0) < 40 and not o.furniture and re.match(r"[^\W\d_]", o.text.strip()):
                    ln = Line(ln.page, ln.text.strip() + " " + o.text.strip(), ln.x0, min(ln.top, o.top), o.x1,
                              max(ln.bottom or ln.top, o.bottom or o.top), o.size or ln.size, o.bold or ln.bold, ln.figure)
                    used.add(j)
                    break
        out.append(ln)
    return out  # top to bottom; `reading_order` puts lines with boxes in reading order


def mark_furniture(pages: list[list[Line]], dims: list[tuple[float, float]]) -> None:
    """Running heads and footers, page numbers and line numbers (lines with boxes only)."""
    n = len(pages)
    edge: Counter = Counter()
    for pno, lines in enumerate(pages):
        h = dims[pno][1] if pno < len(dims) else None
        if not h:
            continue
        seen = set()
        for ln in lines:
            if ln.top is None:
                continue
            if ln.top < 0.1 * h or (ln.bottom or ln.top) > 0.9 * h:
                seen.add(_key(ln.text))
        edge.update(seen)
    need = 2 if n <= 4 else max(2, int(0.25 * n))
    for pno, lines in enumerate(pages):
        h = dims[pno][1] if pno < len(dims) else None
        if not h:
            continue
        # a running head or footer stands apart from the text: a clear gap, or other type, between it and the
        # nearest line towards the middle of the page (a page that repeats another is not all running heads)
        placed = sorted((ln for ln in lines if ln.top is not None), key=lambda x: x.top)
        steps = sorted(b.top - a.top for a, b in zip(placed, placed[1:]) if 0 < b.top - a.top < 40)
        step = steps[len(steps) // 4] if steps else 12.0

        def apart(ln: Line) -> bool:
            k = placed.index(ln)
            other = placed[k + 1] if ln.top < 0.5 * h else placed[k - 1] if k else None
            if other is None or (ln.top >= 0.5 * h and k == 0) or (ln.top < 0.5 * h and k + 1 >= len(placed)):
                return True
            gap = abs(other.top - ln.top)
            return gap > 1.4 * step or (ln.size and other.size and abs(ln.size - other.size) > 0.5)
        # line numbers: a column of short numbers at one x, as manuscripts under review have
        nums = [ln for ln in lines if ln.x0 is not None and re.fullmatch(r"\d{1,4}", ln.text.strip())]
        by_x: Counter = Counter(round(ln.x0 / 4) for ln in nums)
        line_no_x = {x for x, c in by_x.items() if c >= 8}
        for ln in lines:
            if ln.top is None:
                continue
            t = ln.text.strip()
            if ln.x0 is not None and round(ln.x0 / 4) in line_no_x and re.fullmatch(r"\d{1,4}", t):
                ln.furniture = "line-number"
                continue
            at_edge = ln.top < 0.1 * h or (ln.bottom or ln.top) > 0.9 * h
            if not at_edge:
                continue
            if _PAGE_NO.match(t):
                ln.furniture = "number"
            elif n > 1 and edge[_key(t)] >= need and apart(ln):
                ln.furniture = "head"


# ------------------------------------------------------------------------------------------------------------------
# columns and reading order
# ------------------------------------------------------------------------------------------------------------------
def _gutters(lines: list[Line], lo: float, hi: float, depth: int = 0) -> list[float]:
    """x positions between `lo` and `hi` that split the lines into columns: lines of prose stand side by side on both
    sides of it at the same height (what spans the columns, such as a title or an abstract, stands at other heights),
    and few lines cross it."""
    # lines of prose only: a table's cells and a figure's labels stand anywhere and would hide the gap
    span = hi - lo if depth == 0 else 2 * (hi - lo)
    ls = [ln for ln in lines if ln.x0 is not None and ln.x1 is not None and not ln.furniture and not ln.figure
          and len(ln.text.strip()) >= 15 and ln.x1 - ln.x0 >= 0.15 * span]
    if len(ls) < 8 or depth > 2:
        return []
    width = hi - lo
    best, best_score = None, None
    x = lo + 0.25 * width
    while x <= lo + 0.75 * width:
        left = [ln for ln in ls if ln.x1 <= x]
        right = [ln for ln in ls if ln.x0 >= x]
        cross = len(ls) - len(left) - len(right)
        if len(left) >= 4 and len(right) >= 4:
            rows = {round(ln.top / 3) for ln in right}
            side = sum(1 for ln in left if {round(ln.top / 3) - 1, round(ln.top / 3), round(ln.top / 3) + 1} & rows)
            if side >= 4 and side >= 0.3 * min(len(left), len(right)) and cross <= 0.6 * (len(left) + len(right)):
                score = (-side, cross, abs(x - (lo + hi) / 2))
                if best_score is None or score < best_score:
                    best, best_score = x, score
        x += 2.0
    if best is None:
        return []
    # the gap's middle: from the right edge of the left lines to the left edge of the right lines
    right_edge = max((ln.x1 for ln in ls if ln.x1 <= best), default=best)
    left_edge = min((ln.x0 for ln in ls if ln.x0 >= best), default=best)
    g = (right_edge + left_edge) / 2 if left_edge > right_edge else best
    out = [g]
    out += _gutters([ln for ln in ls if ln.x1 <= g], lo, g, depth + 1)
    out += _gutters([ln for ln in ls if ln.x0 >= g], g, hi, depth + 1)
    return sorted(out)


def reading_order(lines: list[Line], width: float) -> tuple[list[Line], int]:
    """The page's lines in reading order and how many columns it has."""
    pos = [ln for ln in lines if ln.top is not None and ln.x0 is not None]
    if len(pos) < len(lines) or not pos:
        return lines, 1  # no boxes: the order the text came in
    gut = _gutters(pos, 0.0, width)
    if not gut:
        return sorted(lines, key=lambda ln: (round(ln.top, 1), ln.x0)), 1
    bounds = [float("-inf")] + gut + [float("inf")]

    def col_of(ln: Line) -> int:
        for k in range(len(bounds) - 1):
            if bounds[k] - 2 <= ln.x0 and (ln.x1 or ln.x0) <= bounds[k + 1] + 2:
                return k
        return -1

    for ln in pos:
        ln.col = col_of(ln)
    # bands: what spans the columns cuts the page; within a band, column by column
    ordered: list[Line] = []
    band: list[Line] = []
    for ln in sorted(pos, key=lambda ln: (ln.top, ln.x0)):
        if ln.col == -1 and not ln.furniture:
            ordered += sorted(band, key=lambda x: (x.col, x.top, x.x0))
            band = []
            ordered.append(ln)
        else:
            band.append(ln)
    ordered += sorted(band, key=lambda x: (x.col if x.col >= 0 else 99, x.top, x.x0))
    # furniture keeps its place at the top or the bottom of the page
    head = [ln for ln in ordered if ln.furniture and ln.top < 0.5 * (max(x.bottom or x.top for x in pos) or 1)]
    rest = [ln for ln in ordered if ln not in head]
    return head + rest, len(gut) + 1


# ------------------------------------------------------------------------------------------------------------------
# tables
# ------------------------------------------------------------------------------------------------------------------
def _rows(lines: list[Line]) -> list[list[Line]]:
    """Lines that share a baseline (within a column), left to right."""
    rows: list[list[Line]] = []
    for ln in sorted(lines, key=lambda x: (x.top, x.x0)):
        if rows and abs(rows[-1][0].top - ln.top) < 0.5 * (ln.size or 8) and ln.col == rows[-1][0].col:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    for r in rows:
        r.sort(key=lambda x: x.x0)
    return rows


def _table_row(r: list[Line]) -> bool:
    """Pieces of one row that read as cells: two or more, apart by a clear gap, mostly short (a line of prose cut
    by a formula has long pieces close together)."""
    if len(r) < 2:
        return False
    gaps = [b.x0 - a.x1 for a, b in zip(r, r[1:]) if a.x1 is not None and b.x0 is not None]
    if not gaps or min(gaps) < 9:
        return False
    short = sum(1 for c in r if len(c.text.strip()) <= 30)
    return short >= 0.5 * len(r) and max(len(c.text.strip()) for c in r) <= 60


def find_tables(lines: list[Line]) -> list[tuple[list[Line], list[list[str]]]]:
    """Runs of three or more rows with two or more pieces whose left edges line up: (the lines, rows of cells)."""
    pos = [ln for ln in lines if ln.top is not None and ln.x0 is not None and not ln.furniture and not ln.figure]
    if len(pos) < 6:
        return []
    out = []
    by_col: dict[int, list[Line]] = {}
    for ln in pos:
        by_col.setdefault(ln.col, []).append(ln)
    for _col, ls in sorted(by_col.items()):
        rows = _rows(ls)
        i = 0
        while i < len(rows):
            if not _table_row(rows[i]):
                i += 1
                continue
            j = i
            run = []
            while j < len(rows):
                r = rows[j]
                if run:
                    gap = r[0].top - run[-1][0].top
                    if gap > 3.2 * (r[0].size or 10):
                        break
                if _table_row(r) or (run and len(r) == 1 and j + 1 < len(rows) and _table_row(rows[j + 1])):
                    run.append(r)
                    j += 1
                else:
                    break
            multi = [r for r in run if _table_row(r)]
            if len(multi) >= 3:
                xs = Counter(round(c.x0 / 6) for r in multi for c in r)
                cols = sorted(x for x, n in xs.items() if n >= 0.5 * len(multi))
                if len(cols) >= 2:
                    anchors = [x * 6 for x in cols]
                    grid = []
                    for r in run:
                        cells = [""] * len(anchors)
                        for c in r:
                            k = min(range(len(anchors)), key=lambda q: abs(anchors[q] - c.x0) if c.x0 >= anchors[q] - 8
                                    else 1e9 + abs(anchors[q] - c.x0))
                            cells[k] = (cells[k] + " " + c.text.strip()).strip()
                        if len(r) == 1 and grid and not cells[0]:
                            # a cell's second line: it belongs to the row above
                            grid[-1] = [(a + " " + b).strip() for a, b in zip(grid[-1], cells)]
                        else:
                            grid.append(cells)
                    out.append(([c for r in run for c in r], grid))
                    i = j
                    continue
            i = max(i + 1, j if run and len(multi) < 3 and j > i + 1 else i + 1)
    return out


# ------------------------------------------------------------------------------------------------------------------
# blocks
# ------------------------------------------------------------------------------------------------------------------
_ENDS = re.compile(r"[.!?:;][\"'”’)\]]*$")
_STARTS_UPPER = re.compile(r"[\"'“‘(\[]*[A-ZÀ-ÖØ-Þ0-9]")
_BULLET = re.compile(r"^([•◦▪▫‣∙·●○■□➢►\-–*]|\(?[a-z0-9ivx]{1,3}[.)])\s+")
_SECTION_NO = re.compile(r"^(\d{1,2}(\.\d{1,2}){0,3}\.?|[IVX]{1,5}\.|[A-Z]\.)\s+\S")


def _first_word_width(ln: Line) -> float:
    """About how wide the first word of a line is (with the space before it), from the line's width per character."""
    if ln.x0 is None or ln.x1 is None or not ln.text.strip():
        return 0.0
    per = (ln.x1 - ln.x0) / max(1, len(ln.text.strip()))
    return (len(ln.text.strip().split()[0]) + 1) * per


def _leading(lines: list[Line]) -> float:
    gaps = sorted(b.top - a.top for a, b in zip(lines, lines[1:])
                  if a.top is not None and b.top is not None and 0 < b.top - a.top < 40 and a.col == b.col)
    # the line spacing: the commonest small gap (paragraph gaps are larger, and on a short page may be most of them)
    return gaps[len(gaps) // 4] if gaps else 12.0


def make_blocks(lines: list[Line], width: float | None, body_size: float | None) -> list[Block]:
    """The page's lines (in reading order) grouped into paragraphs."""
    blocks: list[Block] = []
    lead = _leading(lines)
    col_edges: dict[int, tuple[float, float]] = {}
    for ln in lines:
        if ln.x0 is not None and ln.x1 is not None and not ln.furniture:
            a, b = col_edges.get(ln.col, (ln.x0, ln.x1))
            col_edges[ln.col] = (min(a, ln.x0), max(b, ln.x1))
    cur: list[Line] = []

    def flush():
        if cur:
            blocks.append(Block(cur[0].page, list(cur)))
            cur.clear()

    for ln in lines:
        if not cur:
            cur.append(ln)
            continue
        prev = cur[-1]
        new = False
        t = ln.text.strip()
        pt = prev.text.strip()
        if ln.furniture or prev.furniture or ln.figure != prev.figure or ln.col != prev.col:
            new = True
        elif ln.top is None or prev.top is None:
            if ln.blank_before:
                new = True
            elif _ENDS.search(pt) and len(pt) < 50 and _STARTS_UPPER.match(t):
                new = True
        else:
            gap = ln.top - prev.top
            left, right = col_edges.get(ln.col, (ln.x0, ln.x1 or ln.x0))
            colw = max(1.0, (right or 0) - (left or 0))
            if gap < -2 or gap > 1.55 * max(lead, 1.2 * min(ln.size or 0, prev.size or 0)):
                new = True  # (lines in large type, a title over two lines, stand further apart)
            elif ln.size and prev.size and abs(ln.size - prev.size) > 0.9:
                new = True
            elif ln.bold != prev.bold and (len(pt) < 90 or len(t) < 90):
                new = True
            elif ln.x0 is not None and left is not None and ln.x0 - left > 6 and prev.x0 is not None \
                    and prev.x0 - left < 3 and _ENDS.search(pt):
                new = True  # an indented first line after a sentence's end
            elif prev.x1 is not None and right is not None and _ENDS.search(pt) and _STARTS_UPPER.match(t) \
                    and right - prev.x1 > max(0.06 * colw, _first_word_width(ln) * 1.15):
                new = True  # a short last line ends a paragraph: the next line's first word would have fitted
        if not new and _BULLET.match(t) and len(t) > 2:
            new = True
        if new:
            flush()
        cur.append(ln)
    flush()
    # a heading run into its paragraph without a gap ("Results" over the first line of its text): its own block
    out: list[Block] = []
    for b in blocks:
        if len(b.lines) >= 2 and _inline_heading(b.lines[0], b.lines[1:], col_edges):
            out.append(Block(b.page, b.lines[:1]))
            out.append(Block(b.page, b.lines[1:]))
        else:
            out.append(b)
    return out


def _inline_heading(first: Line, rest: list[Line], col_edges: dict) -> bool:
    t = first.text.strip()
    if not (2 <= len(t) <= 80) or t[-1] in ".,;:!?-–—/" or not re.match(r"[A-ZÀ-ÖØ-Þ0-9]", t):
        return False
    if len(re.findall(r"[^\W\d_]", t)) < 2 or _PAGE_NO.match(t) or not _STARTS_UPPER.match(rest[0].text.strip()):
        return False
    if first.x1 is not None and first.x0 is not None:
        left, right = col_edges.get(first.col, (first.x0, first.x1))
        return (first.x1 - first.x0) < 0.6 * max(1.0, right - left)
    lens = sorted(len(ln.text.strip()) for ln in rest)
    return len(t) < 0.6 * lens[len(lens) // 2] and len(t.split()) <= 10


# ------------------------------------------------------------------------------------------------------------------
# what each block is
# ------------------------------------------------------------------------------------------------------------------
_REFS_HEAD = re.compile(r"^(\d+\.?\s*)?(references?( cited)?|bibliography|literature( cited)?|works cited|reference list|"
                        r"sources|bibliografie|literatur|literatuur|références|referencias|irodalom)\s*:?$", re.I)
_BACK_HEAD = re.compile(
    r"^(\d+\.?\s*)?(acknowledge?ments?|funding( information| sources)?|financial (support|disclosure)|"
    r"conflicts? of interests?|competing interests?|declaration of (competing )?interests?|declarations?|"
    r"disclosure( statement)?|author(s'|'s)? contributions?|credit authorship contribution statement|contributions|"
    r"data (and code )?availability( statement)?|availability of data( and materials?)?|code availability|"
    r"ethics( statement| approval)?|ethical approval|informed consent|consent for publication|"
    r"supplementary (material|materials|information|data)|supporting information|additional information|"
    r"notes on contributors|about the authors?|author information|publisher'?s note|open access|abbreviations|"
    r"orcid|copyright|licen[cs]e)\s*:?$", re.I)
_ABSTRACT = re.compile(r"^(abstract|summary|a b s t r a c t|executive summary)\b\s*[:.—–-]?\s*", re.I)
_CAPTION = re.compile(r"^(fig\.?|figure|tab\.?|table|box|chart|graph|map|plate|exhibit|scheme|photo|image|diagram)"
                      r"\s*[A-Z]?\d+[a-z]?(\.\d+)?\s*([.:|—–-]|\s+[A-Z(])", re.I)
_FRONT = re.compile(r"@|\b(universit|institut|department|faculty|school of|laborator|centre for|center for|college|"
                    r"received|accepted|published|revised|available online|corresponding author|correspondence|"
                    r"e-?mail|keywords?|key words|jel( classification)?|orcid|issn|doi\b|doi:|https?://|www\.|"
                    r"open access|citation:|cite this|editor:|edited by|reviewed by|©|copyright|all rights reserved|"
                    r"creative commons|cc by|licen[cs]ed under|published by|article history|article info|"
                    r"permission to (reproduce|use|copy)|preprint|under review|submitted to)", re.I)
_BACK_TEXT = re.compile(r"^(downloaded from|this article is (licensed|distributed)|© the author|creative commons|"
                        r"open access this article|publisher'?s note)", re.I)
# what front matter begins with (a paragraph that only mentions a university or a year it was published is text)
_FRONT_START = re.compile(r"^(received|accepted|published( online)?|revised|available online|corresponding author|"
                          r"correspondence|e-?mail|keywords?|key words|jel|orcid|issn|doi\b|doi:|https?://|open access|"
                          r"citation:|cite this|to cite this|editor:|edited by|reviewed by|handling editor|©|copyright|"
                          r"article history|article info|research article|original (article|research)|review article)",
                          re.I)
_KEYWORDS = re.compile(r"^(keywords?|key ?words|jel( codes| classification)?|index terms|subjects?)\s*[:—–.-]", re.I)
_FOOT_MARK = re.compile(r"^([¹²³⁴⁵⁶⁷⁸⁹⁰*∗†‡§¶]|\d{1,2}(?=[\s\w(\[]))")


def _heading_like(b: Block, body_size: float | None) -> bool:
    t = " ".join(ln.text.strip() for ln in b.lines)
    if len(b.lines) > 3 or not (2 <= len(t) <= 160) or len(re.findall(r"[^\W\d_]", t)) < 2:
        return False
    if t[-1] in ".,;" and not re.fullmatch(r"(\d+\.)+", t.split()[0] if t.split() else ""):
        return False
    if _PAGE_NO.match(t):
        return False
    size = b.lines[0].size
    big = bool(size and body_size and size >= body_size + 0.8)
    bold = all(ln.bold for ln in b.lines)
    if t[-1] in "!?" and not (big or bold):
        return False  # a question in the text, not a title that asks one
    numbered = bool(_SECTION_NO.match(t)) and len(t.split()) <= 14 and t[-1] not in ".:"
    caps = t.isupper() and len(t.split()) <= 10
    known = bool(_REFS_HEAD.match(t) or _BACK_HEAD.match(t) or re.fullmatch(
        r"(\d+\.?\s*)?(introduction|background|methods?|methodology|materials and methods|results|discussion|"
        r"conclusions?|results and discussion|limitations|appendix( [a-z0-9]+)?|abstract|summary|"
        r"executive summary|literature review|theory|data|findings|recommendations|case study)", t, re.I))
    if b.lines[0].top is None:  # no boxes: a short line on its own that does not end a sentence
        return (known or numbered or caps or (len(t) <= 80 and _STARTS_UPPER.match(t) is not None
                and len(b.lines) == 1)) and t[-1] not in ".,;"
    return big or bold or numbered or caps or known


_SECTION_NAMES = re.compile(
    r"(\d+\.?\s*)?(introduction|background|methods?|methodology|materials and methods|results|discussion|"
    r"conclusions?|results and discussion|limitations|appendix( [a-z0-9]+)?|literature review|theory|"
    r"theoretical framework|data|findings|recommendations|case study|related work|overview|context)", re.I)
_FUNCTION_WORDS = frozenset("the of and to in is are was were we for with on that this it be as by an a or from at "
                            "our their you do how what which not have has can will between after before but also into "
                            "over more most than its had been these those there when while about".split())


def _sentence_like(t: str) -> bool:
    words = re.findall(r"[^\W\d_]+", t.lower())
    return len(words) >= 5 and (sum(w in _FUNCTION_WORDS for w in words) >= 2
                                or (len(words) >= 6 and t.rstrip()[-1:] in ".!?" and not _FRONT.search(t)))


def _is_section(t: str) -> bool:
    return bool(_SECTION_NO.match(t) or _SECTION_NAMES.fullmatch(t.strip(" .:")))


def classify(blocks: list[Block], body_size: float | None, dims: list[tuple[float, float]], pdf: bool,
             known_headings: set[str] | None, version: int = 2) -> None:
    """Set each block's kind (see the module's docstring)."""
    v3 = version >= 3
    total = sum(len(" ".join(ln.text for ln in b.lines)) for b in blocks) or 1
    done = 0
    title_set = False
    front_zone = pdf       # the first pages of a PDF until its abstract, its first section or a long paragraph
    marked: set[str] = set()
    if v3 and not pdf:
        # reader 3: a file that marks fewer than three headings (a .md copied out of a PDF marks none) gets the
        # heading rules too; and a text file that looks published has its front matter set aside as a PDF's is
        if known_headings is not None and len(known_headings) < 3:
            marked, known_headings = set(known_headings), None
        from . import reader3

        front_zone = reader3.looks_published(blocks, _FRONT)
    zone = None            # 'abstract' | 'back' | 'references' | 'index' while under such a heading
    last_abstract = None
    # reader 3: the text of the next block that is not page furniture (a "heading" that goes on in it is not one)
    nexts: list[str | None] = [None] * len(blocks)
    if v3:
        following = None
        for i in range(len(blocks) - 1, -1, -1):
            nexts[i] = following
            if not blocks[i].lines[0].furniture:
                following = " ".join(ln.text.strip() for ln in blocks[i].lines).strip()
    for bi, b in enumerate(blocks):
        t = " ".join(ln.text.strip() for ln in b.lines).strip()
        frac = done / total
        done += len(t)
        h = dims[b.page][1] if pdf and b.page < len(dims) else None
        if b.kind == "table":
            continue
        if b.lines[0].furniture:
            b.kind = "furniture"
            continue
        if b.lines[0].figure:
            b.kind = "figure"
            continue
        if known_headings is not None:
            heading = " ".join(t.split()) in known_headings
        else:
            heading = " ".join(t.split()) in marked or _heading_like(b, body_size)
            if heading and v3 and b.lines[0].top is None and " ".join(t.split()) not in marked:
                from . import reader3

                heading = not reader3.not_a_heading(t, nexts[bi])
        if front_zone and (b.page > 0 or (heading and (_is_section(t) or _ABSTRACT.match(t)))
                           or (not heading and len(t) >= 300 and not _FRONT.search(t[:200]))
                           or (not heading and _ABSTRACT.match(t) and len(t) > 120)
                           or (v3 and not pdf and frac > 0.15)):
            front_zone = False
        if heading:
            if _REFS_HEAD.match(t) and frac > 0.3:
                zone = "references"
                b.kind = "references"
                continue
            if _BACK_HEAD.match(t) and frac > 0.4:
                zone = "back"
                b.kind = "back"
                continue
            if v3 and frac > 0.5:
                from . import reader3

                if reader3.END_NOTES.match(t):
                    zone = "back"
                    b.kind = "back"
                    continue
                if reader3.INDEX_HEAD.match(t) and frac > 0.6:
                    zone = "index"
                    b.kind = "index"
                    continue
            if _ABSTRACT.fullmatch(t) or _ABSTRACT.match(t) and len(t) < 30:
                zone = "abstract"
                b.kind = "heading"
                continue
            zone = None
            # the title: the largest type on the first page, near its top
            if (pdf and not title_set and b.page == 0 and body_size and b.lines[0].size
                    and b.lines[0].size >= body_size + 2 and h and b.lines[0].top < 0.5 * h):
                b.kind = "title"
                title_set = True
                continue
            if v3 and not pdf and front_zone and not title_set and frac < 0.05 and len(t.split()) >= 2 \
                    and not _FRONT.search(t):
                b.kind = "title"  # reader 3: a text file's first heading, in its front matter, is its title
                title_set = True
                continue
            if front_zone and (title_set or (v3 and not pdf)) and not _is_section(t):
                b.kind = "front"  # names and affiliations set large under the title
                continue
            b.kind = "heading"
            continue
        if pdf and b.page <= 1 and _KEYWORDS.match(t) and len(t) < 600:
            b.kind = "front"
            continue
        if zone == "references":
            b.kind = "references"
            continue
        if zone == "back":
            b.kind = "back"
            continue
        if zone == "index":
            b.kind = "index"
            continue
        if _CAPTION.match(t):
            b.kind = "caption"
            continue
        if pdf and h and b.lines[0].top is not None and body_size and b.lines[0].size and _FOOT_MARK.match(t) and (
                (b.lines[0].size < 0.88 * body_size and b.lines[0].top > 0.6 * h)
                or (b.lines[0].size < 0.96 * body_size and b.lines[0].top > 0.75 * h and not t[0].isdigit())):
            b.kind = "footnote"
            continue
        if zone == "abstract":
            if last_abstract is not None and last_abstract.lines[0].col != b.lines[0].col:
                zone = None  # an abstract set across the page ends where the columns begin
            else:
                b.kind = "abstract"
                last_abstract = b
                continue
        if _ABSTRACT.match(t) and b.page <= 1 and len(t) > 120:
            b.kind = "abstract"
            continue
        if (pdf or v3) and _BACK_TEXT.match(t):
            b.kind = "back"
            continue
        if v3 and frac < 0.08 and len(t) < 600:
            from . import reader3

            if reader3.publishing_details(t):
                b.kind = "front"  # reader 3: a copyright page, an ISBN, a printer, other books by the author
                continue
        if front_zone and ((len(t) < 160 and _FRONT.search(t)) or _FRONT_START.match(t)
                           or (len(t) < 300 and ("@" in t or not _sentence_like(t))) or _author_line(t)
                           or (len(t) < 800 and len({m.group(0).lower() for m in _FRONT.finditer(t)}) >= 3)):
            b.kind = "front"
            continue
        b.kind = "body"
        front_zone = False  # front matter comes before the text
    # a reference list without a heading: the last blocks, each read like an entry
    if not any(b.kind == "references" for b in blocks):
        from .ingest import reference_like

        k = len(blocks)
        while k > 0 and blocks[k - 1].kind in ("body", "furniture") and (
                blocks[k - 1].kind == "furniture" or reference_like(" ".join(ln.text for ln in blocks[k - 1].lines))):
            k -= 1
        tail = [b for b in blocks[k:] if b.kind == "body"]
        if len(tail) >= 4:
            for b in tail:
                b.kind = "references"


def _author_line(t: str) -> bool:
    """A line of names: capitalised words, commas, "and", superscript marks; no sentence."""
    words = t.replace(",", " ").replace("·", " ").split()
    if not (2 <= len(words) <= 40) or _ENDS.search(t) and not t.endswith("."):
        return False
    caps = sum(1 for w in words if w[:1].isupper() or w.lower() in ("and", "&", "de", "van", "der", "von", "la"))
    return caps >= 0.8 * len(words) and not re.search(r"\b(the|of|is|are|was|we|this)\b", t)


# ------------------------------------------------------------------------------------------------------------------
# the document
# ------------------------------------------------------------------------------------------------------------------
@dataclass
class Reading:
    blocks: list[Block] = field(default_factory=list)
    tables: list[Block] = field(default_factory=list)
    report: dict = field(default_factory=dict)


def read_blocks(raw, version: int = READER) -> tuple[list[Block], dict]:
    """The blocks of a RawDoc in reading order, with their kinds and repaired text, and the reading report. `version`
    2 reads as ENLENS 0.15.0 did; 3 adds the rules of `reader3.py`."""
    from . import reader3

    v3 = version >= 3
    counts: Counter = Counter()
    pdf = raw.kind == "pdf"
    engine = "text"
    dims: list[tuple[float, float]] = []
    pages: list[list[Line]] = []
    if pdf:
        engine = "pypdf"
        got = None
        if pdfminer_available():
            try:
                got = _pdfminer_pages(raw.path)
            except Exception:  # noqa: BLE001 - a PDF pdfminer cannot read: pypdf's text
                got = None
        if got is not None and len(got[0]) == len(raw.pages):
            engine = "pdfminer"
            pages, dims = got
            pages = [join_section_numbers(p) for p in pages]
            for i, lines in enumerate(pages):
                chars = sum(len(ln.text.strip()) for ln in lines)
                if chars < 30 and len(raw.pages[i].strip()) > chars:  # recognised by OCR, or text pdfminer missed
                    pages[i] = _text_lines(raw.pages[i], i)
                    counts["pages_without_boxes"] += 1
        else:
            sizes = getattr(raw, "page_sizes", None) or []
            for i, text in enumerate(raw.pages):
                spots = raw.line_pos[i] if raw.line_pos and i < len(raw.line_pos) else None
                h = sizes[i][1] if i < len(sizes) else None
                pages.append(_text_lines(text, i, spots, h))
                dims.append(sizes[i] if i < len(sizes) else (0.0, 0.0))
    else:
        pages = [_text_lines(t, i) for i, t in enumerate(raw.pages)]
    if pdf and dims:
        mark_furniture(pages, dims)
    layout: dict = {}
    if v3:
        # lines without positions (text files, OCR, pypdf without them): text printed twice, running heads and page
        # numbers by repetition, and paragraphs in hard-wrapped text
        reader3.undouble_lines(pages, counts)
        layout = reader3.text_furniture(pages)
        layout["wrapped"] = reader3.paragraph_breaks(pages) is not None
    all_lines = [ln for p in pages for ln in p]
    sizes = Counter()
    for ln in all_lines:
        if ln.size and not ln.furniture:
            sizes[round(ln.size)] += len(ln.text)
    body_size = float(sizes.most_common(1)[0][0]) if sizes else None
    if v3:
        # ligatures a converter broke with a space ("fi nd"), joined before the document's words are counted, so the
        # splitting of words run together does not take "infl uenced" for two words and part them again
        lig_words = reader3.ligature_words(all_lines)
        if lig_words is not None:
            for ln in all_lines:
                ln.text = reader3.join_ligature_gaps(ln.text, lig_words, counts)
            reader3.join_ligature_breaks(pages, lig_words, counts)
            all_lines = [ln for p in pages for ln in p]
    vocab = _vocabulary(all_lines)
    bigrams = _bigrams(all_lines)

    blocks: list[Block] = []
    multi_col = 0
    for pno, lines in enumerate(pages):
        width = dims[pno][0] if pno < len(dims) else 0.0
        if pdf and width:
            lines, ncol = reading_order(lines, width)
            multi_col += ncol > 1
        # page furniture leaves the flow of the text: what stands above it first, the rest (and line numbers) last.
        # Reader 3: in lines without positions it stays where it stood, a block of its own.
        h = dims[pno][1] if pno < len(dims) else 0.0
        placed_lines = any(ln.top is not None for ln in lines)
        furn = [ln for ln in lines if ln.furniture] if placed_lines or not v3 else []
        lines = [ln for ln in lines if not ln.furniture] if placed_lines or not v3 else lines
        above = [ln for ln in furn if ln.furniture in ("head", "number") and h and ln.top is not None and ln.top < 0.5 * h]
        below = [ln for ln in furn if ln not in above and ln.furniture in ("head", "number")]
        numbers = [ln for ln in furn if ln.furniture in ("line-number", "turned")]
        tables = find_tables(lines) if pdf and engine == "pdfminer" else []
        in_table: dict[int, int] = {}
        for k, (tl, _grid) in enumerate(tables):
            for ln in tl:
                in_table[id(ln)] = k
        page_blocks: list[Block] = []
        rest: list[Line] = []
        placed: set[int] = set()

        def flush_rest():
            if rest:
                page_blocks.extend(make_blocks(list(rest), width, body_size))
                rest.clear()

        for ln in lines:
            k = in_table.get(id(ln))
            if k is None:
                rest.append(ln)
                continue
            if k in placed:
                continue
            flush_rest()
            placed.add(k)
            tl, grid = tables[k]
            page_blocks.append(Block(pno, sorted(tl, key=lambda x: (x.top, x.x0)), kind="table", rows=grid))
        flush_rest()
        blocks.extend(Block(pno, [ln], kind="furniture") for ln in above)
        blocks.extend(page_blocks)
        blocks.extend(Block(pno, [ln], kind="furniture") for ln in below)
        if numbers:
            blocks.append(Block(pno, numbers, kind="furniture"))
    classify(blocks, body_size, dims, pdf, raw.headings if not pdf else None, version)
    parts: dict = {}
    if v3:
        # books and theses: the contents, front and end matter, the index
        total = sum(len(" ".join(ln.text for ln in b.lines)) for b in blocks) or 1
        fracs, done = [], 0
        for b in blocks:
            fracs.append(done / total)
            done += len(" ".join(ln.text for ln in b.lines))
        parts = reader3.book_parts(blocks, fracs)
    damaged = v3 and reader3.damaged_spacing("\n".join(ln.text for ln in all_lines))

    # text of each block, repaired
    for b in blocks:
        if b.kind == "table" and b.rows:
            b.rows = [[repair(c, counts) for c in row] for row in b.rows]
            b.text = "\n".join(" | ".join(c for c in row) for row in b.rows)
            continue
        texts = [repair(ln.text, counts) for ln in b.lines]
        b.text = join_lines(texts, vocab, counts)
        if b.kind not in ("furniture", "figure", "table"):
            b.text = split_run_together(b.text, vocab, bigrams, counts)
            if damaged:
                b.text = reader3.split_runs(b.text, vocab, bigrams, _COMMON | _CLOSED, counts)
    blocks = [b for b in blocks if b.text.strip()]
    # captions of tables: the caption block just before or after a table
    for i, b in enumerate(blocks):
        if b.kind == "table":
            for j in (i - 1, i + 1):
                if 0 <= j < len(blocks) and blocks[j].kind == "caption" and blocks[j].text.lower().startswith(("tab",)):
                    b.caption = blocks[j].text
                    break
    # a paragraph that goes on in the next content block (a column or a page turned mid-sentence); a word
    # hyphenated across that turn is put together at the end of the first block ("complex-" + "ity. An" ->
    # "complexity." + "An")
    content = [b for b in blocks if b.kind in ("body", "abstract")]
    for a, c in zip(content, content[1:]):
        if a.kind == c.kind and not _ENDS.search(a.text.rstrip()) and c.text[:1].islower():
            a.continues = True
            if a.text.endswith(("-", "\u2010")) and _TAIL.search(a.text):
                head, _sp, rest = c.text.partition(" ")
                joined = join_lines([a.text, head], vocab, counts)
                a.text = joined
                c.text = rest.lstrip()
    blocks = [b for b in blocks if b.text.strip()]
    report = {
        "reader": version, "engine": engine, "pages": len(raw.pages),
        "pages_with_text": sum(1 for p in pages if sum(len(ln.text.strip()) for ln in p) >= 30),
        "ocr_pages": getattr(raw, "ocr_pages", 0) or 0,
        "scanned_pages": getattr(raw, "scanned_pages", 0) or 0,
        "multi_column_pages": multi_col,
        "repairs": {k: counts[k] for k in ("hyphens_joined", "hyphens_kept", "words_split", "ligatures", "spaces",
                                           "accents")},
        "tables": sum(1 for b in blocks if b.kind == "table"),
    }
    if v3:
        report["repairs"]["doubled"] = counts["doubled"]
        report["text_layout"] = layout
        report["book"] = parts
    return blocks, report


def assemble(blocks: list[Block], n_pages: int) -> tuple[str, list[tuple[int, int]]]:
    """The stored text: each page's blocks one per line, pages apart by a blank line (as reader 1). Sets each
    block's start and end."""
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    for p in range(n_pages):
        if p:
            parts.append("\n\n")
            pos += 2
        start = pos
        for k, b in enumerate(by_page.get(p, [])):
            if k:
                parts.append("\n")
                pos += 1
            b.start = pos
            parts.append(b.text)
            pos += len(b.text)
            b.end = pos
        spans.append((start, pos))
    return "".join(parts), spans


def make_passages(text: str, blocks: list[Block], spans, max_chars: int, min_chars: int):
    """Passages that never mix what features read with what they leave out: a heading goes with the text under it,
    short paragraphs of one kind are put together up to `min_chars`, a paragraph cut by a column or page goes on in
    the same passage, long ones are cut between sentences at `max_chars`."""
    from .ingest import Passage, page_of, reference_like, unreadable

    ends = [e + 2 for _s, e in spans]
    out: list[Passage] = []
    groups: list[tuple[str, list[Block]]] = []  # (group kind, blocks)
    for b in blocks:
        g = "in" if b.included else b.kind
        last = groups[-1] if groups else None
        if last is not None:
            lk, lbs = last
            prev = lbs[-1]
            size = lbs[-1].end - lbs[0].start
            same = lk == g and (
                prev.kind == "heading" or prev.kind == "title" and b.kind != "body"
                or (g == "in" and prev.continues)
                or (g == "in" and prev.kind == b.kind and size < min_chars and prev.page == b.page)
                or (g != "in" and prev.page == b.page and size < max_chars))
            if g == "in" and prev.kind in ("heading",) and b.kind in INCLUDED:
                same = True
            if same:
                lbs.append(b)
                continue
        groups.append((g, [b]))

    for g, bs in groups:
        kind = next((b.kind for b in bs if b.kind not in ("heading", "title")), bs[0].kind)
        a0, b1 = bs[0].start, bs[-1].end
        sents: list[tuple[int, int]] = []
        for b in bs:
            if b.kind == "table":
                sents.append((b.start, b.end))
                continue
            for a, z in split_sentences(text[b.start:b.end], offset=b.start):
                while z - a > max_chars:
                    cut = text.rfind(" ", a + min_chars, a + max_chars)
                    forced = cut <= a
                    cut = cut if not forced else a + max_chars
                    sents.append((a, cut))
                    a = cut if forced else cut + 1
                if z > a:
                    sents.append((a, z))
        if not sents:
            sents = [(a0, b1)]
        cur: list[tuple[int, int]] = []
        # a group longer than max_chars is cut into parts of about equal size (not one full part and a scrap)
        parts = max(1, -(-(b1 - a0) // max_chars))
        target = (b1 - a0) / parts

        def flush():
            if not cur:
                return
            a, z = cur[0][0], cur[-1][1]
            body = text[a:z]
            if g == "in":
                section = "unreadable" if unreadable(body) else "reference_like" if reference_like(body) else "body"
            elif g == "references":
                section = "references"
            else:
                section = "left_out"
            p = Passage(len(out), a, z, page_of(a, spans, ends), section)
            p.block = kind
            out.append(p)
            cur.clear()

        for a, z in sents:
            if cur and (z - cur[0][0] > max_chars or (parts > 1 and cur[-1][1] - cur[0][0] >= target)):
                flush()
            cur.append((a, z))
        flush()
    return out


def build_document(raw, max_chars: int = 1100, min_chars: int = 200, version: int = READER):
    """A Document read by reader 2 or 3 (see `ingest.read_document`)."""
    from .ingest import Document, Layout, guess_doi, guess_title

    blocks, report = read_blocks(raw, version)
    text, spans = assemble(blocks, max(1, len(raw.pages)))
    for n, b in enumerate(blocks, 1):
        b.n = n
    title = guess_title(raw, text)
    t_block = next((b for b in blocks if b.kind == "title"), None)
    if t_block is not None and not raw.meta_title:
        title = t_block.text[:300]
    doc = Document("d" + raw.sha1[:10], raw, text, spans, title, guess_doi(raw, text, spans))
    doc.passages = make_passages(text, blocks, spans, max_chars, min_chars)
    lay = Layout()
    # Paragraphs, as quotes are cited ("page 2, paragraph 3"; "paragraph 7" in files without pages). In a file
    # without pages every block that counts is one, as reader 1 counted blocks between blank lines. In a PDF every
    # page starts one, and a heading and the text under it are one paragraph, as is a paragraph a column cut in two.
    prev = None
    for b in blocks:
        if b.kind in ("heading", "title"):
            lay.headings.append((b.start, b.end, text[b.start:b.end]))
        if b.kind not in INCLUDED:
            continue
        pg = b.page + 1 if raw.paginated else None
        if not raw.paginated or prev is None or prev.page != b.page or not (
                prev.kind in ("heading", "title") or prev.continues):
            lay.paragraphs.append((pg, b.start))
        prev = b
    doc.layout = lay
    if not raw.paginated:
        for p in doc.passages:
            p.page = None
        doc.paragraphs = [s0 for _pg, s0 in lay.paragraphs]
    doc.blocks = blocks
    doc.reading = finish_report(report, blocks, doc.passages, text, raw.kind)
    return doc


def finish_report(report: dict, blocks: list[Block], passages, text: str, raw_kind: str = "") -> dict:
    """The reading report (A5): what the reader did and whether the document read well, in figures and warnings."""
    kinds = Counter(b.kind for b in blocks)
    chars = Counter()
    for b in blocks:
        chars[b.kind] += len(b.text)
    total = sum(chars.values()) or 1
    included = sum(v for k, v in chars.items() if k in INCLUDED)
    body = [p for p in passages if p.section == "body"]
    unreadable = sum(1 for p in passages if p.section == "unreadable")
    out = dict(report)
    out.update({
        "blocks": dict(sorted(kinds.items())),
        "left_out_chars": {k: v for k, v in sorted(chars.items()) if k not in INCLUDED},
        "included_share": round(included / total, 3),
        "passages": len(passages), "body_passages": len(body), "unreadable_passages": unreadable,
        "words": len(text.split()),
    })
    warnings: list[str] = []
    pages = out.get("pages") or 0
    missing = pages - (out.get("pages_with_text") or 0)
    if missing > 0:
        warnings.append(f"{missing} of {pages} pages have no text: they look scanned"
                        + (" and could not be recognised." if out.get("scanned_pages", 0) > out.get("ocr_pages", 0)
                           else "."))
    if out.get("ocr_pages"):
        warnings.append(f"The text of {out['ocr_pages']} pages was recognised from their image (OCR): check quotes "
                        "from them against the page.")
    in_passages = len(passages) - sum(1 for p in passages if p.section in ("left_out", "references"))
    if in_passages and unreadable > 0.1 * in_passages:
        warnings.append(f"{unreadable} passages could not be read: the PDF's text layer is garbled (a font without a "
                        "character map). Recognising its pages (OCR) may help.")
    if total > 400 and included < 0.35 * total:
        warnings.append(f"Only {round(100 * included / total)}% of the text counts as the document's own text; the "
                        "rest was set aside. Look at what was left out in the reading view.")
    if not body and total > 100:
        warnings.append("No passage of this document is used by searches, codes, themes or checks.")
    if (out.get("reader") or 2) >= 3:
        from . import reader3

        warnings += reader3.report_warnings(out, raw_kind, text)
    out["warnings"] = warnings
    out["quality"] = "poor" if (not body and total > 100) or (pages and missing > 0.5 * pages) or (
        in_passages and unreadable > 0.3 * in_passages) else "fair" if warnings else "good"
    return out


# 0.15.7: where to look for each warning of a reading report, so the Reading panel can take the person there
# ("page": the pages of the original, beside the text; "left_out": what the reader set aside, shown in the text).
# Matched on the words finish_report and reader3.report_warnings write, which reports already stored use too.
WARNING_PLACES = (("look scanned", "page"), ("recognised from their image", "page"),
                  ("text layer is garbled", "page"), ("counts as the document's own text", "left_out"),
                  ("No passage of this document is used", "left_out"))


def warning_place(warning: str) -> str | None:
    """Where the person can see what a reading report's warning is about ("page", "left_out"), or None when the
    warning is advice with nothing to look at (add the PDF instead of a copied text, say)."""
    return next((place for words, place in WARNING_PLACES if words in warning), None)


# ------------------------------------------------------------------------------------------------------------------
# a person's corrections (A4: Restore, Leave out)
# ------------------------------------------------------------------------------------------------------------------
def block_fp(text: str) -> str:
    """A block's fingerprint: its words, so a correction finds its block again when the document is read anew."""
    import hashlib

    words = " ".join(re.findall(r"[^\W_]+", text.lower()))
    return hashlib.sha1(words.encode("utf-8")).hexdigest()[:16]


BOUNDS = ("start", "end")   # 0.15.1: "Text starts here" and "Text ends here", kept in block_choices as "<side>:<fp>:<k>"


def bound_key(side: str, fps: list[str], i: int) -> str:
    """The choice that marks block i (of blocks with fingerprints `fps`, in reading order) as where the text starts
    or ends: its fingerprint and which of the blocks with the same words it is, so it holds when read again."""
    return f"{side}:{fps[i]}:{sum(1 for f in fps[:i] if f == fps[i])}"


def bound_index(choices: dict, side: str, fps: list[str]) -> int | None:
    """Where the person said the text starts or ends (a block index), if they did and the block is still there."""
    key = next((k for k in choices if k.startswith(side + ":")), None)
    if key is None:
        return None
    _side, fp, k = key.split(":", 2)
    seen = -1
    for i, f in enumerate(fps):
        if f == fp:
            seen += 1
            if str(seen) == k:
                return i
    return None


def choose_inclusion(items: list[tuple[str, str]], choices: dict) -> list[int]:
    """Whether each block counts (1) or is left out (0), for blocks given as (text, kind) in reading order: its kind;
    then the person's *Text starts here* and *Text ends here* (what comes before or after is left out); then the
    person's *Restore* or *Leave out* of that block, which always wins."""
    want = [1 if kind in INCLUDED else 0 for _t, kind in items]
    if not choices:
        return want
    fps = [block_fp(t) for t, _k in items]
    first = bound_index(choices, "start", fps)
    last = bound_index(choices, "end", fps)
    for i in range(len(items)):
        if (first is not None and i < first) or (last is not None and i > last):
            want[i] = 0
        if fps[i] in choices:
            want[i] = int(choices[fps[i]])
    return want


def apply_choices(cx, doc_id: str) -> list[int]:
    """Apply the person's corrections of a document's blocks: each block's `included` from its kind, then where the
    person said the text starts and ends, then their choices by fingerprint (`choose_inclusion`), and every passage's
    section from its blocks. A passage that holds several blocks (a heading and its paragraph, short paragraphs put
    together) is read when any of them is. Returns the blocks whose inclusion changed."""
    rows = cx.execute("SELECT n, start, end, kind, included FROM blocks WHERE doc_id=? ORDER BY n", (doc_id,)).fetchall()
    if not rows:
        return []
    (text,) = cx.execute("SELECT text FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    choices = {fp: inc for fp, inc in cx.execute("SELECT fp, included FROM block_choices WHERE doc_id=?", (doc_id,))}
    changed = []
    want: dict[int, int] = {}
    chosen = choose_inclusion([(text[a:z], kind) for _n, a, z, kind, _inc in rows], choices)
    for (n, _a, _z, _kind, inc), w in zip(rows, chosen):
        want[n] = w
        if w != inc:
            changed.append(n)
    if changed:
        cx.executemany("UPDATE blocks SET included=? WHERE doc_id=? AND n=?", [(want[n], doc_id, n) for n in changed])
    spans = [(a, z, want[n], kind) for n, a, z, kind, _inc in rows]
    ups = []
    for pid, a, z, section in cx.execute("SELECT passage_id, start, end, section FROM passages WHERE doc_id=?",
                                         (doc_id,)).fetchall():
        mine = [(inc, kind) for b0, b1, inc, kind in spans if b0 < z and b1 > a]
        if not mine:
            continue
        inc = any(i for i, _k in mine)
        if inc:
            if section in ("left_out", "references"):
                from .ingest import reference_like, unreadable

                body = text[a:z]
                new = "unreadable" if unreadable(body) else "reference_like" if reference_like(body) else "body"
            else:
                new = section
        else:
            new = "references" if all(k == "references" for _i, k in mine) else "left_out"
        if new != section:
            ups.append((new, pid))
    if ups:
        cx.executemany("UPDATE passages SET section=? WHERE passage_id=?", ups)
    return changed

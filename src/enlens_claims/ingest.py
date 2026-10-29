"""Read PDFs, HTML and text into documents and passages with page and character offsets.

All offsets point into the stored document text: one cleaned string per document, pages joined by a
blank line. Quotes, evidence and highlights are resolved against that string.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import re
import shutil
import sqlite3
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .store import Workspace, now
from .textutil import find_dois, split_sentences

SUPPORTED = {".pdf", ".html", ".htm", ".txt", ".md", ".docx"}
REF_HEADING = re.compile(
    r"(?:^|\s)(References|REFERENCES|Bibliography|BIBLIOGRAPHY|Literature [Cc]ited|Works [Cc]ited|Reference [Ll]ist)"
    r"\s*:?\s+(?=\[?\(?\d|[A-Z][A-Za-z'\-]+,?\s+[A-Z]|[A-Z]{2,})"
)


@dataclass
class RawDoc:
    path: Path
    kind: str
    pages: list[str]
    meta_title: str | None = None
    sha1: str = ""
    paginated: bool = True  # False for text without page breaks: passages then carry no page number
    headings: set[str] | None = None  # the heading lines a web page or markdown file marks as such
    ocr_pages: int = 0       # PDF pages without a text layer whose text was recognised (OCR)
    scanned_pages: int = 0   # PDF pages without a text layer (recognised or not)
    line_pos: list | None = None  # PDFs: per page, the (x, y) where each line of its text starts (None: unknown)


@dataclass
class Passage:
    seq: int
    start: int
    end: int
    page: int | None
    section: str


@dataclass
class Document:
    doc_id: str
    raw: RawDoc
    text: str
    page_spans: list[tuple[int, int]]
    title: str
    doi: str | None
    passages: list[Passage] = field(default_factory=list)
    paragraphs: list[int] = field(default_factory=list)  # where each paragraph starts (documents without pages)
    layout: "Layout | None" = None                       # paragraphs (with their page) and headings, all documents


# ------------------------------------------------------------------------------------------
# reading
# ------------------------------------------------------------------------------------------
class _TextOnly(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "table", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title: str | None = None
        self._in_title = False
        self.headings: set[str] = set()
        self._heading: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "noscript"):
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "noscript") and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading is not None:
            t = " ".join("".join(self._heading).split())
            if t:
                self.headings.add(t)
            self._heading = None
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        elif not self.skip:
            self.parts.append(data)
            if self._heading is not None:
                self._heading.append(data)


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:  # streamed: a large PDF is never held in memory for its checksum
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_file(path: Path, ocr: "OcrOptions | None" = None) -> RawDoc:
    ext = path.suffix.lower()
    if ext == ".pdf":
        sha1 = _sha1(path)
        pages, title, done, scanned, pos = _read_pdf(path, ocr)
        return RawDoc(path, "pdf", pages, title, sha1, ocr_pages=done, scanned_pages=scanned, line_pos=pos)
    if ext == ".docx":
        sha1 = _sha1(path)
        pages, title, heads = _read_docx(path)
        return RawDoc(path, "docx", pages, title, sha1, paginated=len(pages) > 1, headings=heads)
    data = path.read_bytes()
    sha1 = hashlib.sha1(data).hexdigest()
    if ext in (".html", ".htm"):
        p = _TextOnly()
        p.feed(data.decode("utf-8", errors="replace"))
        return RawDoc(path, "html", ["".join(p.parts)], (p.title or "").strip() or None, sha1, paginated=False,
                      headings=p.headings)
    text = data.decode("utf-8", errors="replace")
    heads = None
    if ext == ".md":
        heads = markdown_headings(text)
        text = strip_markdown(text)
    pages = text.split("\f") if "\f" in text else [text]
    return RawDoc(path, "text", pages, None, sha1, paginated="\f" in text, headings=heads)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DOCX_MAX = 200 * 1024 ** 2   # bytes of XML read from one Word file (a zip): a bound against zip bombs


def _read_docx(path: Path) -> tuple[list[str], str | None, set[str]]:
    """A Word file (.docx: a zip of XML) with the standard library: its paragraphs (separated by a blank line, as in a
    text file), its headings (paragraph styles Title and Heading 1 to 9), its pages where Word marked them (a page
    break, or where Word last laid out a new page), and its title (document properties). Tables are read row by row;
    footnotes, comments and text boxes are left out."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("word/document.xml")
        if info.file_size > DOCX_MAX:
            raise ValueError("The Word file's text is too large to read.")
        root = ET.fromstring(zf.read(info))
        title = None
        try:
            core = ET.fromstring(zf.read("docProps/core.xml"))
            t = core.find("{http://purl.org/dc/elements/1.1/}title")
            title = (t.text or "").strip() or None if t is not None else None
        except KeyError:
            title = None
    body = root.find(f"{_W}body")
    pages: list[list[str]] = [[]]
    heads: set[str] = set()

    def para_text(p) -> tuple[str, bool]:
        """The paragraph's text, and whether a new page starts in it (before its text)."""
        out, new_page = [], False
        for el in p.iter():
            tag = el.tag
            if tag == f"{_W}t":
                out.append(el.text or "")
            elif tag == f"{_W}tab":
                out.append("\t")
            elif tag in (f"{_W}br", f"{_W}cr"):
                if el.get(f"{_W}type") == "page":
                    if "".join(out).strip():
                        out.append("\f")
                    else:
                        new_page = True
                else:
                    out.append("\n")
            elif tag == f"{_W}lastRenderedPageBreak":
                if "".join(out).strip():
                    out.append("\f")
                else:
                    new_page = True
            elif tag in (f"{_W}noBreakHyphen",):
                out.append("-")
        return "".join(out), new_page

    def style(p) -> str:
        ps = p.find(f"{_W}pPr/{_W}pStyle")
        return (ps.get(f"{_W}val") or "") if ps is not None else ""

    def add(text: str, new_page: bool, heading: bool) -> None:
        if new_page and any(x.strip() for x in pages[-1]):
            pages.append([])
        for k, piece in enumerate(text.split("\f")):
            if k and any(x.strip() for x in pages[-1]):
                pages.append([])
            piece = piece.strip()
            if piece:
                pages[-1].append(piece)
                if heading:
                    heads.add(" ".join(piece.split()))

    for child in list(body) if body is not None else []:
        if child.tag == f"{_W}p":
            text, new_page = para_text(child)
            st = style(child).lower().replace(" ", "")
            add(text, new_page, st == "title" or bool(re.fullmatch(r"heading[1-9]", st)))
        elif child.tag == f"{_W}tbl":
            for row in child.iter(f"{_W}tr"):
                cells = []
                for cell in row.iter(f"{_W}tc"):
                    cells.append(" ".join(para_text(p)[0].replace("\f", " ").strip() for p in cell.iter(f"{_W}p")).strip())
                add(" | ".join(c for c in cells if c), False, False)
    out = ["\n\n".join(pg) for pg in pages if any(x.strip() for x in pg)]
    return out or [""], title, heads


def _md_line(ln: str) -> str:
    ln = re.sub(r"^\s{0,3}#{1,6}\s+", "", ln)
    return re.sub(r"\s*\|\s*", " ", ln)


def strip_markdown(text: str) -> str:
    """Remove markdown table rules, cell bars and heading marks so table text reads as plain words."""
    lines = []
    for ln in text.split("\n"):
        if re.fullmatch(r"[\s|:\-]*\|[\s|:\-]*", ln) and "-" in ln:
            continue  # table separator row
        lines.append(_md_line(ln))
    return "\n".join(lines)


def markdown_headings(text: str) -> set[str]:
    """The heading lines of a markdown file (# …), as `strip_markdown` leaves them."""
    return {" ".join(_md_line(ln).split()) for ln in text.split("\n") if re.match(r"^\s{0,3}#{1,6}\s+\S", ln)}


# ------------------------------------------------------------------------------------------
# OCR of scanned PDF pages (optional: `pip install 'enlens-claims[ocr]'` and the program tesseract)
# ------------------------------------------------------------------------------------------
SCANNED_CHARS = 30   # a PDF page with less text than this is taken to be a scan
OCR_DPI = 200


@dataclass
class OcrOptions:
    mode: str = "auto"   # auto: recognise the text of scanned pages when OCR is installed; off: never
    lang: str = "eng"    # Tesseract languages, e.g. "eng+nld"


_OCR_STATUS: list = [0.0, None]


def ocr_status(max_age: float = 60.0) -> dict:
    """Whether scanned pages can be read here: {"available": bool, "missing": [...], "languages": [...]}.
    Checked again after a minute, so installing Tesseract while the app runs is noticed."""
    import importlib.util
    import time

    if _OCR_STATUS[1] is not None and time.time() - _OCR_STATUS[0] < max_age:
        return dict(_OCR_STATUS[1])

    missing = [m for m, mod in (("pypdfium2", "pypdfium2"), ("pillow", "PIL")) if importlib.util.find_spec(mod) is None]
    exe = shutil.which("tesseract")
    if not exe:
        missing.append("tesseract")
    langs: list[str] = []
    if exe:
        try:
            import subprocess

            r = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=10)
            langs = [ln.strip() for ln in (r.stdout or "").splitlines()[1:] if ln.strip() and ln.strip() != "osd"]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    _OCR_STATUS[:] = [time.time(), {"available": not missing, "missing": missing, "languages": langs}]
    return dict(_OCR_STATUS[1])


def _low_priority() -> None:  # runs in the OCR child process before tesseract starts (POSIX)
    import os

    try:
        os.nice(10)
    except OSError:
        pass


def _ocr_pages(path: Path, numbers: list[int], lang: str) -> dict[int, str]:
    """The text of the given pages (0-based), recognised one page at a time at low priority on one thread, so a
    local model working at the same time keeps the computer's resources. Each page image is freed at once."""
    import io
    import os
    import subprocess

    import pypdfium2 as pdfium

    exe = shutil.which("tesseract")
    if not exe or not re.fullmatch(r"[A-Za-z_]{2,}(\+[A-Za-z_]{2,})*", lang or ""):
        return {}
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    out: dict[int, str] = {}
    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in numbers:
            if i >= len(pdf):
                continue
            page = pdf[i]
            try:
                bitmap = page.render(scale=OCR_DPI / 72, grayscale=True)
                image = bitmap.to_pil()
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                del image, bitmap
                png = buf.getvalue()
                buf.close()
            finally:
                page.close()
            try:
                r = subprocess.run([exe, "stdin", "stdout", "-l", lang], input=png, capture_output=True, env=env,
                                   timeout=300, preexec_fn=_low_priority if os.name == "posix" else None)
            except (OSError, subprocess.SubprocessError):
                continue
            finally:
                del png
            if r.returncode == 0:
                out[i] = r.stdout.decode("utf-8", errors="replace")
    finally:
        pdf.close()
    return out


class _LineSpots:
    """Collects where each line of a page's extracted text starts on the page, during the same extraction (pypdf's
    text visitor sees the text exactly as it is returned), so paragraph gaps and indents can be seen later."""

    def __init__(self):
        self.line = 0
        self.spots: dict[int, tuple[float, float]] = {}

    def __call__(self, text, cm, tm, _font, _size):
        if not text:
            return
        try:
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        except (TypeError, IndexError):
            x = y = None
        for k, piece in enumerate(text.split("\n")):
            if k:
                self.line += 1
            if piece.strip() and self.line not in self.spots and x is not None:
                self.spots[self.line] = (float(x), float(y))

    def lines(self, text: str) -> list[tuple[float, float] | None]:
        return [self.spots.get(i) for i in range(text.count("\n") + 1)]


def _read_pdf(path: Path, ocr: OcrOptions | None = None) -> tuple[list[str], str | None, int, int, list | None]:
    """The text of each page, the title from the metadata, (pages recognised by OCR, scanned pages), and where each
    line starts on its page (for the layout; None for pages read another way)."""
    pages: list[str] = []
    pos: list | None = []
    title = None
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        try:
            meta = reader.metadata
            title = (meta.title if meta else None) or None
        except Exception:
            title = None
        for pg in reader.pages:
            spots = _LineSpots()
            try:
                t = pg.extract_text(visitor_text=spots) or ""
                pages.append(t)
                pos.append(spots.lines(t))
            except Exception:
                pages.append("")
                pos.append(None)
    except Exception:
        pages, pos = [], []
    n_pdf = len(pages)
    if sum(len(p.strip()) for p in pages) < 200:
        try:  # optional fallback
            from pdfminer.high_level import extract_text

            alt = extract_text(str(path)) or ""
            if len(alt.strip()) > sum(len(p.strip()) for p in pages):
                pages = alt.split("\f")
                pos = None
        except Exception:
            pass
    if title and (len(title) < 8 or re.search(r"microsoft|untitled|\.docx?$|\.pdf$", title, re.I)):
        title = None
    scanned = [i for i, p in enumerate(pages) if len(p.strip()) < SCANNED_CHARS] if len(pages) == n_pdf else []
    done = 0
    if scanned and ocr is not None and ocr.mode != "off" and ocr_status()["available"]:
        for i, t in _ocr_pages(path, scanned, ocr.lang).items():
            if len(t.strip()) > len(pages[i].strip()):
                pages[i] = t
                if pos is not None:
                    pos[i] = None
                done += 1
    return pages, title, done, len(scanned), pos


# ------------------------------------------------------------------------------------------
# cleaning and segmentation
# ------------------------------------------------------------------------------------------
def clean_page(text: str) -> str:
    t = text.replace("\r", "\n")
    t = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", t)  # hyphenation at line ends
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r"\s*\n\s*", " ", t)  # line breaks inside a page become spaces
    return t.strip()


def assemble(pages: list[str]) -> tuple[str, list[tuple[int, int]]]:
    text_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    for i, p in enumerate(pages):
        c = clean_page(p)
        if i:
            text_parts.append("\n\n")
            pos += 2
        spans.append((pos, pos + len(c)))
        text_parts.append(c)
        pos += len(c)
    return "".join(text_parts), spans


# ------------------------------------------------------------------------------------------
# layout: paragraphs and headings, found in the raw page text (the stored text keeps no line breaks)
# ------------------------------------------------------------------------------------------
_P, _H, _E = "\x02", "\x03", "\x04"          # markers: paragraph start, heading start, heading end
_ENDS_SENTENCE = re.compile(r"[.!?:][\"'”’)\]]*$")
_STARTS_UPPER = re.compile(r"[\"'“‘(\[]*[A-ZÀ-ÖØ-Þ]")


@dataclass
class Layout:
    paragraphs: list[tuple[int | None, int]] = field(default_factory=list)  # (page or None, document offset)
    headings: list[tuple[int, int, str]] = field(default_factory=list)       # (start, end, text)


def _is_heading(t: str, prev: str | None, nxt: str | None, short: float, known: set[str] | None = None) -> bool:
    """A short line with no closing punctuation, after the end of a sentence (or a blank line), followed by text:
    "Summary", "3. Discussion", "Results and implications". Web pages and markdown say which lines are headings
    (`known`: h1–h6 elements, # lines); for them only those count."""
    if known is not None:
        return " ".join(t.split()) in known
    if not (2 <= len(t) <= 80) or len(t) > short or nxt is None:
        return False
    if t[-1] in ".,;:!?-–—/" or not re.match(r"[A-ZÀ-ÖØ-Þ0-9]", t):
        return False
    if len(re.findall(r"[^\W\d_]", t)) < 2 or re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", t, re.I):
        return False
    return prev is None or prev == "" or bool(_ENDS_SENTENCE.search(prev))


_SECTION_NO = re.compile(r"(\d{1,2}(\.\d{1,2})*\.?|[IVX]{1,4}\.)\s+[A-ZÀ-ÖØ-Þ]")


def _pdf_breaks(lines: list[str], spots: list | None) -> set[int]:
    """Lines of a PDF page that start a paragraph by their position: after a vertical gap clearly larger than the
    line spacing, or indented from the left margin after a line that ends a sentence."""
    if not spots or len(spots) != len(lines):
        return set()
    seq = [(i, spots[i]) for i, ln in enumerate(lines) if ln.strip() and spots[i] is not None]
    gaps = [a[1][1] - b[1][1] for a, b in zip(seq, seq[1:]) if 0 < a[1][1] - b[1][1] < 200]
    if len(gaps) < 3:
        return set()
    step = sorted(gaps)[len(gaps) // 4]  # the line spacing: the commonest small gap (paragraph gaps are larger)
    xs = sorted(p[0] for _i, p in seq)
    margin = xs[len(xs) // 4]  # the left margin: most lines start there
    out = set()
    for (i0, p0), (i1, p1) in zip(seq, seq[1:]):
        gap = p0[1] - p1[1]
        if gap > 1.45 * step:
            out.add(i1)
        elif (0 < gap and p1[0] - margin >= max(6.0, 0.6 * step) and p0[0] - margin < 0.3 * step
              and _ENDS_SENTENCE.search(lines[i0].strip())):
            out.add(i1)
    return out


def _page_layout(page: str, pdf: bool, known: set[str] | None = None,
                 spots: list | None = None) -> tuple[str, list[int], list[tuple[int, int]]] | None:
    """Mark paragraph and heading lines of one raw page, clean it as `clean_page` does, and return
    (cleaned text, paragraph offsets, heading spans) in the cleaned page. None when the page cannot be mapped."""
    if any(c in page for c in (_P, _H, _E)):
        return None
    if "\r" in page:
        spots = None
    lines = page.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stripped = [ln.strip() for ln in lines]
    filled = [len(s) for s in stripped if s]
    if not filled:
        return None
    median = sorted(filled)[len(filled) // 2]
    short = 0.8 * median if pdf and median > 40 else 80.0   # wrapped PDF lines: a heading is clearly shorter
    nonblank = [i for i, s in enumerate(stripped) if s]
    first = nonblank[0]
    out = list(lines)
    placed = _pdf_breaks(lines, spots) if pdf else set()
    for j, i in enumerate(nonblank):
        t = stripped[i]
        prev = stripped[i - 1] if i > 0 else None
        nxt = stripped[nonblank[j + 1]] if j + 1 < len(nonblank) else None
        block_start = i == first or prev == ""
        heading = _is_heading(t, prev if i > first else None, nxt, short, known)
        lead = len(lines[i]) - len(lines[i].lstrip())
        body = lines[i].rstrip()
        para = block_start or (pdf and (heading or i in placed))
        if pdf and not para and prev and _ENDS_SENTENCE.search(prev):
            # a short line that ends a sentence, then a capital; or a numbered section ("2. Results", "IV. Data")
            para = (len(prev) < 0.8 * median and bool(_STARTS_UPPER.match(t))) or bool(_SECTION_NO.match(t))
        if heading:
            out[i] = body[:lead] + (_P if para else "") + _H + body[lead:] + _E + lines[i][len(body):]
        elif para:
            out[i] = lines[i][:lead] + _P + lines[i][lead:]
    marked = clean_page("\n".join(out))
    text, paras, heads, h_at = [], [], [], None
    for ch in marked:
        if ch == _P:
            paras.append(len(text))
        elif ch == _H:
            h_at = len(text)
        elif ch == _E:
            if h_at is not None:
                heads.append((h_at, len(text)))
            h_at = None
        else:
            text.append(ch)
    cleaned = "".join(text)
    if cleaned != clean_page(page):  # the markers changed how the page was cleaned: do not guess
        return None
    return cleaned, sorted(set(paras)), heads


def layout(raw: "RawDoc", text: str, spans: list[tuple[int, int]]) -> Layout:
    """Paragraphs and headings of a document, as offsets into its stored text (which is not changed).

    - text files and web pages: a paragraph is a block between blank lines, as 0.5.1 counted them;
    - PDFs: every page starts a paragraph (they are numbered per page: "page 2, paragraph 3"), and so does a line
      after a vertical gap, an indented line after the end of a sentence, a line after a short line that ends a
      sentence when it starts with a capital, a numbered section ("2. Results") and a heading;
    - headings (any kind): see `_is_heading`. A heading and the text that follows it without a break are one
      paragraph, so a reader counts "the paragraph under Results" as one.
    """
    out = Layout()
    pdf = raw.kind == "pdf"
    for n, (page, (s0, e0)) in enumerate(zip(raw.pages, spans), 1):
        spots = raw.line_pos[n - 1] if raw.line_pos and n - 1 < len(raw.line_pos) else None
        got = _page_layout(page, pdf, raw.headings, spots)
        pg = n if raw.paginated else None
        if got is None or got[0] != text[s0:e0]:
            if raw.paginated and e0 > s0:
                out.paragraphs.append((pg, s0))  # at least the page itself
            continue
        _cleaned, paras, heads = got
        if raw.paginated and e0 > s0 and (not paras or paras[0] > 0):
            paras = [0] + paras
        out.paragraphs += [(pg, s0 + p) for p in paras if s0 + p < e0]
        out.headings += [(s0 + a, s0 + b, text[s0 + a:s0 + b]) for a, b in heads if b > a]
    if not raw.paginated and not out.paragraphs and text:
        out.paragraphs = [(None, s) for s in paragraph_starts(raw.pages, text)]
    return out


def paragraph_starts(pages: list[str], text: str) -> list[int]:
    """Where each paragraph of the source (blocks separated by a blank line) starts in the cleaned text, so a quote
    in a text or web page can be cited as "paragraph 7". Cleaning joins lines, so the breaks are found in the source."""
    out: list[int] = []
    cursor = 0
    for page in pages:
        for para in re.split(r"\n[ \t]*\n", page.replace("\r\n", "\n").replace("\r", "\n")):
            key = clean_page(para)[:60]
            if not key:
                continue
            pos = text.find(key, cursor)
            if pos < 0:
                continue
            out.append(pos)
            cursor = pos + len(key)
    return out


def page_of(offset: int, spans: list[tuple[int, int]], ends: list[int] | None = None) -> int:
    """1-based page number for a document offset (the blank line after a page counts as that page).

    `ends` (each span's end + 2, precomputed by the caller) makes the lookup a binary search.
    """
    if ends is None:
        ends = [e + 2 for _s, e in spans]
    i = bisect.bisect_right(ends, offset)
    return i + 1 if i < len(spans) else max(1, len(spans))


def references_start(text: str) -> int | None:
    """Offset where the reference list begins, if a heading is found in the last 60% of the text."""
    floor = int(len(text) * 0.4)
    best = None
    for m in REF_HEADING.finditer(text):
        if m.start(1) >= floor:
            best = m.start(1)
            break
    return best


def reference_like(s: str) -> bool:
    """True for passages that read like bibliography entries rather than prose."""
    years = len(re.findall(r"\b(19|20)\d{2}[a-z]?\b", s))
    dois = len(re.findall(r"10\.\d{4,9}/", s))
    etal = len(re.findall(r"\bet al\.?", s))
    vols = len(re.findall(r"\b\d+\s*\(\d+\)\s*[:,]\s*\d+", s)) + len(re.findall(r"\bpp?\.\s*\d+", s))
    words = max(1, len(s.split()))
    return dois >= 2 or (years + etal + vols) / words > 0.08


CID_RE = re.compile(r"\(cid:\d+\)")
_WORD_RE = re.compile(r"[^\W\d_]{2,}")
# function words of the languages the corpus may contain; prose has many, glyph-code garble has none
_FUNCTION_WORDS = frozenset(
    "the of and to in for is on that by with as are from be this or an at which it can will not has have was "
    "de la le les et des du en el los las y que con por para del una un se al lo es da do dos das em os ao "
    "der die das und von mit den dem ist im zu het een van voor op te zijn niet".split())


def unreadable(s: str) -> bool:
    """True when a PDF text layer has no usable character map.

    Two forms occur: '(cid:53)(cid:72)...' codes, and fonts whose glyph codes come out as shifted
    letters and control characters ('5HQHZDEOH DQG ...' for 'Renewable and ...').
    """
    n = max(1, len(s))
    if len(CID_RE.findall(s)) * 8 > 0.2 * n:
        return True
    ctrl = sum(1 for c in s if (ord(c) < 32 and c not in "\n\t") or c == "�" or 0xE000 <= ord(c) <= 0xF8FF)
    if ctrl > 0.05 * n:
        return True
    words = _WORD_RE.findall(s.lower())
    numbers = len(re.findall(r"(?<![^\s(])\d[\d.,%]*(?![^\s),;:])", s))  # tables and charts are mostly numbers
    return (len(words) >= 30 and numbers < 0.1 * len(words)
            and sum(w in _FUNCTION_WORDS for w in words) < 0.02 * len(words))


def make_passages(text: str, spans: list[tuple[int, int]], max_chars: int = 1100, min_chars: int = 200) -> list[Passage]:
    ref_at = references_start(text)
    sents: list[tuple[int, int]] = []
    for s, e in spans:
        for a, b in split_sentences(text[s:e], offset=s):
            # break very long "sentences" (tables, run-on extraction) at whitespace
            while b - a > max_chars:
                cut = text.rfind(" ", a + min_chars, a + max_chars)
                cut = cut if cut > a else a + max_chars
                sents.append((a, cut))
                a = cut + 1
            if b > a:
                sents.append((a, b))
    out: list[Passage] = []
    cur: list[tuple[int, int]] = []
    ends = [e + 2 for _s, e in spans]

    def flush():
        if not cur:
            return
        a, b = cur[0][0], cur[-1][1]
        pg = page_of(a, spans, ends)
        if ref_at is not None and a >= ref_at:
            section = "references"
        elif unreadable(text[a:b]):
            section = "unreadable"
        elif reference_like(text[a:b]):
            section = "reference_like"
        else:
            section = "body"
        out.append(Passage(len(out), a, b, pg, section))
        cur.clear()

    for a, b in sents:
        crosses_refs = ref_at is not None and cur and cur[0][0] < ref_at <= a
        new_page = cur and page_of(a, spans, ends) != page_of(cur[0][0], spans, ends)
        if cur and ((b - cur[0][0] > max_chars) or crosses_refs or (new_page and cur[-1][1] - cur[0][0] >= min_chars)):
            flush()
        cur.append((a, b))
    flush()
    return out


def guess_title(raw: RawDoc, text: str) -> str:
    if raw.meta_title:
        return re.sub(r"\s+", " ", raw.meta_title).strip()[:300]
    if raw.kind in ("text", "docx") and raw.pages:  # a text file's title is its first line (cleaning joins the lines)
        first = next((ln.strip() for ln in raw.pages[0].splitlines() if ln.strip()), "")
        if 10 <= len(first) <= 250:
            return first
    head = text[:400]
    first = re.split(r"(?<=[.!?])\s", head)[0]
    return (first or raw.path.stem)[:200]


def guess_doi(raw: RawDoc, text: str, spans: list[tuple[int, int]]) -> str | None:
    """The paper's own DOI: from the file name, else the most frequent DOI before the references."""
    stem = raw.path.stem.replace("_", "/").replace("%2F", "/")
    from_name = find_dois(stem)
    if from_name:
        return from_name[0]
    cut = references_start(text) or len(text)
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for s, e in spans[:4]:
        for d in find_dois(text[s:min(e, cut)]):
            counts[d] += 1
            first_seen.setdefault(d, s)
    if not counts:
        return None
    return sorted(counts, key=lambda d: (-counts[d], first_seen[d]))[0]


def build_document(raw: RawDoc, max_chars: int = 1100, min_chars: int = 200) -> Document:
    text, spans = assemble(raw.pages)
    doc = Document("d" + raw.sha1[:10], raw, text, spans, guess_title(raw, text), guess_doi(raw, text, spans))
    doc.passages = make_passages(text, spans, max_chars, min_chars)
    doc.layout = layout(raw, text, spans)
    if not raw.paginated:
        for p in doc.passages:
            p.page = None
        doc.paragraphs = [s0 for _pg, s0 in doc.layout.paragraphs]
    return doc


# ------------------------------------------------------------------------------------------
# input discovery
# ------------------------------------------------------------------------------------------
MAX_UNPACKED = 8 * 1024 ** 3   # bytes written from the zips of one ingest, nested ones included (zip bombs)


def _safe_extract(zf: zipfile.ZipFile, dest: Path, budget: list[int] | None = None) -> list[Path]:
    out = []
    root = dest.resolve()
    budget = budget if budget is not None else [MAX_UNPACKED]
    for info in zf.infolist():
        name = info.filename
        if info.is_dir() or name.startswith("__MACOSX") or Path(name).name.startswith("._"):
            continue
        if info.file_size > budget[0]:
            break  # the rest would exceed the budget: stop unpacking
        budget[0] -= info.file_size
        target = (dest / name).resolve()
        if not target.is_relative_to(root) or target == root:
            continue  # zip-slip guard (a string prefix test would let '../x_evil/...' through for a folder 'x')
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        out.append(target)
    return out


def read_manifests(files: list[Path]) -> dict[str, dict]:
    """manifest.csv files (columns file, reference, doi) say which references each file is.

    Several rows may point at the same file (one work cited in several ways). Keyed by file name. Files saved
    by a spreadsheet are read whether they are UTF-8 (with or without a byte-order mark) or Windows-1252.
    """
    from .review import read_csv_rows

    out: dict[str, dict] = {}
    for m in files:
        if m.name.lower() != "manifest.csv":
            continue
        for row in read_csv_rows(m):
            names = set()
            for col in ("file", "markdown_file", "text_file"):
                pth = Path((row.get(col) or "").strip().replace("\\", "/"))
                if pth.name:
                    names |= {pth.name, "stem:" + pth.stem}  # a converted copy (.txt) keeps the stem
            for name in filter(None, names):
                e = out.setdefault(name, {"references": [], "doi": ""})
                ref = (row.get("reference") or "").strip()
                if ref and ref not in e["references"]:
                    e["references"].append(ref)
                if (row.get("doi") or "").strip() and not e["doi"]:
                    e["doi"] = row["doi"].strip()
    return out


# notes that travel with a corpus but are not sources
NOT_SOURCES = {"problems.txt", "readme.txt", "readme.md", "license.txt", "notes.txt", "worker_guide.md", "system.md"}


def discover(inputs: list[str | Path], unpack_dir: Path, manifests: list[Path] | None = None) -> list[Path]:
    files: list[Path] = []
    queue = [Path(p) for p in inputs]
    depth: dict[Path, int] = {}
    budget = [MAX_UNPACKED]  # shared by every zip of this call, nested ones included
    while queue:
        p = queue.pop(0)
        if p.is_dir():
            queue.extend(sorted(x for x in p.rglob("*") if x.is_file()))
        elif p.suffix.lower() == ".zip" and zipfile.is_zipfile(p):
            if depth.get(p, 0) > 2:
                continue
            # one folder per zip file: two zips with the same name (from different folders) must not mix
            tag = hashlib.sha1(str(p.resolve()).encode()).hexdigest()[:8]
            stem = re.sub(r"[^A-Za-z0-9_-]", "_", p.stem).strip("_")[:60] or "zip"  # no dots: '...zip' cannot be '..'
            dest = unpack_dir / f"{stem}-{tag}"
            if not dest.resolve().is_relative_to(unpack_dir.resolve()):
                continue
            with zipfile.ZipFile(p) as zf:
                for x in _safe_extract(zf, dest, budget):
                    depth[x] = depth.get(p, 0) + 1
                    queue.append(x)
        elif p.suffix.lower() in SUPPORTED and p.is_file() and p.name.lower() not in NOT_SOURCES:
            files.append(p)
        elif p.name.lower() == "manifest.csv" and manifests is not None:
            manifests.append(p)
    return files


def ingest(ws: Workspace, inputs: list[str | Path], exclude: list[str] | None = None,
           progress=None, should_stop=None, ocr: OcrOptions | None = None) -> dict:
    """Add documents. `exclude` holds file-name patterns (e.g. 'A_18_*') to leave out, such as a wrong download.

    `progress(done, total, file_name)` is called before each file is read (for a progress bar). Each document is
    stored in its own transaction; a file that cannot be read is listed under `failed` and the rest go on.
    `ocr` (default: automatic, English) recognises the text of scanned PDF pages when OCR is installed; scanned
    files that stay without text are listed under `scanned_no_text`.
    """
    from fnmatch import fnmatch

    from .textutil import clean_doi

    cfg = ws.config["passages"]
    manifest_files: list[Path] = []
    files = discover(inputs, ws.root / "inputs", manifest_files)
    skipped = [f for f in files if any(fnmatch(f.name, pat) for pat in exclude or [])]
    skip = set(skipped)
    files = [f for f in files if f not in skip]
    declared = read_manifests(manifest_files)
    stats = {"files": len(files), "added": 0, "duplicates": 0, "empty": 0, "passages": 0, "declared": 0}
    if exclude:
        stats["excluded"] = [f.name for f in skipped]
    known = {r[0] for r in ws.query("SELECT sha1 FROM documents")}
    for i, f in enumerate(files):
        if should_stop and should_stop():
            stats["stopped"] = True
            break
        if progress:
            progress(i, len(files), f.name)
        try:
            raw = read_file(f, ocr if ocr is not None else OcrOptions())
        except (OSError, ValueError) as e:  # one unreadable file should not stop the others
            stats.setdefault("failed", []).append(f"{f.name}: {e}")
            continue
        if raw.sha1 in known:
            stats["duplicates"] += 1
            continue
        doc = build_document(raw, cfg["max_chars"], cfg["min_chars"])
        if raw.ocr_pages:
            stats.setdefault("ocr", []).append(f.name)
        if raw.scanned_pages > raw.ocr_pages:
            stats.setdefault("scanned_no_text", []).append(f.name)
        if len(doc.text.strip()) < 100:
            stats["empty"] += 1
            stats.setdefault("empty_files", []).append(f.name)
            continue
        known.add(raw.sha1)
        dec = declared.get(f.name) or declared.get("stem:" + f.stem) or {}
        if dec:
            stats["declared"] += 1
            doc.doi = clean_doi(dec.get("doi")) or doc.doi
            if dec["references"]:
                doc.title = re.sub(r"https?://\S+", "", dec["references"][0]).strip(" ,.")[:250]
        elif declared:
            stats.setdefault("not_in_manifest", []).append(f.name)
        try:
            _store_document(ws, doc, raw, f, dec)
        except sqlite3.IntegrityError:  # the same file, added meanwhile by another ingest
            stats["duplicates"] += 1
            continue
        stats["added"] += 1
        stats["passages"] += len(doc.passages)
        bad = sum(1 for p in doc.passages if p.section == "unreadable")
        if bad > 0.3 * max(1, len(doc.passages)):
            stats.setdefault("mostly_unreadable", []).append(f.name)
    if progress:
        progress(len(files), len(files), "")
    return stats


def _store_document(ws: Workspace, doc: "Document", raw: RawDoc, f: Path, dec: dict) -> None:
    """One document with its pages and passages, in one transaction (other work is not blocked for long)."""
    with ws.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, path, sha1, title, doi, kind, n_pages, n_chars, text, added_at, "
                   "declared_ref, ocr_pages, scanned_pages) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (doc.doc_id, str(f), raw.sha1, doc.title, doc.doi, raw.kind,
                    len(doc.page_spans) if raw.paginated else None,
                    len(doc.text), doc.text, now(), json.dumps(dec["references"], ensure_ascii=False) if dec else None,
                    raw.ocr_pages if raw.kind == "pdf" else None, raw.scanned_pages if raw.kind == "pdf" else None))
        if raw.paginated:
            cx.executemany("INSERT INTO pages VALUES (?,?,?,?)",
                           [(doc.doc_id, n + 1, s, e) for n, (s, e) in enumerate(doc.page_spans)])
        lay = doc.layout or Layout([(None, s0) for s0 in doc.paragraphs])
        if lay.paragraphs:
            cx.executemany("INSERT INTO paragraphs(doc_id, n, start, page) VALUES (?,?,?,?)",
                           [(doc.doc_id, n + 1, s0, pg) for n, (pg, s0) in enumerate(lay.paragraphs)])
        if lay.headings:
            cx.executemany("INSERT INTO headings(doc_id, start, end, text) VALUES (?,?,?,?)",
                           [(doc.doc_id, a, b, t) for a, b, t in lay.headings])
        cx.executemany(
            "INSERT INTO passages(passage_id, doc_id, seq, page, start, end, text, section) VALUES (?,?,?,?,?,?,?,?)",
            [(f"{doc.doc_id}:{p.seq:04d}", doc.doc_id, p.seq, p.page, p.start, p.end, doc.text[p.start:p.end], p.section)
             for p in doc.passages])
        ws.bump_corpus(cx)


def doc_text(ws: Workspace, doc_id: str) -> str:
    return ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc_id,)) or ""


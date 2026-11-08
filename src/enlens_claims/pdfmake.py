"""0.15: a small PDF writer for documents whose true text is known.

`enlens measure` and the tests make PDFs with the layouts that trouble a reader (two columns, running heads, page and
line numbers, words hyphenated across lines, tables, footnotes) from text they know, so what a reader made of them
can be compared with the truth. Only the standard PDF fonts (Helvetica, Helvetica-Bold, Times-Roman), Windows-1252
text and no compression: the files are small, made the same way every time, and need nothing beyond Python.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# glyph widths (1/1000 of the font size) of the characters 32 to 126, from the fonts' Adobe metrics
_W = {
    "Helvetica": [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
                  556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778,
                  722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278,
                  278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
                  556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584],
    "Helvetica-Bold": [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556,
                       556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667,
                       611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
                       667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556,
                       278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584],
    "Times-Roman": [250, 333, 408, 500, 500, 833, 778, 180, 333, 333, 500, 564, 250, 333, 250, 278, 500, 500, 500, 500,
                    500, 500, 500, 500, 500, 500, 278, 278, 564, 564, 564, 444, 921, 722, 667, 667, 722, 611, 556, 722,
                    722, 333, 389, 722, 611, 889, 722, 722, 556, 722, 667, 556, 611, 722, 722, 944, 722, 722, 611, 333,
                    278, 333, 469, 500, 333, 444, 500, 444, 500, 444, 333, 500, 500, 278, 278, 500, 278, 778, 500, 500,
                    500, 500, 333, 389, 278, 500, 500, 722, 500, 500, 444, 480, 200, 480, 541],
}
FONTS = tuple(_W)


def text_width(s: str, font: str = "Helvetica", size: float = 10) -> float:
    w = _W[font]
    return sum(w[ord(c) - 32] if 32 <= ord(c) < 127 else 556 for c in s) * size / 1000


@dataclass
class Page:
    width: float = 595.0   # A4 in points
    height: float = 842.0
    items: list[tuple[str, float, float, str, float]] = field(default_factory=list)  # text, x, y, font, size

    def text(self, s: str, x: float, y: float, font: str = "Helvetica", size: float = 10) -> None:
        """One run of text with its baseline starting at (x, y), y counted from the bottom of the page."""
        if font not in _W:
            raise ValueError(f"unknown font {font!r}; one of {', '.join(FONTS)}")
        self.items.append((s, float(x), float(y), font, float(size)))


def wrap(text: str, width: float, font: str = "Helvetica", size: float = 10,
         hyphenate: dict[str, int] | None = None) -> list[str]:
    """Lines of at most `width` points. A word in `hyphenate` (word -> where to cut) that does not fit is cut there
    with a hyphen, as typesetting does ("exam-" / "ple"); a word with a hyphen of its own may break after it
    ("long-" / "term")."""
    lines: list[str] = []
    cur = ""
    words = text.split()
    i = 0
    while i < len(words):
        w = words[i]
        trial = f"{cur} {w}" if cur else w
        if text_width(trial, font, size) <= width or not cur:
            cur = trial
            i += 1
            continue
        cut = (hyphenate or {}).get(w)
        if cut is None and "-" in w[1:-1]:
            cut = w.index("-", 1) + 1
            head, tail = w[:cut], w[cut:]
        elif cut is not None:
            head, tail = w[:cut] + "-", w[cut:]
        else:
            head = tail = None
        if head and text_width(f"{cur} {head}", font, size) <= width:
            lines.append(f"{cur} {head}")
            cur = ""
            words[i] = tail
            continue
        lines.append(cur)
        cur = ""
    if cur:
        lines.append(cur)
    return lines


def _esc(s: str) -> bytes:
    data = s.encode("cp1252", errors="replace")
    return data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def write(pages: list[Page], path: str | Path | None = None, title: str | None = None) -> bytes:
    """The PDF of `pages` (also written to `path` when given)."""
    fonts = list(FONTS)
    objs: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    font_refs = {}
    for f in fonts:
        objs.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /{f} /Encoding /WinAnsiEncoding >>".encode())
        font_refs[f] = len(objs)
    res = " ".join(f"/F{k} {font_refs[f]} 0 R" for k, f in enumerate(fonts))
    kids = []
    for pg in pages:
        ops = [b"BT"]
        for s, x, y, font, size in pg.items:
            ops.append(b"/F%d %s Tf 1 0 0 1 %s %s Tm (" % (fonts.index(font), _num(size), _num(x), _num(y))
                       + _esc(s) + b") Tj")
        ops.append(b"ET")
        stream = b"\n".join(ops)
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_num(pg.width).decode()} "
                    f"{_num(pg.height).decode()}] /Resources << /Font << {res} >> >> /Contents {content} 0 R >>".encode())
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    info = ""
    if title:
        objs.append(b"<< /Title (" + _esc(title) + b") >>")
        info = f" /Info {len(objs)} 0 R"
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R{info} >>\nstartxref\n{xref}\n%%EOF\n".encode()
    data = bytes(out)
    if path is not None:
        Path(path).write_bytes(data)
    return data


def _num(v: float) -> bytes:
    return (f"{v:.2f}".rstrip("0").rstrip(".") or "0").encode()


class Flow:
    """Paragraphs poured into one or more columns over as many pages as they need, with optional running heads,
    page numbers and line numbers: the layouts a reader has to undo.

    `columns` is a list of (x, width); text runs down the first column, then the next, then onto a new page.
    """

    def __init__(self, columns: list[tuple[float, float]] | None = None, top: float = 770, bottom: float = 80,
                 font: str = "Times-Roman", size: float = 10, leading: float = 12.5,
                 running_head: str | None = None, page_numbers: bool = False, line_numbers: bool = False,
                 first_page: int = 1):
        self.columns = columns or [(72, 451)]
        self.top, self.bottom = top, bottom
        self.font, self.size, self.leading = font, size, leading
        self.running_head, self.page_numbers, self.line_numbers = running_head, page_numbers, line_numbers
        self.pages: list[Page] = []
        self.first_page = first_page
        self._col = 0
        self._y = top
        self._new_page()

    @property
    def page(self) -> Page:
        return self.pages[-1]

    def _new_page(self) -> None:
        pg = Page()
        n = self.first_page + len(self.pages)
        if self.running_head:
            pg.text(self.running_head, self.columns[0][0], 806, "Helvetica", 8)
        if self.page_numbers:
            pg.text(str(n), pg.width / 2 - 4, 40, "Helvetica", 9)
        self.pages.append(pg)
        self._col, self._y = 0, self.top
        self._line_no = 0

    def _advance(self, h: float) -> None:
        if self._y - h < self.bottom:
            if self._col + 1 < len(self.columns):
                self._col += 1
                self._y = self.top
            else:
                self._new_page()

    def line(self, s: str, font: str | None = None, size: float | None = None, indent: float = 0.0) -> None:
        size = size or self.size
        self._advance(self.leading)
        x = self.columns[self._col][0]
        self.page.text(s, x + indent, self._y, font or self.font, size)
        if self.line_numbers and self._col == 0:
            self._line_no += 1
            self.page.text(str(self._line_no), x - 28, self._y, "Helvetica", 7)
        self._y -= self.leading * size / self.size

    def gap(self, h: float | None = None) -> None:
        self._y -= self.leading * 0.8 if h is None else h

    def paragraph(self, text: str, font: str | None = None, size: float | None = None, indent: float = 12.0,
                  hyphenate: dict[str, int] | None = None, gap: bool = True) -> None:
        width = self.columns[self._col][1]
        for k, ln in enumerate(wrap(text, width - (indent if indent else 0), font or self.font, size or self.size,
                                    hyphenate)):
            self.line(ln, font, size, indent if k == 0 else 0.0)
        if gap:
            self.gap()

    def heading(self, text: str, size: float | None = None) -> None:
        self.gap(4)
        self.line(text, "Helvetica-Bold", size or self.size + 1)
        self.gap(2)

    def new_page(self) -> None:
        self._new_page()

    def write(self, path: str | Path | None = None, title: str | None = None) -> bytes:
        return write(self.pages, path, title)

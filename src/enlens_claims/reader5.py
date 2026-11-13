"""Reader 5 (ENLENS 0.18.1): tables from their ruled lines, tables that run over a page, and figures.

`reader.read_blocks(raw, version=5)` calls the rules here; `version=4` and below still read exactly as before. Nothing
here uses a model, and nothing stores a picture: a figure costs a page number, a box and its caption, and the picture
is drawn from the original PDF when it is shown (`gui/api_corpus.py`, `GET …/figures/<n>.png`).

1. **Ruled tables.** Reader 2 finds a table only where its columns have clear gaps between them, so a table whose cells
   hold sentences, or whose numbers are aligned on the right, was read as paragraphs. pdfminer also gives the page's
   lines and boxes (`LTLine`, `LTRect`, `LTCurve`: the rules a layout program draws). A set of rules that cross
   (a grid), or horizontal rules of one width stacked above and below rows of cells (a typesetter's top, header and
   bottom rules), that holds text in at least two rows and two columns is a table. Its rows come from the rules
   between them, or else from the text's baselines; its columns from the vertical rules, or else from where the cells'
   text stands. A box round one paragraph has one column and is not a table.
2. **A table over a page.** The table at the foot of a page and the table at the head of the next, with as many
   columns and the same width, are one table (on the first page, with the header row once if the next page repeats it).
3. **Figures.** An image or form (`LTFigure`, `LTImage`) and a cluster of drawn lines, boxes and curves (a chart, a
   diagram) with the small type that labels it, are a block of their own, kind `figure`: its page, its box, the words
   inside it (left out of passages, as in reader 2) and its caption, the block of kind `caption` just below or above it
   ("Figure 3. …"), which stays a block of its own and counts as before. A figure without any words is a block of no
   text: it has no place in the stored text and no passage, only a box. Logos and icons (too small, or repeated in
   the margin of other pages) and scans (an image as big as the page) are not figures.

A table or figure is found only where the lines are, so pages read without boxes (a scan read by OCR, a PDF pdfminer
cannot read) and text files get no new blocks. Word files and web pages keep an image's caption and alternative text
(`ingest._docx_text`, `ingest._TextOnly`).
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

THIN = 2.5        # a line or box this thin (points) is a rule
MIN_RULE = 6.0    # a rule shorter than this is a tick, not a rule
MERGE = 2.5       # rules this close (points) are one
CELL_PAD = 3.0    # the text of a cell may stand this far outside the rules round it
CLUSTER_GAP = 6.0     # drawings this close (points) belong to one figure
MIN_DRAWINGS = 6      # a cluster of fewer lines and boxes is a rule, a bullet or an underline, not a figure
MIN_FIGURE = (50.0, 35.0)   # the smallest figure: width and height in points (a logo or an icon is smaller)
_ZONE_SIDE = 32.0     # small type this near a figure's side (points) labels it (tick labels, legends)
_ZONE_TOP = 18.0
_ZONE_BELOW = 26.0

_CAPTION = re.compile(r"^(fig\.?|figure|chart|graph|map|plate|exhibit|scheme|photo|image|diagram|picture|panel)"
                      r"\s*[A-Z]?\d+[a-z]?(\.\d+)?\s*([.:|—–-]|\s+[A-Z(])", re.I)


# ------------------------------------------------------------------------------------------------------------------
# what pdfminer gives
# ------------------------------------------------------------------------------------------------------------------
@dataclass
class Drawing:
    """One line, box or curve of a page, in points from the top left."""
    x0: float
    top: float
    x1: float
    bottom: float
    kind: str            # 'h' a horizontal rule, 'v' a vertical rule, 'box' an outlined rectangle, 'fill' a filled
    #                      rectangle (a bar, a shaded row), 'curve' anything else (a tick, a diagonal, a path)
    in_fig: bool = False     # inside an image or form: part of that figure, not a rule of a table


@dataclass
class PageShapes:
    drawings: list[Drawing] = field(default_factory=list)
    figures: list[tuple[float, float, float, float, bool]] = field(default_factory=list)  # x0, top, x1, bottom, image


def record(obj, rec: PageShapes, height: float, in_fig: bool) -> None:
    """Add what `obj` (a pdfminer layout object) draws to the page's shapes: called for every object of the page
    that `reader._pdfminer_pages` walks, only when it is reading for reader 5."""
    from pdfminer.layout import LTCurve, LTFigure, LTImage

    if isinstance(obj, LTFigure):
        x0, y0, x1, y1 = (float(v) for v in obj.bbox)
        rec.figures.append((x0, height - y1, x1, height - y0, _has_image(obj)))
    elif isinstance(obj, LTImage):
        x0, y0, x1, y1 = (float(v) for v in obj.bbox)
        rec.figures.append((x0, height - y1, x1, height - y0, True))
    elif isinstance(obj, LTCurve):  # LTLine and LTRect are curves too
        x0, y0, x1, y1 = (float(v) for v in obj.bbox)
        w, h = x1 - x0, y1 - y0
        if h <= THIN and w >= MIN_RULE:
            kind = "h"
        elif w <= THIN and h >= MIN_RULE:
            kind = "v"
        elif type(obj).__name__ == "LTRect" and w > THIN and h > THIN:
            # an outlined rectangle is a cell's or a table's border; a filled one a bar or shading
            kind = "box" if getattr(obj, "stroke", True) else "fill"
        else:
            kind = "curve"
        rec.drawings.append(Drawing(x0, height - y1, x1, height - y0, kind, in_fig))


def _has_image(fig, depth: int = 0) -> bool:
    from pdfminer.layout import LTFigure, LTImage

    for c in fig:
        if isinstance(c, LTImage) or (depth < 3 and isinstance(c, LTFigure) and _has_image(c, depth + 1)):
            return True
    return False


# ------------------------------------------------------------------------------------------------------------------
# what a page holds
# ------------------------------------------------------------------------------------------------------------------
@dataclass
class Obj:
    """A table or a figure found on a page, before it is made a Block."""
    kind: str                                   # 'table' | 'figure'
    box: tuple[float, float, float, float]      # x0, top, x1, bottom
    lines: list = field(default_factory=list)   # the lines of text inside it
    rows: list[list[str]] | None = None         # a table's rows of cells
    cols: list[float] | None = None             # a table's column edges, where its rules gave them
    image: bool = False

    def block(self, pno: int):
        from .reader import Block, Line

        lines = sorted(self.lines, key=lambda ln: (round(ln.top, 1), ln.x0))
        if not lines:
            # a figure without words: one empty line that stands for it, so every rule that looks at a block's first
            # line (is it page furniture? is it figure text?) has one to look at
            lines = [Line(pno, "", self.box[0], self.box[1], self.box[2], self.box[3], None, False, True)]
        return Block(pno, lines, kind=self.kind, rows=self.rows, box=self.box)


def _centre(ln) -> tuple[float, float]:
    return (ln.x0 + (ln.x1 if ln.x1 is not None else ln.x0)) / 2, (ln.top + (ln.bottom if ln.bottom is not None
                                                                                else ln.top)) / 2


def _inside(ln, box, pad: float = 0.0) -> bool:
    if ln.x0 is None or ln.top is None:
        return False
    cx, cy = _centre(ln)
    return box[0] - pad <= cx <= box[2] + pad and box[1] - pad <= cy <= box[3] + pad


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _overlap(a, b) -> float:
    """The area two boxes share."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _area(a) -> float:
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


def _x_overlap(a, b) -> float:
    return min(a[2], b[2]) - max(a[0], b[0])


# ------------------------------------------------------------------------------------------------------------------
# ruled tables
# ------------------------------------------------------------------------------------------------------------------
def _merge(segs: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """Segments (position, from, to) lying on one line (within `MERGE`) and touching or overlapping are one."""
    out: list[list[float]] = []
    for pos, a, b in sorted(segs):
        for s in reversed(out):
            if s[0] < pos - MERGE:
                out.append([pos, a, b])     # nothing nearer to join (sorted by position)
                break
            if abs(s[0] - pos) <= MERGE and a <= s[2] + MERGE and b >= s[1] - MERGE:
                s[1], s[2] = min(s[1], a), max(s[2], b)
                break
        else:
            out.append([pos, a, b])
    return [(s[0], s[1], s[2]) for s in sorted(out)]


def rules(rec: PageShapes) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """The horizontal rules (y, x from, x to) and the vertical rules (x, y from, y to) of the page, rules on one line
    joined, from lines, thin boxes and the sides of outlined boxes. What lies inside an image or form is left out."""
    hs: list[tuple[float, float, float]] = []
    vs: list[tuple[float, float, float]] = []
    for d in rec.drawings:
        if d.in_fig:
            continue
        if d.kind == "h":
            hs.append(((d.top + d.bottom) / 2, d.x0, d.x1))
        elif d.kind == "v":
            vs.append(((d.x0 + d.x1) / 2, d.top, d.bottom))
        elif d.kind == "box":
            hs += [(d.top, d.x0, d.x1), (d.bottom, d.x0, d.x1)]
            vs += [(d.x0, d.top, d.bottom), (d.x1, d.top, d.bottom)]
    return _merge(hs), _merge(vs)


def _grids(hs, vs) -> list[tuple[tuple[float, float, float, float], list, list]]:
    """Sets of rules that cross: (box, its horizontal rules, its vertical rules). Two or more of each."""
    n = len(hs) + len(vs)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (y, a, b) in enumerate(hs):
        for j, (x, c, d) in enumerate(vs):
            if a - MERGE <= x <= b + MERGE and c - MERGE <= y <= d + MERGE:
                parent[find(i)] = find(len(hs) + j)
    groups: dict[int, tuple[list, list]] = {}
    for i, h in enumerate(hs):
        groups.setdefault(find(i), ([], []))[0].append(h)
    for j, v in enumerate(vs):
        groups.setdefault(find(len(hs) + j), ([], []))[1].append(v)
    out = []
    for gh, gv in groups.values():
        if len(gh) >= 2 and len(gv) >= 2:
            box = (min(min(h[1] for h in gh), min(v[0] for v in gv)), min(min(h[0] for h in gh), min(v[1] for v in gv)),
                   max(max(h[2] for h in gh), max(v[0] for v in gv)), max(max(h[0] for h in gh), max(v[2] for v in gv)))
            out.append((box, gh, gv))
    return sorted(out, key=lambda g: (g[0][1], g[0][0]))


def _baseline_rows(lines: list) -> list[list]:
    """Lines that share a baseline, left to right."""
    rows: list[list] = []
    for ln in sorted(lines, key=lambda x: (x.top, x.x0)):
        if rows and abs(rows[-1][0].top - ln.top) < 0.5 * (ln.size or 8):
            rows[-1].append(ln)
        else:
            rows.append([ln])
    for r in rows:
        r.sort(key=lambda x: x.x0)
    return rows


def _levels(values: list[float], gap: float = 3.0) -> list[float]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= gap:
            out[-1].append(v)
        else:
            out.append([v])
    return [statistics.fmean(g) for g in out]


def _columns_from_text(lines: list) -> list[tuple[float, float]]:
    """Column intervals from where the text stands: the lines' spans, joined where they overlap or nearly touch."""
    spans = sorted((ln.x0, ln.x1 if ln.x1 is not None else ln.x0) for ln in lines)
    out: list[list[float]] = []
    for a, b in spans:
        if out and a <= out[-1][1] + 4.0:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def build_table(box, hs, vs, lines: list, drawings: list[Drawing], page_h: float):
    """The table a set of rules makes with the lines inside it: an `Obj`, or None when it is not a table. `hs` and `vs`
    are the rules that bound it (horizontal: y, from, to; vertical: x, from, to)."""
    if box[3] - box[1] > 0.85 * page_h or box[2] - box[0] < 60 or box[3] - box[1] < 14:
        return None   # a frame round the page, a rule under a heading
    inside = [ln for ln in lines if _inside(ln, box, CELL_PAD) and ln.text.strip()]
    if len(inside) < 4:
        return None
    # a chart: many bars, marks or curves among its rules (a shaded row is as wide as the table, a bar is not)
    width = box[2] - box[0]
    marks = sum(1 for d in drawings if d.kind in ("fill", "curve") and not d.in_fig and _overlap(
        (d.x0, d.top, d.x1, d.bottom), box) > 0 and (d.x1 - d.x0) < 0.6 * width)
    if marks > 6:
        return None
    long_lines = sum(1 for ln in inside if len(ln.text.strip()) > 110)
    if long_lines >= 2:
        return None   # paragraphs in a box
    # columns: the vertical rules that run most of the table's height, else where the text stands
    height = box[3] - box[1]
    inner = _levels([v[0] for v in vs if v[2] - v[1] >= 0.5 * height], 3.0)
    col_edges: list[float] | None = None
    if len(inner) >= 3:
        col_edges = inner
        bounds = [(col_edges[k], col_edges[k + 1]) for k in range(len(col_edges) - 1)]
        ncol = len(bounds)
    else:
        bounds = _columns_from_text(inside)
        ncol = len(bounds)
    if ncol < 2:
        return None

    def col_of(ln) -> int:
        cx = _centre(ln)[0]
        if col_edges is not None:
            for k, (a, b) in enumerate(bounds):
                if cx < b or k == ncol - 1:
                    return k if cx >= a - CELL_PAD or k == 0 else max(0, k - 1)
        best, best_d = 0, 1e9
        for k, (a, b) in enumerate(bounds):
            d = 0.0 if a <= cx <= b else min(abs(cx - a), abs(cx - b))
            if d < best_d:
                best, best_d = k, d
        return best

    # rows: the bands between horizontal rules when there are enough of them, else the text's baselines
    levels = _levels([h[0] for h in hs if h[2] - h[1] >= 0.6 * width], 3.0)
    base = _baseline_rows(inside)
    row_lines: list[list] = []
    if len(levels) >= 3:
        bands = [[ln for ln in inside if levels[k] - CELL_PAD <= _centre(ln)[1] < levels[k + 1] + CELL_PAD]
                 for k in range(len(levels) - 1)]
        bands = [b for b in bands if b]
        if len(bands) >= 2 and len(bands) >= 0.5 * len(base):
            row_lines = bands
    if not row_lines:
        row_lines = base
    grid: list[list[str]] = []
    for rl in row_lines:
        cells = [""] * ncol
        for ln in sorted(rl, key=lambda x: (round(x.top, 1), x.x0)):
            k = col_of(ln)
            cells[k] = (cells[k] + " " + ln.text.strip()).strip()
        if any(cells):
            grid.append(cells)
    if len(grid) < 2 or sum(1 for r in grid if sum(1 for c in r if c) >= 2) < 2:
        return None
    # cells hold words, not paragraphs
    filled = [c for r in grid for c in r if c]
    if len(filled) < 4 or statistics.median(len(c) for c in filled) > 160:
        return None
    out_box = _union(box, (min(ln.x0 for ln in inside), min(ln.top for ln in inside),
                           max((ln.x1 if ln.x1 is not None else ln.x0) for ln in inside),
                           max((ln.bottom if ln.bottom is not None else ln.top) for ln in inside)))
    return Obj("table", out_box, inside, grid, col_edges)


def ruled_tables(rec: PageShapes, lines: list, page_h: float) -> list[Obj]:
    """The tables of a page that its rules make: grids first, then typesetters' stacks of horizontal rules."""
    hs, vs = rules(rec)
    if len(hs) > 300 or len(vs) > 300:
        return []   # hundreds of rules on a page: a plot's grid or a map, not a table (and slow to pair up)
    out: list[Obj] = []
    taken: list[tuple] = []   # the boxes of tables found
    left = set(id(ln) for ln in lines)

    def take(t: Obj) -> None:
        out.append(t)
        taken.append(t.box)
        for ln in t.lines:
            left.discard(id(ln))

    for box, gh, gv in _grids(hs, vs):
        pool = [ln for ln in lines if id(ln) in left]
        t = build_table(box, gh, gv, pool, rec.drawings, page_h)
        if t is not None:
            take(t)
    # stacks: horizontal rules of one width, one above the other, with rows of cells between them
    free = [h for h in hs if h[2] - h[1] >= 60 and not any(_overlap((h[1], h[0] - 1, h[2], h[0] + 1), b) > 0
                                                           for b in taken)]
    groups: list[list[tuple[float, float, float]]] = []
    for h in sorted(free, key=lambda h: (h[1], h[2])):
        for g in groups:
            if abs(g[0][1] - h[1]) <= 5 and abs(g[0][2] - h[2]) <= 5:
                g.append(h)
                break
        else:
            groups.append([h])
    for g in groups:
        g.sort()
        run: list[tuple[float, float, float]] = []
        slabs_ok: list[bool] = []
        pool = [ln for ln in lines if id(ln) in left]
        for a, b in zip(g, g[1:]):
            slab = [ln for ln in pool if a[0] + 1 < _centre(ln)[1] < b[0] - 1 and g[0][1] - 3 <= _centre(ln)[0]
                    <= g[0][2] + 3 and ln.text.strip()]
            rows = _baseline_rows(slab)
            multi = [r for r in rows if len(r) >= 2 and all(len(c.text.strip()) <= 60 for c in r)]
            slabs_ok.append(bool(rows) and b[0] - a[0] <= 320 and len(multi) >= 0.6 * len(rows))
        i = 0
        while i < len(g) - 1:
            if not slabs_ok[i]:
                i += 1
                continue
            j = i
            while j < len(slabs_ok) and slabs_ok[j]:
                j += 1
            run = g[i:j + 1]
            box = (run[0][1], run[0][0], run[0][2], run[-1][0])
            pool = [ln for ln in lines if id(ln) in left]
            t = build_table(box, run, [], pool, rec.drawings, page_h)
            if t is not None:
                take(t)
            i = j + 1
    return out


# ------------------------------------------------------------------------------------------------------------------
# figures
# ------------------------------------------------------------------------------------------------------------------
def _clusters(items: list[Drawing]) -> list[tuple[tuple[float, float, float, float], int]]:
    """Drawings joined where they touch or lie within `CLUSTER_GAP` of each other: (box, how many)."""
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def near(a: Drawing, b: Drawing) -> bool:
        return (a.x0 - CLUSTER_GAP <= b.x1 and b.x0 - CLUSTER_GAP <= a.x1 and a.top - CLUSTER_GAP <= b.bottom
                and b.top - CLUSTER_GAP <= a.bottom)

    # a grid of cells, so that only drawings that share a cell are compared (a page can hold thousands of paths)
    cell = 24.0
    grid: dict[tuple[int, int], list[int]] = {}
    for i, d in enumerate(items):
        for cx in range(int((d.x0 - CLUSTER_GAP) // cell), int((d.x1 + CLUSTER_GAP) // cell) + 1):
            for cy in range(int((d.top - CLUSTER_GAP) // cell), int((d.bottom + CLUSTER_GAP) // cell) + 1):
                grid.setdefault((cx, cy), []).append(i)
    for members in grid.values():
        if len(members) <= 60:
            pairs = ((members[x], members[y]) for x in range(len(members)) for y in range(x + 1, len(members)))
        else:   # a crowded cell (a dense plot): neighbours in order of position are enough to join it
            order = sorted(members, key=lambda i: (items[i].x0, items[i].top))
            pairs = zip(order, order[1:])
        for i, j in pairs:
            if near(items[i], items[j]):
                parent[find(i)] = find(j)
    groups: dict[int, list[Drawing]] = {}
    for i, d in enumerate(items):
        groups.setdefault(find(i), []).append(d)
    return [((min(d.x0 for d in g), min(d.top for d in g), max(d.x1 for d in g), max(d.bottom for d in g)), len(g))
            for g in groups.values()]


def _small_type(ln, body_size: float | None) -> bool:
    """Type smaller than the body's, or short, as the labels of a chart are."""
    if body_size and ln.size:
        return ln.size <= 0.95 * body_size
    return len(ln.text.strip()) <= 12


def _label_like(ln, long_lines: list, body_size: float | None) -> bool:
    """Whether a line outside a figure's box may label it: type smaller than the body's, or a short line in the body's
    type that no long line of text runs on from (the last line of a paragraph above or below the figure has one) and
    that is not a heading."""
    if _small_type(ln, body_size):
        return True
    if len(ln.text.strip()) > 42 or ln.bold or (body_size and ln.size and ln.size > 1.05 * body_size):
        return False      # a heading, or a line that may be a paragraph's
    x1 = ln.x1 if ln.x1 is not None else ln.x0
    gap = 1.8 * (ln.size or 10)
    return not any(o is not ln and abs(o.top - ln.top) <= gap and min(o.x1, x1) - max(o.x0, ln.x0) > 0
                   for o in long_lines)


def _absorb(box, lines: list, taken: set[int], body_size: float | None) -> list:
    """The lines that label a figure: inside its box, or in small type just left of it, right of it, above it, or
    below it (tick labels, a legend, a title, axis labels), until the first caption."""
    mine: list = []
    below: list = []
    long_lines = [ln for ln in lines if ln.x0 is not None and ln.x1 is not None and ln.top is not None
                  and len(ln.text.strip()) >= 40 and not _CAPTION.match(ln.text.strip())]
    for ln in lines:
        if id(ln) in taken or ln.x0 is None or ln.top is None or not ln.text.strip():
            continue
        cx, cy = _centre(ln)
        t = ln.text.strip()
        if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]:
            if not _CAPTION.match(t):
                mine.append(ln)
            continue
        if _CAPTION.match(t) or len(t) > 42 or not _label_like(ln, long_lines, body_size):
            continue
        x1 = ln.x1 if ln.x1 is not None else ln.x0
        bt = ln.bottom if ln.bottom is not None else ln.top
        if box[1] - 2 <= cy <= box[3] + 2 and box[0] - _ZONE_SIDE <= ln.x0 and x1 <= box[0] + 2:
            mine.append(ln)       # to the left (a scale)
        elif box[1] - 2 <= cy <= box[3] + 2 and ln.x0 >= box[2] - 2 and x1 <= box[2] + _ZONE_SIDE + 60:
            mine.append(ln)       # to the right (a legend)
        elif box[0] - 12 <= cx <= box[2] + 12 and box[1] - _ZONE_TOP <= ln.top and bt <= box[1] + 2:
            mine.append(ln)       # above (a title)
        elif box[0] - 12 <= cx <= box[2] + 12 and box[3] - 2 <= ln.top <= box[3] + _ZONE_BELOW:
            below.append(ln)      # below (axis labels): taken in order, stopping at a line that is not one
    for ln in sorted(below, key=lambda x: (x.top, x.x0)):
        mine.append(ln)
    return mine


def figure_candidates(rec: PageShapes, page_w: float, page_h: float, tables: list[Obj]) -> list[tuple]:
    """The boxes of a page's figures before their labels are looked for: (x0, top, x1, bottom, has_image)."""
    boxes: list[list] = []
    for x0, t, x1, b, img in rec.figures:
        if (x1 - x0) >= 0.85 * page_w and (b - t) >= 0.85 * page_h:
            continue      # a scan, a page wrapped in a form
        boxes.append([x0, t, x1, b, img])
    tb = [t.box for t in tables]
    free = []
    for d in rec.drawings:
        if d.in_fig:
            continue
        box = (d.x0, d.top, d.x1, d.bottom)
        if (d.x1 - d.x0) >= 0.85 * page_w and (d.bottom - d.top) >= 0.85 * page_h:
            continue      # a border round the page
        if any(_overlap(box, b) > 0.5 * max(1.0, _area(box)) or (_area(box) == 0 and _overlap(
                (box[0], box[1] - 1, box[2], box[3] + 1), b) > 0) for b in tb):
            continue      # the rules of a table
        free.append(d)
    for box, n in _clusters(free):
        if n >= MIN_DRAWINGS and box[2] - box[0] >= MIN_FIGURE[0] and box[3] - box[1] >= MIN_FIGURE[1] \
                and not ((box[2] - box[0]) >= 0.85 * page_w and (box[3] - box[1]) >= 0.85 * page_h):
            boxes.append([*box, False])
    # boxes that overlap are one figure
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _overlap(boxes[i][:4], boxes[j][:4]) > 0 or (
                        abs(_x_overlap(boxes[i][:4], boxes[j][:4])) >= 0 and _gap(boxes[i][:4], boxes[j][:4]) < 4):
                    u = _union(boxes[i][:4], boxes[j][:4])
                    boxes[i] = [*u, boxes[i][4] or boxes[j][4]]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return [tuple(b) for b in boxes if not any(_overlap(b[:4], t) > 0.3 * max(1.0, _area(b[:4])) for t in tb)]


def _gap(a, b) -> float:
    """How far apart two boxes are (0 when they overlap)."""
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return (dx * dx + dy * dy) ** 0.5


def repeated(candidates: list[list[tuple]], dims: list[tuple[float, float]]) -> set[tuple[int, tuple]]:
    """The figure boxes that stand in the same place on several pages (a logo in a header, a seal in a footer): not
    figures. Returns (page, key) pairs, key being the box rounded to 8 points."""
    seen: dict[tuple, set[int]] = {}
    for pno, boxes in enumerate(candidates):
        for b in boxes:
            seen.setdefault(_key(b), set()).add(pno)
    drop = set()
    n = len(candidates)
    for key, pages in seen.items():
        if len(pages) >= 2 and len(pages) >= min(3, n):
            for p in pages:
                drop.add((p, key))
    return drop


def _key(b) -> tuple:
    return tuple(round(v / 8) for v in b[:4])


def figures(rec: PageShapes, lines: list, tables: list[Obj], dims: tuple[float, float], body_size: float | None,
            skip_keys: set, pno: int) -> list[Obj]:
    """The figures of a page: images, forms and clusters of drawing with the small type that labels them."""
    from . import reader

    page_w, page_h = dims
    out: list[Obj] = []
    taken: set[int] = set(id(ln) for t in tables for ln in t.lines)
    page_chars = sum(len(ln.text) for ln in lines) or 1
    for cand in sorted(figure_candidates(rec, page_w, page_h, tables), key=lambda b: (b[1], b[0])):
        if (pno, _key(cand)) in skip_keys:
            continue
        box = cand[:4]
        image = bool(cand[4])
        w, h = box[2] - box[0], box[3] - box[1]
        if w < MIN_FIGURE[0] or h < MIN_FIGURE[1]:
            continue      # an icon, a bullet, a logo
        if (cand[4] and w >= 0.7 * page_w and h >= 0.7 * page_h) or (w >= 0.95 * page_w and h >= 0.95 * page_h):
            continue
        members = _absorb(box, lines, taken, body_size)
        if sum(len(ln.text) for ln in members) > 0.5 * page_chars and len(members) >= 8:
            continue      # a page wrapped in a form, or a page of mostly labels: not a figure
        if not image:
            chars = sum(len(ln.text) for ln in members)
            if chars > 900 or (chars > 300 and _area(box) > 0.5 * page_w * page_h):
                continue  # more words than a chart has, or a page laid out with boxes (a slide): it is text
            inner = [ln for ln in members if box[0] <= _centre(ln)[0] <= box[2] and box[1] <= _centre(ln)[1] <= box[3]]
            if sum(1 for ln in inner if len(ln.text.strip()) >= 45 and not _small_type(ln, body_size)) >= 2:
                continue  # paragraphs among the lines: a ruled form or a boxed text, not a figure
            if len(inner) >= 4:
                tabs = reader.find_tables(inner)
                if tabs and sum(len(tl) for tl, _g in tabs) >= 0.5 * len(inner):
                    continue      # rows of cells under shading: the gaps between columns find that table
        full = box
        for ln in members:
            full = _union(full, (ln.x0, ln.top, ln.x1 if ln.x1 is not None else ln.x0,
                                 ln.bottom if ln.bottom is not None else ln.top))
        for ln in members:
            ln.figure = True
            ln.furniture = ""
            taken.add(id(ln))
        out.append(Obj("figure", full, members, None, None, image))
    return out


# ------------------------------------------------------------------------------------------------------------------
# a page
# ------------------------------------------------------------------------------------------------------------------
def page_objects(rec: PageShapes | None, lines: list, dims: tuple[float, float], body_size: float | None,
                 skip_keys: set, pno: int) -> tuple[list[Obj], list]:
    """The tables and figures a page's rules and drawings make, and the page's lines without theirs. Page furniture
    that stands inside a table's rules (a number of the last row at the foot of the page) is a cell, not furniture."""
    if rec is None or not lines or not dims[0]:
        return [], lines
    placed = [ln for ln in lines if ln.top is not None and ln.x0 is not None]
    if len(placed) < len(lines) or not placed:
        return [], lines
    tables: list[Obj] = []
    if rec.drawings:
        # a table's furniture mark is lifted only for the lines inside its rules
        tables = ruled_tables(rec, placed, dims[1])
        for t in tables:
            for ln in t.lines:
                ln.furniture = ""
    figs = figures(rec, [ln for ln in placed if not ln.furniture], tables, dims, body_size, skip_keys, pno) \
        if (rec.figures or rec.drawings) else []
    if not tables and not figs:
        return [], lines
    gone = set(id(ln) for o in tables + figs for ln in o.lines)
    return tables + figs, [ln for ln in lines if id(ln) not in gone]


def candidate_keys(shapes: list[PageShapes | None], dims: list[tuple[float, float]]) -> set:
    """The figure boxes that repeat on pages (logos, seals), as (page, key) pairs to leave out. Looked at from the
    images and forms only: a drawn chart does not repeat."""
    per_page: list[list[tuple]] = []
    for rec, d in zip(shapes, dims):
        per_page.append([f for f in (rec.figures if rec is not None else [])
                         if (f[2] - f[0]) < 0.85 * d[0] or (f[3] - f[1]) < 0.85 * d[1]])
    return repeated(per_page, dims)


def place(blocks: list, objs: list[Obj], pno: int) -> list:
    """The page's blocks with its tables and figures put where they stand: before the first block that starts below
    the top of the object and overlaps it sideways, else after the last block that overlaps it, else last."""
    out = list(blocks)
    for o in sorted(objs, key=lambda o: (o.box[1], o.box[0])):
        at = None
        last = None
        for i, b in enumerate(out):
            bb = b.bbox
            if bb is None:
                continue
            side = _x_overlap(bb, o.box)
            if side <= 0.3 * max(1.0, min(bb[2] - bb[0], o.box[2] - o.box[0])):
                continue
            last = i
            if bb[1] >= o.box[1] - 1:
                at = i
                break
        if at is None:
            at = (last + 1) if last is not None else len(out)
        out.insert(at, o.block(pno))
    return out


# ------------------------------------------------------------------------------------------------------------------
# a table over a page
# ------------------------------------------------------------------------------------------------------------------
def _norm_row(row: list[str]) -> list[str]:
    return [" ".join(c.lower().split()) for c in row]


def join_tables(blocks: list, dims: list[tuple[float, float]], body_size: float | None) -> int:
    """Tables that run over a page made one, in place: the table that is the last block of a page and the table that
    is the first block of the next (page furniture aside), with the same number of columns and the same width, or the
    same header row. The one block keeps the first page and its box; the header row the next page repeats is dropped.
    A table over three pages or more is joined page by page. Returns how many tables were joined to the one before."""
    by_page: dict[int, list] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    joined = 0
    gone: set[int] = set()
    open_table = None      # the table that ended its page and may go on
    for p in range(len(dims)):
        content = [b for b in by_page.get(p, []) if b.kind != "furniture"]
        h = dims[p][1]
        if open_table is not None:
            if content and content[0].kind == "table" and _continues(open_table, content[0], h):
                _merge_into(open_table, content[0])
                gone.add(id(content[0]))
                joined += 1
                content = content[1:]
                if not content:
                    continue      # the page held only the rest of the table: it may go on again
            open_table = None
        tail = [b for b in content if not _footnote_like(b, body_size, h)]
        if tail and tail[-1].kind == "table" and tail[-1].rows:
            bb = tail[-1].bbox
            if bb is not None and bb[3] > 0.55 * h:
                open_table = tail[-1]
    if gone:
        blocks[:] = [b for b in blocks if id(b) not in gone]
    return joined


def _footnote_like(b, body_size: float | None, h: float) -> bool:
    ln = b.lines[0] if b.lines else None
    return bool(ln is not None and ln.top is not None and body_size and ln.size and ln.size < 0.9 * body_size
                and ln.top > 0.7 * h and b.kind != "table")


def _continues(a, b, h: float) -> bool:
    """Whether table `b`, first on its page, goes on from table `a`."""
    if not a.rows or not b.rows:
        return False
    ab, bb = a.bbox, b.bbox
    if ab is None or bb is None or bb[1] > 0.45 * h:
        return False
    if len(a.rows[0]) != len(b.rows[0]):
        return False
    header_again = _norm_row(b.rows[0]) == _norm_row(a.rows[0])
    similar = abs(ab[0] - bb[0]) <= 20 and abs(ab[2] - bb[2]) <= 20
    return header_again or similar


def _merge_into(a, b) -> None:
    box = a.bbox   # the first page's part: where the picture of the table is drawn from
    rows = list(b.rows)
    if rows and a.rows and _norm_row(rows[0]) == _norm_row(a.rows[0]):
        rows = rows[1:]
    a.rows = list(a.rows) + rows
    a.lines = list(a.lines) + list(b.lines)
    a.box = box
    if a.caption is None:
        a.caption = b.caption


# ------------------------------------------------------------------------------------------------------------------
# captions, and images in Word files and web pages
# ------------------------------------------------------------------------------------------------------------------
def mark_text_figures(blocks: list, figures: set[str]) -> None:
    """Word files and web pages have no boxes, only text: the alternative texts of their images (`RawDoc.figures`, each
    a paragraph of its own) are blocks of kind `figure`, left out of passages like the words inside a PDF's figure."""
    for b in blocks:
        if b.kind != "furniture" and " ".join(" ".join(ln.text for ln in b.lines).split()) in figures:
            b.kind = "figure"



def link_captions(blocks: list) -> None:
    """A figure's caption: the block of kind `caption` that begins "Figure 3." (and the like) just below it, else just
    above it, on the same page. The caption stays a block of its own; the figure keeps its text in `caption`."""
    for i, b in enumerate(blocks):
        if b.kind != "figure" or b.caption:
            continue
        bb = b.bbox
        for j in (i + 1, i - 1):
            if 0 <= j < len(blocks):
                c = blocks[j]
                if c.kind == "caption" and c.page == b.page and _CAPTION.match(c.text.strip()) \
                        and not c.text.lower().startswith(("tab",)):
                    cb = c.bbox
                    if bb is not None and cb is not None and _gap(bb, cb) > 70:
                        continue
                    b.caption = c.text
                    break

"""A highlighted PDF to keep (F7): a copy of the original PDF with ENLENS's quotes highlighted, readable in any PDF
reader; for text files and web pages, an HTML copy of the text with coloured marks.

- Colours: green for supports, amber for partly supports, red for contradicts. Labels (F2), concept mentions (F3)
  and reference chains (F5) are separate layers that can be switched on (blue, purple, grey).
- Each highlight carries a note: the hypothesis or code, the judgement, the certainty, who judged it, and the
  person's note.
- Quotes that cannot be placed are listed in a note on the first page, never silently dropped.

ENLENS stores character offsets in its own extracted text, not page coordinates, so each quote is found on its page
again:
1. exact boxes (preferred): with the optional `pdfminer` extra, the page's characters are read with their boxes; the
   quote is located in that text with `find_quote` (which ignores line breaks and typographic quotes; hyphens at
   line ends are joined the way ingest joins them), and the boxes are joined per line into quad points;
2. line boxes (fallback, core only): pypdf's text visitor gives each text run's start and font size; highlights then
   run from the quote's estimated start to its estimated end on the right lines;
3. scanned pages read by OCR: Tesseract's word boxes (TSV), at the resolution used for reading.
The annotations are written with pypdf (`pypdf.annotations.Highlight`).
"""
from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .store import Workspace
from .textutil import find_quote

LAYERS = ("judgements", "labels", "concepts", "references")
COLOURS = {"supports": "2e9e4f", "partially_supports": "f2b01e", "refutes": "d64545", "label": "3b82f6",
           "concept": "9b5de5", "reference": "9aa0a6"}
CSS_COLOURS = {"supports": "#b9e8c6", "partially_supports": "#ffe3a3", "refutes": "#f7c0c0", "label": "#c7dcff",
               "concept": "#e4d4fb", "reference": "#e3e5e8"}
WORDS = {"supports": "Supports", "partially_supports": "Partly supports", "refutes": "Contradicts"}
_HYPHEN_END = re.compile(r"[a-z]-$")


@dataclass
class Mark:
    start: int                 # document offsets (ENLENS's text)
    end: int
    quote: str
    kind: str                  # a key of COLOURS
    note: str
    layer: str
    page: int | None = None
    placed: bool = False
    method: str = ""
    quads: list = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# what to highlight
# ---------------------------------------------------------------------------------------------
def collect(ws: Workspace, doc_id: str, hyp_ids: list[str] | None = None, layers=("judgements",),
            framework: str = "sdg", concept: str | None = None, threshold: float | None = None) -> list[Mark]:
    from .claimcheck import GRADES, certainty_word, effective

    thr = float(ws.config["thresholds"]["support_confidence"]) if threshold is None else float(threshold)
    marks: list[Mark] = []
    if "judgements" in layers:
        sql = ("SELECT v.*, c.text AS claim, c.hyp_id, h.text AS hyp FROM verifications v JOIN user_claims c ON "
               "c.claim_id=v.subject_id LEFT JOIN hypotheses h ON h.hyp_id=c.hyp_id WHERE v.subject_kind='user_claim' "
               "AND v.doc_id=?")
        args: list = [doc_id]
        if hyp_ids:
            sql += f" AND c.hyp_id IN ({','.join('?' * len(hyp_ids))})"
            args += hyp_ids
        for v in ws.query(sql, args):
            e = effective(v)
            if e["verdict"] not in GRADES:
                continue
            mine = bool(v["user_verdict"])
            start, end, quote = ((v["user_start"], v["user_end"], v["user_quote"]) if mine and v["user_quote"]
                                 else (v["start"], v["end"], v["quote"]))
            if start is None or not quote:
                continue
            counted = mine or (e["confidence"] or 0) >= thr
            who = "you" if mine else "the AI"
            cert = "" if mine else f", {certainty_word(v['confidence'])} certainty ({round((v['confidence'] or 0) * 100)}%)"
            lines = [f"Hypothesis: {v['hyp'] or v['claim']}"]
            if v["hyp"] and v["claim"] != v["hyp"]:
                lines.append(f"Part checked: {v['claim']}")
            lines.append(f"Judgement: {WORDS[e['verdict']]} (by {who}{cert})" + ("" if counted else
                                                                                  " — not counted at this strictness"))
            if mine and v["verdict"] in GRADES and v["verdict"] != v["user_verdict"]:
                lines.append(f"The AI's own judgement: {WORDS[v['verdict']]}")
            if v["scope_note"]:
                lines.append(f"About another group (AI): {v['scope_note']}")
            if v["refers_to"]:
                lines.append(f"Refers to: {v['refers_to']}")
            if v["user_note"]:
                lines.append(f"Your note: {v['user_note']}")
            marks.append(Mark(start, end, quote, e["verdict"], "\n".join(lines), "judgements", v["page"]))
    if "labels" in layers:
        from . import frameworks, profile

        fw = frameworks.get(framework, ws)
        for r in profile.effective(ws, framework, doc_ids=[doc_id]):
            if r["start"] is None or not r["quote"]:
                continue
            desc = fw.codes[r["code"]].description if r["code"] in fw.codes else ""
            who = {"model": "the AI", "person": "you"}.get(r["source"], r["source"])
            lines = [f"{fw.label} {r['code']}: {desc}"[:400],
                     f"{'Main topic' if r['relevance'] == 'main' else 'Mentioned'}"
                     + (f", {r['direction'].replace('_', ' ')}" if r["direction"] and r["direction"] != "not_stated" else "")
                     + f" (by {who}" + (f", {round((r['confidence'] or 0) * 100)}%" if r["source"] == "model" else "") + ")"]
            if r["reason"]:
                lines.append(f"Why: {r['reason']}")
            if r.get("person_note"):
                lines.append(f"Your note: {r['person_note']}")
            marks.append(Mark(r["start"], r["end"], r["quote"], "label", "\n".join(lines), "labels", r["page"]))
    if "concepts" in layers and concept:
        from . import terms

        ids = terms.concept_of(ws, concept)
        label = ws.scalar("SELECT label FROM terms WHERE term_id=?", (concept,)) or ""
        q = ",".join("?" * len(ids))
        text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc_id,)) or ""
        for r in ws.query(f"SELECT start, end FROM term_mentions WHERE doc_id=? AND term_id IN ({q}) ORDER BY start",
                          (doc_id, *ids)):
            marks.append(Mark(r["start"], r["end"], text[r["start"]:r["end"]], "concept", f"Concept: {label}", "concepts"))
    if "references" in layers:
        from .references import chains

        for ch in chains(ws, doc_id):
            for m in ch["mentions"]:
                marks.append(Mark(m["start"], m["end"], m["text"], "reference",
                                  f"Refers to: {ch['name']} (chain {ch['chain_id']}, {ch['size']} mentions)", "references"))
    _pages(ws, doc_id, marks)
    marks.sort(key=lambda m: (m.start, m.end))
    return marks


def _pages(ws: Workspace, doc_id: str, marks: list[Mark]) -> None:
    import bisect

    rows = ws.query("SELECT page, start, end FROM pages WHERE doc_id=? ORDER BY page", (doc_id,))
    if not rows:
        return
    ends = [r["end"] + 2 for r in rows]
    for m in marks:
        i = min(len(rows) - 1, bisect.bisect_right(ends, m.start))
        m.page = rows[i]["page"]


# ---------------------------------------------------------------------------------------------
# finding a quote on a PDF page
# ---------------------------------------------------------------------------------------------
@dataclass
class PageText:
    text: str
    boxes: list            # per character: (x0, y0, x1, y1, line) or None
    method: str
    width: float = 0.0
    height: float = 0.0
    x0: float = 0.0
    y0: float = 0.0


def _join_lines(lines: list[list[tuple[str, tuple | None]]]) -> tuple[str, list]:
    """Characters of the page's lines into one string, as ingest joins them: a hyphen that ends a line between two
    lower-case letters is dropped, other line ends become a space."""
    chars: list[str] = []
    boxes: list = []
    for k, line in enumerate(lines):
        txt = "".join(c for c, _b in line)
        nxt = "".join(c for c, _b in lines[k + 1]) if k + 1 < len(lines) else ""
        drop = bool(_HYPHEN_END.search(txt.rstrip())) and nxt[:1].islower()
        items = list(line)
        if drop:
            while items and items[-1][0].isspace():
                items.pop()
            items = items[:-1]
        for c, b in items:
            chars.append(c)
            boxes.append(b)
        if not drop:
            chars.append(" ")
            boxes.append(None)
    return "".join(chars), boxes


def _pdfminer_pages(path: Path) -> dict[int, PageText] | None:
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams, LTAnno, LTChar, LTTextContainer, LTTextLine
    except ImportError:
        return None
    out: dict[int, PageText] = {}
    line_no = 0
    try:
        for pno, page in enumerate(extract_pages(str(path), laparams=LAParams()), 1):
            lines: list[list] = []

            def walk(obj):
                nonlocal line_no
                if isinstance(obj, LTTextLine):
                    line_no += 1
                    items = []
                    for ch in obj:
                        if isinstance(ch, LTChar):
                            items.append((ch.get_text(), (ch.x0, ch.y0, ch.x1, ch.y1, line_no)))
                        elif isinstance(ch, LTAnno):
                            t = ch.get_text()
                            if t and t != "\n":
                                items.append((t, None))
                    lines.append(items)
                elif isinstance(obj, LTTextContainer) or hasattr(obj, "__iter__"):
                    try:
                        for x in obj:
                            walk(x)
                    except TypeError:
                        pass

            for obj in page:
                walk(obj)
            text, boxes = _join_lines(lines)
            x0, y0, x1, y1 = page.bbox
            out[pno] = PageText(text, boxes, "exact", x1 - x0, y1 - y0, x0, y0)
    except Exception:
        return None
    return out


def _pypdf_pages(reader) -> dict[int, PageText]:
    """Line boxes from pypdf's text visitor: each run's start and font size; characters get estimated widths."""
    out: dict[int, PageText] = {}
    for pno, page in enumerate(reader.pages, 1):
        runs: list[tuple[str, float, float, float]] = []

        def visit(text, cm, tm, _font, size):
            if not text:
                return
            try:
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                scale = abs(tm[0] * cm[0]) or abs(tm[3] * cm[3]) or 1.0
            except (TypeError, IndexError):
                return
            runs.append((text, float(x), float(y), float(size or 10) * float(scale or 1.0)))

        try:
            page.extract_text(visitor_text=visit)
        except Exception:
            continue
        lines: list[list] = [[]]
        line = 0
        for text, x, y, size in runs:
            cw = 0.5 * size
            col = 0
            for c in text:
                if c == "\n":
                    lines.append([])
                    line += 1
                    col = 0
                    continue
                lines[-1].append((c, (x + col * cw, y - 0.25 * size, x + (col + 1) * cw, y + 0.85 * size, f"p{line}")))
                col += 1
            if text and not text.endswith("\n"):
                pass
        text, boxes = _join_lines([ln for ln in lines if ln])
        box = page.mediabox
        out[pno] = PageText(text, boxes, "lines", float(box.width), float(box.height), float(box.left),
                            float(box.bottom))
    return out


def _ocr_page(path: Path, pno: int, lang: str = "eng") -> PageText | None:
    """Word boxes of a scanned page from Tesseract (TSV), at the resolution ingest reads scans with."""
    import subprocess

    from .ingest import OCR_DPI, find_tesseract, ocr_status

    if not ocr_status()["available"]:
        return None
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[pno - 1]
        w, h = page.get_size()
        img = page.render(scale=OCR_DPI / 72, grayscale=True).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
    finally:
        pdf.close()
    exe = find_tesseract()
    if not exe:
        return None
    r = subprocess.run([exe, "stdin", "stdout", "-l", lang, "tsv"], input=buf.getvalue(), capture_output=True, timeout=300)
    if r.returncode != 0:
        return None
    k = 72 / OCR_DPI
    lines: dict[tuple, list] = {}
    for row in r.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        key = (cols[2], cols[3], cols[4])
        left, top, wd, ht = (int(c) for c in cols[6:10])
        word = cols[11]
        n = len(word)
        for i, c in enumerate(word):
            box = ((left + wd * i / n) * k, h - (top + ht) * k, (left + wd * (i + 1) / n) * k, h - top * k, key)
            lines.setdefault(key, []).append((c, box))
        lines[key].append((" ", None))
    text, boxes = _join_lines(list(lines.values()))
    return PageText(text, boxes, "ocr", float(w), float(h))


def _quads(pt: PageText, a: int, b: int) -> list[tuple[float, float, float, float]]:
    """One rectangle per line for characters a..b of the page text."""
    per: dict = {}
    for i in range(a, b):
        bx = pt.boxes[i] if i < len(pt.boxes) else None
        if bx is None:
            continue
        x0, y0, x1, y1, line = bx
        r = per.get(line)
        per[line] = (min(r[0], x0), min(r[1], y0), max(r[2], x1), max(r[3], y1)) if r else (x0, y0, x1, y1)
    out = []
    for r in per.values():  # inside the page box
        x0 = max(pt.x0, min(r[0], pt.x0 + pt.width))
        x1 = max(pt.x0, min(r[2], pt.x0 + pt.width))
        y0 = max(pt.y0, min(r[1], pt.y0 + pt.height))
        y1 = max(pt.y0, min(r[3], pt.y0 + pt.height))
        if x1 > x0 and y1 > y0:
            out.append((x0, y0, x1, y1))
    return out


def place(path: Path, marks: list[Mark], use_pdfminer: bool = True, ocr_lang: str = "eng") -> dict:
    """Find each mark on its page; returns {"method": exact|lines, ...}."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    exact = _pdfminer_pages(path) if use_pdfminer else None
    lines = None
    ocr_cache: dict[int, PageText | None] = {}
    for m in marks:
        candidates = [m.page] if m.page else list(range(1, len(reader.pages) + 1))
        if m.page:
            candidates += [p for p in (m.page - 1, m.page + 1) if 1 <= p <= len(reader.pages)]
        for pno in candidates:
            got = None
            for source in ("exact", "lines", "ocr"):
                if source == "exact" and not exact:
                    continue
                if source == "lines":
                    if lines is None:
                        lines = _pypdf_pages(reader)
                    pt = lines.get(pno)
                elif source == "exact":
                    pt = exact.get(pno)
                else:
                    if pno not in ocr_cache:
                        base = (exact or {}).get(pno) or (lines or {}).get(pno)
                        ocr_cache[pno] = _ocr_page(path, pno, ocr_lang) if not (base and base.text.strip()) else None
                    pt = ocr_cache[pno]
                if not pt or not pt.text.strip():
                    continue
                hit = find_quote(pt.text, m.quote)
                if hit:
                    q = _quads(pt, hit[0], hit[1])
                    if q:
                        got = (q, pt.method)
                        break
            if got:
                m.quads, m.method, m.placed, m.page = got[0], got[1], True, pno
                break
    return {"pages": len(reader.pages), "exact": bool(exact)}


def write_pdf(path: Path, marks: list[Mark], title: str = "") -> bytes:
    """The PDF with a highlight (and its note) for every placed mark, and a note on page 1 listing the rest."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Highlight, Text
    from pypdf.generic import ArrayObject, FloatObject, NameObject, NumberObject, TextStringObject

    reader = PdfReader(str(path))
    writer = PdfWriter(clone_from=reader)
    placed = [m for m in marks if m.placed]
    for m in placed:
        xs = [v for q in m.quads for v in (q[0], q[2])]
        ys = [v for q in m.quads for v in (q[1], q[3])]
        quad = []
        for x0, y0, x1, y1 in m.quads:
            quad += [x0, y1, x1, y1, x0, y0, x1, y0]
        ann = Highlight(rect=(min(xs), min(ys), max(xs), max(ys)), quad_points=ArrayObject(FloatObject(v) for v in quad),
                        highlight_color=COLOURS.get(m.kind, "ffff00"), printing=True)
        ann[NameObject("/Contents")] = TextStringObject(m.note)
        ann[NameObject("/T")] = TextStringObject("ENLENS")
        ann[NameObject("/CA")] = FloatObject(0.55 if m.layer == "judgements" else 0.4)
        ann[NameObject("/F")] = NumberObject(4)
        writer.add_annotation(page_number=m.page - 1, annotation=ann)
    missing = [m for m in marks if not m.placed]
    if missing and len(writer.pages):
        box = writer.pages[0].mediabox
        lines = [f"ENLENS: {len(missing)} of {len(marks)} quotes could not be placed on the pages of this PDF "
                 "(for example where the PDF's text differs from the text ENLENS read). They are:"]
        for m in missing[:60]:
            lines.append(f"- page {m.page or '?'}: “{m.quote[:160]}” ({m.note.splitlines()[0][:120]})")
        if len(missing) > 60:
            lines.append(f"... and {len(missing) - 60} more.")
        note = Text(rect=(float(box.left) + 10, float(box.top) - 40, float(box.left) + 40, float(box.top) - 10),
                    text="\n".join(lines), open=True)
        note[NameObject("/T")] = TextStringObject("ENLENS")
        writer.add_annotation(page_number=0, annotation=note)
    if title:
        writer.add_metadata({"/Title": title})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------
# text files and web pages: an HTML copy with coloured marks
# ---------------------------------------------------------------------------------------------
def write_html(text: str, marks: list[Mark], name: str) -> bytes:
    bounds = sorted({0, len(text), *(m.start for m in marks), *(m.end for m in marks)})
    order = {"refutes": 0, "partially_supports": 1, "supports": 2, "label": 3, "concept": 4, "reference": 5}
    parts = []
    for a, b in zip(bounds, bounds[1:]):
        if a >= b:
            continue
        on = [m for m in marks if m.start <= a and b <= m.end]
        seg = html.escape(text[a:b])
        if on:
            top = min(on, key=lambda m: order.get(m.kind, 9))
            notes = "\n\n".join(dict.fromkeys(m.note for m in on))
            seg = (f'<mark style="background:{CSS_COLOURS.get(top.kind, "#ffe08a")}" title="{html.escape(notes)}">'
                   f"{seg}</mark>")
        parts.append(seg)
    for m in marks:
        m.placed = True
        m.method = "text"
    legend = " ".join(f'<span class="k" style="background:{CSS_COLOURS[k]}">{w}</span>' for k, w in
                      (("supports", "supports"), ("partially_supports", "partly supports"), ("refutes", "contradicts"),
                       ("label", "codebook label"), ("concept", "concept"), ("reference", "reference")))
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1\"><meta name=\"color-scheme\" content=\"light\">"
            f"<title>{html.escape(name)}</title><style>"
            "body{margin:0;font:15px/1.6 Georgia,serif;background:#fbfaf6;color:#1d1d1b}"
            "header{position:sticky;top:0;padding:10px 16px;font:13px/1.5 system-ui,sans-serif;background:#efece3;"
            "border-bottom:1px solid #ddd8cc}.k{padding:1px 6px;border-radius:3px;margin-right:4px}"
            "pre{white-space:pre-wrap;word-wrap:break-word;font:inherit;margin:0;padding:16px;max-width:46rem}"
            "mark{color:inherit;padding:1px 0;cursor:help}</style></head><body>"
            f"<header><strong>{html.escape(name)}</strong> · the text ENLENS read, with its quotes marked "
            f"(hover a mark for its note) · {legend}</header><pre>{''.join(parts)}</pre></body></html>").encode()


# ---------------------------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------------------------
def annotate_document(ws: Workspace, doc_id: str, hyp_ids: list[str] | None = None, layers=("judgements",),
                      framework: str = "sdg", concept: str | None = None, use_pdfminer: bool = True,
                      threshold: float | None = None) -> dict:
    """{"name", "content_type", "body", "marks", "placed", "missing", "method"} for one document."""
    from .sources import original_file

    bad = [x for x in layers if x not in LAYERS]
    if bad:
        raise ValueError(f"Unknown layer {bad[0]!r}; use {', '.join(LAYERS)}.")
    d = ws.query("SELECT doc_id, title, kind, text FROM documents WHERE doc_id=?", (doc_id,))
    if not d:
        raise KeyError(doc_id)
    d = dict(d[0])
    marks = collect(ws, doc_id, hyp_ids, layers, framework, concept, threshold)
    info = original_file(ws, doc_id)
    stem = re.sub(r"[^\w .-]+", " ", (info.get("name") or d["title"] or doc_id)).strip()[:80] or doc_id
    stem = re.sub(r"\.(pdf|html?|txt|md)$", "", stem, flags=re.I)
    if d["kind"] == "pdf" and info["available"]:
        place(Path(info["path"]), marks, use_pdfminer)
        body = write_pdf(Path(info["path"]), marks, title=f"{d['title'] or stem} (highlighted by ENLENS)")
        out = {"name": f"{stem} - highlighted.pdf", "content_type": "application/pdf", "body": body}
    else:
        body = write_html(d["text"] or "", marks, d["title"] or stem)
        out = {"name": f"{stem} - highlighted.html", "content_type": "text/html; charset=utf-8", "body": body,
               "note": None if d["kind"] != "pdf" else info.get("reason")}
    methods = sorted({m.method for m in marks if m.placed})
    out.update(marks=len(marks), placed=sum(m.placed for m in marks), missing=[
        {"page": m.page, "quote": m.quote, "note": m.note} for m in marks if not m.placed], method=methods)
    return out


def annotate_hypothesis_zip(ws: Workspace, hyp_id: str, layers=("judgements",), use_pdfminer: bool = True,
                            threshold: float | None = None) -> tuple[bytes, dict]:
    """A zip of the documents behind a hypothesis's answer (every document with a graded excerpt), highlighted."""
    if not ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hyp_id,)):
        raise KeyError(hyp_id)
    docs = [r[0] for r in ws.query(
        "SELECT DISTINCT v.doc_id FROM verifications v JOIN user_claims c ON c.claim_id=v.subject_id JOIN documents d ON "
        "d.doc_id=v.doc_id WHERE v.subject_kind='user_claim' AND c.hyp_id=? AND (v.verdict IN ('supports', "
        "'partially_supports', 'refutes') OR v.user_verdict IN ('supports', 'partially_supports', 'refutes')) "
        "ORDER BY d.title", (hyp_id,))]
    if not docs:
        raise ValueError("No document has a judged excerpt for this hypothesis: there is nothing to highlight.")
    buf = io.BytesIO()
    summary = {"documents": 0, "marks": 0, "placed": 0, "missing": 0}
    names: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        report = []
        for doc in docs:
            r = annotate_document(ws, doc, [hyp_id], layers, use_pdfminer=use_pdfminer, threshold=threshold)
            name = r["name"]
            n = 2
            while name in names:
                name = re.sub(r"(\.\w+)$", f" ({n})\\1", r["name"])
                n += 1
            names.add(name)
            zf.writestr(name, r["body"], compress_type=zipfile.ZIP_STORED if name.endswith(".pdf") else zipfile.ZIP_DEFLATED)
            summary["documents"] += 1
            summary["marks"] += r["marks"]
            summary["placed"] += r["placed"]
            summary["missing"] += len(r["missing"])
            report.append(f"{name}: {r['placed']} of {r['marks']} quotes highlighted"
                          + (f" ({', '.join(r['method'])})" if r["method"] else ""))
        hyp = ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (hyp_id,))
        zf.writestr("README.txt", f"Highlighted copies made by ENLENS for the hypothesis:\n{hyp}\n\n"
                                  "Green: supports. Amber: partly supports. Red: contradicts. Each highlight has a note "
                                  "with the judgement, who made it and the certainty.\n\n" + "\n".join(report) + "\n")
    return buf.getvalue(), summary


def check_placement(ws: Workspace, doc_id: str, use_pdfminer: bool = True) -> dict:
    """For the F7 measure: how many quotes of a PDF land on their words (the text under the boxes, read again with
    pdfminer, is the quote) or at least on the right lines."""
    from .sources import original_file

    info = original_file(ws, doc_id)
    if not info["available"] or not str(info["path"]).lower().endswith(".pdf"):
        raise ValueError("This document has no original PDF here.")
    marks = collect(ws, doc_id, layers=("judgements", "labels"))
    place(Path(info["path"]), marks, use_pdfminer)
    return {"quotes": len(marks), "placed": sum(m.placed for m in marks),
            "by_method": {k: sum(1 for m in marks if m.method == k) for k in ("exact", "lines", "ocr")}}

"""0.17.2: reader 4, a PDF page that holds only its running head, and faster marking of PDFs.

- A PDF whose page holds nothing but the short line repeated at the top of every page stopped the whole add with an
  IndexError (`reader.mark_furniture`). Guarded so that every page that read before reads the same: no new reader
  number for it (the fingerprint of a PDF with running heads, taken with the code before, still holds).
- Reader 4: a text file with one paragraph per line (Word's "plain text") is read paragraph by paragraph, not as one
  block; a table inside a Word table's cell is read once, not three times; text in a Word file's content controls
  and custom XML is read, not dropped. Reader 3 still reads all of these byte for byte as before (fingerprints taken
  with the code before reader 4), and a document of reader 3 moves to reader 4.
- Marking a PDF (`annotate.place`) reads with pdfminer only the pages its marks can be on.
"""
from __future__ import annotations

import random
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from helpers import make_pdf
from test_0_15_1_reader3 import _sentence

from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import annotate, ingest, measure, pdfmake, reader, reread
from enlens_claims.store import Workspace

# fingerprints of reader 3's reading of the files below, taken with ENLENS's code before reader 4 (commit a0088bb)
PINNED = {
    "lines_txt_3": "555f8a740a8e533a2ee624ce90c6bfae61ed5a14",
    "heads_pdf_2": "83b44400e2bc5f976238b373e1735fd5f0d48de1",
    "heads_pdf_3": "83b44400e2bc5f976238b373e1735fd5f0d48de1",
    "nested_docx_3": "9211ea9bb8fbf6f4fc0f83796e7e49a9ed6eb79b",
    "controls_docx_3": "94e91f0dad6bb5a6049dab744483e7ebd11c915e",
}


# ------------------------------------------------------------------------------------------------------------------
# the files
# ------------------------------------------------------------------------------------------------------------------
def lines_txt(folder: Path, n: int = 120) -> tuple[Path, list[str]]:
    """What Word saves as plain text: a title, then one paragraph per line, no blank lines, Windows line ends."""
    rng = random.Random(4)
    paras = [" ".join(_sentence(rng) for _ in range(rng.randint(2, 5))) for _ in range(n)]
    path = folder / "plain.txt"
    path.write_bytes(("Water and hydrogen in dry regions\r\n" + "\r\n".join(paras) + "\r\n").encode("utf-8"))
    return path, paras


def heads_pdf(folder: Path) -> Path:
    """Two columns, a running head and page numbers on every page (as test_0_15_0_read_with_new_reader's paper)."""
    rng = random.Random(7)
    fl = pdfmake.Flow(columns=[(56, 230), (310, 230)], running_head="Journal of Dry Regions 12 (2026)",
                      page_numbers=True)
    for _ in range(30):
        fl.paragraph(" ".join(_sentence(rng) for _ in range(4)))
    path = folder / "heads.pdf"
    fl.write(path)
    return path


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def _tc(*blocks: str) -> str:
    return "<w:tc>" + "".join(blocks) + "</w:tc>"


def _tbl(*rows: list[str]) -> str:
    return "<w:tbl>" + "".join("<w:tr>" + "".join(r) + "</w:tr>" for r in rows) + "</w:tbl>"


def _docx(path: Path, body: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
    return path


def nested_docx(folder: Path) -> Path:
    inner = _tbl([_tc(_p("Inner cell one")), _tc(_p("Inner cell two"))],
                 [_tc(_p("Inner cell three")), _tc(_p("Inner cell four"))])
    body = (_p("Water use of the planned plants", "Heading1")
            + _p("The table below lists each site with the water it would draw, and the sources of that water.")
            + _tbl([_tc(_p("Site")), _tc(_p("Water use"))],
                   [_tc(_p("Outer cell A")), _tc(_p("Outer cell B"), inner)])
            + _p("Desalination would cover part of the demand by 2030, the operators say."))
    return _docx(folder / "nested.docx", body)


def controls_docx(folder: Path) -> Path:
    """Text inside content controls (a cover page, an abstract box, a control around a table's row) and custom XML."""
    body = (
        '<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Cover Pages"/></w:docPartObj></w:sdtPr><w:sdtContent>'
        + _p("Hydrogen and water in arid export regions", "Title") + _p("A report for the regional water board")
        + "</w:sdtContent></w:sdt>"
        + _p("Introduction", "Heading1")
        + _p("Electrolysers need clean water, and the regions with the most sun often have the least of it.")
        + '<w:sdt><w:sdtPr><w:alias w:val="Abstract"/></w:sdtPr><w:sdtContent>'
        + _p("Summary of findings", "Heading1")
        + _p("Farmers near the planned plants fear that the long-term supply of water will fall as the plants grow.")
        + "</w:sdtContent></w:sdt>"
        + '<w:customXml w:element="finding">'
        + _p("The operators say desalination will cover forty per cent of the demand by 2031.")
        + "</w:customXml>"
        + _tbl([_tc(_p("Site")), _tc(_p("Cubic metres a day"))],
               ["<w:sdt><w:sdtContent>" + _tc(_p("Ouarzazate")) + _tc(_p("127")) + "</w:sdtContent></w:sdt>"])
        + _p("The board will decide in the spring.")
    )
    return _docx(folder / "controls.docx", body)


def _fp(path: Path, version: int) -> str:
    return measure.fingerprint(ingest.read_document(path, reader=version))


# ------------------------------------------------------------------------------------------------------------------
# the page that holds only its running head
# ------------------------------------------------------------------------------------------------------------------
def test_a_pdf_page_that_holds_only_its_running_head_no_longer_stops_the_add(tmp_path):
    pages = []
    for i in range(6):
        pages.append("Draft for comment" if i in (2, 4) else
                     "Draft for comment\n" + " ".join(_sentence(random.Random(i)) for _ in range(12)))
    path = make_pdf(tmp_path / "draft.pdf", pages)
    for version in (2, 3, 4):
        doc = ingest.read_document(path, reader=version)   # raised IndexError in mark_furniture
        assert doc.passages
        # on a page of its own the line stands apart from any text: a running head (where text follows it without a
        # gap, it stays text, as before)
        alone = [b for b in doc.blocks if b.page in (2, 4)]
        assert [(b.text, b.kind) for b in alone] == [("Draft for comment", "furniture")] * 2
    ws = Workspace.create(tmp_path / "ws")
    st = ingest.ingest(ws, [path], ai_access="cloud")
    assert st["added"] == 1, st


def test_running_heads_of_a_pdf_read_as_before_the_guard(tmp_path):
    path = heads_pdf(tmp_path)
    assert _fp(path, 2) == PINNED["heads_pdf_2"]
    assert _fp(path, 3) == PINNED["heads_pdf_3"]
    assert _fp(path, 4) == _fp(path, 3)                      # reader 4 changes nothing in a PDF


# ------------------------------------------------------------------------------------------------------------------
# reader 4
# ------------------------------------------------------------------------------------------------------------------
def test_the_reader_is_4():
    assert ingest.READER == reader.READER >= 4   # (0.18.1: reader 5 is current; reader 4 stays as it was)


def test_a_text_file_with_one_paragraph_per_line_is_read_paragraph_by_paragraph(tmp_path):
    path, paras = lines_txt(tmp_path)
    old = ingest.read_document(path, reader=3)
    assert sum(1 for b in old.blocks if b.kind == "body") == 1          # reader 3: one block
    assert measure.fingerprint(old) == PINNED["lines_txt_3"]
    doc = ingest.read_document(path, reader=4)
    body = [b for b in doc.blocks if b.kind == "body"]
    assert [b.text for b in body] == paras
    assert doc.reading["reader"] == 4 and doc.reading["text_layout"]["paragraph_lines"] is True
    # quotes are cited by their own paragraph, not all as paragraph 1
    assert len(doc.layout.paragraphs) >= len(paras)
    at = [next(b.n for b in body if b.start < p.end <= b.end) for p in doc.passages if p.section == "body"]
    assert sorted(set(at)) == [b.n for b in body]


def test_hard_wrapped_and_blank_line_text_files_read_as_reader_3_did(tmp_path):
    from test_0_15_1_reader3 import make_book

    rng = random.Random(9)
    paras = [" ".join(_sentence(rng) for _ in range(4)) for _ in range(40)]
    blank = tmp_path / "blank.txt"
    blank.write_text("\n\n".join(paras), encoding="utf-8")            # long lines, a blank line between
    wrapped = tmp_path / "wrapped.txt"
    import textwrap
    wrapped.write_text("\n".join(ln for p in paras for ln in textwrap.wrap(p, 72)), encoding="utf-8")
    book, *_ = make_book(tmp_path)
    for path in (blank, wrapped, book):
        assert _fp(path, 4) == _fp(path, 3), path.name
    # a few long lines that do not end sentences (text wrapped very wide) are not taken for paragraphs
    wide = tmp_path / "wide.txt"
    wide.write_text("\n".join(ln for p in paras for ln in textwrap.wrap(p, 200)), encoding="utf-8")
    assert _fp(wide, 4) == _fp(wide, 3)


def test_a_table_inside_a_word_tables_cell_is_read_once(tmp_path):
    path = nested_docx(tmp_path)
    old = ingest.read_document(path, reader=3)
    assert old.text.count("Inner cell one") == 3                         # the bug, kept by reader 3
    assert measure.fingerprint(old) == PINNED["nested_docx_3"]
    doc = ingest.read_document(path, reader=4)
    for t in ("Inner cell one", "Inner cell four", "Outer cell B", "Site"):
        assert doc.text.count(t) == 1, t
    assert "Outer cell A | Outer cell B" in doc.text and "Inner cell one | Inner cell two" in doc.text
    assert doc.text.index("Outer cell B") < doc.text.index("Inner cell one") < doc.text.index("Desalination")


def test_text_in_word_content_controls_and_custom_xml_is_read(tmp_path):
    path = controls_docx(tmp_path)
    old = ingest.read_document(path, reader=3)
    assert "Summary of findings" not in old.text and "forty per cent" not in old.text  # dropped by reader 3
    assert measure.fingerprint(old) == PINNED["controls_docx_3"]
    doc = ingest.read_document(path, reader=4)
    for t in ("Hydrogen and water in arid export regions", "Summary of findings", "Farmers near the planned plants",
              "forty per cent", "Ouarzazate | 127", "The board will decide"):
        assert doc.text.count(t) == 1, t
    assert "Summary of findings" in doc.raw.headings
    assert next(b for b in doc.blocks if b.text == "Summary of findings").kind == "heading"
    # in the order of the file
    order = [doc.text.index(t) for t in ("Hydrogen and water", "Introduction", "Summary of findings", "forty per cent",
                                          "Ouarzazate", "The board")]
    assert order == sorted(order)


def test_a_word_file_without_them_reads_the_same_by_both_readers(tmp_path):
    body = _p("Results", "Heading1") + "".join(_p(_sentence(random.Random(i))) for i in range(30)) \
        + _tbl([_tc(_p("Site")), _tc(_p("Use"))], [_tc(_p("A")), _tc(_p("12"))])
    path = _docx(tmp_path / "plain.docx", body)
    raw = ingest.read_file(path)
    assert raw.before_4 is None                         # nothing to keep twice
    assert _fp(path, 4) == _fp(path, 3)


def test_reader_3_reads_the_same_from_a_raw_read_for_reader_4(tmp_path):
    """`build_document(raw, version=3)` reads the Word text reader 3 read, however the file was read."""
    for path in (nested_docx(tmp_path), controls_docx(tmp_path)):
        raw = ingest.read_file(path)
        assert raw.before_4 is not None
        assert measure.fingerprint(reader.build_document(raw, version=3)) == _fp(path, 3)
        assert measure.fingerprint(ingest.build_document(ingest.read_file(path), reader=3)) == _fp(path, 3)
        assert measure.fingerprint(reader.build_document(raw, version=4)) == _fp(path, 4)


def test_a_document_of_reader_3_is_offered_reader_4_and_moves(tmp_path, monkeypatch):
    path, paras = lines_txt(tmp_path)
    ws = Workspace.create(tmp_path / "ws")
    with monkeypatch.context() as mp:
        mp.setattr(ingest, "READER", 3)
        assert ingest.ingest(ws, [path], ai_access="cloud")["added"] == 1
    doc_id = ws.scalar("SELECT doc_id FROM documents")
    assert ws.scalar("SELECT reader FROM documents") == 3
    assert ws.scalar("SELECT COUNT(*) FROM blocks WHERE doc_id=? AND kind='body'", (doc_id,)) == 1
    c = reread.check(ws, doc_id)
    assert c["ok"] and c["reader"] == 3 and c["new_reader"] == ingest.READER
    assert reread.move(ws, doc_id)["moved"] is not None
    assert ws.scalar("SELECT reader FROM documents") == ingest.READER
    assert ws.scalar("SELECT COUNT(*) FROM blocks WHERE doc_id=? AND kind='body'", (doc_id,)) == len(paras)
    assert not reread.check(ws, doc_id)["ok"]                          # already read by the newest reader


def test_the_reading_view_still_shows_a_document_of_reader_3(api, tmp_path, monkeypatch):
    from test_0_15_0_reader import _project

    path = controls_docx(tmp_path)
    monkeypatch.setattr(ingest, "READER", 3)
    d = next(iter(_project(api, tmp_path, [path]).values()))
    monkeypatch.setattr(ingest, "READER", 4)
    assert d["reader"] == 3
    st, v = api("GET", f"/api/projects/R/documents/{d['doc_id']}?view=blocks&limit=1000")
    assert st == 200 and v["reader"] == 3 and v["new_reader"] == 4 and v["reading"]["reader"] == 3
    assert v["blocks"] and all(b["kind"] for b in v["blocks"]) and v["blocks"][0]["label"]
    assert "Summary of findings" not in " ".join(b["text"] for b in v["blocks"])   # reader 3's text, as it was read
    st, lst = api("GET", "/api/projects/R/documents")
    assert st == 200 and lst["new_reader"] == 4 and lst["documents"][0]["reader"] == 3


# ------------------------------------------------------------------------------------------------------------------
# marking a PDF
# ------------------------------------------------------------------------------------------------------------------
def test_marking_a_pdf_reads_only_the_pages_its_marks_can_be_on(tmp_path, monkeypatch):
    pytest.importorskip("pdfminer")
    import pdfminer.high_level as hl

    pages = [f"Page {n} marker sentence for page {n} of the report.\n" + _sentence(random.Random(n)) for n in
             range(1, 41)]
    path = make_pdf(tmp_path / "long.pdf", pages)
    seen: list[int] = []
    real = hl.extract_pages

    def spy(*a, **k):
        for page in real(*a, **k):
            seen.append(page.pageid)
            yield page
    monkeypatch.setattr(hl, "extract_pages", spy)
    marks = [annotate.Mark(0, 0, f"marker sentence for page {p} of", "supports", "", "judgements", page=p)
             for p in (5, 30)]
    marks.append(annotate.Mark(0, 0, "marker sentence for page 21 of", "supports", "", "judgements", page=20))
    info = annotate.place(path, marks)
    assert info["exact"] and len(seen) == 9                  # pages 4-6, 19-21 and 29-31
    assert [(m.placed, m.method, m.page) for m in marks] == [(True, "exact", 5), (True, "exact", 30),
                                                              (True, "exact", 21)]  # a page off: its neighbour
    # a mark of unknown page is still looked for on every page
    seen.clear()
    m = annotate.Mark(0, 0, "marker sentence for page 33 of", "supports", "", "judgements")
    annotate.place(path, [m])
    assert len(seen) == 40 and m.placed and m.page == 33
    # marks on pages the file does not have: nothing read, nothing placed, no error
    seen.clear()
    m = annotate.Mark(0, 0, "marker sentence for page 3 of", "supports", "", "judgements", page=90)
    annotate.place(path, [m])
    assert seen == [] and not m.placed


def test_a_word_contents_box_is_read_and_set_aside_as_contents(tmp_path):
    """Word's table of contents is a content control: reader 4 reads it, and the rules for books set it aside."""
    def entry(title: str, page: int) -> str:
        return ('<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:hyperlink w:anchor="_Toc1">'
                f'<w:r><w:t>{escape(title)}</w:t></w:r><w:r><w:tab/></w:r>'
                '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGEREF _Toc1 \\h </w:instrText></w:r>'
                f'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>{page}</w:t></w:r>'
                '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:hyperlink></w:p>')
    heads = ["Introduction", "Water use of the plants", "Farmers and the supply", "Desalination", "Conclusions"]
    body = ('<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr>'
            '<w:sdtContent>' + _p("Contents", "TOCHeading") + "".join(entry(h, 3 * i + 1) for i, h in enumerate(heads))
            + "</w:sdtContent></w:sdt>")
    rng = random.Random(2)
    for h in heads:
        body += _p(h, "Heading1") + "".join(_p(" ".join(_sentence(rng) for _ in range(4))) for _ in range(6))
    doc = ingest.read_document(_docx(tmp_path / "toc.docx", body), reader=4)
    assert [b.kind for b in doc.blocks[:7]] == ["contents"] * 6 + ["heading"]
    assert "PAGEREF" not in doc.text                     # the field's code is not text
    assert [b.text for b in doc.blocks if b.kind == "heading"] == heads
    assert "Contents" not in ingest.read_document(tmp_path / "toc.docx", reader=3).text

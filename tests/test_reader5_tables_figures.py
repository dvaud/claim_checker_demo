"""0.18.1 (roadmap A6): reader 5, tables from their ruled lines, tables over a page, and figures.

- readers 2 to 4 read every file as before (fingerprints of text, passages and blocks, taken with the code before
  reader 5), whatever the file holds: ruled tables, charts, images, Word files and web pages with images;
- a table ruled in a grid (sentences in its cells) and one set with a rule above, under the header and below (numbers
  aligned on the right) are found with their rows and cells; a box round one paragraph is not a table;
- a table that runs over a page is one table (a repeated header row once), over three pages too; a table with another
  number of columns on the next page is not joined to it;
- a chart drawn in lines and boxes, with its labels, and a picture are blocks of kind `figure`: their page, their box,
  the words inside them left out of passages, their caption (which stays a block of its own and counts); a figure
  without words is a block of no text that no passage covers; logos that repeat on every page, scans and small
  icons are not figures; a figure stands where it is on the page, also in a column of two;
- the picture is drawn from the original PDF when asked for (`GET …/figures/<n>.png`) and nothing of it is stored;
- Word files and web pages keep an image's alternative text as a figure block (reader 5 only);
- `enlens measure` has four documents of known text for these, and reader 5 reads each at least as well as reader 4.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from test_0_15_0_reader import _project

from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import ingest, measure, pdfmake, reader, reader5

needs_pdfminer = pytest.mark.skipif(not reader.pdfminer_available(), reason="the pdfminer extra is not installed")

# fingerprints (`_whole`) of readers 2, 3 and 4 reading the files below, taken with ENLENS's code before reader 5
# (commit 29eec77): a reader number is frozen
PINNED: dict[str, str] = {
    "g_ruled_table_2": "5a0dced0b1ba5a2dde505b6651658536cb61f4e1",
    "g_ruled_table_3": "5a0dced0b1ba5a2dde505b6651658536cb61f4e1",
    "g_ruled_table_4": "5a0dced0b1ba5a2dde505b6651658536cb61f4e1",
    "h_booktabs_table_2": "0394aac2348a1171b53a28034261016d5e2f5a2b",
    "h_booktabs_table_3": "0394aac2348a1171b53a28034261016d5e2f5a2b",
    "h_booktabs_table_4": "0394aac2348a1171b53a28034261016d5e2f5a2b",
    "i_table_over_a_page_2": "06744168ddb94f8ab4131043a1e6a60fd0d63add",
    "i_table_over_a_page_3": "06744168ddb94f8ab4131043a1e6a60fd0d63add",
    "i_table_over_a_page_4": "06744168ddb94f8ab4131043a1e6a60fd0d63add",
    "image_docx_2": "a4cd51d508bee826126f4e2ec5b2976813d722dc",
    "image_docx_3": "a4cd51d508bee826126f4e2ec5b2976813d722dc",
    "image_docx_4": "a4cd51d508bee826126f4e2ec5b2976813d722dc",
    "image_html_2": "7563b5afb22d24b9e2cc784c7eba04bf067108ba",
    "image_html_3": "7563b5afb22d24b9e2cc784c7eba04bf067108ba",
    "image_html_4": "7563b5afb22d24b9e2cc784c7eba04bf067108ba",
    "j_figures_2": "8f46608528bee902951b0b5b325cbef563a74c4d",
    "j_figures_3": "8f46608528bee902951b0b5b325cbef563a74c4d",
    "j_figures_4": "8f46608528bee902951b0b5b325cbef563a74c4d",
}


def _whole(doc) -> str:
    """One hash of a reading: `measure.fingerprint` and every block's page, kind, place, text, rows and box."""
    h = hashlib.sha1(measure.fingerprint(doc).encode())
    for b in getattr(doc, "blocks", []):
        h.update(repr((b.page, b.kind, b.n, b.start, b.end, b.text, b.rows, b.caption, b.continues, b.bbox)).encode())
    return h.hexdigest()


def _read(path, r: int):
    return ingest.read_document(Path(path), reader=r)


# ------------------------------------------------------------------------------------------------------------------
# the files
# ------------------------------------------------------------------------------------------------------------------
W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
     'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"')
INTRO = "The survey counted the nests of ground birds on four plots of heathland over three springs of walking."
OUTRO = "The next paragraph goes on with the text of the paper and its main result, set out in full for the reader."
ALT = "A bar chart of the nests found on each of the four plots"


def docx_with_image(folder: Path) -> Path:
    def p(t: str) -> str:
        return f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'

    image = (f'<w:p><w:r><w:drawing><wp:inline><wp:docPr id="1" name="Picture 1" descr="{ALT}"/></wp:inline>'
             "</w:drawing></w:r></w:p>")
    body = p(INTRO) + image + p("Figure 1. Nests found on each plot.") + p(OUTRO)
    path = folder / "image.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
    return path


def html_with_image(folder: Path) -> Path:
    path = folder / "image.html"
    path.write_text(f"<html><body><p>{INTRO}</p><figure><img src=\"a.png\" alt=\"{ALT}\"><figcaption>Figure 1. Nests "
                    f"found on each plot.</figcaption></figure><p>{OUTRO}</p></body></html>", encoding="utf-8")
    return path


def _grid(pg: "pdfmake.Page", xs: list[float], top: float, rows: list[list[str]], h: float = 16.0) -> float:
    """A table ruled in a grid, row by row from `top` down, on page `pg`; the y of its foot."""
    y = top
    for row in rows:
        for x, cell in zip(xs, row):
            pg.text(cell, x + 5, y - 11, "Helvetica", 9)
        y -= h
    for k in range(len(rows) + 1):
        pg.rule(xs[0], top - k * h, xs[-1], top - k * h, 0.6)
    for x in xs:
        pg.rule(x, top, x, y, 0.6)
    return y


def _sentence_lines(fl: "pdfmake.Flow", n: int, seed: str = "alpha") -> None:
    words = f"{seed} the heathland plots were walked in lines a few metres apart and every nest was marked".split()
    for k in range(n):
        fl.paragraph(" ".join(words[(k + i) % len(words)] for i in range(40)))


@pytest.fixture(scope="module")
def known5(tmp_path_factory):
    return {c.name: c for c in measure.make_table_figure_texts(tmp_path_factory.mktemp("known5"))}


# ------------------------------------------------------------------------------------------------------------------
# frozen
# ------------------------------------------------------------------------------------------------------------------
def test_reader_5_is_the_current_reader():
    assert reader.READER == 5 and ingest.READER == 5


@needs_pdfminer
def test_readers_2_to_4_read_the_new_files_as_before(known5, tmp_path):
    files = {c.name: c.path for c in known5.values()}
    files["image_docx"] = docx_with_image(tmp_path)
    files["image_html"] = html_with_image(tmp_path)
    got = {f"{name}_{r}": _whole(_read(path, r)) for name, path in files.items() for r in (2, 3, 4)}
    assert got == PINNED


@needs_pdfminer
def test_the_old_known_texts_are_read_by_reader_5_as_by_reader_4(tmp_path):
    for c in measure.make_known_texts(tmp_path):
        a, b = _read(c.path, 4), _read(c.path, 5)
        assert (a.text, [(p.start, p.end, p.section) for p in a.passages]) == \
               (b.text, [(p.start, p.end, p.section) for p in b.passages]), c.name
        assert [(x.kind, x.text) for x in a.blocks] == [(x.kind, x.text) for x in b.blocks], c.name


def test_a_block_without_a_box_has_the_box_of_its_lines():
    ln = reader.Line(0, "text", 10.0, 20.0, 50.0, 30.0)
    assert reader.Block(0, [ln]).bbox == (10.0, 20.0, 50.0, 30.0)
    assert reader.Block(0, [ln], box=(1.0, 2.0, 3.0, 4.0)).bbox == (1.0, 2.0, 3.0, 4.0)


@needs_pdfminer
def test_pdfmake_pages_without_rules_are_written_as_before(tmp_path):
    pg = pdfmake.Page()
    pg.text("Plain", 72, 700)
    a = pdfmake.write([pg])
    pg.rule(72, 690, 200, 690)
    assert pdfmake.write([pg]) != a and b"/XObject" not in pdfmake.write([pg])
    assert b"/XObject" not in a


# ------------------------------------------------------------------------------------------------------------------
# tables
# ------------------------------------------------------------------------------------------------------------------
@needs_pdfminer
def test_a_table_ruled_in_a_grid_is_found_with_its_rows_and_cells(known5):
    c = known5["g_ruled_table"]
    doc = _read(c.path, 5)
    tables = [b for b in doc.blocks if b.kind == "table"]
    assert len(tables) == 1
    t = tables[0]
    assert t.rows[0] == ["Soil", "How the sheets describe its water", "Crops the sheets suggest"] and len(t.rows) == 4
    assert t.rows[1][0] == "Sandy loam" and t.rows[1][1].startswith("Drains quickly after rain") \
        and t.rows[1][1].endswith("so it needs watering.")      # a cell that wraps inside its rules is one cell
    assert t.rows[3][2] == "Sugar beet, oilseed rape, and most vegetables."
    assert t.caption.startswith("Table 2.") and t.bbox[0] == pytest.approx(72, abs=1) and t.bbox[2] == pytest.approx(523, abs=1)
    body = measure.body_text(doc)
    assert "Sandy loam" not in body and "Sugar beet" not in body and "Table 2. Three soils" in body
    figs_5 = measure.figures(body, c.body, c.boilerplate)
    figs_4 = measure.figures(measure.body_text(_read(c.path, 4)), c.body, c.boilerplate)
    assert figs_5["precision"] == 1.0 and figs_5["recall"] == 1.0 and figs_4["precision"] < 1.0


@needs_pdfminer
def test_a_table_with_a_rule_above_under_the_header_and_below_is_found(known5):
    doc = _read(known5["h_booktabs_table"].path, 5)
    (t,) = [b for b in doc.blocks if b.kind == "table"]
    assert t.rows[0] == ["Group", "0.5 m", "1.0 m", "1.5 m", "2.0 m"]
    assert t.rows[1] == ["Barnacles", "412", "388", "251", "96"] and len(t.rows) == 5
    assert t.bbox[0] == pytest.approx(100, abs=1) and t.bbox[2] == pytest.approx(470, abs=1)   # the rules' width


@needs_pdfminer
def test_a_table_that_runs_over_a_page_is_one_table(known5):
    c = known5["i_table_over_a_page"]
    doc = _read(c.path, 5)
    tables = [b for b in doc.blocks if b.kind == "table"]
    assert len(tables) == 1 and tables[0].page == 0
    rows = tables[0].rows
    assert rows[0] == ["Year", "Spring", "Summer", "Autumn"] and len(rows) == 41    # the header row once
    assert [r[0] for r in rows[1:]] == [str(1970 + i) for i in range(40)]
    assert not any(b.kind == "table" and b.page == 1 for b in doc.blocks)
    assert doc.reading["tables"] == 1 and doc.reading["tables_joined"] == 1
    # the box is the first page's part, so the picture of the table is a crop of one page
    assert tables[0].bbox[3] < 842
    four = _read(c.path, 4)
    assert sum(1 for b in four.blocks if b.kind == "table") != 1 or len(
        [b for b in four.blocks if b.kind == "table"][0].rows) < 41


@needs_pdfminer
def test_a_table_over_three_pages_is_one_and_one_with_other_columns_is_not_joined(tmp_path):
    header = ["No.", "Plot", "Count"]
    rows = [[str(n), f"Plot {n % 7}", str(10 + n)] for n in range(1, 60)]
    xs = [100.0, 160.0, 300.0, 400.0]
    pages = [pdfmake.Page() for _ in range(3)]
    for k, pg in enumerate(pages):
        pg.text(f"Page {k + 1} of the survey notes", 72, 806, "Helvetica", 8)
    pages[0].text("The counts by plot are set out in the table that follows and runs over the pages.", 72, 700,
                  "Times-Roman", 10)
    _grid(pages[0], xs, 300, [header] + rows[:8])                     # the foot of page 1
    _grid(pages[1], xs, 770, [header] + rows[8:48])                   # all of page 2
    _grid(pages[2], xs, 770, [header] + rows[48:])                    # the head of page 3
    path = tmp_path / "three.pdf"
    pdfmake.write(pages, path)
    doc = _read(path, 5)
    (t,) = [b for b in doc.blocks if b.kind == "table"]
    assert t.rows[0] == header and len(t.rows) == 1 + len(rows) and t.rows[-1] == rows[-1]
    # the same table with four columns on the second page is another table
    pages[1] = pdfmake.Page()
    _grid(pages[1], [100.0, 160.0, 250.0, 330.0, 400.0], 770, [header + ["Note"]] + [r + ["x"] for r in rows[8:20]])
    pages[2] = pdfmake.Page()
    pdfmake.write(pages, tmp_path / "wider.pdf")
    other = _read(tmp_path / "wider.pdf", 5)
    assert len([b for b in other.blocks if b.kind == "table"]) == 2


@needs_pdfminer
def test_a_box_round_a_paragraph_is_not_a_table(tmp_path):
    fl = pdfmake.Flow(columns=[(72, 400)])
    fl.heading("A framed note", 14)
    fl.paragraph("The first paragraph of the note is set in the ordinary way, with nothing round it, and it runs to a "
                 "few lines so that the page looks like a page of a report.")
    top = fl._y + 12
    fl.paragraph("The framed paragraph says that the figures in this note are provisional, that they were counted by "
                 "volunteers, and that a final count will be published when the season ends and the plots are closed.")
    fl.page.box(66, fl._y + 4, 412, top - fl._y - 4)
    fl.paragraph("The last paragraph goes on after the frame with the discussion of what the counts may mean.")
    path = tmp_path / "frame.pdf"
    fl.write(path)
    doc = _read(path, 5)
    assert not any(b.kind in ("table", "figure") for b in doc.blocks)
    assert "provisional" in measure.body_text(doc)


# ------------------------------------------------------------------------------------------------------------------
# figures
# ------------------------------------------------------------------------------------------------------------------
@needs_pdfminer
def test_a_chart_and_a_picture_are_figure_blocks_with_their_box_words_and_caption(known5):
    c = known5["j_figures"]
    doc = _read(c.path, 5)
    figs = [b for b in doc.blocks if b.kind == "figure"]
    assert len(figs) == 2 and doc.reading["figures"] == 2
    chart, picture = figs
    assert chart.page == 0 and picture.page == 1
    for label in ("Plot North", "Plot West", "Mean nests found", "60"):
        assert label in chart.text
    assert chart.caption == "Figure 1. Mean count of nests on each plot, over the three years of the survey."
    assert picture.caption.startswith("Figure 2. The edge of the northern plots")
    # the chart's box holds its bars and its labels; the picture's box is the picture
    x0, y0, x1, y1 = chart.bbox
    assert 100 < x0 < 140 and x1 > 380 and y1 - y0 > 120
    assert picture.bbox == pytest.approx((140, 72, 290, 172), abs=1)
    # words inside are left out of passages, the captions stay in
    body = measure.body_text(doc)
    assert "Plot North" not in body and "Figure 1. Mean count" in body and "Figure 2. The edge" in body
    assert [b.included for b in doc.blocks if b.kind == "caption"] == [True, True, True]
    assert all(p.section == "left_out" for p in doc.passages if p.block == "figure")
    # the figure stands between the paragraph before it and its caption
    kinds = [b.kind for b in doc.blocks if b.page == 0]
    assert kinds.index("figure") + 1 == kinds.index("caption", kinds.index("figure"))


@needs_pdfminer
def test_a_figure_without_words_is_a_block_of_no_text_that_no_passage_covers(known5):
    doc = _read(known5["j_figures"].path, 5)
    picture = [b for b in doc.blocks if b.kind == "figure"][1]
    assert picture.text == "" and picture.start == picture.end
    assert not any(p.start < picture.end <= p.end and p.start != p.end for p in doc.passages if picture.text)
    assert all(p.end > p.start for p in doc.passages)
    assert all(doc.text[p.start:p.end].strip() for p in doc.passages)


@needs_pdfminer
def test_logos_icons_and_scans_are_not_figures_but_a_picture_among_them_is(tmp_path):
    pixels = bytes(range(64))
    pages = []
    for k in range(3):
        fl = pdfmake.Flow(columns=[(72, 451)], running_head="Heathland Survey")
        _sentence_lines(fl, 4, "beta")
        pg = fl.pages[0]
        pg.image(450, 770, 90, 50, pixels, 8, 8)      # a logo in the head of every page
        pg.image(100, 300, 20, 20, pixels, 8, 8)      # an icon
        pages.append(pg)
    pages[1].image(120, 300, 160, 110, pixels, 8, 8)  # one picture
    path = tmp_path / "logos.pdf"
    pdfmake.write(pages, path)
    doc = _read(path, 5)
    figs = [b for b in doc.blocks if b.kind == "figure"]
    assert [b.page for b in figs] == [1]
    scan = pdfmake.Page()
    scan.image(0, 0, 595, 842, pixels, 8, 8)
    pdfmake.write([scan], tmp_path / "scan.pdf")
    assert not any(b.kind == "figure" for b in _read(tmp_path / "scan.pdf", 5).blocks)


@needs_pdfminer
def test_a_figure_stands_in_its_column_between_the_paragraphs_of_that_column(tmp_path):
    fl = pdfmake.Flow(columns=[(60, 225), (310, 225)])
    marks = []
    for k in range(5):
        fl.paragraph(" ".join(f"left{k}word{i}" for i in range(60)), indent=0)
        marks.append(f"left{k}word0")
        if k == 1:
            fl.gap(6)
            base = fl._y - 90
            pg = fl.page
            pg.rule(100, base, 260, base, 0.8)
            pg.rule(100, base, 100, base + 80, 0.8)
            for j in range(5):
                pg.box(112 + 28 * j, base, 18, 15 + 12 * j, 0.5)
                pg.text(f"k{j}", 114 + 28 * j, base - 9, "Helvetica", 7)
            fl._y = base - 24
    path = tmp_path / "columns.pdf"
    fl.write(path)
    doc = _read(path, 5)
    assert not any(b.kind == "table" for b in doc.blocks)
    kinds = [(b.kind, b.text[:9]) for b in doc.blocks]
    fig_at = next(i for i, (k, _t) in enumerate(kinds) if k == "figure")
    left1 = max(i for i, (_k, t) in enumerate(kinds) if t == "left1word")
    assert fig_at == left1 + 1, kinds


@needs_pdfminer
def test_text_beside_a_figure_is_not_swallowed_by_it(known5):
    c = known5["j_figures"]
    doc = _read(c.path, 5)
    f = measure.figures(measure.body_text(doc), c.body, c.boilerplate)
    assert f["recall"] == 1.0 and f["precision"] == 1.0 and f["boilerplate_left"] == 0


@needs_pdfminer
def test_without_pdfminer_a_pdf_still_reads_and_has_no_tables_or_figures(known5, monkeypatch):
    monkeypatch.setattr(reader, "pdfminer_available", lambda: False)
    for name in ("g_ruled_table", "j_figures"):
        doc = _read(known5[name].path, 5)
        assert not any(b.kind in ("table", "figure") and b.box is not None for b in doc.blocks) and doc.text


# ------------------------------------------------------------------------------------------------------------------
# Word files and web pages
# ------------------------------------------------------------------------------------------------------------------
def test_a_word_file_and_a_web_page_keep_an_images_alternative_text_as_a_figure_block(tmp_path):
    for make in (docx_with_image, html_with_image):
        path = make(tmp_path)
        doc = _read(path, 5)
        figs = [b for b in doc.blocks if b.kind == "figure"]
        assert [b.text for b in figs] == [ALT] and figs[0].caption == "Figure 1. Nests found on each plot."
        assert doc.reading["figures"] == 1
        assert ALT not in measure.body_text(doc) and "Figure 1. Nests found" in measure.body_text(doc)
        older = _read(path, 4)
        assert ALT not in older.text and not any(b.kind == "figure" for b in older.blocks)
    raw = ingest.read_file(tmp_path / "image.docx")
    assert ALT in raw.pages[0] and ALT not in raw.as_read_by(4).pages[0] and ALT not in raw.as_read_by(3).pages[0]


def test_a_picture_without_alternative_text_adds_nothing(tmp_path):
    path = tmp_path / "plain.html"
    path.write_text(f"<html><body><p>{INTRO}</p><img src=\"a.png\"><img src=\"b.png\" alt=\"\"><p>{OUTRO}</p></body></html>",
                    encoding="utf-8")
    assert _read(path, 5).text == _read(path, 4).text


# ------------------------------------------------------------------------------------------------------------------
# in a project, and the picture
# ------------------------------------------------------------------------------------------------------------------
@needs_pdfminer
def test_figures_are_stored_as_blocks_and_their_picture_is_drawn_when_asked_for(api, known5, tmp_path):
    from enlens_claims.gui.server import page_images_available

    docs = _project(api, tmp_path, [known5["j_figures"].path, known5["i_table_over_a_page"].path])
    d = docs["Counting Ground Nests on Four Heathland Plots"]
    assert d["reader"] == 5
    st, v = api("GET", f"/api/projects/R/documents/{d['doc_id']}?view=blocks&limit=500")
    assert st == 200 and v["reading"]["figures"] == 2
    figs = [b for b in v["blocks"] if b["kind"] == "figure"]
    assert len(figs) == 2 and all(b["included"] is False and len(b["box"]) == 4 and b["page"] for b in figs)
    assert figs[1]["text"] == "" and figs[1]["start"] == figs[1]["end"]
    assert [b["text"] for b in v["blocks"] if b["kind"] == "caption"][1].startswith("Figure 1. Mean count")
    # nothing of the picture is stored: a row of numbers, no image
    ws_blocks = [r for r in api("GET", f"/api/projects/R/documents/{d['doc_id']}?view=blocks&limit=500")[1]["blocks"]]
    assert ws_blocks and not any("png" in str(b).lower() for b in ws_blocks)
    if not page_images_available():
        return
    n1, n2 = figs[0]["n"], figs[1]["n"]
    st, png = api("GET", f"/api/projects/R/documents/{d['doc_id']}/figures/{n1}.png")
    assert st == 200 and png[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image

    w, h = Image.open(io.BytesIO(png)).size
    x0, y0, x1, y1 = figs[0]["box"]
    assert w == pytest.approx((x1 - x0 + 8) * 2, abs=4) and h == pytest.approx((y1 - y0 + 8) * 2, abs=4)
    st, small = api("GET", f"/api/projects/R/documents/{d['doc_id']}/figures/{n2}.png?scale=0.5")
    assert st == 200 and Image.open(io.BytesIO(small)).size[0] < w
    # the token may ride in the address, as for the picture of a page (an <img> cannot send a header)
    st, again = api("GET", f"/api/projects/R/documents/{d['doc_id']}/figures/{n1}.png?token={api.token}", token=False)
    assert st == 200 and again == png
    # a block that is not a figure or a table has no picture; neither has a block that is not there
    body_n = next(b["n"] for b in v["blocks"] if b["kind"] == "body")
    assert api("GET", f"/api/projects/R/documents/{d['doc_id']}/figures/{body_n}.png")[0] == 404
    assert api("GET", f"/api/projects/R/documents/{d['doc_id']}/figures/999.png")[0] == 404
    assert api("GET", f"/api/projects/R/documents/{d['doc_id']}/figures/x.png")[0] == 404
    # a table found from its rules can be drawn too
    t = docs["Forty Years of Rain at One Waterworks"]
    st, tv = api("GET", f"/api/projects/R/documents/{t['doc_id']}?view=blocks&limit=500")
    tn = next(b["n"] for b in tv["blocks"] if b["kind"] == "table")
    assert api("GET", f"/api/projects/R/documents/{t['doc_id']}/figures/{tn}.png")[0] == 200
    # Leave out and Restore on a figure without words work (there is no passage to change)
    for included in (True, False):
        assert api("PUT", f"/api/projects/R/documents/{d['doc_id']}/blocks/{n2}", {"included": included})[0] == 200


# ------------------------------------------------------------------------------------------------------------------
# measured
# ------------------------------------------------------------------------------------------------------------------
@needs_pdfminer
def test_the_new_known_texts_are_made_the_same_way_every_time(known5, tmp_path):
    again = measure.make_table_figure_texts(tmp_path)
    assert [c.name for c in again] == list(known5)
    for c in again:
        assert c.path.read_bytes() == known5[c.name].path.read_bytes() and c.body == known5[c.name].body


@needs_pdfminer
def test_reader_5_reads_the_new_known_texts_better_than_reader_4_and_the_old_ones_as_well(tmp_path):
    res = measure.run(readers=[4, 5], work=tmp_path / "w")
    assert list(res["known"]) == ["a_one_column", "b_two_columns", "c_line_numbers", "d_front_and_back_matter",
                                  "e_table", "f_footnotes", "g_ruled_table", "h_booktabs_table",
                                  "i_table_over_a_page", "j_figures"]
    better = 0
    for name, row in res["known"].items():
        four, five = row["readers"]["4"], row["readers"]["5"]
        for k in ("recall", "precision", "order"):
            assert five[k] >= four[k] - 1e-9, (name, k, four, five)
        for k in ("run_together", "broken", "boilerplate_left"):
            assert five[k] <= four[k], (name, k, four, five)
        better += (five["precision"], -five["boilerplate_left"]) > (four["precision"], -four["boilerplate_left"])
        if row.get("tables") is not None:
            assert five["tables_found"] == row["tables"] and five["figures_found"] == row["figures"], (name, five)
    assert better >= 3     # the grid table, the table over a page, the figures
    assert all(all(d.values()) for d in res["determinism"].values())
    md = measure.to_markdown(res)
    assert "### Tables and figures found" in md and "Ten small documents" in md


def test_the_reading_test_of_the_earlier_readers_still_has_its_six_documents(tmp_path):
    res = measure.run(readers=[1, 2, 3, 4], work=tmp_path / "w")
    assert len(res["known"]) == 6

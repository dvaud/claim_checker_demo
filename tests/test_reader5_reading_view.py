"""0.18.1 (reader 5): the reading view shows a figure's picture in the text, where it stands, with its caption and the
way to its page; reader 5 is offered where it can change the reading (not to a reader-4 text file)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from _fakedom import NODE
from test_reader import _project
from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import measure, reader

VIEWS = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static" / "views"
needs_pdfminer = pytest.mark.skipif(not reader.pdfminer_available(), reason="the pdfminer extra is not installed")


def _src(*files: str) -> str:
    """The text of these view files (0.18.4 split sources.js: the list, the document page and its parts)."""
    return "\n".join((VIEWS / f).read_text(encoding="utf-8") for f in files)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_reader_5_is_offered_where_it_can_change_the_reading(tmp_path):
    m = re.search(r"^export function newReaderFor\(d, latest\) \{.*?^\}", _src("doc-shared.js"), re.S | re.M)
    assert m, "newReaderFor is gone from doc-shared.js"
    docs = [{"reader": r, "kind": k} for r in (1, 2, 3, 4, 5) for k in ("pdf", "html", "text", "docx")]
    probe = tmp_path / "probe.mjs"
    probe.write_text(m.group(0) + f"\nconsole.log(JSON.stringify({json.dumps(docs)}.map((d) => newReaderFor(d, 5))));\n",
                     encoding="utf-8")
    r = subprocess.run([NODE, str(probe)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    offered = {(d["reader"], d["kind"]) for d, yes in zip(docs, json.loads(r.stdout)) if yes}
    every = {(r, k) for r in (1, 2, 3) for k in ("pdf", "html", "text", "docx")}  # reader 3 text: offered 4 and 5
    assert offered == every | {(4, "pdf"), (4, "html"), (4, "docx")}  # a reader-4 text file reads the same by reader 5
    assert re.search(r"^export const reader = \{ latest: 5 \};", _src("doc-shared.js"), re.M)


def test_a_figure_is_shown_in_the_text_with_its_caption_and_its_page():
    src = _src("doc-page.js", "doc-leave-out.js", "doc-reading.js")
    # shown, not folded: in place(), the fold of the left-out blocks while changing them, and the greying
    # (reader 5 only: an earlier reader's figure block is the words inside a figure, folded with its Restore)
    assert "const shownFigure = (b) => reading && (d.reader || 1) >= 5 && b.kind === \"figure\" && !!b.box && !!d.page_images" in src
    assert 'b.included === false && b.kind !== "table" && !shownFigure(b)) {' in src           # place()
    assert 'const folds = (b) => b.included === false && b.kind !== "table" && !shownFigure(b);' in src
    assert 'b.kind !== "table" && !shownFigure(b);' in src                                     # greyNow
    body = src[src.index("function figureBody(b, decos) {"):src.index("function figureGone(b) {")]
    assert 'loading: "lazy", decoding: "async"' in body
    assert "/figures/${b.n}.png?scale=1.5&token=${encodeURIComponent(TOKEN)}" in body
    assert "alt: cap ? cap.text : `Figure on page ${b.page}`" in body
    assert 'h("figcaption"' in body and '"Open the page"' in body and 'link({ kind: "jump"' in body
    assert '"Words in the figure"' in body and "fold({ sm: true }" in body
    # the caption: the block just after it, else just before it
    cap = src[src.index("function captionOf(b) {"):src.index("function figureBody(b, decos) {")]
    assert "[i + 1, i - 1]" in cap and '"caption"' in cap
    # a picture that cannot be drawn: folded as before, silently (no toast, no error)
    gone = src[src.index("function figureGone(b) {"):src.index("function openPageAt(page) {")]
    assert "figureFailed.add(b.n)" in gone and "dv-fold" in gone and "toast" not in gone and "showError" not in gone
    assert 'img.addEventListener("error", () => figureGone(b))' in body
    # the Page panel opens at the figure's page; nothing to leave out or restore on a figure
    assert "goTo: (p) => go(p, false)" in src and "panels.page.goTo(page)" in src
    acts = src[src.index("function blockActions(b) {"):]
    assert acts.index('if (b.kind === "figure" && (d.reader || 1) >= 5) return null;') < acts.index("Leave out")


def test_the_news_of_reader_5_is_said_to_documents_of_reader_4():
    src = _src("sources.js", "doc-reading.js", "doc-shared.js")
    assert "const READER_5_NEWS = " in src and "shows figures and pictures with their captions" in src
    assert ": READER_5_NEWS)" in src and "`Read by the reader of ENLENS 0.17.2 to 0.18.0. ${READER_5_NEWS}`" in src
    assert "`Read by the reader of ENLENS 0.15.1 to 0.17.1. ${READER_4_NEWS}`" in src  # reader 3 keeps its sentence


@needs_pdfminer
def test_a_figure_of_reader_5_has_its_box_and_its_picture(api, tmp_path):  # noqa: F811
    from enlens_claims.gui.api_common import page_images_available

    case = next(c for c in measure.make_table_figure_texts(tmp_path / "known") if c.name == "j_figures")
    docs = _project(api, tmp_path, [case.path])
    d = next(iter(docs.values()))
    assert d["reader"] == 5
    st, v = api("GET", f"/api/projects/R/documents/{d['doc_id']}?view=blocks&limit=500")
    assert st == 200
    figs = [b for b in v["blocks"] if b["kind"] == "figure"]
    assert figs and all(b["box"] and len(b["box"]) == 4 for b in figs)
    if not page_images_available():
        return
    assert v.get("page_images") or d.get("page_images")  # what the page asks before showing a picture
    st, png = api("GET", f"/api/projects/R/documents/{d['doc_id']}/figures/{figs[0]['n']}.png?scale=1.5&token={api.token}",
                  token=False)
    assert st == 200 and png[:8] == b"\x89PNG\r\n\x1a\n"

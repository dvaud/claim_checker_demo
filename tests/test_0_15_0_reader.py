"""0.15: the new reader (reader 2, reader.py) and the reading view.

- text repair: ligatures, odd and zero-width spaces, accents set apart, soft hyphens; words cut at a line end are
  joined, compounds keep their hyphen ("long-term", "non-fiction", "COVID-19"); words that ran together are split
  only when the document writes them apart;
- the known-text PDFs of `enlens measure`: every word of the body in order, nothing of the running heads, page and
  line numbers, front and back matter, tables and footnotes in what features read;
- two columns are read column by column; running heads are told from a page that repeats another;
- a table is kept as rows and cells with its caption, and left out of the passages;
- passages never mix what features read with what they leave out; reading is the same twice; without pdfminer the
  text layer is read (no columns, no tables) and nothing breaks;
- paragraphs are numbered as quotes are cited: every block in a file without pages, a heading with its text in a PDF;
- the project stores blocks, tables, the reading report and a block kind on each passage;
- the reading view: blocks by kind, Restore and Leave out (kept by the block's text, applied again), a table for
  Excel, a picture of the page, and how well each document read in the list of documents.
"""
from __future__ import annotations

import io
import json
from collections import Counter

import pytest

from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import ingest, measure, pdfmake, reader
from enlens_claims.store import Workspace

needs_pdfminer = pytest.mark.skipif(not reader.pdfminer_available(), reason="the pdfminer extra is not installed")


# --- text repair -----------------------------------------------------------------------------------------------------
def test_ligatures_spaces_and_accents_are_put_right():
    c = Counter()
    assert reader.repair("eﬃcient ﬁsh and​more caf´e", c) == "efficient fish andmore café"
    assert c["ligatures"] == 2 and c["spaces"] == 2 and c["accents"] == 1


def test_line_end_hyphens_join_words_and_keep_compounds():
    vocab = Counter({"example": 0, "term": 3, "long": 2})
    c = Counter()
    assert reader.join_lines(["an exam-", "ple of it"], vocab, c) == "an example of it"
    assert reader.join_lines(["the long-", "term view"], vocab, c) == "the long-term view"
    assert reader.join_lines(["read non-", "fiction"], vocab, c) == "read non-fiction"
    assert reader.join_lines(["the for-", "mation of"], vocab, c) == "the formation of"
    assert reader.join_lines(["the COVID-", "19 crisis"], vocab, c) == "the COVID-19 crisis"
    assert reader.join_lines(["a re­", "search"], vocab, c) == "a research"
    assert reader.join_lines(["some-", "times it"], vocab, c) == "sometimes it"   # English writes it as one word
    assert c["hyphens_joined"] == 4 and c["hyphens_kept"] == 2


def test_words_that_ran_together_are_split_only_where_the_document_writes_them_apart():
    lines = [reader.Line(0, t) for t in ["the use of the water", "of the plant and of the river", "ofthe river"]]
    vocab, bigrams, c = reader._vocabulary(lines), reader._bigrams(lines), Counter()
    assert reader.split_run_together("ofthe river", vocab, bigrams, c) == "of the river"
    assert reader.split_run_together("another income", vocab, bigrams, c) == "another income"
    assert c["words_split"] == 1


# --- the known texts -------------------------------------------------------------------------------------------------
@needs_pdfminer
def test_the_known_texts_are_read_whole_in_order_and_without_boilerplate(tmp_path):
    for case in measure.make_known_texts(tmp_path):
        doc = ingest.read_document(case.path, reader=2)
        f = measure.figures(measure.body_text(doc), case.body, case.boilerplate)
        assert f["recall"] >= 0.99 and f["order"] >= 0.99, (case.name, f)
        assert f["boilerplate_left"] == 0, (case.name, f)
        old = measure.figures(measure.body_text(ingest.read_document(case.path, reader=1)), case.body, case.boilerplate)
        assert f["precision"] >= old["precision"], case.name


@needs_pdfminer
def test_two_columns_are_read_column_by_column_under_a_full_width_abstract(tmp_path):
    case = next(c for c in measure.make_known_texts(tmp_path) if c.name.startswith("b_"))
    doc = ingest.read_document(case.path, reader=2)
    assert doc.reading["multi_column_pages"] >= 1
    kinds = [b.kind for b in doc.blocks]
    assert kinds[:3] == ["furniture", "title", "heading"] and "abstract" in kinds
    body = measure.body_text(doc)
    # the left column ends mid-sentence and the right column goes on with it
    assert "typed the sequence faster and with fewer errors" in " ".join(body.split())


@needs_pdfminer
def test_a_table_is_kept_as_rows_and_cells_with_its_caption_and_left_out(tmp_path):
    case = next(c for c in measure.make_known_texts(tmp_path) if c.name.startswith("e_"))
    doc = ingest.read_document(case.path, reader=2)
    tables = [b for b in doc.blocks if b.kind == "table"]
    assert len(tables) == 1 and tables[0].caption.startswith("Table 1.")
    rows = tables[0].rows
    assert rows[0][0] == "Branch" and len(rows) >= 4 and all(len(r) == len(rows[0]) for r in rows)
    in_table = [p for p in doc.passages if p.start >= tables[0].start and p.end <= tables[0].end]
    assert in_table and all(p.section == "left_out" and p.block == "table" for p in in_table)
    assert any(b.kind == "caption" and b.included for b in doc.blocks)


@needs_pdfminer
def test_passages_never_mix_what_is_read_with_what_is_left_out(tmp_path):
    for case in measure.make_known_texts(tmp_path):
        doc = ingest.read_document(case.path, reader=2)
        for p in doc.passages:
            kinds = {b.included for b in doc.blocks if b.start < p.end and b.end > p.start}
            assert len(kinds) == 1, (case.name, doc.text[p.start:p.end][:80])
            assert (p.section in ("left_out", "references")) == (not kinds.pop())


@needs_pdfminer
def test_reading_is_the_same_twice(tmp_path):
    for case in measure.make_known_texts(tmp_path):
        a, b = ingest.read_document(case.path, reader=2), ingest.read_document(case.path, reader=2)
        assert a.text == b.text and [(p.start, p.end, p.section) for p in a.passages] == \
               [(p.start, p.end, p.section) for p in b.passages]


@needs_pdfminer
def test_a_page_that_repeats_another_is_not_taken_for_running_heads(tmp_path):
    page = "Green hydrogen production needs water. In arid regions it competes with farming for water. " * 4
    fl = pdfmake.Flow(running_head="Hydrogen Notes", page_numbers=True)
    for _ in range(2):
        fl.paragraph(page)
        fl.new_page()
    fl.paragraph(page)
    path = tmp_path / "same.pdf"
    fl.write(path)
    doc = ingest.read_document(path, reader=2)
    furn = [b.text for b in doc.blocks if b.kind == "furniture"]
    assert "Hydrogen Notes" in furn and all("water" not in t for t in furn)
    assert measure.body_text(doc).count("competes with farming") == 12


def test_without_pdfminer_the_text_layer_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, "pdfminer_available", lambda: False)
    case = next(c for c in measure.make_known_texts(tmp_path) if c.name.startswith("a_"))
    doc = ingest.read_document(case.path, reader=2)
    assert doc.reading["engine"] == "pypdf" and doc.reading["tables"] == 0
    f = measure.figures(measure.body_text(doc), case.body, case.boilerplate)
    assert f["recall"] >= 0.98


# --- paragraphs and headings ------------------------------------------------------------------------------------------
def test_paragraphs_are_numbered_as_quotes_are_cited(tmp_path):
    from helpers import make_pdf

    (tmp_path / "s.txt").write_text("Rivermouth survey, 2024\n\nMethods. We asked workers.\n\nFindings. It fell.")
    doc = ingest.read_document(tmp_path / "s.txt")
    starts = [doc.text[s0:s0 + 9] for _pg, s0 in doc.layout.paragraphs]
    assert starts == ["Rivermout", "Methods. ", "Findings."]          # every block of a text file
    make_pdf(tmp_path / "p.pdf", ["Wellbeing study of hybrid workers in the panel\n\nAbstract. Hybrid workers were "
                                  "happier than office workers.\n\nResults\nLoneliness rose among young remote workers."
                                  " It did not rise among hybrid workers.", "Second page. The effect was largest."])
    doc = ingest.read_document(tmp_path / "p.pdf")
    assert [(pg, doc.text[s0:s0 + 9]) for pg, s0 in doc.layout.paragraphs] == [
        (1, "Wellbeing"), (1, "Abstract."), (1, "Results\nL"), (2, "Second pa")]   # "Results" goes with its text
    assert [t for _a, _b, t in doc.layout.headings] == ["Results"]
    md = tmp_path / "m.md"
    md.write_text("# Findings\n\nHomes use more heat.\n\n## Method\n\nA survey.\n")
    doc = ingest.read_document(md)
    assert [t for _a, _b, t in doc.layout.headings] == ["Findings", "Method"]


# --- stored in the project -----------------------------------------------------------------------------------------
@needs_pdfminer
def test_the_project_stores_blocks_tables_the_report_and_block_kinds(tmp_path):
    cases = measure.make_known_texts(tmp_path / "k")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [c.path for c in cases])
    assert ws.scalar("SELECT COUNT(*) FROM documents WHERE reader=?", (ingest.READER,)) == len(cases)
    assert ws.scalar("SELECT COUNT(*) FROM passages WHERE block IS NULL") == 0
    assert ws.scalar("SELECT COUNT(*) FROM doc_tables") == 1
    rep = json.loads(ws.scalar("SELECT reading_json FROM documents WHERE title LIKE 'Who Borrows%'"))
    assert rep["reader"] == ingest.READER and rep["tables"] == 1 and rep["quality"] == "good"
    # a block's passages follow its inclusion
    for r in ws.query("SELECT doc_id, start, end, included FROM blocks"):
        secs = {x[0] for x in ws.query("SELECT section FROM passages WHERE doc_id=? AND start>=? AND end<=?",
                                       (r["doc_id"], r["start"], r["end"]))}
        if r["included"]:
            assert not secs & {"left_out"}
        else:
            assert secs <= {"left_out", "references"}
    d = ws.scalar("SELECT doc_id FROM documents LIMIT 1")
    ws.remove_document(d)
    assert not ws.scalar("SELECT COUNT(*) FROM blocks WHERE doc_id=?", (d,))


def test_a_persons_choice_holds_when_the_document_is_stored_again(tmp_path):
    (tmp_path / "a.txt").write_text("Annual report 2024\n\n" + "Hydrogen demand rose in the north. " * 6 +
                                    "\n\nCopyright 2024 the authors, all rights reserved here.")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [tmp_path / "a.txt"])
    doc_id = ws.scalar("SELECT doc_id FROM documents")
    text = ws.scalar("SELECT text FROM documents")
    n, a, z = next(tuple(r) for r in ws.query("SELECT n, start, end FROM blocks WHERE doc_id=?", (doc_id,))
                   if "Copyright" in text[r[1]:r[2]])
    with ws.connect() as cx:
        cx.execute("INSERT INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES (?,?,0,'body','me','x')",
                   (doc_id, reader.block_fp(text[a:z])))
        reader.apply_choices(cx, doc_id)
    assert ws.scalar("SELECT included FROM blocks WHERE doc_id=? AND n=?", (doc_id, n)) == 0
    sec = ws.scalar("SELECT section FROM passages WHERE doc_id=? AND start<=? AND end>=?", (doc_id, a, z))
    assert sec == "left_out"
    # stored again (as reading it anew does): the choice is found by the block's words and applied again
    with ws.connect() as cx:
        for t in ("blocks", "doc_tables", "passages"):
            cx.execute(f"DELETE FROM {t} WHERE doc_id=?", (doc_id,))
        doc = ingest.read_document(tmp_path / "a.txt")
        cx.executemany("INSERT INTO passages(passage_id, doc_id, seq, page, start, end, text, section, block) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", [(f"{doc_id}:{p.seq:04d}", doc_id, p.seq, p.page, p.start, p.end,
                                                       doc.text[p.start:p.end], p.section, p.block)
                                                      for p in doc.passages])
        doc.doc_id = doc_id
        ingest.store_blocks(cx, doc)
    assert ws.scalar("SELECT included FROM blocks WHERE doc_id=? AND n=?", (doc_id, n)) == 0


# --- the reading view ----------------------------------------------------------------------------------------------
def _project(api, tmp_path, files):
    api("PUT", "/api/settings", {"backend": "baseline"})
    api("POST", "/api/projects", {"name": "R"})
    for f in files:
        api("POST", f"/api/projects/R/uploads?batch=b1&name={f.name}", raw=f.read_bytes())
    api.wait(api("POST", "/api/projects/R/ingest", {"batch": "b1"})[1]["job"]["id"])
    return {d["title"]: d for d in api("GET", "/api/projects/R/documents")[1]["documents"]}


@needs_pdfminer
def test_the_reading_view_restore_and_leave_out(api, tmp_path):
    cases = measure.make_known_texts(tmp_path / "k")
    docs = _project(api, tmp_path, [c.path for c in cases])
    d = docs["What Do Coastal Residents Know about Erosion?"]
    assert d["reading_quality"] == "good" and d["reader"] == ingest.READER
    st, v = api("GET", f"/api/projects/R/documents/{d['doc_id']}?view=blocks&limit=500")
    assert st == 200 and v["reading"]["reader"] == ingest.READER and v["new_reader"] == ingest.READER
    kinds = Counter(b["kind"] for b in v["blocks"])
    assert kinds["front"] and kinds["back"] and kinds["references"] and kinds["furniture"]
    assert all(b["label"] for b in v["blocks"] if not b["included"])         # what each left-out block is
    labelled = [b["label"] for b in v["blocks"] if b["included"] and b["label"]]
    assert labelled[0].startswith("Page 1, paragraph 1")
    back = next(b for b in v["blocks"] if b["kind"] == "back" and "Regional Coastal Futures" in b["text"])
    body_before = api("GET", "/api/projects/R/documents")[1]["documents"]
    st, r = api("PUT", f"/api/projects/R/documents/{d['doc_id']}/blocks/{back['n']}", {"included": True})
    assert st == 200 and r["blocks"] and all(b["included"] and b["changed"] for b in r["blocks"])
    st, v2 = api("GET", f"/api/projects/R/documents/{d['doc_id']}?view=blocks&limit=500")
    assert next(b for b in v2["blocks"] if b["n"] == back["n"])["included"] is True
    after = {x["doc_id"]: x for x in api("GET", "/api/projects/R/documents")[1]["documents"]}
    before = {x["doc_id"]: x for x in body_before}
    assert after[d["doc_id"]]["passages"] > before[d["doc_id"]]["passages"]   # the funding text is read now
    st, r = api("PUT", f"/api/projects/R/documents/{d['doc_id']}/blocks/{back['n']}", {"included": False})
    assert st == 200 and not any(b["changed"] for b in r["blocks"])          # back as the reader had it
    after = {x["doc_id"]: x for x in api("GET", "/api/projects/R/documents")[1]["documents"]}
    assert after[d["doc_id"]]["passages"] == before[d["doc_id"]]["passages"]
    assert api("PUT", f"/api/projects/R/documents/{d['doc_id']}/blocks/9999", {"included": True})[0] == 404
    assert api("PUT", f"/api/projects/R/documents/{d['doc_id']}/blocks/1", {"included": "yes"})[0] == 400


@needs_pdfminer
def test_a_table_downloads_for_excel_and_a_page_as_a_picture(api, tmp_path):
    from openpyxl import load_workbook

    cases = measure.make_known_texts(tmp_path / "k")
    docs = _project(api, tmp_path, [c.path for c in cases])
    d = docs["Who Borrows What? Loans at Four Public Libraries"]
    st, v = api("GET", f"/api/projects/R/documents/{d['doc_id']}?view=blocks&limit=500")
    assert v["tables"] == 1
    t = next(b for b in v["blocks"] if b["kind"] == "table")
    assert t["table"]["rows"][0][0] == "Branch" and t["table"]["caption"].startswith("Table 1.")
    st, body = api("GET", f"/api/projects/R/documents/{d['doc_id']}/tables/1.xlsx")
    assert st == 200
    sh = load_workbook(io.BytesIO(body)).active
    assert sh["A1"].value.startswith("Table 1.") and sh["A4"].value == "Branch" and isinstance(sh["B5"].value, float)
    assert api("GET", f"/api/projects/R/documents/{d['doc_id']}/tables/7.xlsx")[0] == 404
    from enlens_claims.gui.server import page_images_available

    if page_images_available():
        assert v["page_images"] is True
        st, png = api("GET", f"/api/projects/R/documents/{d['doc_id']}/pages/1.png?scale=0.5")
        assert st == 200 and png[:8] == b"\x89PNG\r\n\x1a\n"
        assert api("GET", f"/api/projects/R/documents/{d['doc_id']}/pages/99.png")[0] == 404
    else:
        assert v["page_images"] is False


def test_a_document_read_before_0_15_says_so(api, tmp_path, monkeypatch):
    (tmp_path / "old.txt").write_text("An old reading. " * 30)
    monkeypatch.setattr(ingest, "READER", 1)
    docs = _project(api, tmp_path, [tmp_path / "old.txt"])
    monkeypatch.setattr(ingest, "READER", 2)
    d = next(iter(docs.values()))
    assert d["reader"] == 1 and d["reading_quality"] is None
    st, v = api("GET", f"/api/projects/R/documents/{d['doc_id']}?view=blocks")
    assert v["reader"] == 1 and v["new_reader"] == 2 and v["reading"]["older"] is True
    assert v["blocks"][0]["label"].startswith("Paragraph")          # the reading view of reader 1, as before


@pytest.fixture
def app_api(home):
    """The app's server with its App (to see its jobs), as test_app's `api` fixture makes it."""
    import threading

    from test_app import Api

    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token), app
    srv.shutdown()
    srv.server_close()


@needs_pdfminer
def test_read_with_the_new_reader_from_the_app(app_api, tmp_path, monkeypatch):
    """The preview changes nothing; the move runs as a job (then key terms and keyword codes, as after adding a
    document); a second move is refused in words; a job running in the project holds a move back."""
    api, app = app_api
    case = next(c for c in measure.make_known_texts(tmp_path / "k") if c.name.startswith("d_"))
    monkeypatch.setattr(ingest, "READER", 1)
    docs = _project(api, tmp_path, [case.path])
    monkeypatch.setattr(ingest, "READER", 2)
    d = next(iter(docs.values()))
    base = f"/api/projects/R/documents/{d['doc_id']}"
    st, pre = api("GET", f"{base}/reread")
    assert st == 200 and pre["ok"] is True and pre["new_reader"] == 2 and "counts" in pre and "not_placed" in pre
    assert api("GET", base)[1]["reader"] == 1                       # the preview changed nothing

    class Busy:  # a job of the project still running
        project, state, title = "R", "running", "Adding sources"
    app.jobs.jobs["busy"] = Busy()
    st, body = api("POST", f"{base}/reread")
    assert st == 409 and "Adding sources" in body["error"]
    del app.jobs.jobs["busy"]
    st, body = api("POST", f"{base}/reread")
    assert st == 200 and body["job"]["kind"] == "reread"
    job = api.wait(body["job"]["id"])
    assert job["state"] == "done", job
    assert job["result"]["report"]["moved"] is True and "glossary" in job["result"]
    v = api("GET", f"{base}?view=blocks&limit=500")[1]
    assert v["reader"] == 2 and any(b["kind"] == "front" for b in v["blocks"])
    st, again = api("GET", f"{base}/reread")
    assert again["ok"] is False and again["reason"]
    assert api("POST", f"{base}/reread")[0] == 409
    # removing the document removes the answers kept as records under the old passages' ids too
    from enlens_claims import home as home_mod

    ws = home_mod.open_project("R")
    assert api("DELETE", base)[0] == 200
    assert not ws.scalar("SELECT COUNT(*) FROM tasks WHERE task_id LIKE ?", (f"%{d['doc_id']}:%",))


def test_removing_a_document_removes_its_records_under_old_passage_ids(tmp_path):
    (tmp_path / "a.txt").write_text("Hydrogen demand rose in the north. " * 12)
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [tmp_path / "a.txt"])
    doc = ws.scalar("SELECT doc_id FROM documents")
    with ws.connect() as cx:
        for tid in (f"label:sdg:{doc}:r1-0003", f"extract:{doc}:r1-0001", "label:sdg:dother:0001"):
            cx.execute("INSERT INTO tasks(task_id, kind, status) VALUES (?, 'label', 'done')", (tid,))
            cx.execute("INSERT INTO results(task_id, attempt, kind) VALUES (?, 1, 'label')", (tid,))
    ws.remove_document(doc)
    assert [r[0] for r in ws.query("SELECT task_id FROM tasks")] == ["label:sdg:dother:0001"]
    assert ws.scalar("SELECT COUNT(*) FROM results") == 1

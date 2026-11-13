"""0.15.7: documents read by an earlier reader are moved from the Documents page, and a reading report's warnings can
be looked at and marked as checked.

- `reread.move(..., keep_all=True)` leaves a document as it was when any of its results would find no place;
- `POST /api/projects/<p>/new-reader` moves several documents in one job: the ones whose results all find their place
  move, the others are listed with the reason and keep their reading; with `doc_ids`, only those;
- `PUT …/documents/<id>/reading-checked` marks a reading as checked (and takes it back): the list of documents says
  so, the document's report says who and when, a document read before 0.15 has nothing to mark;
- each warning of a reading report says where to look (the pages, or what was left out);
- on Windows a Claude Code run is recognised by its command line (procs.windows_command_line), not its number alone.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from enlens_claims import ingest, pdfmake, reader, reread
from enlens_claims.store import Workspace

from test_read_with_new_reader import HEAD, Q_WATER, SITES, _add, _check, _dump, _para, _paper  # noqa: F401
from test_app import Api, api, home  # noqa: F401  (fixtures)


def _lost_quote(ws: Workspace) -> str:
    """A quote with reader 1's running head and page number in it: words the new reader does not have in that order."""
    text = ws.scalar("SELECT text FROM documents")
    i = text.index(HEAD, 10)
    bad = text[i + len(HEAD) - 5:i + len(HEAD) + 22].strip()
    return bad[:bad.rfind(" ")]


def test_keep_all_leaves_a_document_with_a_result_that_would_be_lost_as_it_was(tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "ws")
    doc = _add(ws, monkeypatch, _paper(tmp_path))
    _check(ws, [(_lost_quote(ws), "supports"), (Q_WATER, "supports")])
    before = _dump(ws)
    with pytest.raises(reread.WouldLose, match="1 of its results would not find their place") as e:
        reread.move(ws, doc, keep_all=True)
    assert e.value.report["not_placed"] and _dump(ws) == before
    assert ws.scalar("SELECT reader FROM documents") == 1


def _other_paper(folder) -> object:
    """A second paper like `_paper`, with a closing paragraph of its own (the same file twice is one document)."""
    fl = pdfmake.Flow(columns=[(56, 230), (310, 230)], running_head=HEAD, page_numbers=True)
    for i in range(len(SITES)):
        fl.paragraph(_para(i))
    fl.paragraph("A second survey of the same sites, made a year later, found the wells lower again.")
    path = folder / "survey.pdf"
    fl.write(path)
    return path


def _project(home, tmp_path, monkeypatch, lost: bool) -> tuple[str, str, str]:  # noqa: F811
    """A project with two documents read before 0.15: one whose results all find their place, and one with a result
    that would be lost (`lost`) or none."""
    home.create_project("Demo")
    ws = home.open_project("Demo")
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    one = _add(ws, monkeypatch, _paper(a))
    two = _add(ws, monkeypatch, _other_paper(b))
    if lost:
        text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (two,))
        i = text.index(HEAD, 10)
        bad = text[i + len(HEAD) - 5:i + len(HEAD) + 22].strip()
        bad = bad[:bad.rfind(" ")]
        _check(ws, [(Q_WATER, "supports"), (bad, "supports")])  # the first paper's passage comes first for both
    return "Demo", one, two


def test_several_documents_move_from_the_documents_page(api, home, tmp_path, monkeypatch):  # noqa: F811
    name, one, two = _project(home, tmp_path, monkeypatch, lost=True)
    st, lst = api("GET", f"/api/projects/{name}/documents")
    assert st == 200 and lst["new_reader"] == ingest.READER
    assert {d["doc_id"]: d["reader"] for d in lst["documents"]} == {one: 1, two: 1}
    st, r = api("POST", f"/api/projects/{name}/new-reader", {})
    assert st == 200 and r["job"]["kind"] == "new_reader" and "2 documents" in r["job"]["title"]
    job = api.wait(r["job"]["id"], timeout=120)
    assert job["state"] == "done", job
    res = job["result"]
    ws = home.open_project(name)
    readers = dict(ws.query("SELECT doc_id, reader FROM documents"))
    lost = [k for k in res["kept"] if k.get("not_placed")]
    assert len(res["moved"]) + len(res["kept"]) == 2 and len(lost) == 1
    assert readers[lost[0]["doc_id"]] == 1 and "would not find their place" in lost[0]["reason"]
    moved = res["moved"][0]
    assert readers[moved["doc_id"]] == ingest.READER and moved["title"]
    # nothing older is left but the one kept: a second run reads only it, and keeps it as it was again
    st, r = api("POST", f"/api/projects/{name}/new-reader", {})
    assert st == 200 and "1 document " in r["job"]["title"] + " "
    assert api.wait(r["job"]["id"], timeout=120)["result"]["kept"][0]["doc_id"] == lost[0]["doc_id"]


def test_only_the_documents_chosen_move(api, home, tmp_path, monkeypatch):  # noqa: F811
    name, one, two = _project(home, tmp_path, monkeypatch, lost=False)
    st, r = api("POST", f"/api/projects/{name}/new-reader", {"doc_ids": [two, "not-a-document"]})
    assert st == 200
    res = api.wait(r["job"]["id"], timeout=120)["result"]
    assert [m["doc_id"] for m in res["moved"]] == [two] and not res["kept"]
    ws = home.open_project(name)
    assert dict(ws.query("SELECT doc_id, reader FROM documents")) == {one: 1, two: ingest.READER}
    assert api("POST", f"/api/projects/{name}/new-reader", {"doc_ids": "all"})[0] == 400
    assert api("POST", f"/api/projects/{name}/new-reader", {"doc_ids": [two]})[0] == 409  # already on the new reader


def test_a_reading_is_marked_as_checked_and_unmarked(api, home, tmp_path, monkeypatch):  # noqa: F811
    home.create_project("Demo")
    ws = home.open_project("Demo")
    folder = tmp_path / "new"
    folder.mkdir()
    doc = _add(ws, monkeypatch, _other_paper(folder), reader=ingest.READER)
    old = _add(ws, monkeypatch, _paper(tmp_path), reader=1)
    rep = json.loads(ws.scalar("SELECT reading_json FROM documents WHERE doc_id=?", (doc,)))
    rep.update(quality="fair", warnings=["Only 20% of the text counts as the document's own text; the rest was set "
                                         "aside. Look at what was left out in the reading view."])
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET reading_json=? WHERE doc_id=?", (json.dumps(rep), doc))
    row = lambda: next(d for d in api("GET", "/api/projects/Demo/documents")[1]["documents"] if d["doc_id"] == doc)  # noqa: E731
    assert row()["reading_quality"] == "fair" and row()["reading_checked"] is False
    st, view = api("GET", f"/api/projects/Demo/documents/{doc}")
    assert st == 200 and view["reading"]["places"] == ["left_out"] and "checked" not in view["reading"]
    st, r = api("PUT", f"/api/projects/Demo/documents/{doc}/reading-checked", {"checked": True})
    assert st == 200 and r["checked"]["at"] and r["checked"]["by"]
    assert row()["reading_checked"] is True and row()["reading_quality"] == "fair"  # the report itself is unchanged
    assert api("GET", f"/api/projects/Demo/documents/{doc}")[1]["reading"]["checked"] == r["checked"]
    assert "places" not in json.loads(ws.scalar("SELECT reading_json FROM documents WHERE doc_id=?", (doc,)))
    assert api("PUT", f"/api/projects/Demo/documents/{doc}/reading-checked", {"checked": False})[1] == {"checked": None}
    assert row()["reading_checked"] is False
    assert api("PUT", f"/api/projects/Demo/documents/{doc}/reading-checked", {"checked": "yes"})[0] == 400
    st, body = api("PUT", f"/api/projects/Demo/documents/{old}/reading-checked", {"checked": True})
    assert st == 409 and "before 0.15" in body["error"]
    assert api("PUT", "/api/projects/Demo/documents/nothing/reading-checked", {"checked": True})[0] == 404


def test_each_warning_says_where_to_look():
    report = {"pages": 10, "pages_with_text": 6, "scanned_pages": 4, "ocr_pages": 4, "reader": 3, "engine": "pypdf"}
    blocks = [reader.Block(page=1, lines=[], kind="furniture", text="x" * 900, start=0, end=900),
              reader.Block(page=1, lines=[], kind="body", text="y" * 100, start=900, end=1000)]
    out = reader.finish_report(report, blocks, [], "x" * 1000, "pdf")
    places = {w: reader.warning_place(w) for w in out["warnings"]}
    assert any(p == "page" and "scanned" in w for w, p in places.items())
    assert any(p == "page" and "OCR" in w for w, p in places.items())
    assert any(p == "left_out" and "counts as the document's own text" in w for w, p in places.items())
    assert any(p is None and "pdfminer" in w for w, p in places.items())  # advice, with nothing to look at


def test_the_page_offers_the_move_and_the_checked_mark():
    from pathlib import Path

    views = Path(ingest.__file__).parent / "gui" / "static" / "views"
    # the list (sources.js), the Reading panel (doc-reading.js) and what they share (doc-shared.js)
    js = "\n".join((views / f).read_text(encoding="utf-8") for f in ("sources.js", "doc-reading.js", "doc-shared.js"))
    assert '`/api/projects/${P(project)}/new-reader`' in js and "j.kind === \"new_reader\"" in js
    assert "`${docBase}/reading-checked`" in js and "Checked: it reads well enough" in js
    assert 'query.preview === "1"' in js and "&preview=1" in js


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_windows_reads_a_command_line_and_an_ended_process_has_none():
    from enlens_claims.procs import windows_command_line

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "a-marker-word"])
    try:
        assert "a-marker-word" in (windows_command_line(proc.pid) or "")
    finally:
        proc.kill()
        proc.wait()
    assert windows_command_line(proc.pid) is None  # ended, though its handle still holds the number
    assert windows_command_line(2 ** 22 + 12345) is None


# --- 0.15.7: a project's folder can be moved or removed on Windows -------------------------------------------------
def test_close_all_closes_the_connections_of_every_thread_and_they_reopen(tmp_path):
    import sqlite3
    import threading

    ws = Workspace.create(tmp_path / "ws")
    ws.query("SELECT 1")  # this thread's connection
    other = []  # a request's or a job's, still open when its thread ends (until the garbage collector frees it)
    t = threading.Thread(target=lambda: other.append(ws._conn()))
    t.start()
    t.join()
    held = list(ws._all)
    assert len(held) == 2 and other[0] in held
    ws.close_all()
    for cx in held:
        with pytest.raises(sqlite3.ProgrammingError):  # closed
            cx.execute("SELECT 1")
    assert ws.query("SELECT 1")  # this thread goes on with a new connection


def test_a_project_used_by_other_threads_is_moved_to_the_trash(home, tmp_path):  # noqa: F811
    import threading

    home.create_project("Gone")
    ws = home.open_project("Gone")
    t = threading.Thread(target=lambda: ws.query("SELECT COUNT(*) FROM documents"))
    t.start()
    t.join()
    assert "moved to" in home.remove_project("Gone")
    assert "Gone" not in home.list_projects() and not (home.home() / "projects" / "Gone").exists()
    assert len(list((home.home() / "trash").iterdir())) == 1


def test_the_connector_leaves_no_database_open_between_calls(home):  # noqa: F811
    import sqlite3

    home.create_project("Kept")
    ws = home.open_project("Kept")
    ws.query("SELECT 1")
    cx = ws._local.cx
    home.release_open_projects()  # what the connector does after each call on Windows
    with pytest.raises(sqlite3.ProgrammingError):
        cx.execute("SELECT 1")
    assert ws.query("SELECT 1") and home.open_project("Kept") is ws  # reopened on the next use, still kept


@pytest.mark.skipif(os.name != "nt", reason="Windows only: it refuses to move a folder with an open file")
def test_a_folder_with_a_file_held_open_is_not_half_moved(tmp_path):
    from enlens_claims import home as core

    src = tmp_path / "project"
    src.mkdir()
    (src / "a.txt").write_text("a")
    held = open(src / "b.txt", "w")
    try:
        with pytest.raises(core.FolderInUse, match="still open"):
            core.move_folder(src, tmp_path / "trash", tries=2)
        assert (src / "a.txt").exists() and not (tmp_path / "trash").exists()  # everything stayed where it was
    finally:
        held.close()
    core.move_folder(src, tmp_path / "trash")
    assert (tmp_path / "trash" / "a.txt").exists()


def test_the_windows_files_end_their_lines_once(tmp_path, monkeypatch):
    from enlens_claims.gui import launcher

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no PowerShell")))
    monkeypatch.setattr(launcher, "_com_shortcut", lambda *a: False)
    cmd = launcher._windows_shortcut(tmp_path, str(tmp_path / "python.exe"), ["-m", "enlens_claims.gui.launch"])
    raw = cmd.read_bytes()
    assert b"\r\r" not in raw and raw.count(b"\r\n") == raw.count(b"\n") == 4

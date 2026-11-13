"""The deep dive after 0.17.0, adding documents and *Read with the new reader*: a file already in the project is not
read again, a reading process that crashes or is stopped leaves the app as it is, a reading sends back and keeps only
what is stored, and a move does its slow alignment without holding the project's database. What a reader produces and
where a result goes do not change. Each test here failed before its fix."""
from __future__ import annotations

import os
import pickle
import random
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import pytest
from helpers import make_pdf
from test_read_with_new_reader import Q_DESAL, Q_WATER, _add, _check, _paper

from enlens_claims import claimcheck, ingest, pdfmake, reread
from enlens_claims.store import Workspace

OFF = ingest.OcrOptions(mode="off")


def _page(i: int, p: int) -> str:
    topics = ["green hydrogen", "water stress", "the electricity grid", "ammonia exports", "offshore wind",
              "decent work and jobs", "poverty and the poor", "drinking water and sanitation"]
    a, b = topics[(i + p) % len(topics)], topics[(2 * i + p + 3) % len(topics)]
    return (f"Report {i}, page {p}. The study of {a} in region {i * 7 + p} finds that {a} depends on {b}.\n"
            f"A second paragraph, number {p}, says that {b} and {a} return in the plan of {i} with new costs "
            f"of {i * 13 + p} million euros a year, and that the plan needs a long text to count as a passage.")


def _docx(path: Path, text: str, title: str | None = None, padding: int = 0) -> Path:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{para}</w:t></w:r></w:p>' for para in text.split("\n"))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {w}><w:body>{body}</w:body></w:document>')
        if title:
            z.writestr("docProps/core.xml",
                       '<cp:coreProperties xmlns:cp="c" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                       f"<dc:title>{title}</dc:title><!--{' ' * padding}--></cp:coreProperties>")
    return path


def _folder(tmp_path: Path) -> Path:
    d = tmp_path / "batch"
    d.mkdir()
    for i in range(3):
        make_pdf(d / f"paper_{i}.pdf", [_page(i, p) for p in range(3)], title=f"Paper number {i}")
    (d / "note.txt").write_text("\n\n".join(_page(10, p) for p in range(4)) + "\n")
    paras = "".join(f"<p>{_page(11, p)}</p>" for p in range(3))
    (d / "page.html").write_text(f"<html><title>A page</title><body>{paras}</body></html>")
    _docx(d / "word.docx", "\n".join(_page(12, p) for p in range(3)), title="A Word file")
    (d / "broken.docx").write_bytes(b"PK\x03\x04 not a zip file, only its first bytes" * 10)
    return d


def _rows(ws: Workspace) -> dict:
    cols = [r[1] for r in ws.query("PRAGMA table_info(documents)") if r[1] != "added_at"]
    return {"documents": [tuple(r) for r in ws.query(f"SELECT {', '.join(cols)} FROM documents ORDER BY rowid")],
            "passages": [tuple(r) for r in ws.query("SELECT * FROM passages ORDER BY rowid")],
            "blocks": [tuple(r) for r in ws.query("SELECT * FROM blocks ORDER BY rowid")],
            "paragraphs": [tuple(r) for r in ws.query("SELECT * FROM paragraphs ORDER BY rowid")],
            "headings": [tuple(r) for r in ws.query("SELECT * FROM headings ORDER BY rowid")],
            "pages": [tuple(r) for r in ws.query("SELECT * FROM pages ORDER BY rowid")],
            "tables": [tuple(r) for r in ws.query("SELECT * FROM doc_tables ORDER BY rowid")]}


def _worker_code(monkeypatch, patch: str) -> list:
    """Reading processes started with `patch` (Python run in them before they take files): the processes started."""
    started = []
    real = subprocess.Popen

    def popen(args, *a, **kw):
        if isinstance(args, list) and any("enlens_claims.readworker" in str(x) for x in args):
            args = [x.replace("from enlens_claims.readworker import main;", patch + "; from enlens_claims.readworker "
                              "import main;") if isinstance(x, str) else x for x in args]
            p = real(args, *a, **kw)
            started.append(p)
            return p
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return started


# ---- R4: a file already in the project is not parsed again ----------------------------------------------------
@pytest.mark.parametrize("workers", [1, 2])
def test_adding_a_folder_again_reads_none_of_the_files_already_in_the_project(tmp_path, monkeypatch, workers):
    folder = _folder(tmp_path)
    ws = Workspace.create(tmp_path / "ws")
    first = ingest.ingest(ws, [folder], ocr=OFF, workers=workers)
    assert first["added"] == 6 and first["duplicates"] == 0 and len(first["failed"]) == 1
    rows = _rows(ws)
    read, started = [], []
    real_read, real_process = ingest.read_file, ingest._Readings._process
    monkeypatch.setattr(ingest, "read_file", lambda f, *a, **k: read.append(f.name) or real_read(f, *a, **k))
    monkeypatch.setattr(ingest._Readings, "_process", lambda self: started.append(1) or real_process(self))
    again = ingest.ingest(ws, [folder], ocr=OFF, workers=workers)
    assert again["added"] == 0 and again["duplicates"] == 6
    assert again["failed"] == first["failed"]  # a file that could not be read is still tried, and still said
    assert set(read) <= {"broken.docx"}       # the others were parsed again before: every PDF, the Word file...
    if workers > 1:
        assert len(started) <= 1  # only the broken file went to a reading process
    assert _rows(ws) == rows


def test_a_duplicate_found_by_its_checksum_is_what_ingest_needs_of_it(tmp_path, monkeypatch):
    folder = _folder(tmp_path)
    f = folder / "paper_1.pdf"
    raw = ingest.read_file(f, OFF)
    monkeypatch.setattr(ingest, "read_file", lambda *a, **k: pytest.fail("a duplicate was read"))
    got = ingest._read_whole(f, OFF, 1100, 200, None, {raw.sha1})
    assert got[0] == "ok" and got[2] is None and got[1].sha1 == raw.sha1 and got[1].kind == "pdf"


# ---- R10: a reading process that crashes takes only its file with it ------------------------------------------
@pytest.mark.parametrize("how", ["exit", "signal"])
def test_a_file_that_ends_its_reading_process_is_listed_as_unreadable_and_not_read_in_the_app(tmp_path, monkeypatch,
                                                                                                how):
    if how == "signal" and os.name == "nt":
        pytest.skip("no signals on Windows")
    folder = _folder(tmp_path)
    (folder / "crash.txt").write_text("\n\n".join(_page(20, p) for p in range(3)))
    die = "os._exit(3)" if how == "exit" else "os.kill(os.getpid(), 9)"
    started = _worker_code(monkeypatch, "import os; from enlens_claims import ingest as _i; _r = _i._read_whole; "
                                        f"_i._read_whole = lambda f, *a, **k: {die} if f.name == 'crash.txt' "
                                        "else _r(f, *a, **k)")
    here = []
    plain = ingest._Readings.here
    monkeypatch.setattr(ingest._Readings, "here", lambda self, i: here.append(self.files[i].name) or plain(self, i))
    ws = Workspace.create(tmp_path / "ws")
    stats = ingest.ingest(ws, [folder], ocr=OFF, workers=2)
    crashed = [x for x in stats.get("failed", []) if x.startswith("crash.txt: ")]
    assert len(crashed) == 1 and crashed == [f"crash.txt: {ingest.CRASHED}"]
    assert "crash.txt" not in here  # before, the app read it itself: a file that crashes its reader crashed the app
    assert stats["added"] == 6 and stats["read_at_once"] == 2
    names = {Path(r[0]).name for r in ws.query("SELECT path FROM documents")}
    assert "crash.txt" not in names and {"note.txt", "paper_2.pdf", "word.docx"} <= names
    assert len(started) >= 2 and all(p.poll() is not None for p in started)  # the next files went to a new process


def test_a_reading_process_that_ends_on_its_own_still_leaves_the_file_to_be_read_here(tmp_path, monkeypatch):
    folder = _folder(tmp_path)
    (folder / "quits.txt").write_text("\n\n".join(_page(21, p) for p in range(3)))
    _worker_code(monkeypatch, "import os; from enlens_claims import ingest as _i; _r = _i._read_whole; "
                              "_i._read_whole = lambda f, *a, **k: os._exit(0) if f.name == 'quits.txt' "
                              "else _r(f, *a, **k)")
    ws = Workspace.create(tmp_path / "ws")
    stats = ingest.ingest(ws, [folder], ocr=OFF, workers=2)
    assert stats["added"] == 7 and len(stats["failed"]) == 1  # no crash: read here, as before


# ---- R19: Stop does not wait for the file being read ----------------------------------------------------------
def test_stop_ends_a_file_being_read_in_a_process_at_once(tmp_path, monkeypatch):
    folder = _folder(tmp_path)
    (folder / "a_slow.txt").write_text("\n\n".join(_page(22, p) for p in range(3)))
    started = _worker_code(monkeypatch, "import time; from enlens_claims import ingest as _i; _r = _i._read_whole; "
                                        "_i._read_whole = lambda f, *a, **k: time.sleep(30) if f.name == 'a_slow.txt' "
                                        "else _r(f, *a, **k)")
    at: list[float] = []
    ws = Workspace.create(tmp_path / "ws")
    t0 = time.monotonic()
    stats = ingest.ingest(ws, [folder], ocr=OFF, workers=2,
                          progress=lambda i, n, name: at.append(time.monotonic()) if name == "a_slow.txt" else None,
                          should_stop=lambda: bool(at) and time.monotonic() - at[0] > 0.3)
    assert time.monotonic() - t0 < 10  # it waited for the whole file (here 30 s; hours for a long scanned book)
    assert stats["stopped"] is True and stats["added"] == 0
    assert started and all(p.poll() is not None for p in started)


# ---- R14: a reading process sends back what is stored, and the same is stored ---------------------------------
def _columns_pdf(path: Path, n: int) -> Path:
    fl = pdfmake.Flow(columns=[(56, 230), (310, 230)], running_head="Journal of Columns 3 (2026) 1-9",
                      page_numbers=True)
    for i in range(n):
        fl.paragraph(f"Paragraph {i} of the paper says that the plant at site {i} draws {100 + i} cubic metres of "
                     f"water a day, and that farmers near site {i} fear the supply will fall as the plant grows "
                     "each year.")
    fl.write(path)
    return path


def test_a_reading_sends_back_only_what_is_stored_and_stores_the_same_rows(tmp_path, monkeypatch):
    d = tmp_path / "pdfs"
    d.mkdir()
    _columns_pdf(d / "a.pdf", 60)
    _columns_pdf(d / "b.pdf", 30)
    got = ingest._read_whole(d / "a.pdf", OFF, 1100, 200)
    raw = ingest.read_file(d / "a.pdf", OFF)
    full = ("ok", raw, ingest.build_document(raw, 1100, 200))
    assert got[1].pages == [] and got[1].line_pos is None and all(len(b.lines) <= 1 for b in got[2].blocks)
    assert [b.bbox for b in got[2].blocks] == [b.bbox for b in full[2].blocks]
    light, heavy = len(pickle.dumps(got, protocol=5)), len(pickle.dumps(full, protocol=5))
    assert light < 0.6 * heavy, (light, heavy)

    def ingest_in(name: str, **kw) -> dict:
        ws = Workspace.create(tmp_path / name)
        ingest.ingest(ws, [d], ocr=OFF, **kw)
        return _rows(ws)

    lightened_here, at_once = ingest_in("one", workers=1), ingest_in("two", workers=2)
    monkeypatch.setattr(ingest, "_lighten", lambda doc: doc)
    monkeypatch.setattr(ingest, "_lighten_raw", lambda raw: raw)
    whole = ingest_in("whole", workers=1)
    assert whole["blocks"] and any(r[7] is not None for r in whole["blocks"])  # with their boxes
    assert lightened_here == whole and at_once == whole


# ---- R18: a Word file's properties are read within a bound ----------------------------------------------------
def test_a_word_files_properties_are_read_only_when_they_are_of_a_sensible_size(tmp_path):
    text = "\n".join(_page(30, p) for p in range(2))
    small = ingest.read_file(_docx(tmp_path / "small.docx", text, title="Water and hydrogen"), OFF)
    assert small.meta_title == "Water and hydrogen"
    big = ingest.read_file(_docx(tmp_path / "big.docx", text, title="Water and hydrogen",
                                 padding=2 * 1024 ** 2), OFF)
    assert big.meta_title is None and big.pages == small.pages  # the text is read all the same


# ---- R3: the alignment is made without holding the database --------------------------------------------------
@pytest.fixture
def checked(tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "ws")
    doc = _add(ws, monkeypatch, _paper(tmp_path))
    cid, _at = _check(ws, [(Q_WATER, "supports"), (Q_DESAL, "partially_supports")])
    reread._READINGS.clear()
    return ws, doc, cid


def _write_from_elsewhere(ws: Workspace, sql: str, args=()) -> str:
    """A write by another connection that waits half a second at most: "ok" or the error."""
    out = []

    def run():
        cx = sqlite3.connect(ws.db_path, timeout=0.5, isolation_level=None)
        try:
            cx.execute("BEGIN IMMEDIATE")
            cx.execute(sql, args)
            cx.execute("COMMIT")
            out.append("ok")
        except sqlite3.OperationalError as e:
            out.append(str(e))
        finally:
            cx.close()

    t = threading.Thread(target=run)
    t.start()
    t.join()
    return out[0]


def test_moving_a_document_lets_other_work_write_while_its_alignment_is_made(checked, monkeypatch):
    ws, doc, cid = checked
    writes = []
    align = reread._Map._align

    def slow_align(self):
        writes.append(_write_from_elsewhere(ws, "INSERT OR REPLACE INTO meta(key, value) VALUES ('probe', '1')"))
        align(self)

    monkeypatch.setattr(reread._Map, "_align", slow_align)
    rep = reread.move(ws, doc)
    assert writes == ["ok"]  # before: "database is locked" (a 3-million-character document aligned for 80 s)
    assert rep["moved"] and not rep["not_placed"]
    graded = [x for x in claimcheck.result(ws, cid)["passages"] if x["quote"] in (Q_WATER, Q_DESAL)]
    assert len(graded) == 2 and all(x["counted"] for x in graded)


@pytest.mark.parametrize("changes", [1, 2])
def test_a_document_changed_during_its_alignment_is_aligned_again_once(checked, monkeypatch, changes):
    ws, doc, _cid = checked
    calls = []
    align = reread._Map._align

    def changing_align(self):
        calls.append(1)
        if len(calls) <= changes:  # a passage's page changes meanwhile (what the alignment is made from)
            assert _write_from_elsewhere(ws, "UPDATE passages SET page=page+1 WHERE passage_id=?",
                                         (f"{doc}:0001",)) == "ok"
        align(self)

    monkeypatch.setattr(reread._Map, "_align", changing_align)
    if changes == 1:
        assert reread.move(ws, doc)["moved"] and len(calls) == 2
    else:
        with pytest.raises(ValueError, match="changed while it was being read again"):
            reread.move(ws, doc)
        assert len(calls) == 2 and ws.scalar("SELECT reader FROM documents WHERE doc_id=?", (doc,)) == 1


def test_a_move_after_its_preview_aligns_once_and_gives_what_a_move_alone_gives(checked, tmp_path, monkeypatch):
    ws, doc, cid = checked
    ws.close_all()
    shutil.copytree(ws.root, tmp_path / "copy")
    other = Workspace.open(tmp_path / "copy")
    calls = []
    align = reread._Map._align
    monkeypatch.setattr(reread._Map, "_align", lambda self: calls.append(1) or align(self))
    pv = reread.preview(ws, doc)
    rep = reread.move(ws, doc)
    assert len(calls) == 1  # the preview's alignment is used again
    reread._READINGS.clear()
    alone = reread.move(other, doc)
    assert pv == {**rep, "moved": False} and rep == alone

    def rows(w: Workspace) -> list:
        return [tuple(r) for t in ("verifications", "passages", "blocks", "tasks", "labels") for r in
                w.query(f"SELECT * FROM {t} ORDER BY rowid")]

    assert rows(ws) == rows(other)


# ---- R5: a reading kept for later is light, and let go once moved ---------------------------------------------
def test_a_kept_reading_holds_no_lines_and_is_let_go_once_its_document_is_moved(checked):
    ws, doc, _cid = checked
    path = str(Path(ws.scalar("SELECT path FROM documents WHERE doc_id=?", (doc,))).resolve())
    reread.preview(ws, doc)
    (entry,) = [e for k, e in reread._READINGS.items() if k[0] == path]
    kept = entry["doc"]
    assert kept.raw.pages == [] and kept.raw.line_pos is None and all(len(b.lines) <= 1 for b in kept.blocks)
    assert entry["map"] is not None and entry["map"]._f is None  # the alignment, without the normalised text
    reread.move(ws, doc)
    assert not [k for k in reread._READINGS if k[0] == path]


# ---- R11: the tasks are read once for a move's plan, and once for several documents --------------------------
def test_a_move_reads_the_documents_tasks_once_outside_and_once_inside_its_transaction(checked, monkeypatch):
    ws, doc, _cid = checked
    calls = []
    plain = reread._doc_tasks
    monkeypatch.setattr(reread, "_doc_tasks", lambda *a: calls.append(1) or plain(*a))
    reread.move(ws, doc)
    assert len(calls) == 2  # before: three times, two of them holding the database


def test_the_tasks_of_several_documents_are_found_in_one_pass_as_one_by_one(tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "ws")
    with monkeypatch.context() as mp:
        mp.setattr(ingest, "READER", 1)
        ingest.ingest(ws, [_folder(tmp_path)], ocr=OFF, ai_access="cloud")
    claimcheck.open_check(ws, "Hydrogen needs water", terms=["hydrogen", "water"], k=30, per_doc=30)
    docs = {r[0]: set(reread._old_pids(ws._conn(), r[0])) for r in ws.query("SELECT doc_id FROM documents")}
    # ids where one is the beginning of another (instr finds both): made-up tasks naming them
    docs.update({"dx1": {"dx1:0001"}, "dx12": {"dx12:0001"}})
    with ws.connect() as cx:
        cols = [r[1] for r in cx.execute("PRAGMA table_info(tasks)")]
        base = dict(next(iter(ws.query("SELECT * FROM tasks"))))
        for tid, pay in (("label:sdg:dx1:0001", "{}"), ("x:1", '{"passage_id": "dx12:0001"}'),
                         ("x:2", '{"passages": [{"passage_id": "dx1:0001"}, {"passage_id": "dx12:0001"}]}')):
            row = {**base, "task_id": tid, "payload_json": pay}
            cx.execute(f"INSERT INTO tasks({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       [row[c] for c in cols])
    cx = ws._conn()
    many = reread._doc_tasks_many(cx, docs)
    one = {d: reread._doc_tasks(cx, d, old) for d, old in docs.items()}
    assert many == one and sum(map(len, one.values())) > 3 and len(one["dx1"]) == 2 and len(one["dx12"]) == 2
    assert reread.check_many(ws, list(docs)) == {d: reread.check(ws, d) for d in docs if not d.startswith("dx")}


# ---- R15: where a passage's blocks are is looked up, not searched ---------------------------------------------
def test_the_kind_of_a_passages_blocks_is_found_quickly_and_as_before():
    rnd = random.Random(5)
    text = "x" * 400_000
    blocks, pos = [], 0
    while pos < len(text) - 50:
        n = rnd.randint(5, 40)
        blocks.append((pos, pos + n, rnd.choice(["body", "table", "head", "notes"]), rnd.random() < 0.6))
        pos += n + rnd.choice([0, 1, 2])
    blocks += [(a, a + rnd.randint(1, 3000), "figure", False) for a in rnd.sample(range(len(text)), 40)]  # overlapping
    new = [reread._P(f"d:{i:04d}", i, a, min(len(text), a + rnd.randint(1, 900)), "", "body", 1)
           for i, a in enumerate(sorted(rnd.sample(range(len(text)), 20000)))]
    m = reread._Map("", [], text, new, [(0, len(text))], True)
    m.set_blocks(blocks)

    def before(pid: str):
        q = m.by_new[pid]
        mine = [(min(q.end, b[1]) - max(q.start, b[0]), b[2], b[3]) for b in m.blocks
                if b[0] < q.end and b[1] > q.start]
        return None if not mine or any(inc for _n, _k, inc in mine) else max(mine)[1]

    t0 = time.perf_counter()
    got = [m.left_out_passage(q.pid) for q in new]
    took = time.perf_counter() - t0
    some = rnd.sample(range(len(new)), 300)
    assert [got[i] for i in some] == [before(new[i].pid) for i in some]
    assert any(got) and took < 0.5, took  # before: every block looked at for every passage (4 s here, 0.07 s now)

"""0.16 (H2): the keyword index on disk (`cache/search.sqlite`). Every search ranks and finds exactly what the index in
memory of before 0.16 does, as documents come and go; the file is closed with the project, never leaves the computer,
and the app goes on (in memory) when it cannot be written."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from enlens_claims import concordance, ingest, profile, search, searchindex
from enlens_claims.store import Workspace

TOPICS = ["proton exchange membrane", "green hydrogen", "water stress", "electricity grid", "ammonia export",
          "solid oxide cell", "hydrogen valley", "offshore wind", "commuters", "commuting"]


def _text(i: int) -> str:
    paras = []
    for p in range(7):
        a, b, c = TOPICS[(i + p) % len(TOPICS)], TOPICS[(i + 2 * p + 1) % len(TOPICS)], TOPICS[(p + 3) % len(TOPICS)]
        paras.append(f"Report {i}, part {p}. The {a} matters for the {b}; the {a} costs more than the {c}. "
                     f"Water and hydrogen return in part {p}, with the {c} and the {b}.")
    paras.append("References\n\nSmith, J. (2020). Water and hydrogen. Journal of Energy 12, 3-4.")
    return "\n\n".join(paras) + "\n"


QUERIES = ["water", "green hydrogen cost", "proton exchange membrane in the grid", "the of and", "ammonia"]


def _results(ws: Workspace) -> dict:
    docs = [r[0] for r in ws.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    out = {}
    for q in QUERIES:
        for kw in [{}, {"terms": ["valley", "wind"]}, {"second_pass": True}, {"doc_ids": docs[:2]},
                   {"terms": ["wind"], "require_terms": True}, {"k": 12, "per_doc": 1}]:
            out[("rank", q, repr(kw))] = [(r["passage_id"], r["score"], r["found_by"], r["matched"], r["text"], r["title"])
                                         for r in search.rank_passages(ws, q, **kw)]
        out[("docs", q)] = sorted(search.docs_matching(ws, q, ["wind"], set(docs)))
    for q, kw in [("water", {}), ("hydrogen", {"sort": "left"}), ("green hydrogen", {"sort": "right", "mode": "phrase"}),
                  ("water hydrogen", {"mode": "all"}), ("hydrogen cost", {"mode": "near", "near": 4}),
                  ("Smith", {"all_sections": True}), ("water", {"docs": docs[:2], "limit": None}),
                  ("commut", {}), ("Water", {"exact": True})]:
        out[("conc", q, repr(kw))] = concordance.search(ws, q, **kw)
        out[("coll", q, repr(kw))] = concordance.collocates(ws, q, mode=kw.get("mode", "any"), docs=kw.get("docs"),
                                                           all_sections=kw.get("all_sections", False), min_count=1)
    profile.keyword_pass(ws, "sdg")
    out["labels"] = [tuple(r) for r in ws.query(
        "SELECT label_id, code, confidence, source, reason, score FROM labels WHERE source IN ('keywords','meaning',"
        "'both') ORDER BY label_id")]
    return out


def _both(ws: Workspace, monkeypatch) -> tuple[dict, dict]:
    """The results with the index in memory (as before 0.16) and with the index on disk."""
    monkeypatch.setattr(search, "IN_MEMORY", True)
    search._INDEXES.clear()
    mem = _results(ws)
    monkeypatch.setattr(search, "IN_MEMORY", False)
    search._INDEXES.clear()
    disk = _results(ws)
    assert search.passage_index(ws).on_disk
    return mem, disk


def _write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return folder / name


@pytest.fixture
def project(tmp_path):
    ws = Workspace.create(tmp_path / "ws")
    src = tmp_path / "src"
    ingest.ingest(ws, [_write(src, f"report_{i}.txt", _text(i)) for i in range(4)])
    return ws, src


def test_the_index_on_disk_ranks_as_the_index_in_memory(project, monkeypatch):
    ws, src = project
    mem, disk = _both(ws, monkeypatch)
    assert [k for k in mem if mem[k] != disk[k]] == []
    assert any(mem[("conc", "Smith", repr({"all_sections": True}))]["lines"]) and mem[("rank", "water", "{}")]
    assert (ws.root / "cache" / "search.sqlite").is_file()


class _Split:
    """Counts the documents split into words (the slow part kept on disk)."""

    def __init__(self, monkeypatch):
        self.docs: list[str] = []
        real = searchindex._words

        def words(ws, doc_id):
            self.docs.append(doc_id)
            return real(ws, doc_id)

        monkeypatch.setattr(searchindex, "_words", words)


def test_documents_come_and_go(project, monkeypatch):
    ws, src = project
    split = _Split(monkeypatch)
    search.passage_index(ws)
    assert len(split.docs) == 4
    ingest.ingest(ws, [_write(src, "report_4.txt", _text(4)), _write(src, "report_5.txt", _text(5))])
    split.docs.clear()
    mem, disk = _both(ws, monkeypatch)
    assert mem == disk
    assert len(split.docs) == 2   # only the new ones (the index of every section reads the same kept words)
    gone = ws.scalar("SELECT doc_id FROM documents WHERE path LIKE '%report_1.txt'")
    ws.remove_document(gone)
    split.docs.clear()
    mem, disk = _both(ws, monkeypatch)
    assert mem == disk and split.docs == []
    assert not any(gone in str(v) for v in disk[("rank", "water", "{}")])
    # a passage left out of the body (Leave out in the reading view) and a passage's text changed: its document only
    with ws.connect() as cx:
        pids = [r[0] for r in cx.execute("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id "
                                         "LIMIT 2")]
        cx.execute("UPDATE passages SET section='left_out' WHERE passage_id=?", (pids[0],))
        cx.execute("UPDATE passages SET text = text || ' Water, water, offshore wind.' WHERE passage_id=?", (pids[1],))
        ws.bump_corpus(cx)
    split.docs.clear()
    mem, disk = _both(ws, monkeypatch)
    assert mem == disk and len(set(split.docs)) == 1
    import sqlite3

    cx = sqlite3.connect(ws.root / "cache" / "search.sqlite")
    assert sorted(r[0] for r in cx.execute("SELECT doc_id FROM docs")) == \
        sorted(r[0] for r in ws.query("SELECT doc_id FROM documents"))
    cx.close()


def test_a_file_that_cannot_be_written_damaged_or_gone(project, monkeypatch):
    ws, src = project
    monkeypatch.setattr(search, "IN_MEMORY", True)
    search._INDEXES.clear()
    ref = _results(ws)
    monkeypatch.setattr(search, "IN_MEMORY", False)
    split = _Split(monkeypatch)
    # the folder cannot be made: every document split again each time, as before 0.16
    (ws.root / "cache").write_text("a file where the folder would be")
    search._INDEXES.clear()
    assert _results(ws) == ref and len(split.docs) == 8   # the body index and the index of every section
    (ws.root / "cache").unlink()
    # garbage in the file: it is made again, and kept from then on
    (ws.root / "cache").mkdir()
    (ws.root / "cache" / "search.sqlite").write_bytes(b"not a database")
    search._INDEXES.clear()
    split.docs.clear()
    assert _results(ws) == ref and len(split.docs) == 4
    # the folder emptied while the app runs: an index already made goes on; the next one makes the file again
    idx = search.passage_index(ws)
    shutil.rmtree(ws.root / "cache")
    assert [r["passage_id"] for r in search.rank_passages(ws, "water")] == [r[0] for r in ref[("rank", "water", "{}")]]
    assert search.passage_index(ws) is idx
    search._INDEXES.clear()
    assert _results(ws) == ref and (ws.root / "cache" / "search.sqlite").is_file()


def test_nothing_stays_open_and_nothing_leaves_this_computer(project, tmp_path):
    from enlens_claims import bundle

    ws, src = project
    search.rank_passages(ws, "water")
    search.passage_index(ws, all_sections=True)
    moved = ws.root / "cache-moved"   # Windows refuses to rename a folder with an open file (0.15.7)
    (ws.root / "cache").rename(moved)
    moved.rename(ws.root / "cache")
    out = tmp_path / "p.zip"
    bundle.export_project(ws, out)
    assert not [n for n in zipfile.ZipFile(out).namelist() if "cache/" in n or "search.sqlite" in n]


def test_a_passage_gone_while_an_index_is_used(project):
    """An index is one state of the project. A passage removed while it is used (no new state asked for yet) is not
    read as some other passage: the reading stops and says to run it again."""
    ws, src = project
    idx = search.passage_index(ws)
    doc = idx.doc_of[0]
    with ws.connect() as cx:
        cx.execute("DELETE FROM passages WHERE doc_id=?", (doc,))
    with pytest.raises(searchindex.Changed, match="Run it again"):
        idx.read(range(len(idx.ids)))
    with pytest.raises(searchindex.Changed):
        idx.rows[0]


def test_an_update_of_enlens_keeps_the_words(project, monkeypatch):
    """The kept words' stamp is ENLENS's word rule (textutil.py as imported, and the Unicode data), not its version:
    an update that leaves the rule alone does not split every document again."""
    import enlens_claims
    import hashlib
    import sys

    from enlens_claims import textutil

    ws, src = project
    search.passage_index(ws)
    import unicodedata

    code = Path(textutil.__file__).read_bytes()
    extra = f"|{unicodedata.unidata_version}|{sys.version_info[0]}.{sys.version_info[1]}".encode()
    assert textutil.RULE_DIGEST == hashlib.sha1(code + extra).hexdigest()[:16]   # taken when textutil was imported
    assert searchindex.stamp() == f"{searchindex.FORMAT}:{textutil.RULE_DIGEST}:{sys.byteorder}"
    monkeypatch.setattr(enlens_claims, "__version__", "9.9.9")
    split = _Split(monkeypatch)
    search._INDEXES.clear()
    search.passage_index(ws)
    assert split.docs == []


def test_a_document_changed_while_its_words_are_split(project, monkeypatch):
    """Its words are kept under the fingerprint of what was split (both from one read of the project): Leave out
    while a load splits, then Restore, finds the words of the restored passages, not of the left-out ones (review)."""
    import sqlite3

    ws, src = project
    pid = ws.scalar("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id LIMIT 1")
    real = searchindex._words
    state = {"done": False}

    def words(cx, doc_id):
        if not state["done"]:   # another program leaves a passage out meanwhile
            state["done"] = True
            other = sqlite3.connect(ws.db_path)
            other.execute("UPDATE passages SET section='left_out' WHERE passage_id=?", (pid,))
            other.commit()
            other.close()
        return real(cx, doc_id)

    monkeypatch.setattr(searchindex, "_words", words)
    search._INDEXES.clear()
    search.passage_index(ws)
    assert state["done"]
    monkeypatch.setattr(searchindex, "_words", real)
    with ws.connect() as cx:   # Restore
        cx.execute("UPDATE passages SET section='body' WHERE passage_id=?", (pid,))
        ws.bump_corpus(cx)
    mem, disk = _both(ws, monkeypatch)
    assert mem == disk
    assert pid in search.passage_index(ws).pos


def test_a_file_damaged_inside_is_made_again(project):
    ws, src = project
    search.passage_index(ws)
    path = ws.root / "cache" / "search.sqlite"
    import sqlite3

    cx = sqlite3.connect(path)
    cx.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    cx.close()
    data = bytearray(path.read_bytes())
    assert len(data) >= 3 * 4096
    data[4096:len(data)] = b"\x5a" * (len(data) - 4096)   # every page after the first
    path.write_bytes(bytes(data))
    split = []
    real = searchindex._words
    searchindex._words = lambda cx, d: split.append(d) or real(cx, d)
    try:
        search._INDEXES.clear()
        search.passage_index(ws)
        assert len(split) == 4
        split.clear()
        search._INDEXES.clear()
        search.passage_index(ws)
        assert split == []   # made again, and kept
    finally:
        searchindex._words = real

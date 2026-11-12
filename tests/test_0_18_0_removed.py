"""Roles (DESIGN-roles §3.4): a removal a colleague's word causes keeps a small archive per document, restorable for
30 days: the rows `Workspace._document_rows` names (but those made again) and the original kept in `originals/`."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, ingest, removed
from enlens_claims.store import REMADE, Workspace

# DESIGN-roles §3.4: exactly what an archive holds
ARCHIVED = {"documents", "pages", "paragraphs", "headings", "passages", "blocks", "doc_tables", "block_choices",
            "labels", "mentions", "doc_refs", "bib_links", "sync_copies", "theme_members", "claims", "claim_targets",
            "evidence", "interactions", "verifications", "tasks", "results"}

TEXT = ("Local jobs from electrolyser plants\n\n"
        "Electrolyser plants create local jobs mainly during construction. A typical plant of one hundred megawatts "
        "employs about four hundred workers while it is built.\n\n"
        "Permanent jobs are fewer. Operation and maintenance of the same plant employs about thirty people, most of "
        "them technicians trained in the region.\n")


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    ws = Workspace.create(tmp_path / "ws")
    src = tmp_path / "in"
    src.mkdir()
    (src / "jobs.txt").write_text(TEXT, encoding="utf-8")
    (src / "other.txt").write_text(TEXT.replace("jobs", "wages") + "\nA second document stays.\n", encoding="utf-8")
    ingest.ingest(ws, [src])
    docs = {r["title"]: r["doc_id"] for r in ws.query("SELECT doc_id, title FROM documents")}
    doc = next(d for t, d in docs.items() if "jobs" in t.lower() and "wages" not in t.lower())
    other = next(d for d in docs.values() if d != doc)
    # its original is the project's own copy, as one that came from a colleague's zip
    orig = ws.root / "originals" / doc / "jobs.txt"
    orig.parent.mkdir(parents=True)
    shutil.copyfile(src / "jobs.txt", orig)
    pids = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq", (doc,))]
    keep = ws.query("SELECT passage_id FROM passages WHERE doc_id=?", (other,))[0][0]
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET path=? WHERE doc_id=?", (str(orig), doc))
        # a row in every table of §3.4 (and in the tables made again), and one of the other document's beside it
        cx.execute("INSERT INTO claims(claim_id, doc_id, passage_id, claim) VALUES ('c1', ?, ?, 'jobs rise')", (doc, pids[0]))
        cx.execute("INSERT INTO claim_targets(claim_id, target, direction) VALUES ('c1', '8.5', 'up')")
        cx.execute("INSERT INTO evidence(claim_id, field, quote, doc_id) VALUES ('c1', 'claim', 'local jobs', ?)", (doc,))
        cx.execute("INSERT INTO interactions(inter_id, claim_id, doc_id, kind) VALUES ('i1', 'c1', ?, 'stated')", (doc,))
        cx.execute("INSERT INTO verifications(ver_id, subject_kind, subject_id, passage_id, doc_id, verdict) "
                   "VALUES ('v1', 'claim', 'c1', ?, ?, 'supports')", (pids[0], doc))
        cx.execute("INSERT INTO theme_members(run_id, theme_id, passage_id, similarity) VALUES ('r1', 1, ?, 0.5)", (pids[0],))
        cx.execute("INSERT INTO theme_members(run_id, theme_id, passage_id, similarity) VALUES ('r1', 2, ?, 0.5)", (keep,))
        cx.execute("INSERT INTO embeddings(model, passage_id, vec) VALUES ('m', ?, x'00')", (pids[0],))
        cx.execute("INSERT OR IGNORE INTO pages(doc_id, page, start, end) VALUES (?, 1, 0, 100)", (doc,))
        cx.execute("INSERT INTO doc_refs(doc_id, ref_key, method, score) VALUES (?, 'ref1', 'title', 1.0)", (doc,))
        cx.execute("INSERT INTO bib_links(item_key, doc_id, status) VALUES ('item1', ?, 'linked')", (doc,))
        cx.execute("INSERT INTO sync_copies(kind, key, of_key, person_id, at) VALUES ('document', ?, 'x', 'p1', 'now')", (doc,))
        cx.execute("INSERT INTO mentions(doc_id, chain_id, start, end, text, window) VALUES (?, 1, 0, 5, 'Local', 'w')", (doc,))
        cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source) "
                   "VALUES ('l1', ?, ?, 'sdg', '8.5', 'person')", (pids[0], doc))
        cx.execute("INSERT OR REPLACE INTO doc_tables(doc_id, n, block, page, caption, rows_json) VALUES (?, 1, 1, 1, 'T', '[]')", (doc,))
        cx.execute("INSERT OR REPLACE INTO block_choices(doc_id, fp, included, kind, person_id, at) "
                   "VALUES (?, 'fp-not-a-block', 0, 'person', 'p1', 'now')", (doc,))
        for tid, kind in ((f"extract:{pids[0]}", "extract"), (f"label:sdg:{pids[0]}", "label"),
                          (f"resolve:{doc}:1", "resolve"), (f"check:{doc}:r1-0005", "check"),
                          (f"label:sdg:{keep}", "label")):
            cx.execute("INSERT INTO tasks(task_id, kind, model, status, attempts, created_at) VALUES (?,?,'m','done',1,'now')",
                       (tid, kind))
            cx.execute("INSERT INTO results(task_id, attempt, kind, model, raw_json, valid) VALUES (?, 1, ?, 'm', '{}', 1)",
                       (tid, kind))
    return ws, doc, other, orig


def _rows(ws: Workspace, doc: str) -> dict[str, list]:
    out: dict[str, list] = {}
    cx = ws._conn()
    for tbl, where, args in ws._document_rows(doc):
        if tbl in REMADE:
            continue
        out.setdefault(tbl, set()).update(tuple(r) for r in cx.execute(f"SELECT * FROM {tbl} WHERE {where}", args))
    return {t: sorted(v, key=repr) for t, v in out.items()}


def _remove_by_word(ws: Workspace, doc: str, by: str = "pOWNER0000001", cause: str = "removed") -> None:
    """As `ownership._Ctx.remove_here` does: the archive first, then the removal, in one transaction."""
    with ws.connect() as cx:
        removed.archive(ws, cx, doc, by, "Not about jobs.", cause)
        ws.remove_document(doc, why="Not about jobs.")


def test_the_one_list_names_every_table_of_the_design():
    ws_tables = {t for t, _w, _a in Workspace._document_rows(_FakeWs(), "d1")}
    assert ws_tables - set(REMADE) == ARCHIVED


class _FakeWs:
    def _conn(self):
        import sqlite3

        cx = sqlite3.connect(":memory:")
        cx.execute("CREATE TABLE passages(passage_id TEXT, doc_id TEXT)")
        cx.execute("INSERT INTO passages VALUES ('d1:0001', 'd1')")
        return cx


def test_an_archive_gives_back_every_row_and_the_original(project):
    ws, doc, other, orig = project
    before = _rows(ws, doc)
    assert set(before) == ARCHIVED and all(before[t] for t in ARCHIVED), {t for t in ARCHIVED if not before.get(t)}
    other_before = ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=?", (other,))
    _remove_by_word(ws, doc)
    assert not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))
    assert not any(_rows(ws, doc).values())
    assert not orig.exists() and not orig.parent.exists()  # moved into the archive, not copied
    assert ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=?", (other,)) == other_before
    assert ws.scalar("SELECT 1 FROM sync_removed WHERE kind='document' AND key=?", (doc,))
    listed = removed.listing(ws)
    assert [x["doc"] for x in listed] == [doc]
    x = listed[0]
    assert x["by"] == "pOWNER0000001" and x["cause"] == "removed" and x["why"] == "Not about jobs."
    assert dt.datetime.fromisoformat(x["until"]) - dt.datetime.fromisoformat(x["at"]) == dt.timedelta(days=30)
    files = list((ws.root / "backups" / "removed").iterdir())
    assert len(files) == 2  # the rows, and the folder with the original

    assert removed.restore(ws, doc) is True
    assert _rows(ws, doc) == before  # every table of §3.4, row for row
    assert orig.is_file() and ws.scalar("SELECT path FROM documents WHERE doc_id=?", (doc,)) == str(orig.resolve())
    assert not ws.scalar("SELECT 1 FROM sync_removed WHERE kind='document' AND key=?", (doc,))
    assert removed.listing(ws) == [] and not ws.scalar("SELECT COUNT(*) FROM removed_docs")
    assert not list((ws.root / "backups" / "removed").iterdir())
    assert ws.scalar("SELECT COUNT(*) FROM research_log WHERE kind='document-restored'") == 1
    assert removed.restore(ws, doc) is False  # nothing left to restore from


def test_a_second_removal_replaces_the_first_archive(project):
    ws, doc, _other, _orig = project
    _remove_by_word(ws, doc)
    assert removed.restore(ws, doc)
    _remove_by_word(ws, doc, cause="declined")
    assert [x["cause"] for x in removed.listing(ws)] == ["declined"]
    assert len(list((ws.root / "backups" / "removed").glob("*.sqlite"))) == 1


def test_a_document_added_again_since_is_not_doubled(project, tmp_path):
    ws, doc, _other, _orig = project
    _remove_by_word(ws, doc)
    again = tmp_path / "again"
    again.mkdir()
    (again / "jobs.txt").write_text(TEXT, encoding="utf-8")
    ingest.ingest(ws, [again])
    n, passages = ws.scalar("SELECT COUNT(*) FROM documents"), ws.scalar("SELECT COUNT(*) FROM passages")
    assert ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))  # (the same file: the same id)
    assert removed.restore(ws, doc) is True  # it is in: the archive goes, nothing is put in twice
    assert removed.listing(ws) == []
    assert (ws.scalar("SELECT COUNT(*) FROM documents"), ws.scalar("SELECT COUNT(*) FROM passages")) == (n, passages)
    # the same file under another id (a colleague's copy of it): not restored beside it
    _remove_by_word(ws, doc)
    sha = ws.scalar("SELECT sha1 FROM documents LIMIT 1")  # (the other document's: stands in for the same file)
    arc = next((ws.root / "backups" / "removed").glob("*.sqlite"))
    c = sqlite3.connect(arc)
    c.execute("UPDATE documents SET sha1=?", (sha,))
    c.commit()
    c.close()
    assert removed.restore(ws, doc) is False and removed.listing(ws)


def test_archives_older_than_30_days_are_pruned(project, monkeypatch):
    ws, doc, _other, _orig = project
    _remove_by_word(ws, doc)
    real = removed._now()
    monkeypatch.setattr(removed, "_now", lambda: real + dt.timedelta(days=29))
    assert removed.prune(ws) == 0 and removed.listing(ws)
    monkeypatch.setattr(removed, "_now", lambda: real + dt.timedelta(days=31))
    assert removed.prune(ws) == 1
    assert removed.listing(ws) == [] and not ws.scalar("SELECT COUNT(*) FROM removed_docs")
    assert not list((ws.root / "backups" / "removed").iterdir())
    assert removed.restore(ws, doc) is False


def test_an_archive_left_without_its_row_goes_too(project, monkeypatch):
    """A removal whose transaction was undone leaves its archive without a row: pruned once it is as old."""
    ws, doc, _other, _orig = project
    with pytest.raises(RuntimeError):
        with ws.connect() as cx:
            removed.archive(ws, cx, doc, "pOWNER0000001", "", "removed")
            raise RuntimeError("undone")
    assert not ws.scalar("SELECT COUNT(*) FROM removed_docs")
    assert list((ws.root / "backups" / "removed").glob("*.sqlite"))
    # the original it took is found there by the next archive of the document
    _remove_by_word(ws, doc)
    assert removed.restore(ws, doc)
    assert Path(ws.scalar("SELECT path FROM documents WHERE doc_id=?", (doc,))).is_file()
    real = removed._now()
    monkeypatch.setattr(removed, "_now", lambda: real + dt.timedelta(days=31))
    removed.prune(ws)
    assert not list((ws.root / "backups" / "removed").iterdir())


def test_archives_never_travel_in_a_zip(project, tmp_path, monkeypatch):
    ws, doc, _other, _orig = project
    _remove_by_word(ws, doc)
    out = tmp_path / "p.zip"
    bundle.export_project(ws, out)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert not [n for n in names if n.startswith("backups/")]
    copy = bundle.import_project(out, tmp_path / "copy")
    assert removed.listing(copy) == [] and not copy.scalar("SELECT COUNT(*) FROM removed_docs")
    assert json.loads(json.dumps(removed.listing(ws)))  # still restorable here

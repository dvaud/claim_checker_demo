"""0.17.2: the glossary's places in a third less space (`term_mentions` WITHOUT ROWID, its `doc_id` left empty).

- Every reader of the places gives what the queries of 0.17.0 gave on its table (with a rowid and the document of each
  place): the queries of 0.17.0 run here on a copy of the places in that shape.
- A project of 0.17.0 opened now drops its table of places: the glossary is "not made yet" until it is made again, the
  file is made smaller once (VACUUM) when that frees enough and the disk has room.
- An ENLENS before 0.17.2 opens a file of this version without harm: what it runs on opening works on the new table, it
  finds no glossary of its own, it never reads the table as the project's rows; a glossary it makes in the file is
  dropped at the next opening here.
"""
from __future__ import annotations

import math
import sqlite3
import shutil
from collections import defaultdict
from pathlib import Path

import pytest

from enlens_claims import annotate, ingest, reread, sharing, store, terms
from enlens_claims.store import Workspace, passage_range

DEMO = Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"

# what 0.17.0 made: its table of places and its three indexes (store.SCHEMA and store.INDEXES of 0.17.0)
OLD_TABLE = "CREATE TABLE IF NOT EXISTS {t}(term_id TEXT, passage_id TEXT, doc_id TEXT, start INT, end INT)"
OLD_INDEXES = ("CREATE INDEX IF NOT EXISTS ix_{t}_term ON {t}(term_id)",
               "CREATE INDEX IF NOT EXISTS ix_{t}_passage ON {t}(passage_id)",
               "CREATE INDEX IF NOT EXISTS ix_{t}_doc ON {t}(doc_id, term_id)")


def _old_shape(cx, name: str) -> None:
    """The places in the shape of 0.17.0, under `name`: every place with its document."""
    cx.execute(OLD_TABLE.format(t=name))
    for sql in OLD_INDEXES:
        cx.execute(sql.format(t=name))
    cx.execute(f"INSERT INTO {name} SELECT m.term_id, m.passage_id, p.doc_id, m.start, m.end FROM term_mentions m "
               "JOIN passages p ON p.passage_id=m.passage_id")


@pytest.fixture
def demo(tmp_path):
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [DEMO])
    terms.build(ws)
    # a concept of two wordings (a person's link), so the queries over concepts have something to join
    a, b = [r[0] for r in ws.query("SELECT term_id FROM terms ORDER BY tf DESC, term_id LIMIT 2")]
    terms.set_link(ws, a, b, "add", "same")
    with ws.connect() as cx:
        _old_shape(cx, "rel")
    yield ws
    ws.close_all()


# ---------------------------------------------------------------------------------------------
# the readers, against the queries of 0.17.0 (table `rel`, the old shape)
# ---------------------------------------------------------------------------------------------
def _released_key_terms(ws, doc_id=None, passage_id=None, n=20):
    """terms.key_terms as 0.17.0 had it."""
    if doc_id:
        rows = ws.query("SELECT m.term_id, COUNT(*) AS tf, t.label, t.stems, t.df AS df FROM rel m "
                        "JOIN terms t ON t.term_id=m.term_id WHERE m.doc_id=? GROUP BY m.term_id", (doc_id,))
        total = int(ws.scalar("WITH RECURSIVE d(x) AS (SELECT MIN(doc_id) FROM rel UNION ALL SELECT "
                              "(SELECT MIN(doc_id) FROM rel WHERE doc_id > x) FROM d WHERE x IS NOT NULL) "
                              "SELECT COUNT(x) FROM d") or 0) or 1
    else:
        rows = ws.query("SELECT m.term_id, COUNT(*) AS tf, t.label, t.stems, t.passages AS df FROM rel m "
                        "JOIN terms t ON t.term_id=m.term_id WHERE m.passage_id=? GROUP BY m.term_id", (passage_id,))
        total = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'") or 1)
    scored = []
    for r in rows:
        idf = math.log((1 + total) / (1 + r["df"])) + 1
        scored.append({"term_id": r["term_id"], "label": r["label"], "mentions": r["tf"],
                       "score": round((1 + math.log(r["tf"])) * idf, 3), "_st": r["stems"].split(" ")})
    scored.sort(key=lambda x: (-x["score"], x["label"]))
    out = []
    for s in scored:
        if any(len(o["_st"]) > len(s["_st"]) and terms._nested(s["_st"], o["_st"]) and o["mentions"] >= s["mentions"]
               for o in out):
            continue
        out.append(s)
        if len(out) >= n:
            break
    for o in out:
        o.pop("_st")
    return out


def test_key_terms_of_every_document_and_passage_are_as_before(demo):
    docs = [r[0] for r in demo.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    assert terms._docs_with_terms(demo) == int(demo.scalar(
        "SELECT COUNT(DISTINCT doc_id) FROM rel")) == len(docs) > 3
    for d in docs:
        got = terms.key_terms(demo, doc_id=d, n=30)
        assert got and got == _released_key_terms(demo, doc_id=d, n=30)
        ids = [k["term_id"] for k in got[:15]]
        q = ",".join("?" * len(ids))
        spans = [tuple(r) for r in demo.query(f"SELECT term_id, start, end FROM rel WHERE doc_id=? AND term_id IN ({q}) "
                                              "ORDER BY start", (d, *ids))]
        got_spans = terms.key_term_spans(demo, d)["spans"]
        # the order of two terms at one start was the table's own before as now: compared as sets there
        assert [(s["start"]) for s in got_spans] == [s[1] for s in spans]
        assert sorted((s["term_id"], s["start"], s["end"]) for s in got_spans) == sorted(spans)
    for (pid,) in demo.query("SELECT DISTINCT passage_id FROM rel ORDER BY passage_id LIMIT 40"):
        assert terms.key_terms(demo, passage_id=pid) == _released_key_terms(demo, passage_id=pid)
    table = terms.key_terms_table(demo, n=15)
    want = []
    for r in demo.query("SELECT doc_id, title FROM documents ORDER BY title"):
        want += [(r["title"] or r["doc_id"], i, k["label"]) for i, k in enumerate(_released_key_terms(
            demo, doc_id=r["doc_id"], n=15), 1)]
    assert [(r["Document"], r["Rank"], r["Key term"]) for r in table] == want


def test_the_glossary_and_a_concepts_page_are_as_before(demo):
    g = terms.glossary(demo, limit=500)
    in_concept = {r[0]: r[1] for r in demo.query("SELECT term_id, concept_id FROM concept_terms")}
    assert in_concept   # the fixture's concept
    docs = defaultdict(set)
    for r in demo.query("SELECT DISTINCT m.term_id, m.doc_id FROM rel m JOIN concept_terms ct ON ct.term_id=m.term_id"):
        docs[in_concept.get(r[0]) or r[0]].add(r[1])
    pas = {r[0]: r[1] for r in demo.query("SELECT ct.concept_id, COUNT(DISTINCT m.passage_id) AS n FROM rel m "
                                          "JOIN concept_terms ct ON ct.term_id=m.term_id GROUP BY ct.concept_id")}
    concepts = [e for e in g["items"] if e["concept"]]
    assert concepts
    for e in concepts:
        assert e["documents"] == len(docs[e["concept"]]) and e["passages"] == pas[e["concept"]]
    for e in g["items"][:30]:
        card = terms.card(demo, e["term_id"], limit=500)
        ids = terms.concept_of(demo, e["term_id"])
        q = ",".join("?" * len(ids))
        want_docs = []
        for r in demo.query(f"SELECT m.doc_id, d.title, COUNT(*) AS n, COUNT(DISTINCT m.passage_id) AS p, "
                            f"MIN(m.start) AS first FROM rel m JOIN documents d ON d.doc_id=m.doc_id WHERE m.term_id IN "
                            f"({q}) GROUP BY m.doc_id ORDER BY n DESC, d.title", ids):
            end = demo.scalar(f"SELECT MAX(end) FROM rel WHERE doc_id=? AND start=? AND term_id IN ({q})",
                              (r["doc_id"], r["first"], *ids))
            want_docs.append((r["doc_id"], r["title"] or "", r["n"], r["p"], r["first"], end))
        assert [(d["doc_id"], d["title"], d["mentions"], d["passages"], d["first"], d["first_end"])
                for d in card["documents"]] == want_docs
        lines = [(r["doc_id"], r["passage_id"], r["start"], r["end"]) for r in demo.query(
            f"SELECT m.passage_id, m.doc_id, m.start, m.end FROM rel m JOIN passages p ON p.passage_id=m.passage_id "
            f"JOIN documents d ON d.doc_id=m.doc_id WHERE m.term_id IN ({q}) ORDER BY d.title, p.seq, m.start, m.end",
            ids)]
        assert sorted((x["doc_id"], x["passage_id"], x["start"], x["end"]) for x in card["lines"]) == sorted(lines)
        assert [(x["doc_id"], x["start"]) for x in card["lines"]] == [(x[0], x[2]) for x in lines]
        assert card["mentions"] == len(lines) and card["passages"] == len({x[1] for x in lines})
        # snippets: the first place in each document, documents in order, then the next places
        rows = [tuple(r) for r in demo.query("SELECT m.passage_id, m.doc_id, m.start FROM rel m WHERE m.term_id=? "
                                             "ORDER BY m.doc_id, m.start", (e["term_id"],))]
        firsts = list({r[1]: r for r in reversed(rows)}.values())[::-1][:8]
        want = firsts + [r for r in rows if r not in firsts][:8 - len(firsts)]
        assert [x["passage_id"] for x in terms.snippets(demo, e["term_id"], n=8)] == [r[0] for r in want]


def test_terms_in_documents_and_a_concepts_marks_are_as_before(demo):
    ids = [r[0] for r in demo.query("SELECT term_id FROM terms ORDER BY tf DESC LIMIT 60")]
    docs = [r[0] for r in demo.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    for some in (docs[:1], docs[1:3], docs, []):
        want = {r[0] for r in demo.query(f"SELECT DISTINCT term_id FROM rel WHERE term_id IN ({','.join('?' * len(ids))}) "
                                         f"AND doc_id IN ({','.join('?' * len(some))})", [*ids, *some])} if some else set()
        assert terms.terms_in_docs(demo, ids, some) == want
    assert terms.terms_in_docs(demo, ids, docs[:1]) != terms.terms_in_docs(demo, ids, docs)   # not all everywhere
    concept = demo.scalar("SELECT term_id FROM concept_terms LIMIT 1")
    ids = terms.concept_of(demo, concept)
    q = ",".join("?" * len(ids))
    for d in docs:
        marks = annotate.collect(demo, d, layers=("concepts",), concept=concept)
        want = [tuple(r) for r in demo.query(f"SELECT start, end FROM rel WHERE doc_id=? AND term_id IN ({q}) "
                                             "ORDER BY start", (d, *ids))]
        assert sorted((m.start, m.end) for m in marks) == sorted(want)


# ---------------------------------------------------------------------------------------------
# a document's passages: a range of ids
# ---------------------------------------------------------------------------------------------
def test_a_documents_range_holds_its_passages_and_no_others():
    from enlens_claims.sync.common import DOC_ID

    docs = ["d1a2b3c4d5e", "d1a2b3c4d5e-0f1e2d", "d1a2b3c4d5", "d1a2b3c4d5f", "d1a2b3c4d5e_x"]
    pids = [f"{d}:{s:04d}" for d in docs for s in (0, 1, 9999, 10000, 123456)]
    pids += ["d1a2b3c4d5e:r1-0005"]   # an answer kept from an earlier reading names no passage, but sorts here
    cx = sqlite3.connect(":memory:")
    for d in docs:
        lo, hi = passage_range(d)
        assert sorted(p for p in pids if lo <= p < hi) == sorted(p for p in pids if p.rsplit(":", 1)[0] == d)
        got = {r[0] for r in cx.execute(f"SELECT {store.DOC_OF.format(':p')}", {"p": f"{d}:0001"})}
        assert got == {d}
        assert DOC_ID.fullmatch(d.split("_x")[0])
    assert not DOC_ID.fullmatch("d1:2") and ":" not in "d" + "0" * 10   # a document id never has a colon


def test_removing_and_reading_a_document_again_takes_its_places_only(demo):
    docs = [r[0] for r in demo.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    before = {d: demo.scalar("SELECT COUNT(*) FROM term_mentions WHERE passage_id >= ? AND passage_id < ?",
                             passage_range(d)) for d in docs}
    assert all(before.values())
    demo.remove_document(docs[0])
    after = {d: demo.scalar("SELECT COUNT(*) FROM term_mentions WHERE passage_id >= ? AND passage_id < ?",
                            passage_range(d)) for d in docs}
    assert after == {**before, docs[0]: 0}
    # the plan of *Read with the new reader* (also the sync's): the document's places go before its rows change
    plan = reread._Plan()
    plan.first.append(("DELETE FROM term_mentions WHERE passage_id >= ? AND passage_id < ?", passage_range(docs[1])))
    with demo.connect() as cx:
        reread._write_plan(cx, plan)
    assert demo.scalar("SELECT COUNT(*) FROM term_mentions") == sum(after.values()) - after[docs[1]]


# ---------------------------------------------------------------------------------------------
# a project of 0.17.0, and an ENLENS 0.17.0 on a file of this version
# ---------------------------------------------------------------------------------------------
# sync.common.LOCAL_ONLY of 0.17.0: the tables it never reads as the project's rows. Every other table it reads by rowid
# (sharing.ProjectRows), so a table WITHOUT ROWID must be one of these
LOCAL_ONLY_0_17_0 = {"meta", "embeddings", "code_vectors", "terms", "term_mentions", "concepts", "concept_terms",
                     "task_claims", "sync_log", "sqlite_sequence", "versions", "sync_written", "sync_folder_read",
                     "sync_folder_docs", "canon_seen"}


def _as_0_17_0(ws: Workspace, in_new_table: bool = False) -> None:
    """Make the file what 0.17.0 left: its table of places (a rowid, the document of every place, three indexes) and its
    note of the build. `in_new_table`: as an ENLENS 0.17.0 leaves a file of this version where it made its glossary
    (the table as it is here, each place with its document, its indexes made on opening)."""
    with ws.connect() as cx:
        cx.execute("DROP TABLE IF EXISTS rel")
        if in_new_table:
            cx.execute(f"UPDATE term_mentions SET doc_id={store.DOC_OF.format('passage_id')}")
            for sql in OLD_INDEXES:
                cx.execute(sql.format(t="term_mentions"))
        else:
            _old_shape(cx, "rel")
            cx.execute("DROP TABLE term_mentions")
            cx.execute(OLD_TABLE.format(t="term_mentions"))
            for sql in OLD_INDEXES:
                cx.execute(sql.format(t="term_mentions"))
            cx.execute("INSERT INTO term_mentions SELECT * FROM rel")
            cx.execute("DROP TABLE rel")
        cx.execute("INSERT OR REPLACE INTO meta VALUES ('terms_corpus_version', ?)", (str(ws.corpus_version()),))
        cx.execute("DELETE FROM meta WHERE key='glossary_corpus_version'")
    ws.close_all()


def _new_shape(ws: Workspace) -> bool:
    names = {r[0] for r in ws.query("SELECT name FROM sqlite_master WHERE tbl_name='term_mentions'")}
    return names == {"term_mentions", "ix_term_mentions_at"} and \
        "WITHOUT ROWID" in ws.scalar("SELECT sql FROM sqlite_master WHERE name='term_mentions'")


def test_a_project_of_0_17_0_drops_its_places_and_makes_the_glossary_again(demo, monkeypatch):
    before = terms.glossary(demo, limit=500)["items"]
    _as_0_17_0(demo)
    cx = sqlite3.connect(demo.db_path)
    cx.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    size_before = cx.execute("PRAGMA page_count").fetchone()[0]
    assert "WITHOUT ROWID" not in cx.execute("SELECT sql FROM sqlite_master WHERE name='term_mentions'").fetchone()[0]
    cx.close()
    monkeypatch.setattr(store, "VACUUM_MIN_FREE", 0)   # the demo frees far less than a real project
    monkeypatch.setattr(store, "VACUUM_MIN_SHARE", 0)
    ws = Workspace.open(demo.root)
    try:
        assert _new_shape(ws) and not ws.scalar("SELECT COUNT(*) FROM term_mentions")
        st = terms.status(ws)
        assert st["missing"] and not st["built"] and st["terms"] == 0   # "No glossary yet", as if never made
        assert terms.key_term_spans(ws, ws.scalar("SELECT doc_id FROM documents LIMIT 1"))["spans"] == []
        assert ws.scalar("PRAGMA freelist_count") == 0 and ws.scalar("PRAGMA page_count") < size_before   # VACUUM
        terms.build(ws)
        assert terms.status(ws)["built"] and terms.glossary(ws, limit=500)["items"] == before
        assert not ws.scalar("SELECT COUNT(*) FROM term_mentions WHERE doc_id IS NOT NULL")
        # opened again: nothing more is dropped
        ws.close_all()
        ws = Workspace.open(ws.root)
        assert terms.status(ws)["built"] and not terms.status(ws)["stale"]
    finally:
        ws.close_all()


def test_no_vacuum_when_it_frees_little_the_disk_is_short_or_the_file_is_in_use(demo, monkeypatch):
    def freed(ws):
        return ws.scalar("PRAGMA freelist_count")

    _as_0_17_0(demo)
    ws = Workspace.open(demo.root)   # the demo frees far less than VACUUM_MIN_FREE: left as free pages
    assert freed(ws) > 0 and terms.status(ws)["missing"] and _new_shape(ws)
    ws.close_all()
    monkeypatch.setattr(store, "VACUUM_MIN_FREE", 0)
    monkeypatch.setattr(store, "VACUUM_MIN_SHARE", 0)
    terms.build(ws)
    _as_0_17_0(ws)
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda p: real(p)._replace(free=1024))
    ws = Workspace.open(demo.root)
    monkeypatch.setattr(shutil, "disk_usage", real)
    assert freed(ws) > 0 and terms.status(ws)["missing"] and _new_shape(ws)   # dropped all the same
    ws.close_all()
    # another program writes: VACUUM waits VACUUM_WAIT_MS at most and leaves the file as it is
    monkeypatch.setattr(store, "VACUUM_WAIT_MS", 0)
    writer = sqlite3.connect(demo.db_path, isolation_level=None)
    cx = sqlite3.connect(demo.db_path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        assert store._vacuum_after_drop(cx, demo.root) is False
        writer.execute("COMMIT")
        assert cx.execute("PRAGMA freelist_count").fetchone()[0] > 0
        assert store._vacuum_after_drop(cx, demo.root) is True    # free again: it runs
        assert cx.execute("PRAGMA freelist_count").fetchone()[0] == 0
    finally:
        cx.close()
        writer.close()


def test_an_older_enlens_opens_a_file_of_this_version(demo):
    """What 0.17.0 runs on every opening works on the new table: its CREATE TABLE (the table is there) and its indexes,
    one on `doc_id`. It reads `terms_corpus_version`, which this version does not write: it finds no glossary of its
    own. Every table of the file without a rowid is one it never reads as the project's rows. Opened here again, its
    indexes go and the glossary made here stays."""
    before = terms.glossary(demo, limit=500)["items"]
    without_rowid = {r[0] for r in demo.query("SELECT name FROM sqlite_master WHERE type='table' AND "
                                              "upper(sql) LIKE '%WITHOUT ROWID%'")}
    assert without_rowid == {"term_mentions"} and without_rowid <= LOCAL_ONLY_0_17_0
    demo.close_all()
    cx = sqlite3.connect(demo.db_path)
    cx.execute(OLD_TABLE.format(t="term_mentions"))
    for sql in OLD_INDEXES:
        cx.execute(sql.format(t="term_mentions"))
    assert cx.execute("SELECT value FROM meta WHERE key='terms_corpus_version'").fetchone() is None
    assert cx.execute("SELECT COUNT(*) FROM term_mentions WHERE doc_id=?", ("d0",)).fetchone()[0] == 0
    cx.commit()
    cx.close()
    ws = Workspace.open(demo.root)
    try:
        assert _new_shape(ws)
        assert terms.status(ws)["built"] and terms.glossary(ws, limit=500)["items"] == before
    finally:
        ws.close_all()


def test_a_glossary_an_older_enlens_made_is_dropped_at_the_next_opening(demo):
    """0.17.0 makes its glossary in a file of this version: its rows go into the same table (`INSERT ... VALUES` with
    the document of each place, as it writes them), its terms and its note. Opened here, all of it goes."""
    rows = [(r[0], r[1], r[1].split(":")[0], r[2], r[3]) for r in
            demo.query("SELECT term_id, passage_id, start, end FROM term_mentions")]
    with demo.connect() as cx:   # what 0.17.0's build does: everything written again, in its own way
        cx.execute("DELETE FROM term_mentions")
        cx.executemany("INSERT INTO term_mentions VALUES (?,?,?,?,?)", rows)
    _as_0_17_0(demo, in_new_table=True)
    ws = Workspace.open(demo.root)
    try:
        assert terms.status(ws)["missing"] and not ws.scalar("SELECT COUNT(*) FROM term_mentions")
        assert not ws.scalar("SELECT COUNT(*) FROM terms") and _new_shape(ws)
    finally:
        ws.close_all()


# ---------------------------------------------------------------------------------------------
# what leaves the computer
# ---------------------------------------------------------------------------------------------
def test_a_zip_for_a_colleague_holds_no_places(demo, tmp_path):
    out = tmp_path / "shared.zip"
    from enlens_claims import bundle

    bundle.export_project(demo, out, scope="shared")
    import zipfile

    with zipfile.ZipFile(out) as zf:
        zf.extract("enlens.sqlite", tmp_path / "x")
    cx = sqlite3.connect(tmp_path / "x" / "enlens.sqlite")
    try:
        assert cx.execute("SELECT COUNT(*) FROM term_mentions").fetchone()[0] == 0
        assert "term_mentions" in sharing._LOCAL_TABLES
    finally:
        cx.close()

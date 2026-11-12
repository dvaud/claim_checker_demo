"""0.16 (H3): recompute only what changed. The glossary keeps each document's reading (`cache/glossary.sqlite`) and
writes only the mentions that changed; whatever happens to the kept readings, the glossary is the one a build from
scratch makes, mention for mention."""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import ingest, terms, themes
from enlens_claims.store import Workspace, passage_range

TOPICS = ["proton exchange membrane", "green hydrogen", "water stress", "electricity grid", "ammonia export",
          "solid oxide cell", "hydrogen valley", "offshore wind"]


def _text(i: int, extra: str = "") -> str:
    """A small report: each paragraph names a few topics, so terms occur in several documents."""
    paras = []
    for p in range(6):
        a, b, c = TOPICS[(i + p) % len(TOPICS)], TOPICS[(i + 2 * p + 1) % len(TOPICS)], TOPICS[(p + 3) % len(TOPICS)]
        paras.append(f"Report {i}, part {p}. The {a} matters for the {b}. Planners compare the {a} with the {c}, "
                     f"and the {b} returns in the conclusion of part {p} about the {c}.")
    return "\n\n".join(paras + ([extra] if extra else [])) + "\n"


SPACED = ("The Elec tr oly ser stack ran for a year. A second Elec tr oly ser stack followed, and a third "
          "Elec tr oly ser stack is planned with green hydrogen storage.")
WHOLE = ("Each electrolyser stack needs water. The electrolyser makes green hydrogen; one electrolyser per site, "
         "and the electrolyser vendors compete. A cheaper electrolyser stack would help.")


def _write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text(text, encoding="utf-8")
    return p


def _dump(ws: Workspace) -> dict:
    out = {}
    for name, q in [("terms", "SELECT * FROM terms ORDER BY term_id"),
                    ("mentions", "SELECT * FROM term_mentions ORDER BY passage_id, start, end, term_id"),
                    ("abbr", "SELECT a, b, relation, quote_a, quote_b FROM concept_links WHERE source='abbreviation' "
                             "ORDER BY a, b"),
                    ("concepts", "SELECT * FROM concept_terms ORDER BY concept_id, term_id")]:
        out[name] = [tuple(r) for r in ws.query(q)]
    out["counts"] = [[p, list(c.items())] for p, c in terms.passage_term_counts(ws).items()]
    return out


def _from_scratch(ws: Workspace, tmp_path: Path, **kw) -> dict:
    """The glossary a build with nothing kept makes, in a copy of the project."""
    copy = tmp_path / f"scratch-{len(list(tmp_path.glob('scratch-*')))}"
    shutil.copytree(ws.root, copy, ignore=shutil.ignore_patterns("cache", "*.sqlite-shm"))
    other = Workspace.open(copy)
    st = terms.build(other, **kw)
    assert st["documents_kept"] == 0
    return _dump(other)


@pytest.fixture
def project(tmp_path: Path) -> tuple[Workspace, Path]:
    ws = Workspace.create(tmp_path / "ws")
    src = tmp_path / "src"
    files = [_write(src, f"report_{i}.txt", _text(i)) for i in range(5)]
    files.append(_write(src, "spaced.txt", _text(9, SPACED)))
    ingest.ingest(ws, files)
    return ws, src


def test_adding_a_document_reads_only_what_changed(project, tmp_path):
    ws, src = project
    first = terms.build(ws)
    assert first["documents_read"] == 6 and first["documents_kept"] == 0
    assert (ws.root / "cache" / "glossary.sqlite").is_file()
    ingest.ingest(ws, [_write(src, "report_5.txt", _text(5))])
    st = terms.build(ws)
    assert st["documents_read"] == 1 and st["documents_kept"] == 6   # only the new one
    assert _dump(ws) == _from_scratch(ws, tmp_path)
    again = terms.build(ws)   # nothing changed: nothing read, nothing different
    assert again["documents_read"] == 0 and _dump(ws) == _from_scratch(ws, tmp_path)


def test_a_new_document_that_joins_letter_spaced_words_elsewhere(project, tmp_path):
    """"Elec tr oly ser" is read as one word once the documents also write "electrolyser" whole often enough: the
    document with the spaced word is then read again, because its terms change with the new one."""
    ws, src = project
    terms.build(ws)
    assert not ws.scalar("SELECT COUNT(*) FROM terms WHERE stems LIKE '%electrolys%'")
    ingest.ingest(ws, [_write(src, "whole.txt", _text(7, WHOLE)), _write(src, "whole2.txt", _text(8, WHOLE))])
    st = terms.build(ws)
    assert st["documents_read"] == 3   # the two new documents and the one with the spaced word
    spaced = ws.scalar("SELECT doc_id FROM documents WHERE path LIKE '%spaced.txt'")
    assert ws.scalar("SELECT COUNT(*) FROM term_mentions m JOIN terms t ON t.term_id=m.term_id "
                     "WHERE m.passage_id >= ? AND m.passage_id < ? AND t.stems LIKE 'electrolys%' AND t.n_words=1",
                     passage_range(spaced)) == 3
    assert _dump(ws) == _from_scratch(ws, tmp_path)


def test_removing_and_changing_documents(project, tmp_path):
    ws, src = project
    terms.build(ws)
    gone = ws.scalar("SELECT doc_id FROM documents WHERE path LIKE '%report_2.txt'")
    ws.remove_document(gone)
    st = terms.build(ws)
    assert st["documents_read"] == 0 and st["documents_kept"] == 5
    assert not ws.scalar("SELECT COUNT(*) FROM term_mentions WHERE passage_id >= ? AND passage_id < ?",
                         passage_range(gone))
    assert _dump(ws) == _from_scratch(ws, tmp_path)
    # a passage's text changes (as when a document is read again): that document only
    with ws.connect() as cx:
        pid = cx.execute("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id LIMIT 1").fetchone()[0]
        cx.execute("UPDATE passages SET text = text || ' The offshore wind and the ammonia export.' "
                   "WHERE passage_id=?", (pid,))
        ws.bump_corpus(cx)
    st = terms.build(ws)
    assert st["documents_read"] == 1
    assert _dump(ws) == _from_scratch(ws, tmp_path)
    # fewer terms asked for: mentions of the terms left out go, the rest stay
    terms.build(ws, max_terms=5)
    assert ws.scalar("SELECT COUNT(DISTINCT term_id) FROM term_mentions") == 5
    terms.build(ws)
    assert _dump(ws) == _from_scratch(ws, tmp_path)


def test_the_kept_readings_can_be_lost_or_wrong(project, tmp_path):
    ws, src = project
    terms.build(ws)
    ref = _from_scratch(ws, tmp_path)
    cache = ws.root / "cache" / "glossary.sqlite"
    # garbage in every kept reading: each document is read again
    cx = sqlite3.connect(cache)
    cx.execute("UPDATE readings SET counts=x'00', reading=x'01', grams=x'02'")
    cx.commit()
    cx.close()
    st = terms.build(ws)
    assert st["documents_read"] == 6 and _dump(ws) == ref
    # the file itself is not a database: it is made again
    cache.write_bytes(b"not a database")
    st = terms.build(ws)
    assert st["documents_read"] == 6 and _dump(ws) == ref
    assert terms.build(ws)["documents_read"] == 0
    # no folder can be made: everything in memory for one build
    shutil.rmtree(ws.root / "cache")
    (ws.root / "cache").write_text("a file where the folder would be")
    ingest.ingest(ws, [_write(src, "report_6.txt", _text(6))])
    st = terms.build(ws)
    assert st["documents_read"] == 7 and _dump(ws) == _from_scratch(ws, tmp_path)


def test_mentions_changed_behind_the_glossarys_back(project, tmp_path):
    """A document's mentions deleted outside a build (removing a document does this, so does reading one again)
    are written again; a build that finds the table changed while it worked writes everything."""
    ws, src = project
    terms.build(ws)
    doc = ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
    with ws.connect() as cx:
        cx.execute("DELETE FROM term_mentions WHERE passage_id >= ? AND passage_id < ?", passage_range(doc))
        ws.bump_corpus(cx)
    terms.build(ws)
    assert _dump(ws) == _from_scratch(ws, tmp_path)
    # another program writes between this build's look at the table and its writing
    ingest.ingest(ws, [_write(src, "report_7.txt", _text(7))])
    real = terms._label
    state = {"done": False}

    def meddle(spellings):
        if not state["done"]:
            state["done"] = True
            other = sqlite3.connect(ws.db_path)
            other.execute("INSERT INTO term_mentions(term_id, passage_id, start, end) VALUES ('tX', ?, 0, 1)",
                          (f"{doc}:9999",))
            other.commit()
            other.close()
        return real(spellings)

    terms._label = meddle
    try:
        terms.build(ws)
    finally:
        terms._label = real
    assert state["done"] and not ws.scalar("SELECT COUNT(*) FROM term_mentions WHERE term_id='tX'")
    assert _dump(ws) == _from_scratch(ws, tmp_path)


def test_themes_by_words_are_the_same(project, tmp_path):
    """Themes by words read the mentions in the order of the text, whatever order the table holds them in."""
    ws, src = project
    terms.build(ws)
    ingest.ingest(ws, [_write(src, "report_5.txt", _text(5)), _write(src, "whole.txt", _text(7, WHOLE))])
    terms.build(ws)
    rid = themes.run(ws, k=3, seed=0, mode="words")
    mine = [tuple(r) for r in ws.query("SELECT theme_id, passage_id, similarity FROM theme_members WHERE run_id=? "
                                       "ORDER BY passage_id", (rid,))]
    copy = tmp_path / "themes-copy"
    shutil.copytree(ws.root, copy, ignore=shutil.ignore_patterns("cache", "*.sqlite-shm"))
    other = Workspace.open(copy)
    with other.connect() as cx:
        cx.execute("DELETE FROM theme_runs")
        cx.execute("DELETE FROM theme_members")
    terms.build(other)  # from scratch: the table in the order of the text
    rid2 = themes.run(other, k=3, seed=0, mode="words")
    theirs = [tuple(r) for r in other.query("SELECT theme_id, passage_id, similarity FROM theme_members WHERE run_id=? "
                                            "ORDER BY passage_id", (rid2,))]
    assert mine == theirs


def test_the_kept_readings_stay_on_this_computer(project, tmp_path):
    from enlens_claims import bundle, measure

    ws, src = project
    terms.build(ws)
    out = tmp_path / "p.zip"
    bundle.export_project(ws, out)
    assert not [n for n in zipfile.ZipFile(out).namelist() if n.startswith("cache/") or "glossary.sqlite" in n]
    # enlens measure works on a copy without them, so its glossary timing starts afresh, and it times one more
    copy = measure.copy_project(ws.root, tmp_path / "m")
    assert not (copy / "cache").exists() and (copy / "enlens.sqlite").is_file()
    t = measure.measure_timings(Workspace.open(copy))
    assert t["steps"]["terms_one_more_document_read"] == 1, t
    assert t["steps"]["terms_one_more_document_seconds"] >= 0
    assert json.dumps(t)


# ---------------------------------------------------------------------------------------------
# the cases of the 0.16 review: each made the incremental glossary differ from a build from scratch
# ---------------------------------------------------------------------------------------------
FILLER = "Planners discuss the offshore wind farm and the ammonia export terminal. " * 3


def _small(tmp_path: Path, texts: dict[str, str]) -> tuple[Workspace, Path]:
    ws = Workspace.create(tmp_path / "ws")
    src = tmp_path / "src"
    ingest.ingest(ws, [_write(src, n, FILLER + t + "\n") for n, t in texts.items()])
    return ws, src


def test_a_build_stopped_after_reading_a_document_again(tmp_path):
    """A build that reads a document again (the joiner decides its runs otherwise now) keeps that reading at once; if
    it is stopped before writing, the next build must not take the old rows for rows of the new reading."""
    ws, src = _small(tmp_path, {"c.txt": "The turbine blade cracked. A new turbine blade was fitted.",
                                "d.txt": "Each turbine blade is inspected. The turbine blade coating matters.",
                                "s.txt": "The tur bine blade failed. Another tur bine blade failed too."})
    terms.build(ws)
    ingest.ingest(ws, [_write(src, "e.txt", FILLER + "The tur bine pieces. The tur bine parts. The tur bine bits.\n")])
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] >= 4   # after the two documents are read, before anything is written

    with pytest.raises(Exception, match="Stopped"):
        terms.build(ws, should_stop=stop)
    terms.build(ws)
    assert _dump(ws) == _from_scratch(ws, tmp_path)


def test_a_joiner_decision_that_flips_back(project, tmp_path):
    ws, src = project
    terms.build(ws)
    ingest.ingest(ws, [_write(src, "whole.txt", _text(7, WHOLE)), _write(src, "whole2.txt", _text(8, WHOLE))])
    terms.build(ws)
    for name in ("whole.txt", "whole2.txt"):
        ws.remove_document(ws.scalar("SELECT doc_id FROM documents WHERE path LIKE ?", (f"%{name}",)))
    st = terms.build(ws)
    assert st["documents_read"] == 1   # the spaced word is read apart again
    assert _dump(ws) == _from_scratch(ws, tmp_path)


def test_a_build_by_an_earlier_version_in_between(project, tmp_path):
    """A program still on an earlier ENLENS (the connector, say) rebuilds the glossary its way while this one runs:
    every mention rewritten with its document (0.17.2: the same table, whose `doc_id` this version leaves empty), its
    own terms, time and corpus version (`terms_corpus_version`, a name this version no longer writes), no build id. The
    next build must not take its rows for its own; the next opening keeps the glossary this version made after it."""
    ws, src = project
    terms.build(ws, max_terms=12)
    ingest.ingest(ws, [_write(src, "report_6.txt", _text(6))])
    copy = tmp_path / "old-build"
    shutil.copytree(ws.root, copy, ignore=shutil.ignore_patterns("cache", "*.sqlite-shm"))
    other = Workspace.open(copy)
    terms.build(other, max_terms=12)
    rows = [(r["term_id"], r["passage_id"], r["passage_id"].split(":")[0], r["start"], r["end"])
            for r in other.query("SELECT * FROM term_mentions")]
    trows = [tuple(r) for r in other.query("SELECT * FROM terms")]
    with ws.connect() as cx:   # what a build of 0.15 writes
        cx.execute("DELETE FROM terms")
        cx.execute("DELETE FROM term_mentions")
        cx.executemany("INSERT INTO terms VALUES (?,?,?,?,?,?,?,?)", trows)
        cx.executemany("INSERT INTO term_mentions VALUES (?,?,?,?,?)", rows)
        ws.set_meta("terms_corpus_version", ws.corpus_version(), cx)
        ws.set_meta("terms_built_at", "2026-11-09T05:00:00", cx)
    ingest.ingest(ws, [_write(src, "report_7.txt", _text(7))])
    terms.build(ws, max_terms=12)
    want = _from_scratch(ws, tmp_path, max_terms=12)
    assert _dump(ws) == want
    assert not ws.scalar("SELECT COUNT(*) FROM term_mentions WHERE doc_id IS NOT NULL")
    ws.close_all()
    again = Workspace.open(ws.root)
    assert terms.status(again)["built"] and not terms.status(again)["stale"] and _dump(again) == want
    again.close_all()


def test_a_kept_reading_replaced_while_a_build_runs(project, tmp_path, monkeypatch):
    """Another program's build puts another reading of a document in the file while this build works: this build
    goes on with the reading it decided on (read again here), never with places of one and terms of the other."""
    ws, src = project
    terms.build(ws)
    ingest.ingest(ws, [_write(src, "report_5.txt", _text(5))])
    real = terms._Readings.load
    state = {"n": 0}

    def load(self, doc_id, fp, digest):
        state["n"] += 1
        return None if state["n"] in (2, 9) else real(self, doc_id, fp, digest)   # as if replaced meanwhile

    monkeypatch.setattr(terms._Readings, "load", load)
    terms.build(ws)
    assert state["n"] > 9
    monkeypatch.setattr(terms._Readings, "load", real)
    assert _dump(ws) == _from_scratch(ws, tmp_path)
    terms.build(ws)
    assert _dump(ws) == _from_scratch(ws, tmp_path)


def test_spellings_across_other_spaces_are_joined_as_before(tmp_path):
    """"tu  rbine" (two spaces) is no run of the joiner's (one space), but a mention's spelling closes up spaces first
    and then joins it, as before 0.16: the term is "turbine blade"."""
    ws, src = _small(tmp_path, {"c.txt": "The turbine works.", "d.txt": "A turbine stops.",
                                **{f"p{i}.txt": f"The tu  rbine blade. It {w} in year {i}."
                                   for i, w in enumerate(["broke", "failed", "bent"])}})
    terms.build(ws)
    assert ws.scalar("SELECT label FROM terms WHERE stems LIKE '%blad'") == "turbine blade"
    assert _dump(ws) == _from_scratch(ws, tmp_path)


def test_a_locked_file_is_not_taken_for_a_damaged_one(project, monkeypatch):
    """"database is locked" (another program writing) is not damage: the file stays, this build goes on in memory."""
    from enlens_claims import searchindex

    ws, src = project
    terms.build(ws)
    cache = ws.root / "cache" / "glossary.sqlite"
    real = sqlite3.connect

    class Busy:
        def execute(self, *a):
            raise sqlite3.OperationalError("database is locked")

        def close(self):
            pass

    monkeypatch.setattr(searchindex.sqlite3, "connect", lambda *a, **k: Busy())
    with pytest.raises(sqlite3.OperationalError):
        searchindex.connect_cache(cache)
    assert cache.exists()
    st = terms.build(ws)   # nothing kept can be read: every document read, in memory
    assert st["documents_read"] == 6 and cache.exists()
    monkeypatch.setattr(searchindex.sqlite3, "connect", real)
    assert terms.build(ws)["documents_read"] == 0   # the readings are still there


def test_an_update_of_enlens_keeps_the_readings(project, monkeypatch):
    """The readings' stamp is the code that reads (terms.py, textutil.py), not ENLENS's version (0.16 review)."""
    import enlens_claims

    ws, src = project
    terms.build(ws)
    monkeypatch.setattr(enlens_claims, "__version__", "9.9.9")
    assert terms.build(ws)["documents_read"] == 0

"""0.18.0 (roadmap A0's open point): a reading the sync knows as an older or newer reading of a document here is the
same document.

Anna and Ben share a project with a two-column paper read by reader 1. Ben moves it to the new reader (*Read with the
new reader*). Until 0.18, Anna's next file brought her reading in as a second document, a sync clash. Now:

- each keeps the reading they have (nobody's text changes because the other moved theirs);
- the other's results are placed on this copy's reading as reread.py moves results: quotes on the same words, notes
  on their words; what has no place is kept as a record and counted, never lost;
- a check nobody changed since the last exchange makes no sync clash because of the move alone;
- readings that are not known as one (no earlier reading in common) still come in as documents of their own.
"""
from __future__ import annotations

import re

import pytest

from enlens_claims import bundle, claimcheck, notes, reread
from test_0_14_0_shared_projects import Person
from test_0_15_0_read_with_new_reader import HEAD, Q_DESAL, Q_JUDGE, Q_WATER, _add, _check, _paper, _same


@pytest.fixture
def paper_shared(tmp_path, monkeypatch):
    """Anna's project: the paper read by reader 1 and a check on it; Ben's copy from her first file."""
    from enlens_claims.store import Workspace

    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    with anna:
        anna.ws = Workspace.create(tmp_path / "anna-project")
        anna.doc = _add(anna.ws, monkeypatch, _paper(tmp_path))
        anna.cid, _at = _check(anna.ws, [(Q_WATER, "supports")])
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
    return anna, ben


def _doc_text(ws, doc: str) -> str:
    return ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,))


def _placed(ws, doc: str, hyp: str) -> list[tuple[str, bool]]:
    """(quote, whether it stands at its offsets in the document's text) for each excerpt of a check with a quote."""
    text = _doc_text(ws, doc)
    rows = ws.query("SELECT v.quote, v.start, v.end FROM verifications v JOIN user_claims u ON u.claim_id=v.subject_id "
                    "WHERE u.hyp_id=? AND v.quote IS NOT NULL", (hyp,))
    return [(r["quote"], r["start"] is not None and _same(text[r["start"]:r["end"]], r["quote"])) for r in rows]


def test_a_colleagues_older_reading_is_the_same_document_and_their_results_land_on_yours(paper_shared):
    anna, ben = paper_shared
    with ben:
        reread.move(ben.ws, anna.doc)  # Ben reads it with the new reader
        new_text = _doc_text(ben.ws, anna.doc)
        assert new_text != _doc_text(anna.ws, anna.doc)
    with anna:  # Anna, still on reader 1, checks another hypothesis and notes some words
        cid2, _ = _check(anna.ws, [(Q_DESAL, "partially_supports")])
        old_text = _doc_text(anna.ws, anna.doc)
        a = old_text.index(Q_JUDGE)
        nid = notes.add(anna.ws, anna.doc, a, a + len(Q_JUDGE), text="Check the water figure.")["note_id"]
    rep = ben.bring_in(anna.send())
    assert not rep["documents"]["clash"] and not rep["documents"]["new"]
    assert [(x["title"], x["not_placed"]) for x in rep["documents"]["other_reading"]] == \
        [(ben.ws.scalar("SELECT title FROM documents"), 0)]
    assert any("another reading" in line and "stays one document" in line for line in rep["lines"])
    assert rep["checks"]["new"] == 1 and not rep["checks"]["clash"]  # her first check, unchanged, makes no clash
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM documents") == 1
        assert _doc_text(ben.ws, anna.doc) == new_text  # Ben's reading stays as it is
        assert ben.ws.scalar("SELECT reader FROM documents") == reread.ingest.READER
        assert _placed(ben.ws, anna.doc, cid2) == [(Q_DESAL, True)]
        res = claimcheck.result(ben.ws, cid2)
        it = next(x for x in res["passages"] if x["quote"] == Q_DESAL)
        assert it["in_corpus"] and it["verdict"] == "partially_supports"
        n = ben.ws.query("SELECT * FROM notes WHERE note_id=?", (nid,))[0]
        assert _same(new_text[n["start"]:n["end"]], Q_JUDGE) and n["text"] == "Check the water figure."
        # no passage of Ben's copy is named after Anna's reading
        pids = {r[0] for r in ben.ws.query("SELECT passage_id FROM passages")}
        assert all(r[0] in pids or reread.is_tombstone(r[0])
                   for r in ben.ws.query("SELECT passage_id FROM verifications WHERE subject_kind='user_claim'"))
    rep = ben.bring_in(anna.send())  # again: nothing new
    assert not rep["documents"]["other_reading"] or all(x["not_placed"] == 0 for x in rep["documents"]["other_reading"])
    assert rep["checks"]["new"] == 0 and not rep["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM hypotheses") == 2


def test_a_colleagues_newer_reading_lands_on_your_older_one(paper_shared):
    anna, ben = paper_shared
    with ben:
        reread.move(ben.ws, anna.doc)
        cid2, _ = _check(ben.ws, [(Q_DESAL, "refutes")])  # Ben's check, on his new reading
    with anna:
        old_text = _doc_text(anna.ws, anna.doc)
    rep = anna.bring_in(ben.send())
    assert not rep["documents"]["clash"] and len(rep["documents"]["other_reading"]) == 1
    assert rep["checks"]["new"] == 1 and not rep["checks"]["clash"]
    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM documents") == 1
        assert _doc_text(anna.ws, anna.doc) == old_text and anna.ws.scalar("SELECT reader FROM documents") == 1
        assert _placed(anna.ws, anna.doc, cid2) == [(Q_DESAL, True)]
        assert _placed(anna.ws, anna.doc, anna.cid) == [(Q_WATER, True)]


def test_what_has_no_place_on_your_reading_is_kept_as_a_record_and_counted(paper_shared):
    anna, ben = paper_shared
    with ben:
        reread.move(ben.ws, anna.doc)
    with anna:  # a quote with reader 1's running head and page number in it: words Ben's reading has not in that order
        old_text = _doc_text(anna.ws, anna.doc)
        i = old_text.index(HEAD, 10)
        bad = old_text[i + len(HEAD) - 5:i + len(HEAD) + 22].strip()
        bad = bad[:bad.rfind(" ")]
        assert re.search(r"45-67 2 ", bad), bad
        cid2, _ = _check(anna.ws, [(bad, "supports"), (Q_WATER, "supports")])
    rep = ben.bring_in(anna.send())
    assert [x["not_placed"] for x in rep["documents"]["other_reading"]] == [1]
    assert any("1 result found no place in your reading and is kept as records" in line for line in rep["lines"])
    with ben:
        v = ben.ws.query("SELECT * FROM verifications WHERE quote=?", (bad,))[0]
        assert reread.is_tombstone(v["passage_id"]) and v["start"] is None  # points nowhere, as reread.py keeps it
        it = next(x for x in claimcheck.result(ben.ws, cid2)["passages"] if x["quote"] == bad)
        assert it["not_placed"] and it["verdict"] == "supports"  # its excerpt and its judgement are kept
        assert it["text"][it["quote_start"]:it["quote_end"]] == bad


def test_readings_not_known_as_one_still_come_in_as_documents_of_their_own(paper_shared):
    anna, ben = paper_shared
    with ben:  # Ben's reading differs, but not because he moved it: nothing says they are one document
        with ben.ws.connect() as cx:
            cx.execute("UPDATE documents SET text = text || ' (read again)', text_fp=NULL")
    rep = ben.bring_in(anna.send())
    assert not rep["documents"]["other_reading"] and len(rep["documents"]["clash"]) == 1


def test_what_claude_read_of_their_reading_still_counts_here(paper_shared):
    anna, ben = paper_shared
    with ben:
        reread.move(ben.ws, anna.doc)
        share_before = ben.ws.scalar("SELECT COALESCE(sent_share, 0) FROM documents")
    with anna:  # Claude read a passage of Anna's reading that has no place in Ben's (the running head's page break)
        pid = anna.ws.scalar("SELECT passage_id FROM passages WHERE text LIKE ? ORDER BY seq LIMIT 1", (f"%{HEAD}%",))
        with anna.ws.connect() as cx:
            cx.execute("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) VALUES "
                       "(?,?,?,?,?,?)", (pid, anna.doc, "claude_code", "x", "2026-11-11T00:00:00+00:00", "check"))
    rep = ben.bring_in(anna.send())
    assert rep["documents"]["other_reading"]
    with ben:
        assert ben.ws.scalar("SELECT COALESCE(sent_share, 0) FROM documents") >= share_before


def test_a_check_only_you_changed_after_moving_the_document_stays_yours_without_a_clash(paper_shared):
    """Ben moved the paper and then changed Anna's check; Anna changed nothing. Her file's check, placed on Ben's
    reading, differs from his, but its state before the move is one Ben had: his is the newer version."""
    anna, ben = paper_shared
    with ben:
        reread.move(ben.ws, anna.doc)
        claimcheck.set_note(ben.ws, anna.cid, "Ben's note, after the move")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["yours_newer"] == 1 and not rep["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (anna.cid,)) == "Ben's note, after the move"
    with anna:  # and a change Anna makes now is a real clash with Ben's: both are kept
        claimcheck.set_note(anna.ws, anna.cid, "Anna's note")
    rep = ben.bring_in(anna.send())
    assert len(rep["checks"]["clash"]) == 1

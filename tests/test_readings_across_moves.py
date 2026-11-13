"""0.18.1 (roadmap A0's open point, Part A, A2): one document across old and new readings, also after more than one
move. 0.18.0 built the rule (sync/readings.py: a reading among the other's earlier ones is the same document) and
tested it for one move (tests/test_0_18_0_old_readings.py). Here a document moved twice (reader 1, then 3, then the
current one) is still known as one with a colleague's copy that never moved it, in both directions, and the newer
reading is the one the mover keeps."""
from __future__ import annotations

import json

from enlens_claims import ingest, reread
from test_0_18_0_old_readings import _doc_text, paper_shared  # noqa: F401  (fixture)


def _move_twice(p, doc) -> list[str]:
    """Read the document with reader 3, then with the current reader; returns its texts' fingerprints before."""
    with p:
        was = ingest.READER
        ingest.READER = 3
        try:
            reread.move(p.ws, doc)
        finally:
            ingest.READER = was
        reread.move(p.ws, doc)
        assert p.ws.scalar("SELECT reader FROM documents WHERE doc_id=?", (doc,)) == ingest.READER
        return json.loads(p.ws.scalar("SELECT old_fps FROM documents WHERE doc_id=?", (doc,)))


def test_a_reading_two_moves_old_is_the_same_document_both_ways(paper_shared):
    anna, ben = paper_shared
    old_fps = _move_twice(ben, anna.doc)
    assert len(old_fps) == 2 and len(set(old_fps)) == 2   # reader 1's text, then reader 3's
    with ben:
        new_text = _doc_text(ben.ws, anna.doc)
    rep = ben.bring_in(anna.send())                         # Anna's reading by reader 1 reaches Ben
    assert not rep["documents"]["clash"] and not rep["documents"]["new"]
    assert len(rep["documents"]["other_reading"]) == 1
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM documents") == 1
        assert _doc_text(ben.ws, anna.doc) == new_text     # Ben keeps his newer reading
    rep = anna.bring_in(ben.send())                         # and Ben's newer reading reaches Anna
    assert not rep["documents"]["clash"] and not rep["documents"]["new"]
    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM documents") == 1
        assert anna.ws.scalar("SELECT reader FROM documents") == 1   # nobody's reading changes by itself

"""Roles (DESIGN-roles §4.5, §6.2 I4): a proposal accepted by one writer and declined by another, neither knowing the
other's answer. The owner's decision of 2026-11-12: neither counts. The proposal waits again, the change the accept
made is void in every copy, the Owner and every Co-owner are shown the clash, and the next answer given knowing both
decides it.

A crew of four copies in one shared folder: Anna the Owner, Ben a Co-owner, Carol a Member who proposes, Dana a
Member (a third copy). For each kind of proposal (add, remove, loosen, reread, blocks) Anna accepts and Ben declines
offline; their answers reach Dana in one order or the other; then Ben decides again (accept or decline).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from enlens_claims import ownership
from owner_helpers import (accept, add_doc, allow, choices, decline, has, leave_out, level, move, proposals,
                           reader_of, set_level, sync, view)
from owner_more_helpers import canon_of
from roles_helpers import doc_of, make_crew
from test_owner_more import NOTE


@pytest.fixture
def shared(tmp_path) -> Path:
    d = tmp_path / "Dávid" / "Közös mappa"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def crew(tmp_path, monkeypatch, shared):
    anna, ben, carol, dana = make_crew(tmp_path, monkeypatch, shared, co=("Ben",))
    with anna:
        ownership.set_accept_adds(anna.ws, False)
    set_level(anna, doc_of(anna, "jobs"), "none")
    sync(anna, ben, carol, dana)
    return anna, ben, carol, dana


def _propose(kind: str, crew, tmp_path) -> tuple[str, str]:
    """Carol's change of the given kind, proposed and seen by Anna and Ben. Returns (proposal id, document)."""
    anna, ben, carol, dana = crew
    if kind == "add":
        doc = add_doc(carol, tmp_path, "note", text=NOTE)
    elif kind == "remove":
        doc = doc_of(carol, "Grid")
        with carol:
            carol.ws.remove_document(doc)
    elif kind == "loosen":
        doc = doc_of(carol, "jobs")
        set_level(carol, doc, "cloud")
    elif kind == "reread":
        doc = doc_of(carol, "older field report")
        move(carol, doc)
    else:
        doc = doc_of(carol, "Interview")
        leave_out(carol, doc, 0)
    sync(carol, anna, ben, dana)
    got = [q for q in proposals(anna, state="waiting") if q["by"]["id"] == carol.id]
    assert [(q["kind"], q["doc"]) for q in got] == [(kind, doc)]
    return got[0]["id"], doc


def _answer_both_ways(crew, pid: str, anna_first: bool) -> None:
    anna, ben, carol, dana = crew
    accept(anna, pid)                     # neither has heard of the other's answer
    decline(ben, pid, "Not for this project")
    first, second = (anna, ben) if anna_first else (ben, anna)
    sync(first, dana)                     # the third copy hears of one answer first
    sync(second, dana)
    sync(carol, anna, ben, dana, rounds=2)


@pytest.mark.parametrize("kind", ["add", "remove", "loosen", "reread", "blocks"])
@pytest.mark.parametrize("again", ["accept", "decline"])
def test_accepted_and_declined_at_the_same_time_neither_counts_until_decided_again(kind, again, crew, tmp_path):
    anna, ben, carol, dana = crew
    before = canon_of(anna)
    with anna:
        old_reader = reader_of(anna, doc_of(anna, "older field report"))
    pid, doc = _propose(kind, crew, tmp_path)
    blocks_before = choices(anna, doc) if kind == "blocks" else None
    _answer_both_ways(crew, pid, anna_first=again == "accept")
    # in every copy: it waits, answered both ways, and the project's documents are as before the accept
    for p in crew:
        q = next(x for x in view(p)["proposals"] if x["id"] == pid)
        assert q["state"] == "waiting" and q["note"] == "answered both ways", p.name
        assert [x["id"] for x in q["clash"]["accepted"]] == [anna.id] and \
            [x["id"] for x in q["clash"]["declined"]] == [ben.id], p.name
        assert canon_of(p) == before, p.name
    for p in (anna, ben):
        assert [(c["kind"], c["proposal"]) for c in view(p)["clashes"]] == [("answer", pid)], p.name
        assert view(p)["proposals"][0]["can_decide"] or any(x["can_decide"] for x in view(p)["proposals"])
    for p in (carol, dana):
        assert view(p)["clashes"] == [], p.name
    # each copy as §4.5's table says
    if kind == "add":
        assert has(anna, doc) and has(carol, doc)              # nothing undone: it waits, as an addition does
    elif kind == "remove":
        for p in (anna, ben, dana):
            assert has(p, doc), p.name                         # back, in the accepter's copy too
        assert not has(carol, doc)                             # the proposer keeps her removal
    elif kind == "loosen":
        for p in crew:
            assert level(p, doc) == "none" and not view(p)["offers"], p.name
    elif kind == "reread":
        with anna:
            seen = anna.ws._conn().execute("SELECT read_from FROM canon_seen WHERE doc=?", (doc,)).fetchone()[0]
        assert reader_of(anna, doc) > old_reader and seen == carol.id     # kept, held as the proposer's reading
        assert not [q for q in proposals(anna) if q["kind"] == "reread" and q["by"]["id"] == anna.id]
        with anna:                                             # her row still says the accept's event, which is void
            r = anna.ws._conn().execute("SELECT read_n, read_by FROM canon WHERE doc=? AND by=?", (doc, anna.id)).fetchone()
            assert tuple(r) in ownership.canon(anna.ws._conn())[doc]["void"]["read"]
    else:
        assert choices(anna, doc) == blocks_before and choices(ben, doc) == blocks_before
        assert choices(carol, doc) != blocks_before            # the proposer's own choices stay on top
    # decided again, knowing both answers
    (accept if again == "accept" else decline)(ben, pid)
    sync(ben, anna, carol, dana, rounds=3)
    for p in crew:
        q = next(x for x in view(p)["proposals"] if x["id"] == pid)
        assert q["state"] == ("accepted" if again == "accept" else "declined") and q["clash"] is None, p.name
        assert not view(p)["clashes"], p.name
    after = canon_of(anna)
    for p in crew:
        assert canon_of(p) == after, p.name
    if again == "decline":
        assert after == before
    if kind == "add":
        held = [p.name for p in crew if has(p, doc)]
        assert held == (["Anna", "Ben", "Carol", "Dana"] if again == "accept" else ["Carol"])
    elif kind == "remove":
        held = [p.name for p in crew if has(p, doc)]
        assert held == ([] if again == "accept" else ["Anna", "Ben", "Dana"])
    elif kind == "loosen":
        if again == "accept":
            assert after[doc][2] == "cloud" and level(carol, doc) == level(ben, doc) == "cloud"
            for p in (anna, dana):
                assert level(p, doc) == "none" and [o["doc"] for o in view(p)["offers"]] == [doc], p.name
                allow(p, doc)
                assert level(p, doc) == "cloud", p.name
        else:
            assert all(level(p, doc) == "none" for p in crew)
    elif kind == "reread":
        if again == "accept":
            assert after[doc][1] > old_reader and all(reader_of(p, doc) == after[doc][1] for p in crew)
        else:
            assert after[doc][1] == old_reader and reader_of(ben, doc) == reader_of(dana, doc) == old_reader
    else:
        if again == "accept":
            assert all(choices(p, doc) == choices(carol, doc) for p in crew)
        else:
            assert choices(anna, doc) == choices(ben, doc) == choices(dana, doc) == blocks_before


def test_the_owners_accept_at_once_never_decides_an_addition_answered_both_ways(tmp_path, monkeypatch, shared):
    anna, ben, carol, dana = crew = make_crew(tmp_path, monkeypatch, shared, co=("Ben",))
    doc = add_doc(carol, tmp_path, "note", text=NOTE)
    sync(carol, ben)
    pid = [q for q in proposals(ben, state="waiting") if q["doc"] == doc][0]["id"]
    decline(ben, pid)                     # Ben declines it before Anna's copy accepted it at once (unknowing)
    sync(carol, anna)
    assert next(q for q in proposals(anna) if q["id"] == pid)["auto"]
    sync(anna, ben, carol, dana, rounds=3)
    for p in crew:
        q = next(x for x in view(p)["proposals"] if x["id"] == pid)
        assert q["state"] == "waiting" and q["clash"], p.name
        assert doc not in canon_of(p), p.name
    with anna:                            # her copy looks again and again: it does not answer by itself
        ownership.settle(anna.ws)
    sync(anna, ben, rounds=2)
    assert next(x for x in view(ben)["proposals"] if x["id"] == pid)["state"] == "waiting"

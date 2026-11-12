"""0.18.0 (roadmap L2): one owner, several collaborators, proposals by severity (ownership.py).

Three copies of one project (Anna made it and is its owner; Ben and Carol work with her), each with its own person
and ENLENS folder, exchange through one shared folder over several rounds. Each kind of change to the documents is
proposed, accepted and declined; the owner's own changes reach every copy; a stricter AI setting holds at once."""
from __future__ import annotations

from pathlib import Path

import pytest

from enlens_claims import ingest, ownership, people
from enlens_claims.sync import folder
from owner_helpers import (accept, add_doc, check, choices, decline, docs_of, has, included, join, leave_out, level,
                           log_kinds, move, proposals, reader_of, set_level, sync, view)
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)


@pytest.fixture
def shared_dir(tmp_path) -> Path:
    d = tmp_path / "Dávid" / "OneDrive - Közös egyetem" / "Csapat mappa"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def team(anna_and_ben, shared_dir, tmp_path, monkeypatch):
    """Anna (the maker, so the owner), Ben and Carol, all in the shared folder, after two rounds."""
    anna, ben = anna_and_ben
    for p in (anna, ben):
        with p:
            folder.set_folder(p.ws, str(shared_dir))
    carol = Person(tmp_path, "Carol", monkeypatch)
    join(carol, anna, tmp_path, shared_dir)
    sync(anna, ben, carol)
    return anna, ben, carol


def _one(p: Person, **kw) -> dict:
    got = proposals(p, **kw)
    assert len(got) == 1, got
    return got[0]


# ---- who the owner is ----------------------------------------------------------------------------------------
def test_the_maker_is_the_owner_in_every_copy(team):
    anna, ben, carol = team
    for p in team:
        v = view(p)
        assert v["owner"]["id"] == anna.id and v["is_owner"] == (p is anna) and v["how"] == "made"
        assert [x["id"] for x in v["people"] if x["owner"]] == [anna.id]
        assert not v["proposals"] and not v["can_claim"]
    assert view(ben)["can_take_over"] is None


def test_a_project_never_exchanged_is_its_makers_before_any_record(loaded, tmp_path, monkeypatch):
    anna = Person(tmp_path, "Anna", monkeypatch)
    anna.ws = loaded
    with anna:
        v = ownership.view(loaded)
        assert v["is_owner"] and v["owner"]["me"] and not loaded.query("SELECT 1 FROM ownership")
        assert ownership.settle(loaded)["owner"] is None  # nothing is written until it leaves the computer
        ownership.settle(loaded, leaving=True)
        assert ownership.owner(loaded._conn()) == anna.id and "owner" in log_kinds(anna)


def test_the_owners_own_changes_are_the_projects_at_once(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs")
    sync(anna, ben, carol)
    assert has(ben, doc) and has(carol, doc)
    for p in team:
        assert not view(p)["proposals"]
    with anna:
        anna.ws.remove_document(doc, why="Out of scope")
    sync(anna, ben, carol)
    assert not has(ben, doc) and not has(carol, doc)  # the owner's removal reaches every copy
    assert not view(ben)["proposals"] and not view(anna)["proposals"]
    with ben:
        assert "The owner" in ben.ws.scalar("SELECT why FROM research_log WHERE kind='document-removed' ORDER BY "
                                            "rowid DESC LIMIT 1")


# ---- adding a document (low) ---------------------------------------------------------------------------------
def test_an_added_document_is_accepted_at_once_by_the_owners_setting(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(ben, tmp_path, "desalination")
    p = _one(ben, state="waiting")
    assert p["kind"] == "add" and p["severity"] == "low" and p["mine"] and p["can_take_back"]
    assert view(ben)["documents"][doc]["state"] == "proposed"
    sync(ben, carol, anna)       # Carol reads it before the owner: it comes in for now
    assert has(carol, doc) and has(anna, doc)
    sync(ben, carol)
    for p_ in team:
        got = _one(p_, kind="add")
        assert got["state"] == "accepted" and got["auto"] and got["decided_by"]["id"] == anna.id
        assert not view(p_)["documents"] and has(p_, doc)
    assert "proposal" in log_kinds(ben) and "proposal-accepted" in log_kinds(anna)
    assert "proposal-accepted" in log_kinds(carol)  # the owner's entry travels
    # the owner can still undo it: her removal reaches every copy, the proposer's too
    with anna:
        anna.ws.remove_document(doc)
    sync(anna, ben, carol)
    assert not has(ben, doc) and not has(carol, doc)


def test_an_added_document_waits_for_one_click_and_can_be_declined(team, tmp_path):
    anna, ben, carol = team
    with anna:
        ownership.set_accept_adds(anna.ws, False)
    kept = add_doc(ben, tmp_path, "desalination")
    gone = add_doc(ben, tmp_path, "grid")
    hid = check(ben, "Desalination adds little to the cost of hydrogen.")
    sync(ben, carol, anna)
    waiting = proposals(anna, state="waiting")
    assert {x["doc"] for x in waiting} == {kept, gone} and all(x["can_decide"] for x in waiting)
    assert view(carol)["documents"][kept]["state"] == "proposed" and has(carol, gone)
    by_doc = {x["doc"]: x["id"] for x in waiting}
    accept(anna, by_doc[kept], "Fits the question")
    decline(anna, by_doc[gone], "A modelling study: not in scope")
    assert has(anna, kept) and not has(anna, gone)
    sync(anna, ben, carol)
    assert has(carol, kept) and not has(carol, gone)   # declined: it leaves the others
    assert has(ben, kept) and has(ben, gone)           # and stays in the proposer's copy only
    mine = {x["doc"]: x for x in proposals(ben)}
    assert mine[gone]["state"] == "declined" and mine[gone]["reason"] == "A modelling study: not in scope"
    assert mine[kept]["state"] == "accepted" and mine[kept]["reason"] == "Fits the question"
    assert view(ben)["documents"][gone]["state"] == "declined"
    assert "proposal-declined" in log_kinds(ben)
    # more rounds bring nothing back, and Ben's check on his documents is still his
    sync(ben, carol, anna, rounds=3)
    assert not has(carol, gone) and not has(anna, gone) and has(ben, gone)
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,))
    assert not proposals(carol, state="waiting") and not proposals(anna, state="waiting")


def test_a_proposer_can_take_an_added_document_back(team, tmp_path):
    anna, ben, carol = team
    with anna:
        ownership.set_accept_adds(anna.ws, False)
    doc = add_doc(ben, tmp_path, "grid")
    sync(ben, carol, anna)
    assert has(carol, doc)
    with ben:
        ownership.take_back(ben.ws, _one(ben, state="waiting")["id"])
    sync(ben, carol, anna)
    assert has(ben, doc) and not has(carol, doc) and not has(anna, doc)
    assert _one(anna)["state"] == "taken_back" and not proposals(anna, state="waiting")
    with carol:
        with pytest.raises(ownership.NotAllowed):
            ownership.take_back(carol.ws, _one(carol)["id"])


# ---- removing a document (high) ------------------------------------------------------------------------------
def test_a_removal_is_the_owners_decision(team):
    anna, ben, carol = team
    a, b = sorted(docs_of(anna))[:2]
    with ben:
        ben.ws.remove_document(a, why="Not about hydrogen")
        ben.ws.remove_document(b)
    sync(ben, carol, anna, rounds=3)
    assert has(anna, a) and has(carol, a) and has(anna, b)  # nothing leaves before the owner says so
    waiting = {x["doc"]: x for x in proposals(anna, state="waiting")}
    assert set(waiting) == {a, b} and all(x["severity"] == "high" and x["kind"] == "remove" for x in waiting.values())
    with ben:
        with pytest.raises(ownership.NotAllowed):
            ownership.accept(ben.ws, waiting[a]["id"])
    accept(anna, waiting[a]["id"])
    decline(anna, waiting[b]["id"], "Still cited in chapter 2")
    sync(anna, ben, carol)
    assert not has(anna, a) and not has(carol, a) and not has(ben, a)
    assert has(anna, b) and has(carol, b) and not has(ben, b)   # declined: Ben's copy keeps his change
    got = {x["doc"]: x for x in proposals(ben)}
    assert got[a]["state"] == "accepted" and got[b]["state"] == "declined" and got[b]["reason"]
    sync(ben, carol, anna, rounds=3)
    assert has(anna, b) and has(carol, b) and not has(ben, b) and not proposals(anna, state="waiting")
    assert {"proposal", "proposal-accepted", "proposal-declined"} <= set(log_kinds(carol))


# ---- who may read a document with AI -------------------------------------------------------------------------
def test_a_stricter_ai_setting_holds_at_once_and_a_looser_one_waits(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview")
    sync(anna, ben, carol)
    assert level(ben, doc) == "cloud"
    set_level(ben, doc, "none")                       # stricter: never a proposal
    assert level(ben, doc) == "none" and not proposals(ben)
    sync(ben, carol, anna)
    assert level(carol, doc) == "none" and level(anna, doc) == "none"
    sync(anna, ben, carol)
    out = set_level(carol, doc, "local")              # looser: held, proposed
    assert out["proposed"] == [doc] and level(carol, doc) == "none"
    p = _one(carol, state="waiting")
    assert p["kind"] == "loosen" and p["severity"] == "high" and p["detail"]["to"] == "local"
    sync(carol, ben, anna, rounds=3)
    assert level(anna, doc) == level(ben, doc) == level(carol, doc) == "none"   # nothing spreads silently
    accept(anna, _one(anna, state="waiting")["id"])
    assert level(anna, doc) == "local"
    sync(anna, ben, carol, rounds=3)
    assert level(ben, doc) == level(carol, doc) == level(anna, doc) == "local"
    # and the copies that had not followed yet did not make the owner's copy strict again
    assert _one(ben)["state"] == "accepted"


def test_a_declined_looser_setting_changes_nothing_anywhere(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="local")
    sync(anna, ben, carol)
    set_level(ben, doc, "cloud")
    sync(ben, anna, carol)
    decline(anna, _one(anna, state="waiting")["id"], "She asked us to keep it within the team")
    sync(anna, ben, carol, rounds=3)
    assert level(anna, doc) == level(ben, doc) == level(carol, doc) == "local"
    assert _one(ben)["state"] == "declined"


def test_who_made_it_stricter_meanwhile_keeps_it_stricter_when_a_looser_one_is_accepted(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="local")
    sync(anna, ben, carol)
    set_level(ben, doc, "cloud")                      # Ben proposes Claude may read it
    sync(ben, anna)
    set_level(carol, doc, "none")                     # Carol, not having heard of it, makes it stricter
    accept(anna, _one(anna, state="waiting")["id"])   # the owner accepts Ben's proposal before hearing Carol
    assert level(anna, doc) == "cloud"
    sync(carol, anna, ben, carol, anna, ben, rounds=2)
    assert level(anna, doc) == level(ben, doc) == level(carol, doc) == "none"   # the stricter setting holds


def test_a_looser_project_default_opens_nothing_in_a_collaborators_copy(team, tmp_path):
    from enlens_claims import access

    anna, ben, carol = team
    with anna:
        access.set_default(anna.ws, "local")
    doc = add_doc(anna, tmp_path, "interview")        # at the project's default: only a local AI
    sync(anna, ben, carol)
    assert level(ben, doc) == "local"
    with ben:
        ben.ws.query("SELECT 1")
        with ben.ws.connect() as cx:
            cx.execute("UPDATE documents SET ai_access=NULL WHERE doc_id=?", (doc,))
        access.set_default(ben.ws, "cloud")
    assert level(ben, doc) == "local"


# ---- Leave out / Restore (medium) ----------------------------------------------------------------------------
def test_leaving_out_passages_is_proposed_and_reaches_every_copy_when_accepted(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs")
    sync(anna, ben, carol)
    before = included(carol, doc)
    fp = leave_out(ben, doc, 1)
    p = _one(ben, state="waiting")
    assert p["kind"] == "blocks" and p["severity"] == "medium" and p["detail"]["left_out"] == 1
    sync(ben, carol, anna)
    assert included(carol, doc) == before and included(anna, doc) == before and not choices(carol, doc)
    accept(anna, _one(anna, state="waiting")["id"])
    assert choices(anna, doc) == {fp: 0}
    sync(anna, ben, carol)
    assert choices(carol, doc) == {fp: 0} and included(carol, doc) == included(ben, doc) == included(anna, doc)
    assert included(carol, doc) != before and _one(carol)["state"] == "accepted"
    sync(ben, carol, anna, rounds=2)
    assert not proposals(anna, state="waiting")


def test_declined_passages_stay_left_out_in_the_proposers_copy_only(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs")
    sync(anna, ben, carol)
    fp = leave_out(ben, doc, 1)
    sync(ben, anna, carol)
    decline(anna, _one(anna, state="waiting")["id"])
    fp2 = leave_out(anna, doc, 2)                     # the owner's own choice reaches every copy
    sync(anna, ben, carol, rounds=3)
    assert choices(anna, doc) == choices(carol, doc) == {fp2: 0}
    assert choices(ben, doc) == {fp: 0, fp2: 0}       # the project's, with his own on top
    assert [x["state"] for x in proposals(ben)] == ["declined"] and not proposals(anna, state="waiting")


# ---- reading a document again (medium) -----------------------------------------------------------------------
def test_a_new_reading_is_proposed_and_made_in_every_copy_when_accepted(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs", reader=1)
    sync(anna, ben, carol)
    assert reader_of(ben, doc) == reader_of(carol, doc) == 1
    hid = check(carol, "Electrolyser plants create local jobs mainly during construction.")
    with carol:
        mine = carol.ws.scalar("SELECT COUNT(*) FROM verifications v JOIN user_claims c ON c.claim_id=v.subject_id "
                               "WHERE c.hyp_id=? AND v.doc_id=?", (hid, doc))
    assert mine
    move(ben, doc)
    p = _one(ben, state="waiting")
    assert p["kind"] == "reread" and p["severity"] == "medium" and p["detail"]["to_reader"] == ingest.READER
    sync(ben, carol, anna)
    assert reader_of(anna, doc) == reader_of(carol, doc) == 1   # the others keep their reading until she accepts
    accept(anna, _one(anna, state="waiting")["id"])
    assert reader_of(anna, doc) == ingest.READER
    sync(anna, ben, carol, rounds=3)
    assert reader_of(carol, doc) == ingest.READER and _one(carol)["state"] == "accepted"
    with carol:  # Carol's results followed the document: placed on the new reading, none lost
        rows = carol.ws.query("SELECT v.passage_id FROM verifications v JOIN user_claims c ON c.claim_id=v.subject_id "
                              "WHERE c.hyp_id=? AND v.doc_id=?", (hid, doc))
        assert len(rows) == mine
        live = {r[0] for r in carol.ws.query("SELECT passage_id FROM passages WHERE doc_id=?", (doc,))}
        assert all(r[0] in live for r in rows)
        assert not ownership.moves_due(carol.ws) and not ownership.view(carol.ws)["to_apply"]
        fps = {p_.name: p_.ws.scalar("SELECT text_fp FROM documents WHERE doc_id=?", (doc,)) for p_ in (carol,)}
    with anna:
        assert anna.ws.scalar("SELECT text_fp FROM documents WHERE doc_id=?", (doc,)) == fps["Carol"]
    assert not proposals(anna, state="waiting")


def test_a_declined_new_reading_stays_in_the_proposers_copy(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs", reader=1)
    sync(anna, ben, carol)
    move(ben, doc)
    sync(ben, anna, carol)
    decline(anna, _one(anna, state="waiting")["id"], "After the deadline")
    sync(anna, ben, carol, rounds=3)
    assert reader_of(ben, doc) == ingest.READER and reader_of(anna, doc) == reader_of(carol, doc) == 1
    assert _one(ben)["state"] == "declined" and not proposals(anna, state="waiting")


# ---- conflicts -----------------------------------------------------------------------------------------------
def test_two_collaborators_propose_opposite_changes_to_one_document(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs")
    sync(anna, ben, carol)
    with ben:
        ben.ws.remove_document(doc)
    fp = leave_out(carol, doc, 1)
    sync(ben, carol, anna)
    waiting = {x["kind"]: x for x in proposals(anna, state="waiting")}
    assert set(waiting) == {"remove", "blocks"}
    assert waiting["remove"]["conflicts"] == [waiting["blocks"]["id"]]
    accept(anna, waiting["remove"]["id"])
    sync(anna, ben, carol, rounds=3)
    assert not has(anna, doc) and not has(carol, doc) and not has(ben, doc)
    got = {x["kind"]: x for x in proposals(carol)}
    assert got["blocks"]["state"] == "moot" and "removed" in got["blocks"]["note"]
    with anna:
        with pytest.raises(ValueError):
            ownership.accept(anna.ws, got["blocks"]["id"])
    assert fp and not proposals(anna, state="waiting")


def test_a_proposal_for_a_document_the_owner_has_since_removed(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="local")
    sync(anna, ben, carol)
    set_level(ben, doc, "cloud")
    with anna:
        anna.ws.remove_document(doc)
    sync(ben, anna, carol, rounds=3)
    assert _one(anna)["state"] == "moot" and not proposals(anna, state="waiting")
    assert not has(ben, doc) and not has(carol, doc)


# ---- ownership handed over, taken over ----------------------------------------------------------------------
def test_ownership_handed_over_with_proposals_waiting(team):
    anna, ben, carol = team
    a = sorted(docs_of(anna))[0]
    with ben:
        ben.ws.remove_document(a)
    sync(ben, anna, carol)
    with anna:
        with pytest.raises(KeyError):
            ownership.hand_over(anna.ws, "p" + "0" * 11 + "9")
        ownership.hand_over(anna.ws, carol.id, "On leave until March")
    with carol:
        with pytest.raises(ownership.NotAllowed):
            ownership.hand_over(carol.ws, ben.id)   # she has not heard of it yet
    sync(anna, ben, carol)
    for p in team:
        v = view(p)
        assert v["owner"]["id"] == carol.id and v["how"] == "handover" and v["is_owner"] == (p is carol)
    with anna:
        with pytest.raises(ownership.NotAllowed):
            ownership.accept(anna.ws, _one(anna, state="waiting")["id"])
    accept(carol, _one(carol, state="waiting")["id"])
    sync(carol, anna, ben, rounds=3)
    assert not has(anna, a) and not has(ben, a) and not has(carol, a)
    assert not proposals(anna, state="waiting") and "owner" in log_kinds(ben)
    # the new owner's own changes are the project's now; the old owner's are proposals
    b = sorted(docs_of(anna))[0]
    with anna:
        anna.ws.remove_document(b)
    sync(anna, carol, ben)
    assert has(carol, b) and _one(carol, state="waiting")["by"]["id"] == anna.id


def test_the_owner_leaves_and_a_collaborator_takes_over(team, shared_dir):
    import shutil

    anna, ben, carol = team
    with ben:
        with pytest.raises(ownership.NotAllowed):
            ownership.take_over(ben.ws)
    with anna:
        team_dir = shared_dir / folder.team_name(anna.ws)
    shutil.rmtree(team_dir / anna.id)               # Anna left the shared folder
    assert view(ben)["can_take_over"]
    with ben:
        ownership.take_over(ben.ws, "Anna left the group")
    sync(ben, carol)
    for p in (ben, carol):
        v = view(p)
        assert v["owner"]["id"] == ben.id and v["how"] == "takeover"
    a = sorted(docs_of(carol))[0]
    with carol:
        carol.ws.remove_document(a)
    sync(carol, ben)
    accept(ben, _one(ben, state="waiting")["id"])
    sync(ben, carol)
    assert not has(ben, a) and not has(carol, a)


def test_a_hand_over_counts_over_a_take_over_made_at_the_same_time(team, shared_dir, monkeypatch):
    anna, ben, carol = team
    monkeypatch.setattr(ownership, "owner_left", lambda *a: "Nothing was heard of the owner for 20 days.")
    with ben:
        ownership.take_over(ben.ws)
    with anna:
        ownership.hand_over(anna.ws, carol.id)
    sync(anna, ben, carol, rounds=3)
    for p in team:
        assert view(p)["owner"]["id"] == carol.id


# ---- the stricter setting between copies that have and have not followed ------------------------------------
def test_stale_strict_only_names_the_setting_the_owner_loosened(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="none")
    sync(anna, ben, carol)
    set_level(anna, doc, "local")
    with anna:
        ownership.settle(anna.ws)
        cx = anna.ws._conn()
        k = ownership.canon(cx)[doc]
        assert ownership.stale_strict(cx, doc, "none", k["ai_n"] - 1)       # the setting she loosened
        assert not ownership.stale_strict(cx, doc, "none", k["ai_n"])       # made stricter knowing of it
        assert ownership.stale_strict(cx, doc, "none", None)                # a copy that never followed
    sync(ben, anna)   # Ben's copy still says "none": it does not make the owner's strict again
    assert level(anna, doc) == "local"
    sync(anna, ben, carol)
    assert level(ben, doc) == level(carol, doc) == "local"
    assert people.me


# ---- the weak spots of the plan (§10), each probed ------------------------------------------------------------
def test_the_owner_accepts_an_addition_her_copy_does_not_hold_and_it_is_fetched(team, tmp_path, monkeypatch):
    """§6.9, §10.1 (`folder.fetch_documents`): she had removed it from her copy before she accepted it. The scratch
    project the fetch merges from is closed before it is removed (§9.3: Windows cannot remove an open database)."""
    import sqlite3

    from enlens_claims import store

    anna, ben, carol = team
    with anna:
        ownership.set_accept_adds(anna.ws, False)
    doc = add_doc(ben, tmp_path, "desalination")
    sync(ben, carol, anna)
    assert has(anna, doc)
    with anna:
        anna.ws.remove_document(doc, why="Not sure yet")
    sync(anna, ben, carol)
    assert not has(anna, doc) and has(ben, doc) and has(carol, doc)   # her removal of a mere proposal is hers
    p = _one(anna, state="waiting")
    opened = []
    real = store.Workspace.create.__func__

    def create(cls, *a, **kw):
        ws = real(cls, *a, **kw)
        opened.append(ws)
        return ws

    with monkeypatch.context() as m:
        m.setattr(store.Workspace, "create", classmethod(create))
        accept(anna, p["id"], "On second thought: yes")
    assert has(anna, doc)                                               # fetched from the shared folder at once
    assert opened and all(ws.root.name == "work" for ws in opened)
    for ws in opened:
        for cx in list(ws._all):
            with pytest.raises(sqlite3.ProgrammingError):
                cx.execute("SELECT 1")
    with anna:
        assert not anna.ws.query("SELECT 1 FROM sync_removed WHERE kind='document' AND key=?", (doc,))
        assert ownership.canon(anna.ws._conn())[doc]["state"] == "in"
    sync(anna, ben, carol, rounds=2)
    assert has(anna, doc) and has(ben, doc) and has(carol, doc) and _one(carol)["state"] == "accepted"


def test_a_document_the_owner_adds_again_comes_back_to_every_copy(team, tmp_path):
    """§10.1: canon says `in` again after a removal was applied in the collaborators' copies."""
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs")
    sync(anna, ben, carol)
    with anna:
        anna.ws.remove_document(doc)
    sync(anna, ben, carol)
    assert not has(ben, doc) and not has(carol, doc)
    again = add_doc(anna, tmp_path, "jobs")
    assert again == doc
    sync(anna, ben, carol, rounds=2)
    assert has(ben, doc) and has(carol, doc)
    for p in team:
        assert not view(p)["proposals"]


def test_who_left_out_a_passage_stays_known_when_the_projects_choices_are_applied(team, tmp_path):
    """§10.5: the owner's choices applied in a copy do not make every choice of the document the owner's."""
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs")
    sync(anna, ben, carol)
    fp_c = leave_out(carol, doc, 0)                   # Carol's own (a proposal)
    fp_a = leave_out(anna, doc, 2)                    # the owner's (the project's)
    sync(anna, carol)
    with carol:
        rows = {r[0]: r[1] for r in carol.ws.query("SELECT fp, person_id FROM block_choices WHERE doc_id=?", (doc,))}
    assert rows == {fp_c: carol.id, fp_a: anna.id}
    accept(anna, proposals(anna, state="waiting")[0]["id"])
    with anna:
        rows = {r[0]: r[1] for r in anna.ws.query("SELECT fp, person_id FROM block_choices WHERE doc_id=?", (doc,))}
    assert rows == {fp_c: carol.id, fp_a: anna.id}    # accepted: still who proposed it


def test_a_new_owner_keeps_what_was_declined_in_her_copy_as_her_own(team, tmp_path):
    """§10.9: an owner who used to be a collaborator, with her own declined (and waiting) changes still in her copy:
    her next change as the owner, and her answer to someone else's proposal, do not make them the project's."""
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "jobs")
    sync(anna, ben, carol)
    fp_old = leave_out(ben, doc, 1)                   # proposed, then declined
    sync(ben, anna)
    decline(anna, proposals(anna, state="waiting")[0]["id"])
    with anna:
        ownership.hand_over(anna.ws, ben.id)
    sync(anna, ben, carol)
    assert view(ben)["is_owner"] and choices(ben, doc) == {fp_old: 0}
    fp_new = leave_out(ben, doc, 0)                   # his first change of it as the owner
    sync(ben, anna, carol, rounds=2)
    assert choices(anna, doc) == choices(carol, doc) == {fp_new: 0}
    assert choices(ben, doc) == {fp_old: 0, fp_new: 0}
    fp_c = leave_out(carol, doc, 2)                   # Carol's proposal, which he accepts
    sync(carol, ben)
    accept(ben, proposals(ben, state="waiting")[0]["id"])
    sync(ben, anna, carol, rounds=2)
    assert choices(anna, doc) == choices(carol, doc) == {fp_new: 0, fp_c: 0}
    assert choices(ben, doc) == {fp_old: 0, fp_new: 0, fp_c: 0}
    with ben:
        assert set(ownership.canon(ben.ws._conn())[doc]["blocks"]) == {fp_new, fp_c}


def test_a_document_the_owner_removed_is_not_said_to_be_removed_by_you(anna_and_ben, tmp_path):
    """§10.6: a document a colleague's zip brings that the owner removed is reported as the owner's removal, not as
    "you removed earlier"; a collaborator's removal comes in as a proposal (and is listed as removed there, as before:
    removing it here too is the owner's own removal, or another proposal)."""
    from enlens_claims.sync.report import summary

    anna, ben = anna_and_ben
    doc = add_doc(anna, tmp_path, "jobs")
    ben.bring_in(anna.send())
    old = ben.send()                                   # a zip of Ben's that still holds it
    with anna:
        anna.ws.remove_document(doc)
    r = ben.bring_in(anna.send())
    assert not has(ben, doc)
    r = anna.bring_in(old)
    assert r["documents"]["removed_here"] == [] or doc not in r["documents"]["removed_here"]
    r = ben.bring_in(old)                              # his own old zip, as a third copy's would bring it
    assert r["documents"]["not_wanted"] and not r["documents"]["removed_here"]
    assert any("the owner removed it" in line for line in summary(r))
    assert not any("you removed earlier" in line for line in summary(r))
    other = sorted(docs_of(anna))[0]
    with ben:
        ben.ws.remove_document(other)
    r = anna.bring_in(ben.send())
    assert [x["kind"] for x in r["proposals"]["new"]] == ["remove"] and r["documents"]["removed_there"]
    assert has(anna, other)


def test_an_addition_marked_no_ai_with_the_switch_on_never_puts_its_words_in_the_folder(team, tmp_path, shared_dir):
    """§10.7 and §6.10: a collaborator's addition marked No AI, with the keep-out switch on, is proposed and accepted
    like any other; its title, ids and level travel, its words never; the other copies show it as not here."""
    anna, ben, carol = team
    with ben:
        folder.set_keep_out(ben.ws, True)
    marker = "Zebra-quartz-pelican marker sentence"
    from owner_helpers import TEXTS

    doc = add_doc(ben, tmp_path, "kept", ai="none",
                  text=TEXTS["interview"].replace("Interview with a plant manager", "Interview kept within the team")
                  + "\n" + marker + " that only the team may read.\n")
    sync(ben, carol, anna, rounds=2)
    for p in team:
        with p:
            k = ownership.canon(p.ws._conn()).get(doc)
            assert k and k["state"] == "in" and k["ai_access"] == "none", p.name
    assert has(ben, doc) and not has(anna, doc) and not has(carol, doc)
    assert [x["state"] for x in proposals(carol)] == ["accepted"]
    for f in shared_dir.rglob("*"):
        if f.is_file():
            assert marker.encode() not in f.read_bytes(), f
            if f.suffix == ".sqlite":
                import sqlite3

                cx = sqlite3.connect(f)
                try:
                    for (t,) in cx.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                        for row in cx.execute(f"SELECT * FROM {t}"):
                            assert not any(isinstance(v, str) and "Zebra-quartz" in v for v in row), (f, t)
                finally:
                    cx.close()
    assert level(ben, doc) == "none"


def test_loosening_several_documents_at_once_some_held_some_not(team, tmp_path):
    """§10.8: one change of several documents' AI setting in a collaborator's copy: those the project has stricter are
    held and proposed (one research-log entry for them), the others change (one entry), and `proposed` names them."""
    anna, ben, carol = team
    a = add_doc(anna, tmp_path, "interview", ai="local")
    b = add_doc(anna, tmp_path, "grid", ai="none")
    sync(anna, ben, carol)
    own = add_doc(ben, tmp_path, "desalination", ai="local")   # his own proposed addition: not held
    with ben:
        n = ben.ws.scalar("SELECT COUNT(*) FROM research_log")
    from enlens_claims import access

    with ben:
        out = access.set_documents(ben.ws, [a, b, own], setting="cloud")
    assert out["proposed"] == sorted([a, b])
    assert level(ben, a) == "local" and level(ben, b) == "none" and level(ben, own) == "cloud"
    with ben:
        new = ben.ws.query("SELECT kind, text, subject_kind FROM research_log ORDER BY rowid")[n:]
    kinds = [r[0] for r in new]
    assert kinds.count("proposal") == 1 and kinds.count("ai-access") == 1, new
    prop = next(r for r in new if r[0] == "proposal")
    assert "2 documents" in prop[1] and prop[2] == "documents"
    assert {x["doc"] for x in proposals(ben, state="waiting", kind="loosen")} == {a, b}
    with ben:   # the same again proposes nothing more
        n = ben.ws.scalar("SELECT COUNT(*) FROM research_log")
        again = access.set_documents(ben.ws, [a, b], setting="cloud")
        assert again["proposed"] == sorted([a, b]) and ben.ws.scalar("SELECT COUNT(*) FROM research_log") == n


def test_a_looser_setting_asked_for_again_after_a_decline_is_a_new_proposal(team, tmp_path):
    """Builder B's check: after the owner declined a looser setting, asking for it again reaches the owner again (it
    was answered "proposed" while nothing new was written)."""
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="none")
    sync(anna, ben)
    assert set_level(ben, doc, "cloud")["proposed"] == [doc]
    assert set_level(ben, doc, "cloud")["proposed"] == [doc]          # again while it waits: still the one
    assert len(proposals(ben, kind="loosen")) == 1
    sync(ben, anna)
    decline(anna, _one(anna, state="waiting")["id"], "Not yet")
    sync(anna, ben)
    assert set_level(ben, doc, "cloud")["proposed"] == [doc] and level(ben, doc) == "none"
    assert sorted(x["state"] for x in proposals(ben, kind="loosen")) == ["declined", "waiting"]
    sync(ben, anna)
    accept(anna, _one(anna, state="waiting")["id"])
    sync(anna, ben)
    assert level(ben, doc) == level(anna, doc) == "cloud"


def test_a_colleagues_removal_is_said_as_what_it_is_in_a_project_with_an_owner(anna_and_ben, tmp_path):
    """Builder B's check: what came in says a collaborator's removal as a proposal, the owner's as the project's, and
    the owner's decline of this person's own addition as "in your copy only" (not "remove it here too if you
    agree"). The listing `removed_there` stays as it was."""
    from enlens_claims.sync.report import summary

    anna, ben = anna_and_ben
    a, b = sorted(docs_of(anna))[:2]
    with anna:
        ownership.set_accept_adds(anna.ws, False)
        title_a = anna.ws.scalar("SELECT title FROM documents WHERE doc_id=?", (a,))
        title_b = anna.ws.scalar("SELECT title FROM documents WHERE doc_id=?", (b,))
    with ben:
        ben.ws.remove_document(a)
    x = add_doc(ben, tmp_path, "grid")
    r = anna.bring_in(ben.send())
    lines = summary(r)
    assert r["documents"]["removed_there"] == [title_a]
    assert any(line.startswith("Ben proposes removing “") and "waits for the owner" in line for line in lines), lines
    assert not any("remove it here too" in line for line in lines), lines
    decline(anna, next(p["id"] for p in proposals(anna, state="waiting") if p["doc"] == x), "Out of scope")
    with anna:
        anna.ws.remove_document(b)
    r = ben.bring_in(anna.send())
    lines = summary(r)
    assert any(line.startswith(f"The owner removed “{title_b}”") for line in lines), lines
    assert any("stays in your copy only: the owner did not accept" in line for line in lines), lines
    assert not any("remove it here too" in line for line in lines), lines
    assert has(ben, x) and not has(ben, b)


def test_a_copy_without_the_owners_rules_stops_at_a_bundle_in_words(team, tmp_path, monkeypatch):
    """The shared folder's bundles carry L2's tables and rules: they need format 3. A copy that knows only format 2 (the
    shared folder without one owner) stops at them with "needs a newer ENLENS", and merges nothing of them."""
    from enlens_claims.sync import formats

    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "grid")
    sync(anna, rounds=1)
    with anna:
        bundles = sorted((folder.chosen(anna.ws) / folder.team_name(anna.ws) / anna.id / "bundles").glob("*.zip"))
    import json
    import zipfile

    with zipfile.ZipFile(bundles[-1]) as zf:
        meta = json.loads(zf.read("bundle.json"))
    assert meta["sync_needs"] == 3 and meta["sync_format"] == formats.FORMAT
    monkeypatch.setattr(formats, "FORMAT", 2)   # Ben's ENLENS: the shared folder, without the owner's rules
    with ben:
        out = folder.sync_now(ben.ws)
    newer = [x for x in out["problems"] if x["kind"] == "newer_format"]
    assert newer and newer[0]["person"]["id"] == anna.id and "newer ENLENS" in newer[0]["message"]
    assert not has(ben, doc)

"""0.18.0 (roadmap L2), from the stage-4 review: after a take-over, a former owner who is offline and still believes
they own the project changes its documents. Their late changes must not become the project's (ownership.py: the new
owner's copy writes the rows that count again under its own place, `_Ctx.restamp`; a copy that followed a row which
no longer counts follows the project's again), and their late answer to a proposal must not override the owner's
(`_decisions`: the later owner's answer counts)."""
from __future__ import annotations

from pathlib import Path

import pytest

from enlens_claims import ownership
from enlens_claims.sync import folder
from owner_helpers import (accept, add_doc, choices, decline, docs_of, has, join, leave_out, level, proposals,
                           set_level, sync, view)
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)


@pytest.fixture
def team(anna_and_ben, tmp_path, monkeypatch):
    """Anna (the maker, so the owner), Ben and Carol in one shared folder; the owner counts as gone, so a
    collaborator may take the project over."""
    shared = tmp_path / "Közös mappa"
    shared.mkdir()
    anna, ben = anna_and_ben
    for p in (anna, ben):
        with p:
            folder.set_folder(p.ws, str(shared))
    carol = Person(tmp_path, "Carol", monkeypatch)
    join(carol, anna, tmp_path, shared)
    sync(anna, ben, carol)
    monkeypatch.setattr(ownership, "owner_left", lambda *a: "Nothing was heard of the owner for 20 days.")
    return anna, ben, carol


def _take_over(p: Person) -> None:
    with p:
        ownership.take_over(p.ws)


def test_a_former_owners_late_loosening_does_not_spread(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="none")
    sync(anna, ben, carol)
    _take_over(ben)
    sync(ben, carol)
    assert view(carol)["owner"]["id"] == ben.id
    set_level(anna, doc, "cloud")      # offline, she still believes she owns the project
    view(anna)                         # the Team tab: her change is written down as the owner's
    sync(anna, ben, carol, rounds=3)
    assert view(anna)["owner"]["id"] == ben.id
    assert (level(ben, doc), level(carol, doc), level(anna, doc)) == ("none", "none", "none")
    waiting = proposals(ben, state="waiting", kind="loosen")   # her late setting: a proposal to Ben now
    assert [(p["doc"], p["by"]["id"], p["detail"]["to"]) for p in waiting] == [(doc, anna.id, "cloud")]


def test_a_former_owners_late_removal_is_her_proposal(team):
    anna, ben, carol = team
    doc = sorted(docs_of(anna))[0]
    _take_over(ben)
    sync(ben, carol)
    with anna:
        anna.ws.remove_document(doc)
    view(anna)
    sync(anna, ben, carol, rounds=3)
    assert has(ben, doc) and has(carol, doc)
    waiting = proposals(ben, state="waiting", kind="remove")
    assert [(p["doc"], p["by"]["id"]) for p in waiting] == [(doc, anna.id)]


def test_a_copy_that_followed_the_former_owner_first_follows_the_new_owner(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="none")
    sync(anna, ben, carol)
    gone = sorted(docs_of(anna) - {doc})[0]
    _take_over(ben)                    # Ben's record has not reached anyone yet
    set_level(anna, doc, "cloud")
    fp = leave_out(anna, doc)
    with anna:
        anna.ws.remove_document(gone)
    view(anna)
    sync(anna, carol)                  # Carol follows Anna, the owner as far as she knows
    assert level(carol, doc) == "cloud" and fp in choices(carol, doc) and not has(carol, gone)
    sync(ben, carol, anna, rounds=3)   # then Ben's take-over and his rows arrive
    assert view(carol)["owner"]["id"] == ben.id
    assert level(carol, doc) == "none" and fp not in choices(carol, doc) and has(carol, gone)
    assert not [p for p in proposals(ben) if p["by"]["id"] == carol.id]   # nothing proposed in Carol's name


def test_the_owners_answer_counts_over_a_former_owners_late_one(team):
    anna, ben, carol = team
    doc = sorted(docs_of(carol))[0]
    with carol:
        carol.ws.remove_document(doc)
    sync(carol, anna, ben)
    pid = proposals(anna, state="waiting", kind="remove")[0]["id"]
    _take_over(ben)
    accept(ben, pid)                   # the owner accepts Carol's removal
    decline(anna, pid)                 # Anna, offline, declines it
    sync(ben, carol, anna, rounds=3)
    for p in (anna, ben, carol):
        assert [x["state"] for x in proposals(p) if x["id"] == pid] == ["accepted"], p.name
        assert not has(p, doc), p.name


def test_a_stricter_setting_a_former_owner_made_late_is_never_loosened_on_the_way(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="cloud")
    sync(anna, ben, carol)
    _take_over(ben)                    # Ben's record has not reached anyone yet
    set_level(anna, doc, "none")       # a stricter setting holds at once, whoever makes it
    view(anna)
    sync(anna, carol)
    assert level(carol, doc) == "none"
    sync(ben, carol, rounds=1)         # Ben's take-over and rows (still "Claude may read it") reach Carol first
    assert view(carol)["owner"]["id"] == ben.id and level(carol, doc) == "none"
    sync(ben, carol, anna, rounds=3)
    assert (level(ben, doc), level(carol, doc), level(anna, doc)) == ("none", "none", "none")

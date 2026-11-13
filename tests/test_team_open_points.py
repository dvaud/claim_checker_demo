"""0.18.1 (roadmap L, "Still to do" after 0.17.0; Part A, A1): the open points of working together, each first tried
on the code as 0.18.0 left it. A point the 0.18 roles rework had already fixed keeps its test here, so it stays fixed.

1. A collaborator's own removal of a document is undone only when the project went on knowing of it.
2. *Take over* a project shared before 0.17.0 does not turn every earlier removal into a proposal.
3. After a take-over, a former owner's late answer to a proposal the new owner has not answered is not *Accepted*.
5. An older ENLENS refuses, in words, a zip whose format is newer than it understands.
6. *Not now* on a take-over holds for the person in every browser.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from enlens_claims import ownership, removed
from enlens_claims.sync import folder
from owner_helpers import accept, add_doc, docs_of, follow, has, join, proposals, sync, view
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)


@pytest.fixture
def team(anna_and_ben, tmp_path, monkeypatch):
    """Anna (the maker, so the owner), Ben and Carol (Members) in one shared folder; the owner counts as gone, so
    Ben may take the project over."""
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


def _remove(p: Person, doc: str) -> None:
    with p:
        p.ws.remove_document(doc)


# ---- 3. a former owner's late answer ------------------------------------------------------------------------------
def test_a_former_owners_late_accept_is_not_shown_as_accepted(team):
    anna, ben, carol = team
    doc = sorted(docs_of(carol))[0]
    _remove(carol, doc)
    sync(carol, anna, ben)
    pid = proposals(anna, state="waiting", kind="remove")[0]["id"]
    with ben:
        ownership.take_over(ben.ws)
    accept(anna, pid)                  # Anna, offline, still believes she owns the project
    sync(ben, carol, anna, rounds=3)
    follow(anna)
    follow(carol)
    sync(ben, carol, anna, rounds=3)
    for p in (anna, ben, carol):
        assert [x["state"] for x in proposals(p) if x["id"] == pid] == ["waiting"], p.name
    assert has(ben, doc)               # nobody whose word counts accepted it
    # her copy, which removed it when she accepted, keeps her removal as her own proposal to Ben (as a late removal)
    assert sorted((x["by"]["id"], x["state"]) for x in proposals(ben, kind="remove")) == \
        sorted([(carol.id, "waiting"), (anna.id, "waiting")])


# ---- 1. a collaborator's own removal ------------------------------------------------------------------------------
def _out_and_in(p: Person, tmp_path: Path, doc: str) -> None:
    """The owner takes a document out of the project and adds the same file again (the same document)."""
    _remove(p, doc)
    view(p)
    (tmp_path / "again").mkdir(exist_ok=True)
    assert add_doc(p, tmp_path / "again", "interview") == doc
    view(p)


def test_a_members_removal_stands_when_the_owner_went_on_without_knowing_it(team, tmp_path):
    """Anna takes a document out and puts it back; Carol, who has heard of neither, removes it. Anna's going on did
    not know of Carol's removal, so it does not undo it: Carol's copy keeps it out and her proposal waits."""
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview")
    sync(anna, ben, carol)
    assert has(carol, doc)
    _out_and_in(anna, tmp_path, doc)
    _remove(carol, doc)
    view(carol)
    sync(anna, ben, carol, rounds=3)
    assert not has(carol, doc)
    assert [p["state"] for p in proposals(anna, kind="remove") if p["by"]["id"] == carol.id] == ["waiting"]


def test_a_members_removal_is_spent_only_with_a_word(team, tmp_path):
    """The owner saw Carol's removal and went on (took the document out and put it back): the removal is spent, and
    Carol's copy says why the document came back."""
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview")
    sync(anna, ben, carol)
    _remove(carol, doc)
    sync(carol, anna)
    assert [p["state"] for p in proposals(anna, kind="remove")] == ["waiting"]
    _out_and_in(anna, tmp_path, doc)
    sync(anna, carol, rounds=3)
    assert has(carol, doc)             # it came back to her copy, as to every copy
    states = [(p["state"], p["note"]) for p in proposals(carol, kind="remove") if p["by"]["id"] == carol.id]
    assert states == [("moot", "The document was removed from the project and added to it again since.")]

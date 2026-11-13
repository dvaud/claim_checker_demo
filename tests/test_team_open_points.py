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


# ---- 2. *Become the owner* of a project exchanged before there were owners ----------------------------------------
def test_becoming_the_owner_of_an_older_project_says_what_becomes_a_proposal(tmp_path, monkeypatch):
    """What Ben removed and left out before the project had an owner becomes his proposals to Anna once she claims
    it (0.18's rule): his Team tab says so once, instead of the proposals coming unexplained."""
    from owner_more_helpers import as_before_018, join_zip, small_project
    from owner_helpers import leave_out

    shared = tmp_path / "shared"
    shared.mkdir()
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    ben = Person(tmp_path, "Ben", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")
    for p in (anna, ben):
        as_before_018(p)
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben)
    gone, jobs = sorted(docs_of(ben))[:2]
    _remove(ben, gone)
    leave_out(ben, jobs, 1)
    sync(ben, anna)
    assert not view(ben)["notices"]
    with anna:
        ownership.claim(anna.ws)
    sync(anna, ben, anna, rounds=2)
    texts = [n["text"] for n in view(ben)["notices"] if n["kind"] == "claimed"]
    assert len(texts) == 1 and "1 document you removed and what you left out of 1 document" in texts[0], texts
    assert "now your proposals to Anna" in texts[0]
    assert not [n for n in view(anna)["notices"] if n["kind"] == "claimed"]
    sync(anna, ben, rounds=2)
    assert len([n for n in view(ben)["notices"] if n["kind"] == "claimed"]) == 1   # said once


# ---- 5. a zip from a newer ENLENS -------------------------------------------------------------------------------
def test_a_zip_from_a_newer_enlens_is_refused_in_words(tmp_path, monkeypatch):
    import json
    import zipfile

    from enlens_claims import bundle
    from enlens_claims.sync import formats
    from owner_more_helpers import small_project

    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    z = tmp_path / "anna.zip"
    with anna:
        bundle.export_project(anna.ws, z)
    newer = tmp_path / "from-the-future.zip"
    with zipfile.ZipFile(z) as src, zipfile.ZipFile(newer, "w") as out:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith("bundle.json"):
                meta = json.loads(data)
                meta.update(sync_format=formats.FORMAT + 1, sync_needs=formats.FORMAT + 1, version="9.9.9")
                data = json.dumps(meta).encode("utf-8")
            out.writestr(info, data)
    dest = tmp_path / "Ben's copy"
    with pytest.raises(ValueError, match=r"newer ENLENS \(9\.9\.9\).*Update ENLENS.*Nothing was changed"):
        bundle.import_project(newer, dest)
    assert not dest.exists() and not dest.with_name(dest.name + ".importing").exists()
    ws = bundle.import_project(z, tmp_path / "Ben's other copy")   # the same zip, as this ENLENS wrote it, opens
    try:
        assert ws.counts()
    finally:
        ws.close_all()


# ---- 6. *Not now* on a take-over ------------------------------------------------------------------------------------
def test_not_now_on_a_take_over_holds_for_the_person_in_the_project(team):
    anna, ben, carol = team
    with ben:
        ownership.take_over(ben.ws)
    sync(ben, carol)
    v = view(carol)
    qs = [q for q in v["questions"] if q["kind"] == "takeover"]
    assert len(qs) == 1 and v["later"] == []
    with carol:
        ownership.put_off(carol.ws, qs[0]["id"])
        ownership.put_off(carol.ws, qs[0]["id"])     # (twice: kept once)
        with pytest.raises(KeyError):
            ownership.put_off(carol.ws, "o-no-such-question")
    v = view(carol)                                  # what any browser gets: the question, and that it was put off
    assert [q["id"] for q in v["questions"]] == [qs[0]["id"]] and v["later"] == [qs[0]["id"]]
    assert view(anna)["later"] == []                  # Carol's alone
    follow(carol)
    assert view(carol)["later"] == []                 # answered: nothing put off is left to show


# ---- a second take-over at the same place (found by the randomised roles test, seed 34) ----------------------------
def test_a_second_take_over_at_the_same_place_is_refused_in_words(team):
    """Carol took the project over from Ben at place 3; she then followed Dana for place 2 (a rival of Ben's). Her
    second take-over at place 3, after Dana, would never reach colleagues who hold the first (a copy never replaces a
    record it holds): it is refused, and says what to do instead."""
    anna, ben, carol = team
    dana = "p" + "d" * 12
    with carol:
        with carol.ws.connect() as cx:
            cx.execute("INSERT INTO ownership(seq, owner, by, at, kind, after, why) VALUES (2, ?, ?, '2026', "
                       "'takeover', ?, NULL)", (ben.id, ben.id, anna.id))
            cx.execute("INSERT INTO ownership(seq, owner, by, at, kind, after, why) VALUES (2, ?, ?, '2026', "
                       "'takeover', ?, NULL)", (dana, dana, anna.id))
            cx.execute("INSERT INTO ownership(seq, owner, by, at, kind, after, why) VALUES (3, ?, ?, '2026', "
                       "'takeover', ?, NULL)", (carol.id, carol.id, ben.id))
            cx.execute("INSERT OR REPLACE INTO owner_pins(seq, by, owner, state, at) VALUES (2, ?, ?, 'followed', "
                       "'2026')", (dana, dana))
        assert ownership.owner(carol.ws._conn()) == dana
        with pytest.raises(ownership.NotAllowed, match="once before at this point.*would not reach them"):
            ownership.take_over(carol.ws)
        assert ownership.owner(carol.ws._conn()) == dana          # nothing written

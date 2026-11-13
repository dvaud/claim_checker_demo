"""Copies agree again after rival take-overs (0.18.1, roadmap L; found by the randomised roles test, seed 0, rule (a)).

Carol and Ben both take the project over from Anna, neither having heard of the other. Ben follows Carol and then
takes it over from her (a third place). In the end everyone, Ben too, follows Ben's first take-over: the third place
is gone from every chain, and Ben is the owner of the second place again. His copy then writes its rows of the
documents and the roles again for that place, numbered above everything it wrote before. Each table keeps one row per
key and writer, and the higher number must stay: when the place a row names came first instead, Ben's older rows of
the third place outranked his newer ones in every other copy. Those copies then never heard of anything Ben did as the
owner (a document he removed stayed in, a Co-owner he made stayed a Member), and Ben's copy took its own older rows
for forged ones.
"""
from __future__ import annotations

import pytest

from enlens_claims import ownership
from enlens_claims.sync import folder
from owner_helpers import docs_of, follow, has, join, set_role, sync
from roles_helpers import project
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)


@pytest.fixture
def team(anna_and_ben, tmp_path, monkeypatch):
    """Anna (the maker, so the owner), Ben and Carol (Members) in one shared folder; the owner counts as gone, so
    either may take the project over."""
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


def _follow_record(p: Person, seq: int, by: str) -> None:
    with p:
        ownership.follow_owner(p.ws, seq, by)
        for d in ownership.moves_due(p.ws):
            ownership.move_now(p.ws, d)


def _owner_rows(p: Person, who: str) -> dict[str, set]:
    """The places `who`'s rows of the documents and the roles name in this copy."""
    with p:
        return {t: {r[0] for r in p.ws.query(f"SELECT DISTINCT owner_seq FROM {t} WHERE by=?", (who,))}
                for t in ("canon", "roles")}


def test_an_owner_back_at_an_earlier_place_is_heard_by_every_copy(team):
    anna, ben, carol = team
    doc = sorted(docs_of(anna))[0]
    # Carol and Ben take the project over from Anna, neither having heard of the other's take-over (place 2)
    _take_over(carol)
    _take_over(ben)
    sync(carol, ben, anna)
    # Ben follows Carol, and then takes the project over from her (place 3): his rows name place 3 now
    follow(ben, carol.id)
    with ben:
        assert [(r["seq"], r["owner"]) for r in ownership.chain(ben.ws._conn())] == \
            [(1, anna.id), (2, carol.id)]
    _take_over(ben)
    sync(ben, carol, anna, rounds=3)
    assert _owner_rows(anna, ben.id) == {"canon": {3}, "roles": {3}}
    # every copy, Ben's too, follows Ben's first take-over: place 3 is in no chain any more
    for p in (anna, carol, ben):
        _follow_record(p, 2, ben.id)
    sync(ben, carol, anna, rounds=3)
    for p in (anna, ben, carol):
        with p:
            assert [(r["seq"], r["owner"]) for r in ownership.chain(p.ws._conn())] == \
                [(1, anna.id), (2, ben.id)], p.name
            assert not ownership.owner_questions(p.ws._conn()), p.name
    # Ben's rows of place 2, written after his rows of place 3, replaced them in every copy
    for p in (anna, carol):
        assert _owner_rows(p, ben.id) == {"canon": {2}, "roles": {2}}, p.name
    assert project(anna) == project(ben) == project(carol)
    # what Ben does as the owner now reaches everyone
    with ben:
        ben.ws.remove_document(doc)
    set_role(ben, carol, "co")
    sync(ben, carol, anna, rounds=3)
    assert not has(anna, doc) and not has(carol, doc)
    for p in (anna, ben, carol):
        with p:
            assert ownership.role_of(p.ws._conn(), carol.id) == "co", p.name
    assert project(anna) == project(ben) == project(carol)
    # and Ben's copy never took its own older rows for forged ones
    with ben:
        assert [x for x in ownership.refused(ben.ws._conn()) if x["kind"] in ("canon", "roles")] == []

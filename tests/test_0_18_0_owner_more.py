"""0.18.0 (roadmap L2), builder C: scenarios that try to break one owner and several collaborators (ownership.py).

Three or four copies of one project, each with its own person and ENLENS folder (some under a Windows-like home with
accents), exchange through one shared folder with accents and spaces in its path, or by zips only, over many rounds.
The intended outcome of each case is the plan's (`.claude/coordination/0.18-L2-plan.md` §5 and §6). The twelve tests
that showed a defect of the WIP (14af59e) were marked `xfail(strict=True)` until builder A fixed it (5e3dc72): they need
A's code (they fail on 14af59e alone).
"""
from __future__ import annotations

import shutil
import unicodedata
from pathlib import Path

import pytest

from enlens_claims import ingest, ownership, reread, sharing
from enlens_claims.store import Workspace
from enlens_claims.sync import folder
from owner_helpers import (TEXTS, accept, add_doc, allow, check, choices, decline, docs_of, follow, has, included,
                           join, leave_out, level, move, proposals, reader_of, set_level, sync, view)
from owner_more_helpers import (PersonAt, as_017_zip, as_before_018, canon_of, everything, file_names, join_zip,
                                levels_of, log_rows, owner_of, readers_of, results_of, send, small_project, states_of,
                                waiting, zips)
from test_0_14_0_shared_projects import Person

NOTE = ("Field notes from the coastal site\n\n"
        "The desalination plant at the coastal site ran at half its capacity in the dry season. Operators blamed "
        "fouled membranes and a shortage of spare parts.\n\n"
        "Fishermen said the brine outfall had moved twice since the plant opened, each time after a complaint.\n\n"
        "The municipality bought the plant's surplus water for the town's reservoir during the summer months.\n")
POLICY = ("Hydrogen export policy brief\n\n"
          "Export agreements for green hydrogen name water use only in passing. Few of them say who pays for "
          "desalination or how brine is treated.\n\n"
          "Ports need new terminals for ammonia, which take five to eight years to permit and build.\n\n"
          "Importers asked for certificates of origin that count the electricity used for desalination too.\n")


@pytest.fixture
def shared(tmp_path) -> Path:
    d = tmp_path / "Users" / "Dávid" / "OneDrive - Egyetem" / "Közös mappa"
    d.mkdir(parents=True)
    return d


def _trio(tmp_path, monkeypatch, shared, reader=None, ai=None):
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project", reader=reader, ai=ai)
    ben = Person(tmp_path, "Ben", monkeypatch)
    carol = Person(tmp_path, "Carol", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")
    join_zip(carol, anna, tmp_path / "carol-project")
    for p in (anna, ben, carol):
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben, carol)
    return anna, ben, carol


@pytest.fixture
def trio(tmp_path, monkeypatch, shared):
    """Anna made a small project (so she is its owner); Ben and Carol have copies from her zips; all three work
    through the shared folder, after two rounds."""
    return _trio(tmp_path, monkeypatch, shared)


def _doc(p: Person, title_part: str) -> str:
    with p:
        rows = [r[0] for r in p.ws.query("SELECT doc_id FROM documents WHERE title LIKE ?", (f"%{title_part}%",))]
    assert len(rows) == 1, (title_part, rows)
    return rows[0]


def _share(p: Person, hid: str) -> None:
    with p:
        sharing.share(p.ws, [{"kind": "check", "key": hid}])


def _hyps(p: Person) -> set[str]:
    with p:
        return {r[0] for r in p.ws.query("SELECT hyp_id FROM hypotheses")}


def _one(p: Person, **kw) -> dict:
    got = proposals(p, **kw)
    assert len(got) == 1, got
    return got[0]


# ---- 1. the owner offline for many rounds (plan §6.1, §9.1.1) ------------------------------------------------------
def test_the_owner_offline_for_twelve_rounds_loses_nothing_and_finds_the_cards_waiting(trio, tmp_path):
    anna, ben, carol = trio
    desal, jobs, grid = _doc(anna, "Desalination"), _doc(anna, "jobs"), _doc(anna, "Grid")
    hb = check(ben, "Desalination adds little to the cost of hydrogen.")
    hc = check(carol, "Electrolyser plants create local jobs mainly during construction.")
    _share(ben, hb)
    mine = {"Ben": results_of(ben, [hb]), "Carol": results_of(carol, [hc])}
    before_jobs = included(anna, jobs)
    x = y = fp = None
    for i in range(12):
        if i == 0:
            x = add_doc(ben, tmp_path, "interview")
        elif i == 2:
            with ben:
                ben.ws.remove_document(grid, why="A modelling study")
        elif i == 4:
            fp = leave_out(carol, jobs, 1)
        elif i == 6:
            y = add_doc(carol, tmp_path, "note", text=NOTE)
        elif i == 8:
            set_level(carol, desal, "none")      # stricter: holds at once, also without the owner
        elif i == 10:
            hc2 = check(carol, "Brine harms marine life.")
            _share(carol, hc2)
        sync(ben, carol, rounds=1)
    # while she is away: additions reach the other collaborator, provisionally; nothing else changes elsewhere
    assert has(carol, x) and has(ben, y)
    assert view(carol)["documents"][x]["state"] == "proposed" and view(ben)["documents"][y]["state"] == "proposed"
    assert has(carol, grid) and not has(ben, grid)
    assert included(ben, jobs) == before_jobs and included(carol, jobs) != before_jobs
    assert level(ben, desal) == "none"
    assert docs_of(anna) == {desal, jobs, grid} and not view(anna)["proposals"]
    # she comes back
    sync(anna, ben, carol, rounds=2)
    for p in (anna, ben, carol):
        adds = {q["doc"]: q for q in proposals(p, kind="add")}
        assert set(adds) == {x, y} and all(q["state"] == "accepted" and q["auto"] for q in adds.values()), p.name
        assert has(p, x) and has(p, y)
    got = {q["kind"]: q for q in proposals(anna, state="waiting")}
    assert set(got) == {"remove", "blocks"} and got["remove"]["doc"] == grid and got["blocks"]["doc"] == jobs
    assert has(anna, grid) and has(carol, grid) and included(anna, jobs) == before_jobs and choices(carol, jobs) == {fp: 0}
    assert level(anna, desal) == "none"
    assert {hb, hc2} <= _hyps(anna) and hc not in _hyps(anna)
    # nothing anybody made was lost
    assert results_of(ben, [hb]) == mine["Ben"] and results_of(carol, [hc]) == mine["Carol"]


# ---- 2. late joiners (plan §9.1.2) -------------------------------------------------------------------------------
def _busy_team(trio, tmp_path):
    """Proposals of every state in the team: an accepted addition, a declined one, a waiting removal, a declined
    blocks change, an accepted loosening, a waiting new reading is not possible here (reader 2 already)."""
    anna, ben, carol = trio
    desal, jobs, grid = _doc(anna, "Desalination"), _doc(anna, "jobs"), _doc(anna, "Grid")
    with anna:
        ownership.set_accept_adds(anna.ws, False)
    set_level(anna, grid, "local")
    sync(anna, ben, carol)
    kept = add_doc(ben, tmp_path, "interview")
    gone = add_doc(carol, tmp_path, "note", text=NOTE)
    with ben:
        ben.ws.remove_document(desal)
    leave_out(carol, jobs, 1)
    set_level(ben, grid, "cloud")
    sync(ben, carol, anna)
    w = {(q["kind"], q["doc"]): q["id"] for q in proposals(anna, state="waiting")}
    accept(anna, w[("add", kept)])
    decline(anna, w[("add", gone)], "Not a source")
    decline(anna, w[("blocks", jobs)])
    accept(anna, w[("loosen", grid)])
    sync(anna, ben, carol, rounds=2)
    allow(carol, grid)  # roles (DESIGN-roles §6.6): a looser setting is offered in the copies that did not ask for it
    sync(carol, anna, ben)
    return dict(desal=desal, jobs=jobs, grid=grid, kept=kept, gone=gone)


def _eve_from_the_folder(tmp_path, monkeypatch, shared, anna) -> Person:
    """A copy from the folder alone: an empty project of the same id."""
    eve = Person(tmp_path, "Eve", monkeypatch)
    with anna:
        uid = anna.ws.meta("project_uid")
    with eve:
        eve.ws = Workspace.create(tmp_path / "eve-project")
        eve.ws.set_meta("project_uid", uid)
        folder.set_folder(eve.ws, str(shared))
    return eve


def _agrees(p: Person, anna: Person) -> None:
    assert owner_of(p) == anna.id, p.name
    assert canon_of(p) == canon_of(anna), p.name
    assert states_of(p) == states_of(anna), p.name
    assert not [q for q in proposals(p) if q["by"]["id"] == p.id], p.name   # they changed nothing: no proposal


def test_late_joiners_from_a_colleagues_shared_zip_and_from_the_folder_alone_agree(trio, tmp_path, monkeypatch,
                                                                                    shared):
    anna, ben, carol = trio
    d = _busy_team(trio, tmp_path)
    dana = Person(tmp_path, "Dana", monkeypatch)
    join(dana, ben, tmp_path, shared, scope="shared")        # from a collaborator's zip, holding only what he shared
    eve = _eve_from_the_folder(tmp_path, monkeypatch, shared, anna)
    sync(dana, eve, anna, ben, carol, rounds=3)
    for p in (dana, eve):
        _agrees(p, anna)
        assert levels_of(p)[d["grid"]] == "cloud" and not has(p, d["gone"]), p.name   # nothing that was refused
    # the folder alone: exactly the project's documents
    assert docs_of(eve) == {x for x, k in canon_of(anna).items() if k[0] == "in"}
    assert has(carol, d["gone"])


def test_a_copy_from_a_collaborators_zip_holds_the_document_he_only_proposed_to_remove(trio, tmp_path, monkeypatch,
                                                                                         shared):
    anna, ben, carol = trio
    d = _busy_team(trio, tmp_path)                            # Ben's removal of `desal` still waits for Anna
    dana = Person(tmp_path, "Dana", monkeypatch)
    join(dana, ben, tmp_path, shared, scope="shared")
    sync(dana, anna, ben, carol, rounds=3)
    assert canon_of(anna)[d["desal"]][0] == "in" and has(carol, d["desal"])
    assert has(dana, d["desal"])                              # Dana removed nothing: the project's document is hers


def test_a_copy_from_a_collaborators_zip_proposes_nothing_in_its_own_name(trio, tmp_path, monkeypatch, shared):
    anna, ben, carol = trio
    old = add_doc(anna, tmp_path, "interview", reader=1)
    sync(anna, ben, carol)
    jobs = _doc(anna, "jobs")
    leave_out(ben, jobs, 1)
    move(ben, old)
    sync(ben, anna)
    assert {q["kind"] for q in waiting(anna)} == {"blocks", "reread"}
    dana = Person(tmp_path, "Dana", monkeypatch)
    join(dana, ben, tmp_path, shared, scope="shared")
    sync(dana, anna, ben, carol, rounds=2)
    assert not [q for q in proposals(dana) if q["by"]["id"] == dana.id]
    assert {(q["kind"], q["by"]["id"]) for q in waiting(anna)} == {("blocks", ben.id), ("reread", ben.id)}


# ---- 3. zips only (plan §9.1.3) ----------------------------------------------------------------------------------
def test_zips_only_each_kind_proposed_accepted_declined_and_the_copies_converge(tmp_path, monkeypatch):
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project", keys=("desalination", "jobs", "grid"))
    old1 = add_doc(anna, tmp_path, "interview", reader=1)      # read by the earlier reader: to be read again
    old2 = add_doc(anna, tmp_path, "policy", reader=1, text=POLICY)
    ben, carol = Person(tmp_path, "Ben", monkeypatch), Person(tmp_path, "Carol", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")
    join_zip(carol, anna, tmp_path / "carol-project")
    desal, jobs, grid = (_doc(anna, t) for t in ("Desalination", "jobs", "Grid"))
    iv = old1
    set_level(anna, iv, "none")
    zips(anna, ben, carol)
    assert level(ben, iv) == level(carol, iv) == "none" and owner_of(ben) == owner_of(carol) == anna.id
    hb = check(ben, "Seawater desalination adds little to the cost of electrolytic hydrogen.")
    hc = check(carol, "Electrolysers can stabilise a grid with much wind power.")
    before = {"Ben": results_of(ben, [hb]), "Carol": results_of(carol, [hc])}
    # every kind, by both collaborators
    added_b = add_doc(ben, tmp_path, "note", text=NOTE)
    added_c = add_doc(carol, tmp_path, "brief", text=POLICY.replace("Hydrogen export policy brief",
                                                                       "Ammonia terminals in ports"))
    with ben:
        ben.ws.remove_document(grid)
    with carol:
        carol.ws.remove_document(desal)
    fp_b = leave_out(ben, jobs, 0)
    fp_c = leave_out(carol, jobs, 2)
    move(ben, old1)
    move(carol, old2)
    set_level(ben, iv, "local")
    set_level(carol, iv, "cloud")
    zips(ben, carol, anna)
    w = {(q["kind"], q["doc"], q["by"]["id"]): q["id"] for q in proposals(anna, state="waiting")}
    assert {(k, dd) for k, dd, _b in w} == {("remove", grid), ("remove", desal), ("blocks", jobs), ("reread", old1),
                                           ("reread", old2), ("loosen", iv)}
    assert has(anna, added_b) and has(anna, added_c)          # accepted at once by her setting
    accept(anna, w[("remove", grid, ben.id)])
    decline(anna, w[("remove", desal, carol.id)], "Still cited")
    accept(anna, w[("blocks", jobs, ben.id)])
    decline(anna, w[("blocks", jobs, carol.id)])
    decline(anna, w[("reread", old1, ben.id)])
    accept(anna, w[("reread", old2, carol.id)])
    decline(anna, w[("loosen", iv, carol.id)], "Local only")   # (accepting Ben's first would make Carol's moot)
    accept(anna, w[("loosen", iv, ben.id)])
    zips(anna, ben, carol, rounds=3)
    allow(carol, iv)  # roles (DESIGN-roles §6.6): Carol did not ask for Ben's level: it is offered in her copy
    zips(carol, anna, ben)
    for p in (anna, ben, carol):
        assert not has(p, grid), p.name
        assert has(p, added_b) and has(p, added_c), p.name
        assert reader_of(p, old2) == ingest.READER, p.name
        assert level(p, iv) == "local", p.name
        assert owner_of(p) == anna.id
        assert not waiting(p), (p.name, waiting(p))
    assert has(anna, desal) and has(ben, desal) and not has(carol, desal)    # declined: Carol stays without it
    assert reader_of(ben, old1) == ingest.READER and reader_of(anna, old1) == reader_of(carol, old1) == 1  # declined
    assert choices(anna, jobs) == {fp_b: 0} == {k: v for k, v in choices(ben, jobs).items()}
    assert choices(carol, jobs) == {fp_b: 0, fp_c: 0}             # the project's, with her own on top
    assert canon_of(anna) == canon_of(ben) == canon_of(carol)
    assert states_of(anna) == states_of(ben) == states_of(carol)
    assert results_of(ben, [hb]) == before["Ben"] and results_of(carol, [hc]) == before["Carol"]


# ---- 4. a project exchanged before 0.18 (plan §2.1, §6.12, §9.1.4) -----------------------------------------------
def _old_trio(tmp_path, monkeypatch, shared):
    """Anna's project, with Ben's and Carol's copies, as it was exchanged by zips before 0.18 (no owner); then all
    three use the shared folder."""
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    ben, carol = Person(tmp_path, "Ben", monkeypatch), Person(tmp_path, "Carol", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")
    join_zip(carol, anna, tmp_path / "carol-project")
    for p in (anna, ben, carol):
        as_before_018(p)
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben, carol)
    return anna, ben, carol


def test_a_project_exchanged_before_018_has_no_owner_and_works_as_before_until_someone_becomes_it(
        tmp_path, monkeypatch, shared):
    anna, ben, carol = _old_trio(tmp_path, monkeypatch, shared)
    desal, jobs, grid = _doc(anna, "Desalination"), _doc(anna, "jobs"), _doc(anna, "Grid")
    for p in (anna, ben, carol):
        v = view(p)
        assert v["owner"] is None and v["can_claim"] and not v["is_owner"] and not v["proposals"], p.name
    with ben:
        ben.ws.remove_document(grid)
    fp = leave_out(ben, jobs, 1)
    x = add_doc(carol, tmp_path, "note", text=NOTE)
    set_level(carol, desal, "local")
    sync(ben, carol, anna, rounds=2)
    for p in (anna, ben, carol):
        assert owner_of(p) is None and not view(p)["proposals"], p.name
    assert has(anna, grid) and has(carol, grid)                   # a removal does not travel (as before)
    assert not choices(anna, jobs) and not choices(carol, jobs)   # nor Leave out (plan §12.9)
    assert choices(ben, jobs) == {fp: 0}
    assert has(anna, x) and has(ben, x)                            # an added document does
    assert level(anna, desal) == level(ben, desal) == "local"      # and so does a stricter setting
    with anna:
        ownership.claim(anna.ws)
    sync(anna, ben, carol, rounds=2)
    for p in (anna, ben, carol):
        v = view(p)
        assert v["owner"]["id"] == anna.id and v["how"] == "claim" and not v["can_claim"], p.name
    assert canon_of(anna) == canon_of(ben) == canon_of(carol)
    assert set(canon_of(anna)) == docs_of(anna)
    # what Ben did before there was an owner is his to propose now; nothing of it became the project's
    got = {(q["kind"], q["doc"]) for q in proposals(anna, state="waiting")}
    assert got == {("remove", grid), ("blocks", jobs)}
    assert has(anna, grid) and not choices(anna, jobs)
    with ben:
        with pytest.raises(ownership.NotAllowed):
            ownership.claim(ben.ws)


@pytest.mark.parametrize("same_second", [False, True])
def test_two_people_who_claim_an_ownerless_project_at_once_are_each_asked_and_settle_it_by_hand(tmp_path, monkeypatch,
                                                                                               shared, same_second):
    # roles (DESIGN-roles §4.1, §6.6): no clock decides between two first owners. Each claimer follows itself and is
    # asked about the other; a third copy follows whichever it heard of first and is asked about the other
    anna, ben, carol = _old_trio(tmp_path, monkeypatch, shared)
    desal, jobs = _doc(anna, "Desalination"), _doc(anna, "jobs")
    first, second = sorted((ben, carol), key=lambda p: p.id) if same_second else (ben, carol)
    with monkeypatch.context() as mp:   # (the times make no difference any more)
        mp.setattr(ownership, "now", lambda: "2026-11-11T10:00:00+00:00")
        with first:
            ownership.claim(first.ws)
        if not same_second:
            mp.setattr(ownership, "now", lambda: "2026-11-11T10:01:00+00:00")
        with second:
            ownership.claim(second.ws)                             # later, before hearing of the other one
    ben, carol = first, second
    with carol:
        carol.ws.remove_document(desal)                            # as the owner, as far as she knows
    fp = leave_out(carol, jobs, 1)
    sync(carol, anna)                                             # Anna hears of Carol's claim first
    assert owner_of(anna) == carol.id and not has(anna, desal)    # and follows her as the owner
    sync(ben, anna, carol, rounds=3)
    assert (owner_of(anna), owner_of(ben), owner_of(carol)) == (carol.id, ben.id, carol.id)
    for p, other in ((anna, ben), (ben, carol), (carol, ben)):
        assert [(q["kind"], q["owner"]) for q in view(p)["questions"]] == [("founder", other.id)], p.name
    follow(carol, ben.id)                                         # settled by hand: Ben is the first owner
    follow(anna, ben.id)
    with ben:
        ownership.keep_owner(ben.ws, 1, carol.id)                 # (Ben keeps himself: not asked again)
    sync(carol, ben, anna, rounds=3)
    for p in (anna, ben, carol):
        v = view(p)
        assert v["owner"]["id"] == ben.id and v["how"] == "claim" and not v["questions"], p.name
    assert canon_of(anna) == canon_of(ben) == canon_of(carol)
    assert canon_of(ben)[desal][0] == "in" and has(ben, desal)    # Carol's rows stopped counting
    assert json_blocks(canon_of(ben)[jobs]) == {}
    # what she did as the owner is a proposal to Ben now; Anna's copy, which had applied it, follows Ben again
    got = {(q["kind"], q["doc"]) for q in proposals(ben, state="waiting") if q["by"]["id"] == carol.id}
    assert got == {("remove", desal), ("blocks", jobs)} and choices(carol, jobs) == {fp: 0}
    assert has(anna, desal) and fp not in choices(anna, jobs)


def json_blocks(row: tuple) -> dict:
    import json

    return json.loads(row[3])


# ---- 5. a zip from ENLENS 0.17 (plan §6.4, §9.1.5) ---------------------------------------------------------------
def test_a_017_zip_that_adds_a_document_is_a_proposal_in_a_collaborators_copy_and_canon_in_the_owners(
        tmp_path, monkeypatch):
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    ben, old = Person(tmp_path, "Ben", monkeypatch), Person(tmp_path, "Olga", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")
    join_zip(old, anna, tmp_path / "olga-project")                # Olga still runs 0.17: her zips say nothing of L2
    desal, grid = _doc(anna, "Desalination"), _doc(anna, "Grid")
    x = add_doc(old, tmp_path, "note", text=NOTE)
    with old:
        old.ws.remove_document(grid)
    set_level(old, desal, "none")
    f = as_017_zip(send(old, scope="all"), tmp_path / "olga-0.17.zip")
    ben.bring_in(f)
    anna.bring_in(f)
    assert has(ben, x) and has(anna, x)
    p = _one(ben, kind="add")
    assert p["doc"] == x and p["by"]["id"] == ben.id and p["state"] == "waiting"   # the person who brought it in
    assert x in canon_of(anna) and canon_of(anna)[x][0] == "in" and not proposals(anna)
    assert level(ben, desal) == level(anna, desal) == "none" and canon_of(anna)[desal][2] == "none"
    assert has(ben, grid) and has(anna, grid)                     # a 0.17 removal note: listed, nothing removed
    zips(anna, ben)
    assert _one(ben, kind="add")["state"] == "accepted" and canon_of(ben) == canon_of(anna)
    assert level(ben, desal) == "none" and has(ben, grid)


def test_a_017_zip_saying_the_setting_the_owner_loosened_does_not_tighten_it_again_but_another_stricter_one_does(
        tmp_path, monkeypatch):
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    iv = add_doc(anna, tmp_path, "interview", ai="none")
    ben, old = Person(tmp_path, "Ben", monkeypatch), Person(tmp_path, "Olga", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")
    join_zip(old, anna, tmp_path / "olga-project")
    view(ben)                                                     # (Ben's copy has looked once: see the next test)
    set_level(anna, iv, "cloud")                                  # the owner loosens it
    zips(anna, ben)
    allow(ben, iv)                     # roles (DESIGN-roles §6.6): offered in Ben's copy, and allowed
    assert level(ben, iv) == level(anna, iv) == "cloud"
    stale = as_017_zip(send(old, scope="all"), tmp_path / "olga-stale.zip")   # Olga's copy still says No AI
    ben.bring_in(stale)
    anna.bring_in(stale)
    assert level(ben, iv) == level(anna, iv) == "cloud"           # only the setting the owner loosened: left aside
    fresh = as_017_zip(send(old, scope="all"), tmp_path / "olga-fresh.zip",   # Olga's 0.17 sets Only a local AI
                       sql=[("UPDATE documents SET ai_access='local' WHERE doc_id=?", (iv,))])
    ben.bring_in(fresh)
    anna.bring_in(fresh)
    assert level(ben, iv) == level(anna, iv) == "local"           # another stricter setting holds
    zips(anna, ben)
    assert canon_of(anna)[iv][2] == canon_of(ben)[iv][2] == "local" and level(ben, iv) == "local"


def test_a_copy_made_from_a_zip_follows_the_owners_first_loosening(tmp_path, monkeypatch):
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    iv = add_doc(anna, tmp_path, "interview", ai="none")
    ben = Person(tmp_path, "Ben", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")                 # Ben's copy has not looked at the owner's word yet
    set_level(anna, iv, "cloud")                                  # when the owner loosens it
    zips(anna, ben, rounds=2)
    assert level(anna, iv) == "cloud" and canon_of(anna)[iv][2] == "cloud"
    assert level(ben, iv) == "none" and [o["doc"] for o in view(ben)["offers"]] == [iv]   # roles (§6.6): offered
    allow(ben, iv)
    assert level(ben, iv) == "cloud"


# ---- 6. a new reading where a result finds no place (plan §3.1, §9.1.6) -------------------------------------------
def _paper_team(tmp_path, monkeypatch, shared):
    """Anna's project holds a two-column paper read by reader 1 (its running head in the text); Ben and Carol have
    copies; Carol has a check with a quote across the running head (a result the new reader has no place for)."""
    from test_0_15_0_read_with_new_reader import HEAD, Q_WATER, _check, _paper

    anna = Person(tmp_path, "Anna", monkeypatch)
    with anna:
        anna.ws = Workspace.create(tmp_path / "anna-project")
        d = tmp_path / "paper"
        d.mkdir()
        with monkeypatch.context() as mp:
            mp.setattr(ingest, "READER", 1)
            ingest.ingest(anna.ws, [_paper(d)], ai_access="cloud")
        doc = anna.ws.scalar("SELECT doc_id FROM documents")
    ben, carol = Person(tmp_path, "Ben", monkeypatch), Person(tmp_path, "Carol", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")
    join_zip(carol, anna, tmp_path / "carol-project")
    for p in (anna, ben, carol):
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben, carol)
    with carol:
        text = carol.ws.scalar("SELECT text FROM documents")
        i = text.index(HEAD, 10)
        bad = text[i + len(HEAD) - 5:i + len(HEAD) + 22].strip()
        bad = bad[:bad.rfind(" ")]
        hid, _at = _check(carol.ws, [(bad, "supports"), (Q_WATER, "supports")])
    return anna, ben, carol, doc, hid


def test_a_new_reading_that_would_lose_a_result_waits_for_its_person_and_then_keeps_it_as_a_record(
        tmp_path, monkeypatch, shared):
    anna, ben, carol, doc, hid = _paper_team(tmp_path, monkeypatch, shared)
    before = results_of(carol, [hid])
    move(ben, doc)
    sync(ben, anna)
    accept(anna, _one(anna, state="waiting")["id"])
    assert reader_of(anna, doc) == ingest.READER
    sync(anna, carol, ben, rounds=2)
    assert reader_of(ben, doc) == ingest.READER
    assert reader_of(carol, doc) == 1                             # it stays as it is: one result would be lost
    v = view(carol)
    assert [(t["doc"], t["can_force"]) for t in v["to_apply"]] == [(doc, True)]
    assert "would not find their place" in v["to_apply"][0]["note"]
    with carol:
        assert ownership.moves_due(carol.ws) == []                # not tried again each round
    sync(carol, rounds=2)
    assert reader_of(carol, doc) == 1 and results_of(carol, [hid]) == before
    with carol:
        out = ownership.move_now(carol.ws, doc, force=True)
        assert out["moved"] and out["not_placed"] == 1
        pids = [r[0] for r in carol.ws.query("SELECT v.passage_id FROM verifications v JOIN user_claims c ON "
                                             "c.claim_id=v.subject_id WHERE c.hyp_id=?", (hid,))]
    assert reader_of(carol, doc) == ingest.READER and results_of(carol, [hid]) == before
    assert sum(reread.is_tombstone(p) for p in pids) == 1          # the one without a place is kept as a record
    assert not view(carol)["to_apply"]
    sync(carol, anna, ben)
    assert not view(carol)["to_apply"] and not waiting(anna)


# ---- 7. a new reading where a copy has no original file (plan §3.1, §9.1.7) ---------------------------------------
def test_a_new_reading_waits_for_the_original_file_and_is_made_once_it_arrives(trio, tmp_path, shared):
    from enlens_claims.sources import original_file

    anna, ben, carol = trio
    doc = add_doc(anna, tmp_path, "interview", reader=1)
    sync(anna, ben, carol)
    with carol:
        f = Path(original_file(carol.ws, doc)["path"])
        sha1 = carol.ws.scalar("SELECT sha1 FROM documents WHERE doc_id=?", (doc,))
    hold = tmp_path / "held-back"
    hold.mkdir()
    in_folder = sorted(shared.rglob(f"files/{sha1}.*"))
    assert in_folder
    for i, g in enumerate(in_folder):                             # the cloud has not brought the file here yet
        shutil.move(str(g), str(hold / f"{i}-{g.name}"))
    f.unlink()                                                    # and Carol's copy has lost its own
    move(ben, doc)
    sync(ben, anna)
    accept(anna, _one(anna, state="waiting")["id"])
    sync(anna, rounds=1)
    with monkeypatch_files(shared, sha1):
        sync(carol, rounds=2)
        assert reader_of(carol, doc) == 1                         # it cannot be read again now: noted, tried again
        v = view(carol)
        assert [t["doc"] for t in v["to_apply"]] == [doc] and not v["to_apply"][0]["can_force"]
        assert "original file" in v["to_apply"][0]["note"]
        with carol:
            assert ownership.moves_due(carol.ws) == [doc]
    for i, g in enumerate(in_folder):                             # the file arrives in the folder
        g.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(hold / f"{i}-{g.name}"), str(g))
    sync(carol, rounds=1)
    assert reader_of(carol, doc) == ingest.READER
    assert not view(carol)["to_apply"]


class monkeypatch_files:
    """While inside: no file named for `sha1` is in the shared folder (a round that writes one is undone at once)."""

    def __init__(self, shared: Path, sha1: str):
        self.shared, self.sha1 = shared, sha1
        self._orig = None

    def __enter__(self):
        orig = folder.fetch_files

        def fetch_files(ws, team, progress=None, should_stop=None):
            for g in sorted(self.shared.rglob(f"files/{self.sha1}.*")):
                g.unlink()
            return orig(ws, team, progress, should_stop)

        self._orig = orig
        folder.fetch_files = fetch_files
        return self

    def __exit__(self, *exc):
        folder.fetch_files = self._orig
        return False


# ---- 8. fetching a document the owner's word brings back (plan §4.4, §6.9, §9.1.8) -------------------------------
def test_the_owner_accepts_an_addition_her_copy_no_longer_holds_and_it_is_fetched_from_the_folder(trio, tmp_path):
    anna, ben, carol = trio
    with anna:
        ownership.set_accept_adds(anna.ws, False)
    x = add_doc(ben, tmp_path, "interview")
    sync(ben, anna, carol)
    assert has(anna, x) and has(carol, x)
    with anna:
        anna.ws.remove_document(x)                                # out of her copy before she decided
    sync(anna, ben, carol)
    assert has(ben, x) and has(carol, x) and not has(anna, x)     # not the project's: her removal does not travel
    accept(anna, _one(anna, state="waiting")["id"])
    assert has(anna, x)                                           # one fetch from the shared folder
    with anna:
        assert not anna.ws.scalar("SELECT 1 FROM sync_removed WHERE kind='document' AND key=?", (x,))
    sync(anna, ben, carol, rounds=2)
    assert all(has(p, x) for p in (anna, ben, carol)) and canon_of(anna)[x][0] == "in"
    assert canon_of(anna) == canon_of(ben) == canon_of(carol)


def test_a_document_the_owner_adds_again_after_removing_it_comes_back_into_every_copy(trio, tmp_path):
    anna, ben, carol = trio
    doc = add_doc(anna, tmp_path, "interview")
    sync(anna, ben, carol)
    with anna:
        anna.ws.remove_document(doc)
    sync(anna, ben, carol)
    assert not has(ben, doc) and not has(carol, doc)
    again = add_doc(anna, tmp_path, "interview")                  # the same file, on purpose
    assert again == doc
    sync(anna, ben, carol, rounds=2)
    assert canon_of(anna)[doc][0] == "in"
    assert has(ben, doc) and has(carol, doc)                      # canon `in` again: fetched where it was removed
    assert not view(ben)["proposals"] and not view(carol)["proposals"]


def test_an_accepted_addition_whose_reading_is_kept_out_of_the_folder_shows_as_not_here(trio, tmp_path):
    anna, ben, carol = trio
    with ben:
        folder.set_keep_out(ben.ws, True)
    x = add_doc(ben, tmp_path, "interview", ai="none")            # kept out of the folder: only its stub goes
    sync(ben, anna, carol, rounds=2)
    assert canon_of(anna)[x][0] == "in" and canon_of(anna)[x][2] == "none"   # accepted at once all the same
    assert not has(anna, x) and not has(carol, x) and has(ben, x)
    for p in (anna, carol):
        with p:
            assert x in {d["doc_id"] for d in folder.status(p.ws)["not_here"]}, p.name
    assert canon_of(anna) == canon_of(ben) == canon_of(carol)


# ---- 9. the keep-out switch with proposals (plan §6.10, §10.7, §9.1.9) ---------------------------------------------
MARK = "Kestrel-Saffron-0417 is the marker of the kept-out interview."
MARK2 = "Wombat-Indigo-8812 marks the document only a local AI may read."


def test_with_the_keep_out_switch_no_word_of_a_kept_out_document_travels_because_of_a_proposal(
        tmp_path, monkeypatch, shared):
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    iv = add_doc(anna, tmp_path, "interview", ai="none", text=TEXTS["interview"] + "\n" + MARK + "\n")
    ben, carol = Person(tmp_path, "Ben", monkeypatch), Person(tmp_path, "Carol", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")                # (by zip: every copy holds the interview)
    join_zip(carol, anna, tmp_path / "carol-project")
    with anna:
        folder.set_keep_out(anna.ws, True)
    for p in (anna, ben, carol):
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben, carol)
    jobs = _doc(anna, "jobs")
    set_level(ben, iv, "local")                                   # a looser setting: proposed
    fp = leave_out(ben, iv, 1)                                    # blocks of a kept-out document
    with carol:
        carol.ws.remove_document(iv)                              # its removal
    y = add_doc(ben, tmp_path, "local", ai="local", text=POLICY + "\n" + MARK2 + "\n")
    leave_out(carol, jobs, 1)
    sync(ben, carol, anna, rounds=2)
    w = {(q["kind"], q["doc"]): q["id"] for q in proposals(anna, state="waiting")}
    assert set(w) == {("loosen", iv), ("blocks", iv), ("remove", iv), ("blocks", jobs)}
    assert canon_of(anna)[y][0] == "in" and canon_of(anna)[y][2] == "local"
    accept(anna, w[("blocks", iv)])
    decline(anna, w[("remove", iv)])
    accept(anna, w[("loosen", iv)])
    accept(anna, w[("blocks", jobs)])
    sync(anna, ben, carol, rounds=3)
    assert level(anna, iv) == level(ben, iv) == "local" and choices(anna, iv) == {fp: 0}
    assert not has(anna, y) and not has(carol, y)                 # kept out: only its stub travelled

    def blob() -> bytes:
        return b"".join(data for _n, data in everything(shared))

    got = blob()
    assert b"Interview with a plant manager" in got               # titles and ids travel (proposals, stubs)
    for marker in (MARK, MARK2, "remarks on the water permit", "Ports need new terminals for ammonia"):
        assert marker.encode("utf-8") not in got, marker
    # a loosening the owner accepts takes the document out of the switch's reach: then its words may go
    set_level(ben, iv, "cloud")
    sync(ben, anna)
    accept(anna, _one(anna, state="waiting", kind="loosen")["id"])
    sync(anna, ben, carol, rounds=2)
    assert level(ben, iv) == level(anna, iv) == "cloud" and not has(carol, iv)   # (her removal was declined)
    got = blob()
    assert MARK2.encode("utf-8") not in got and b"Ports need new terminals for ammonia" not in got


# ---- 10. hand-over edge cases (plan §6.6, §10.9, §9.1.10) ---------------------------------------------------------
def test_a_new_owner_s_own_waiting_and_declined_proposals_do_not_become_the_projects_silently(trio, tmp_path):
    anna, ben, carol = trio
    jobs, grid = _doc(anna, "jobs"), _doc(anna, "Grid")
    old = add_doc(anna, tmp_path, "interview", reader=1)
    with anna:
        ownership.set_accept_adds(anna.ws, False)
    sync(anna, ben, carol)
    fp = leave_out(ben, jobs, 1)
    move(ben, old)
    x = add_doc(ben, tmp_path, "note", text=NOTE)
    sync(ben, anna, carol)
    for q in proposals(anna, state="waiting"):
        decline(anna, q["id"], "Not now")
    with ben:
        ben.ws.remove_document(grid)                              # and one that still waits
    sync(ben, anna, carol)
    assert _one(anna, state="waiting")["kind"] == "remove"
    with anna:
        ownership.hand_over(anna.ws, ben.id, "Ben leads the next phase")
    sync(anna, ben, carol, rounds=3)
    for p in (anna, ben, carol):
        assert owner_of(p) == ben.id, p.name
    # nothing of his became the project's: his declined changes stay in his copy, the removal still waits
    assert has(anna, grid) and has(carol, grid) and canon_of(ben)[grid][0] == "in"
    assert json_blocks(canon_of(ben)[jobs]) == {} and not choices(carol, jobs) and choices(ben, jobs) == {fp: 0}
    assert canon_of(ben)[old][1] == 1 and reader_of(carol, old) == 1 and reader_of(ben, old) == ingest.READER
    assert x not in canon_of(ben) and not has(carol, x) and has(ben, x)
    assert canon_of(anna) == canon_of(ben) == canon_of(carol)
    w = _one(ben, state="waiting")
    assert w["kind"] == "remove" and w["can_decide"] and w["mine"]
    accept(ben, w["id"])                                          # he answers it himself
    sync(ben, anna, carol, rounds=2)
    assert not has(anna, grid) and not has(carol, grid)
    assert choices(ben, jobs) == {fp: 0} and json_blocks(canon_of(anna)[jobs]) == {}


def test_a_new_reading_the_old_owner_accepted_is_made_in_the_new_owners_copy_and_not_undone(trio, tmp_path):
    anna, ben, carol = trio
    old = add_doc(anna, tmp_path, "interview", reader=1)
    sync(anna, ben, carol)
    move(carol, old)
    sync(carol, anna)
    accept(anna, _one(anna, state="waiting")["id"])
    with anna:
        ownership.hand_over(anna.ws, ben.id)                      # Ben has not heard of the new reading yet
    sync(anna, ben, carol, rounds=3)
    assert owner_of(ben) == ben.id
    for p in (anna, ben, carol):
        assert reader_of(p, old) == ingest.READER, p.name
        assert canon_of(p)[old][1] == ingest.READER, p.name


def test_the_old_owners_last_changes_hold_when_the_hand_over_reaches_a_copy_with_them(trio, tmp_path):
    anna, ben, carol = trio
    jobs, grid = _doc(anna, "jobs"), _doc(anna, "Grid")
    set_level(anna, grid, "none")
    sync(anna, ben, carol)
    assert level(ben, grid) == "none"
    fp = leave_out(anna, jobs, 1)                                 # her own changes: the project's at once
    set_level(anna, grid, "cloud")
    with anna:
        ownership.hand_over(anna.ws, ben.id)                      # in the same round as the hand-over
    sync(anna, ben, carol, rounds=3)
    assert owner_of(carol) == ben.id
    assert fp in json_blocks(canon_of(ben)[jobs])
    assert canon_of(ben)[grid][2] == "cloud"
    allow(ben, grid)                  # roles (DESIGN-roles §6.6): her looser setting is offered in the other copies
    allow(carol, grid)
    for p in (anna, ben, carol):
        assert choices(p, jobs) == {fp: 0}, p.name
        assert level(p, grid) == "cloud", p.name


def test_the_owner_who_handed_over_and_left_cannot_be_taken_over_from_while_the_new_owner_is_there(trio, shared):
    anna, ben, carol = trio
    with anna:
        ownership.hand_over(anna.ws, ben.id)
        team = shared / folder.team_name(anna.ws)
    sync(anna, ben, carol, rounds=2)
    shutil.rmtree(team / anna.id)                                 # Anna leaves the shared folder
    v = view(carol)
    assert v["owner"]["id"] == ben.id and v["can_take_over"] is None
    with carol:
        with pytest.raises(ownership.NotAllowed):
            ownership.take_over(carol.ws)
    with ben:
        with pytest.raises(ownership.NotAllowed):
            ownership.take_over(ben.ws)                           # the owner already
    shutil.rmtree(team / ben.id)                                  # then Ben leaves too
    assert view(carol)["can_take_over"]
    with carol:
        ownership.take_over(carol.ws, "Both left")
    sync(carol, rounds=1)
    v = view(carol)
    assert v["owner"]["id"] == carol.id and v["how"] == "takeover" and v["is_owner"]


# ---- conflicting proposals on one document, and proposals for a document removed since (plan §6.2, §6.3) ---------
def test_two_collaborators_propose_the_same_and_different_changes_to_one_document(trio, tmp_path):
    anna, ben, carol = trio
    desal, jobs, grid = _doc(anna, "Desalination"), _doc(anna, "jobs"), _doc(anna, "Grid")
    set_level(anna, grid, "none")
    sync(anna, ben, carol)
    for p in (ben, carol):
        with p:
            p.ws.remove_document(desal)                           # both propose its removal
    fb = leave_out(ben, jobs, 0)
    fc = leave_out(carol, jobs, 2)                                # different passages of one document
    set_level(ben, grid, "local")
    set_level(carol, grid, "cloud")                               # two loosenings, to different levels
    sync(ben, carol, anna)
    w = {(q["kind"], q["doc"], q["by"]["id"]): q for q in proposals(anna, state="waiting")}
    assert len(w) == 6
    assert set(w[("remove", desal, ben.id)]["conflicts"]) == {w[("remove", desal, carol.id)]["id"]}
    assert len(w[("blocks", jobs, ben.id)]["conflicts"]) == 1
    accept(anna, w[("remove", desal, ben.id)]["id"])
    accept(anna, w[("blocks", jobs, ben.id)]["id"])
    accept(anna, w[("blocks", jobs, carol.id)]["id"])
    accept(anna, w[("loosen", grid, ben.id)]["id"])
    sync(anna, ben, carol, rounds=3)
    allow(carol, grid)                # roles (DESIGN-roles §6.6): Ben's level, offered in Carol's copy
    sync(carol, anna, ben)
    st = {(q["kind"], q["doc"], q["by"]["id"]): (q["state"], q["note"]) for q in proposals(carol)}
    assert st[("remove", desal, carol.id)][0] == "accepted" and "removed" in st[("remove", desal, carol.id)][1]
    assert st[("loosen", grid, carol.id)][0] == "moot"            # the setting was changed since: asked again
    for p in (anna, ben, carol):
        assert not has(p, desal), p.name
        assert choices(p, jobs) == {fb: 0, fc: 0}, p.name
        assert level(p, grid) == "local", p.name
        assert not waiting(p), p.name
    assert canon_of(anna) == canon_of(ben) == canon_of(carol)


def test_every_kind_of_proposal_for_a_document_the_owner_removed_meanwhile(trio, tmp_path):
    anna, ben, carol = trio
    old = add_doc(anna, tmp_path, "interview", reader=1)
    with anna:
        ownership.set_accept_adds(anna.ws, True)
    sync(anna, ben, carol)
    set_level(anna, old, "none")
    sync(anna, ben, carol)
    with anna:
        anna.ws.remove_document(old)                              # before hearing of any of them
    move(ben, old)
    set_level(carol, old, "cloud")
    with carol:
        carol.ws.remove_document(old)
    sync(ben, carol, anna, rounds=2)
    sync(anna, ben, carol, rounds=2)
    got = {(q["kind"], q["by"]["id"]): q for q in proposals(anna)}
    assert got[("reread", ben.id)]["state"] == "moot" and got[("loosen", carol.id)]["state"] == "moot"
    assert got[("remove", carol.id)]["state"] == "accepted"
    assert not any(has(p, old) for p in (anna, ben, carol))
    # adding it again is a new proposal, never accepted at once
    again = add_doc(ben, tmp_path, "interview", reader=1)
    assert again == old
    sync(ben, anna, carol, rounds=2)
    p = _one(anna, state="waiting")
    assert p["kind"] == "add" and p["detail"]["again"] and p["doc"] == old
    assert not has(anna, old) and not has(carol, old) and has(ben, old)
    accept(anna, p["id"])
    sync(anna, ben, carol, rounds=2)
    assert has(anna, old) and has(ben, old) and canon_of(anna)[old][0] == "in"
    # (Carol, who had proposed its removal: see the next test)


@pytest.mark.parametrize("how", ["accepted", "removed by the owner"])
def test_a_document_accepted_again_comes_back_to_the_collaborator_who_had_proposed_its_removal(trio, tmp_path, how):
    anna, ben, carol = trio
    doc = add_doc(anna, tmp_path, "interview")
    sync(anna, ben, carol)
    with carol:
        carol.ws.remove_document(doc)
    if how == "accepted":
        sync(carol, anna)
        accept(anna, _one(anna, state="waiting")["id"])
    else:
        with anna:
            anna.ws.remove_document(doc)
    sync(anna, ben, carol, rounds=2)
    assert not any(has(p, doc) for p in (anna, ben, carol))
    assert add_doc(ben, tmp_path, "interview") == doc            # Ben adds the same file again
    sync(ben, anna)
    accept(anna, _one(anna, state="waiting", kind="add")["id"])
    sync(anna, ben, carol, rounds=3)
    assert has(anna, doc) and has(ben, doc)
    assert not waiting(anna) and not waiting(carol)
    assert has(carol, doc)


# ---- 12. the research log (plan §2, §9.1.12) ----------------------------------------------------------------------
def test_every_proposal_answer_taking_back_and_change_of_owner_is_one_entry_in_every_copy(trio, tmp_path):
    import json

    anna, ben, carol = trio
    desal, jobs, grid = _doc(anna, "Desalination"), _doc(anna, "jobs"), _doc(anna, "Grid")
    x = add_doc(ben, tmp_path, "interview")                       # accepted at once
    with ben:
        ben.ws.remove_document(grid)
    leave_out(carol, jobs, 1)
    set_level(carol, desal, "none")
    sync(ben, carol, anna)
    w = {q["kind"]: q["id"] for q in proposals(anna, state="waiting")}
    accept(anna, w["remove"])
    decline(anna, w["blocks"], "Keep it")
    set_level(ben, jobs, "local")                                 # stricter: the project's at once ...
    sync(ben, anna, ben)
    set_level(ben, jobs, "cloud")                                 # ... and a loosening proposed by Ben ...
    with ben:
        ownership.take_back(ben.ws, _one(ben, state="waiting", kind="loosen")["id"])   # ... and taken back
    with anna:
        ownership.hand_over(anna.ws, carol.id)
    sync(anna, ben, carol, rounds=3)
    logs = {p.name: log_rows(p) for p in (anna, ben, carol)}
    ids = {n: {r[0] for r in rows} for n, rows in logs.items()}
    assert ids["Anna"] == ids["Ben"] == ids["Carol"]
    kinds = [r[1] for r in logs["Anna"]]
    assert {"proposal", "proposal-accepted", "proposal-declined", "proposal-taken-back", "owner"} <= set(kinds)
    seen: dict[tuple, int] = {}
    for _eid, kind, data in logs["Anna"]:
        d = json.loads(data or "{}")
        for pid in d.get("proposals") or ([d["proposal"]] if d.get("proposal") else []):
            seen[(kind, pid)] = seen.get((kind, pid), 0) + 1
    assert seen and all(n == 1 for n in seen.values()), seen      # each act once
    assert kinds.count("owner") == 2                              # made, and handed over
    props = {q["id"] for q in proposals(anna)}
    assert {pid for (k, pid) in seen if k == "proposal"} == props
    assert sum(1 for (k, _p) in seen if k in ("proposal-accepted", "proposal-declined")) == 3
    assert all(has(p, x) for p in (anna, ben, carol))


# ---- 9.3 Windows-like paths: accents (NFC and NFD), spaces, capitals, names that differ only in case ---------------
_FOLDER_NAMES = (r"project\.json", r"p[0-9a-f]{12}/(person|head|read|waiting)\.json",
                 r"p[0-9a-f]{12}/bundles/\d{6,}\.zip", r"p[0-9a-f]{12}/docs/[0-9a-f]{12}\.[0-9a-f]{16}\.zip",
                 r"p[0-9a-f]{12}/files/[0-9a-f]{40}\.[a-z0-9]{1,8}")


def _add_named(p: Person, where: Path, name: str, text: str, reader: int | None = None) -> str:
    where.mkdir(parents=True, exist_ok=True)
    f = where / name
    f.write_text(text, encoding="utf-8")
    with p:
        before = {r[0] for r in p.ws.query("SELECT doc_id FROM documents")}
        was = ingest.READER
        if reader is not None:
            ingest.READER = reader
        try:
            ingest.ingest(p.ws, [f])
        finally:
            ingest.READER = was
        new = [r[0] for r in p.ws.query("SELECT doc_id FROM documents") if r[0] not in before]
    assert len(new) == 1, new
    return new[0]


def _hu(title: str, body: str) -> str:
    return f"{title}\n\n" + body.split("\n\n", 1)[1]


@pytest.fixture
def windows_team(tmp_path, monkeypatch):
    """Dávid (the owner), Ábel Gergő (his ENLENS folder's name decomposed, NFD, as a Mac writes it) and Eszter (a home
    in capitals), under one `Users` folder; the shared folder is in Dávid's OneDrive, with accents and spaces."""
    users = tmp_path / "C" / "Users"
    shared = users / "Dávid" / "OneDrive - Egyetem" / "Közös mappa" / "ENLENS projektek"
    shared.mkdir(parents=True)
    david = PersonAt(tmp_path, "Dávid", monkeypatch, users / "Dávid" / "AppData" / "ENLENS")
    abel = PersonAt(tmp_path, "Ábel Gergő", monkeypatch,
                    users / unicodedata.normalize("NFD", "Ábel Gergő") / "AppData" / "ENLENS")
    eszter = PersonAt(tmp_path, "Eszter", monkeypatch, users / "ESZTER" / "AppData" / "ENLENS")
    small_project(david, users / "Dávid" / "Dokumentumok" / "Hidrogén projekt",
                  names={"desalination": "Éves jelentés 2024.TXT", "jobs": "ÁRVÍZTŰRŐ.txt",
                         "grid": "Hálózat és tükörfúrógép.txt"})
    join_zip(abel, david, users / unicodedata.normalize("NFD", "Ábel Gergő") / "Dokumentumok" / "Hidrogén projekt")
    join_zip(eszter, david, users / "ESZTER" / "Dokumentumok" / "HIDROGÉN PROJEKT")
    for p in (david, abel, eszter):
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(david, abel, eszter)
    return david, abel, eszter, shared, users


def test_windows_like_homes_and_names_every_kind_of_proposal_the_move_and_a_fetch(windows_team):
    from enlens_claims.sources import original_file

    david, abel, eszter, shared, users = windows_team
    assert len({david.id, abel.id, eszter.id}) == 3
    for p in (abel, eszter):
        assert owner_of(p) == david.id
    desal = _doc(david, "Desalination")
    old = _add_named(david, users / "Dávid" / "Letöltések", "Árvíz és hidrogén.TXT",
                     _hu("Árvíz és hidrogén: interjú", TEXTS["interview"]), reader=1)
    sync(david, abel, eszter)
    # two documents whose file names differ only in case, from two people
    up = _add_named(abel, users / "Ábel Gergő" / "Letöltések", "Jelentés.txt", _hu("Jelentés a kikötőkről", POLICY))
    low = _add_named(eszter, users / "ESZTER" / "Letöltések", "jelentés.txt", _hu("Jelentés a terepről", NOTE))
    with eszter:
        eszter.ws.remove_document(desal)
    move(abel, old)
    fp = leave_out(eszter, _doc(eszter, "jobs"), 1)
    sync(abel, eszter, david, rounds=2)
    w = {q["kind"]: q for q in proposals(david, state="waiting")}
    assert set(w) == {"remove", "reread", "blocks"} and has(david, up) and has(david, low)
    for q in w.values():
        accept(david, q["id"])
    with david:
        ownership.set_accept_adds(david.ws, False)
    third = _add_named(abel, users / "Ábel Gergő" / "Asztal", "ÁRVÍZTŰRŐ TÜKÖRFÚRÓGÉP.TXT",
                       _hu("Árvíztűrő tükörfúrógép", TEXTS["grid"]))
    sync(david, abel, eszter, david, rounds=2)
    with david:
        david.ws.remove_document(third)                           # out of his copy before he decides
    sync(david, rounds=1)
    accept(david, _one(david, state="waiting", kind="add")["id"])
    assert has(david, third)                                      # fetched from the folder with its accented name
    sync(david, abel, eszter, rounds=3)
    for p in (david, abel, eszter):
        assert not has(p, desal), p.name
        assert all(has(p, d) for d in (up, low, third, old)), p.name
        assert reader_of(p, old) == ingest.READER, p.name
        assert choices(p, _doc(p, "jobs")) == {fp: 0}, p.name
        with p:
            for d in (up, low, third, old):
                assert original_file(p.ws, d)["available"], (p.name, d)
        assert not waiting(p), p.name
    assert canon_of(david) == canon_of(abel) == canon_of(eszter)
    with david:
        names = {d: david.ws.scalar("SELECT title FROM documents WHERE doc_id=?", (d,)) for d in (up, low, third)}
    assert names[third] == "Árvíztűrő tükörfúrógép"
    # nothing L2 writes into the folder has a name of its own (rows travel in bundles)
    import re

    team = next(shared.iterdir())
    odd = [n for n in file_names(team) if not any(re.fullmatch(r, n) for r in _FOLDER_NAMES)]
    assert not odd, odd


def test_fetching_a_document_leaves_no_connection_to_its_scratch_project_open(windows_team, monkeypatch):
    david, abel, eszter, shared, users = windows_team
    with david:
        ownership.set_accept_adds(david.ws, False)
    x = _add_named(abel, users / "Ábel Gergő" / "Asztal", "Ünnepi beszéd.txt", _hu("Ünnepi beszéd", NOTE))
    sync(abel, david)
    with david:
        david.ws.remove_document(x)
    sync(eszter, david, rounds=1)                                 # (Eszter's first bundle with it: the folder has it)
    assert not has(david, x)
    made: list[Workspace] = []
    real = Workspace.create.__func__

    def create(cls, root, **kw):
        ws = real(cls, root, **kw)
        made.append(ws)
        return ws

    with monkeypatch.context() as mp:
        mp.setattr(Workspace, "create", classmethod(create))
        accept(david, _one(david, state="waiting", kind="add")["id"])
    assert has(david, x) and made
    import sqlite3

    for ws in made:
        for cx in list(ws._all):
            with pytest.raises(sqlite3.ProgrammingError):
                cx.execute("SELECT 1")                            # closed
        assert not Path(ws.root).exists()                         # and the scratch project is gone
    assert readers_of(david)[x] == ingest.READER


def test_the_owner_accepts_an_addition_he_removed_since_his_last_round_and_it_is_fetched(windows_team):
    david, abel, eszter, shared, users = windows_team
    with david:
        ownership.set_accept_adds(david.ws, False)
    x = _add_named(abel, users / "Ábel Gergő" / "Asztal", "Ünnepi beszéd.txt", _hu("Ünnepi beszéd", NOTE))
    sync(abel, david)
    with david:
        david.ws.remove_document(x)
    accept(david, _one(david, state="waiting")["id"])
    sync(david, rounds=1)                                         # (Ábel is away: nobody else writes)
    assert has(david, x)


def test_adding_a_removed_document_again_a_second_time_is_a_proposal_again(trio, tmp_path):
    anna, ben, carol = trio
    doc = add_doc(anna, tmp_path, "interview")
    sync(anna, ben, carol)
    for cycle in range(2):
        with anna:
            anna.ws.remove_document(doc)                          # the owner removes it
        sync(anna, ben, carol)
        assert not has(carol, doc), cycle
        assert add_doc(carol, tmp_path, "interview") == doc       # Carol adds it again: a proposal
        sync(carol, anna, ben)
        p = [q for q in proposals(anna, state="waiting") if q["kind"] == "add"]
        assert len(p) == 1 and p[0]["by"]["id"] == carol.id and p[0]["detail"]["again"], (cycle, p)
        accept(anna, p[0]["id"])
        sync(anna, ben, carol)
        assert all(has(q, doc) for q in (anna, ben, carol)), cycle


# ---- found by the randomised run (tests/test_0_18_0_owner_random.py), each made small ----------------------------
def _restore(p: Person, doc: str, fp: str) -> None:
    """Restore the passage with fingerprint `fp` (as Restore on the document's page)."""
    from enlens_claims import reader as reader2
    from enlens_claims.store import now

    with p:
        with p.ws.connect() as cx:
            kind = cx.execute("SELECT kind FROM block_choices WHERE doc_id=? AND fp=?", (doc, fp)).fetchone()[0]
            cx.execute("INSERT OR REPLACE INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES "
                       "(?,?,?,?,?,?)", (doc, fp, 1, kind, p.id, now()))
            reader2.apply_choices(cx, doc)
            p.ws.bump_corpus(cx)


def test_adding_again_a_document_she_removed_herself_is_a_proposal(trio, tmp_path):
    anna, ben, carol = trio
    x = add_doc(ben, tmp_path, "interview")
    sync(ben, carol, anna, ben, carol)                            # accepted at once; Carol's copy got it from Ben
    assert canon_of(anna)[x][0] == "in" and has(carol, x)
    with carol:
        carol.ws.remove_document(x)
    sync(carol, anna)
    accept(anna, _one(anna, state="waiting")["id"])
    sync(anna, ben, carol)
    assert not any(has(p, x) for p in (anna, ben, carol))
    assert add_doc(carol, tmp_path, "interview") == x             # she changes her mind
    sync(carol, anna, ben)
    p = [q for q in proposals(anna, state="waiting") if q["kind"] == "add"]
    assert len(p) == 1 and p[0]["by"]["id"] == carol.id and p[0]["detail"]["again"], p


def test_the_owner_adding_a_document_she_once_declined_makes_it_the_projects(trio, tmp_path):
    anna, ben, carol = trio
    with anna:
        ownership.set_accept_adds(anna.ws, False)
    x = add_doc(carol, tmp_path, "interview")
    sync(carol, anna)
    decline(anna, _one(anna, state="waiting")["id"])
    sync(anna, ben, carol)
    assert not has(anna, x) and not has(ben, x) and has(carol, x)
    assert add_doc(anna, tmp_path, "interview") == x              # later she adds the same file herself
    sync(anna, ben, carol, rounds=2)
    assert x in canon_of(anna) and canon_of(anna)[x][0] == "in"
    assert has(ben, x) and has(carol, x)


def test_a_passage_the_owner_restores_after_accepting_its_leaving_out_is_restored_in_the_proposers_copy(trio):
    anna, ben, carol = trio
    jobs = _doc(anna, "jobs")
    fp = leave_out(carol, jobs, 1)
    sync(carol, anna)
    accept(anna, _one(anna, state="waiting")["id"])
    _restore(anna, jobs, fp)                                      # she thinks again, before Carol heard of either
    sync(anna, ben, carol, rounds=2)
    assert choices(anna, jobs) == {fp: 1} == choices(ben, jobs)
    assert choices(carol, jobs) == {fp: 1} and included(carol, jobs) == included(anna, jobs)


def test_the_owners_changes_just_before_a_hand_over_are_the_projects(trio):
    anna, ben, carol = trio
    desal, jobs, grid = _doc(anna, "Desalination"), _doc(anna, "jobs"), _doc(anna, "Grid")
    set_level(anna, grid, "none")
    sync(anna, ben, carol)
    set_level(anna, grid, "cloud")                                # her own changes, since her last round
    fp = leave_out(anna, jobs, 1)
    with anna:
        anna.ws.remove_document(desal)
        ownership.hand_over(anna.ws, ben.id)
    sync(anna, ben, carol, rounds=3)
    assert not [q for q in proposals(ben) if q["by"]["id"] == anna.id]   # nothing of hers waits as a proposal
    allow(ben, grid)                  # roles (DESIGN-roles §6.6): her looser setting is offered in the other copies
    allow(carol, grid)
    for p in (anna, ben, carol):
        assert level(p, grid) == "cloud", p.name
        assert choices(p, jobs) == {fp: 0}, p.name
        assert not has(p, desal), p.name

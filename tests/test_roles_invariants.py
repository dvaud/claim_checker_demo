"""Roles (DESIGN-roles §6.2): one test per invariant of the merge rules.

I1 the same rows give the same owner, roles and documents in every copy, whatever the order and whatever the clocks
   said; I2 which rows count (a Co-owner's while their grant holds); I3 a later number that did not know a stricter
   setting does not undo it; I4 at the same time: the document stays, the newer reader counts; I5 parts are merged
   apart; I6 copies that exchange until nothing new comes write no row in the last exchange; I7 every clash is shown
   to the Owner and the Co-owners, logged once, and ended by *Leave it so*.

Two kinds of test: on a bare database (roles_helpers.bare: the rows written by hand, the rule read back), and with a
crew of four copies in one shared folder (Anna the Owner, Ben and Carol Co-owners, Dana a Member).
"""
from __future__ import annotations

import itertools
import json
import random
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, ownership
from owner_helpers import (add_doc, allow, choices, has, leave_out, level, move, proposals, reader_of, set_level,
                           set_role, sync, view)
from owner_more_helpers import send
from roles_helpers import A, B, C, K, answer, bare, clash_entries, doc_of, make_crew, project, put_row, row_keys
from test_0_14_0_shared_projects import Person
from test_0_18_0_owner_more import NOTE


@pytest.fixture
def shared(tmp_path) -> Path:
    d = tmp_path / "Dávid" / "Közös mappa"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def crew(tmp_path, monkeypatch, shared):
    return make_crew(tmp_path, monkeypatch, shared)


# ---- I1 --------------------------------------------------------------------------------------------------------------
def _fresh(tmp_path: Path, monkeypatch, name: str, base: Path, files: list[Path]) -> Person:
    p = Person(tmp_path, name, monkeypatch)
    with p:
        p.ws = bundle.import_project(base, tmp_path / f"{name}-project")
    for f in files:
        p.bring_in(f)
    with p:
        ownership.settle(p.ws)
    return p


def _clocks_changed(src: Path, out: Path, rng: random.Random) -> Path:
    """The same zip with every `at` of the tables that travel set to a random time."""
    with zipfile.ZipFile(src) as zf:
        data = {n: zf.read(n) for n in zf.namelist()}
    db = out.with_suffix(".sqlite")
    db.write_bytes(data["enlens.sqlite"])
    cx = sqlite3.connect(db)
    for t in ("ownership", "roles", "decisions", "canon", "proposals"):
        for (rowid,) in cx.execute(f"SELECT rowid FROM {t}").fetchall():
            at = f"{rng.randint(1990, 2090)}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}T10:00:00+00:00"
            cx.execute(f"UPDATE {t} SET at=? WHERE rowid=?", (at, rowid))
    cx.commit()
    cx.close()
    data["enlens.sqlite"] = db.read_bytes()
    with zipfile.ZipFile(out, "w") as zf:
        for n, b in data.items():
            zf.writestr(n, b)
    return out


def test_i1_the_same_rows_in_any_order_give_the_same_owner_roles_and_documents(crew, tmp_path, monkeypatch):
    anna, ben, carol, dana = crew
    base = send(dana, scope="all")
    desal, jobs, grid, iv = (doc_of(anna, t) for t in ("Desalination", "jobs", "Grid", "Interview"))
    # each changes the documents offline, some of it at the same time
    with ben:
        ben.ws.remove_document(desal)
    leave_out(ben, jobs, 0)
    set_level(carol, grid, "none")
    leave_out(carol, jobs, 2)
    set_level(anna, iv, "local")
    set_level(ben, iv, "none")
    set_role(anna, carol, "member")                 # Anna demotes Carol before her changes reach her
    files = [send(p) for p in (anna, ben, carol)]
    seen = None
    for i, order in enumerate(itertools.permutations(files)):
        got = project(_fresh(tmp_path, monkeypatch, f"F{i}", base, list(order) + list(order)))
        assert seen is None or got == seen, order
        seen = got
    assert seen["roles"][carol.id][0] == "member" and seen["roles"][ben.id][0] == "co"
    assert seen["canon"][iv][1][0] == "none"        # the stricter of two settings made at the same time
    rng = random.Random(7)
    shifted = [_clocks_changed(f, tmp_path / f"shifted-{i}.zip", rng) for i, f in enumerate(files)]
    assert project(_fresh(tmp_path, monkeypatch, "G", base, shifted[::-1])) == seen


# ---- I2 --------------------------------------------------------------------------------------------------------------
def test_i2_a_co_owners_rows_count_until_the_grant_ends_and_the_project_stays_as_it_was(crew, tmp_path):
    anna, ben, carol, dana = crew
    jobs, grid = doc_of(anna, "jobs"), doc_of(anna, "Grid")
    fp = leave_out(ben, jobs, 1)                    # a Co-owner's change: the project's at once
    sync(ben, anna, carol, dana)
    for p in crew:
        assert choices(p, jobs) == {fp: 0}, p.name
    assert view(dana)["proposals"] == []
    with anna:
        old_grant = ownership.roles(anna.ws._conn())[ben.id]["grant"]
    with ben:                                       # offline: as far as Ben knows he is a Co-owner
        ben.ws.remove_document(grid)
    view(ben)
    set_role(anna, ben, "member")                   # before his removal reached her
    sync(anna, carol, dana, ben, rounds=3)
    for p in (anna, carol, dana):
        assert has(p, grid) and choices(p, jobs) == {fp: 0}, p.name   # nothing taken disappears
    assert project(ben)["canon"] == project(anna)["canon"] == project(dana)["canon"]
    assert view(ben)["role"] == "member" and not view(ben)["can_write"]
    assert [(q["doc"], q["by"]["id"]) for q in proposals(anna, state="waiting", kind="remove")] == [(grid, ben.id)]
    # Co-owner again: a new grant; a row written under the old one never counts again
    set_role(anna, ben, "co")
    sync(anna, ben, carol, dana)
    with dana:
        cx = dana.ws._conn()
        new_grant = ownership.roles(cx)[ben.id]["grant"]
        assert new_grant and new_grant != old_grant
        k = ownership.canon(cx)[jobs]
        r = cx.execute("SELECT * FROM canon WHERE doc=? AND by=?", (jobs, anna.id)).fetchone()
        row = dict(r)
        hist = json.loads(row["hist_json"] or "{}")
        hist["state"] = [[k["state_n"], k["state_by"]], [10 ** 6, ben.id]]
        row.update(by=ben.id, grant=old_grant, n=10 ** 6, state="removed", state_n=10 ** 6, state_by=ben.id,
                   hist_json=json.dumps(hist))
        with dana.ws.connect() as w:
            w.execute(f"INSERT OR REPLACE INTO canon({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                      list(row.values()))
        assert ownership.canon(cx)[jobs]["state"] == "in"
        with dana.ws.connect() as w:                # (the control: under the grant that holds, it would count)
            w.execute("UPDATE canon SET grant=? WHERE doc=? AND by=?", (new_grant, jobs, ben.id))
        assert ownership.canon(cx)[jobs]["state"] == "removed"


def test_i2_on_a_bare_database_only_the_latest_owners_rows_and_live_grants_count(tmp_path):
    ws = bare(tmp_path)
    put_row(ws, "d1", B, 5, ai=("none", (5, B)), knew={"ai": [(1, A)]})
    put_row(ws, "d1", A, 2)
    assert K(ws)["d1"]["ai_access"] == "none"
    put_row(ws, "d1", B, 5, grant="gold", ai=("none", (5, B)), knew={"ai": [(1, A)]})
    assert K(ws)["d1"]["ai_access"] == "cloud"     # an old grant: the row does not count
    with ws.connect() as cx:                       # a former owner's row stops counting once the new owner's exists
        cx.execute("INSERT INTO ownership(seq, owner, by, at, kind, after) VALUES (2, ?, ?, '2026', 'handover', ?)",
                   (C, A, A))
        cx.execute("INSERT INTO owner_pins(seq, by, owner, state, at) VALUES (2, ?, ?, 'followed', '2026')", (A, C))
    put_row(ws, "d2", A, 9, ai=("none", (9, A)))
    assert K(ws)["d2"]["ai_access"] == "none"
    with ws.connect() as cx:
        cx.execute("INSERT INTO canon(doc, by, owner_seq, n, state, state_n, ai_access, ai_n, reader, read_n, "
                   "blocks_json, blocks_n) VALUES ('d2', ?, 2, 1, 'in', 1, 'cloud', 1, 1, 1, '{}', 1)", (C,))
    assert K(ws)["d2"]["ai_access"] == "cloud" and K(ws)["d2"]["ai_by"] == C


# ---- I3 --------------------------------------------------------------------------------------------------------------
def test_i3_a_later_number_that_did_not_know_a_stricter_setting_does_not_undo_it(crew):
    anna, ben, carol, dana = crew
    iv = doc_of(anna, "Desalination")
    set_level(anna, iv, "none")                     # Anna: No AI
    view(anna)
    for i in range(3):                              # Ben, unknowing, restores and leaves out (his numbers grow)
        leave_out(ben, iv, 0, included=bool(i % 2))
        view(ben)
    with ben:
        ben_n = ben.ws.scalar("SELECT n FROM canon WHERE doc=? AND by=?", (iv, ben.id))
    with anna:
        anna_n = anna.ws.scalar("SELECT n FROM canon WHERE doc=? AND by=?", (iv, anna.id))
    assert ben_n > anna_n
    sync(ben, anna, carol, dana, rounds=2)
    for p in crew:
        assert level(p, iv) == "none", p.name
    with anna:
        k = ownership.canon(anna.ws._conn())[iv]
        assert k["ai_access"] == "none" and not [c for c in k["clashes"] if c["part"] == "ai"]
    set_level(ben, iv, "cloud")                     # having followed it: his looser word counts
    sync(ben, anna, carol, dana)
    assert project(anna)["canon"][iv][1][0] == "cloud" and level(ben, iv) == "cloud"
    assert level(anna, iv) == "none" and [o["doc"] for o in view(anna)["offers"]] == [iv]   # offered, not set
    allow(anna, iv)
    assert level(anna, iv) == "cloud"


def test_i3_sixty_changes_later_the_old_stricter_word_still_holds(tmp_path):
    ws = bare(tmp_path)
    events = [(n, A) for n in range(2, 63)]        # Anna's 61 changes of who may read it, the last No AI
    hist = [[n, "local" if n % 2 else "none", A] for n, _ in events]
    put_row(ws, "d1", A, 62, ai=("none", (62, A)), ai_hist=hist[-50:])   # her list keeps 50
    put_row(ws, "d1", B, 70, ai=("cloud", (1, A)), blocks=({"x": [0, None]}, (70, B)))   # Ben's, unknowing
    k = K(ws)["d1"]
    assert k["ai_access"] == "none" and "x" in k["blocks"]
    with ws.connect() as cx:                       # and a list that kept the old event never loses it
        cx.execute("DELETE FROM canon WHERE by=?", (B,))
    put_row(ws, "d1", B, 70, ai=("cloud", (1, A)), blocks=({"x": [0, None]}, (70, B)))
    with ws.connect() as cx:
        r = dict(cx.execute("SELECT * FROM canon WHERE by=?", (A,)).fetchone())
    assert len(json.loads(r["ai_hist_json"])) <= 50


def test_i3_the_cap_never_drops_another_rows_current_event(crew):
    anna, ben = crew[:2]
    jobs = doc_of(anna, "jobs")
    for i in range(60):
        set_level(anna, jobs, "local" if i % 2 == 0 else "none")
        view(anna)
    with anna:
        r = anna.ws._conn().execute("SELECT ai_hist_json, hist_json FROM canon WHERE doc=? AND by=?",
                                    (jobs, anna.id)).fetchone()
    assert len(json.loads(r[0])) <= 50
    with anna:
        k = ownership.canon(anna.ws._conn())[jobs]
        assert all(e in {tuple(h[::2]) for h in json.loads(r[0])} | {(k["ai_n"], k["ai_by"])}
                   for e in k["events"]["ai"])


# ---- I4 --------------------------------------------------------------------------------------------------------------
def test_i4_removed_against_kept_at_the_same_time_the_document_stays(crew):
    anna, ben, carol, dana = crew
    grid = doc_of(anna, "Grid")
    with ben:
        ben.ws.remove_document(grid)               # a Co-owner removes it
    view(ben)
    with carol:                                    # another keeps it, unknowing (writes its state again: *Leave it so*)
        with carol.ws.connect() as cx:
            ctx = ownership._Ctx(carol.ws, cx, carol.id)
            ctx.put(grid, ("state",))
            ctx.follow(grid, "state")
            ctx.save()
    sync(ben, carol, anna, dana, rounds=3)
    for p in crew:
        assert has(p, grid), p.name                # in Ben's copy too: his removal is spent
        assert project(p)["canon"][grid][0][0] == "in", p.name
    assert [c["part"] for c in view(anna)["clashes"]] == ["state"]


def test_i4_on_a_bare_database_the_newer_reader_and_the_stricter_level_count(tmp_path):
    ws = bare(tmp_path)
    put_row(ws, "d1", B, 5, read=(("fp3", 3), (5, B)), knew={"read": [(1, A)]})
    put_row(ws, "d1", C, 6, read=(("fp4", 4), (6, C)), knew={"read": [(1, A)]})
    k = K(ws)["d1"]
    assert (k["reader"], k["text_fp"]) == (4, "fp4") and [c["part"] for c in k["clashes"]] == ["read"]
    put_row(ws, "d2", B, 5, ai=("none", (5, B)), knew={"ai": [(1, A)]})
    put_row(ws, "d2", C, 6, ai=("local", (6, C)), knew={"ai": [(1, A)]})
    assert K(ws)["d2"]["ai_access"] == "none"
    put_row(ws, "d3", B, 5, state=("removed", (5, B)), knew={"state": [(1, A)]})
    put_row(ws, "d3", C, 6, state=("in", (6, C)), knew={"state": [(1, A)]})
    assert K(ws)["d3"]["state"] == "in"
    put_row(ws, "d3", C, 7, state=("in", (6, C)), knew={"state": [(1, A)]})          # copied: still at the same time
    assert K(ws)["d3"]["state"] == "in"
    put_row(ws, "d4", B, 5, blocks=({"x": [0, None]}, (5, B)))
    put_row(ws, "d4", C, 6, blocks=({"y": [0, None]}, (6, C)))
    assert K(ws)["d4"]["blocks"] == {"y": [0, None]}                                   # the larger person id's
    put_row(ws, "d4", B, 8, blocks=({"x": [0, None], "y": [0, None]}, (8, B)), knew={"blocks": [(5, B), (6, C)]})
    k = K(ws)["d4"]
    assert k["blocks"] == {"x": [0, None], "y": [0, None]} and not k["clashes"]       # a word knowing both


# ---- I5 --------------------------------------------------------------------------------------------------------------
def test_i5_ai_blocks_and_a_reading_changed_at_once_by_three_writers_all_hold(crew):
    anna, ben, carol, dana = crew
    old, iv = doc_of(anna, "older field report"), doc_of(anna, "Interview")
    set_level(anna, old, "none")                   # Anna: who may read it with AI
    set_level(anna, iv, "local")
    view(anna)
    fp = leave_out(ben, iv, 0)                     # Ben: which passages are read
    view(ben)
    move(carol, old)                               # Carol: reads it again with the new reader
    view(carol)
    new = reader_of(carol, old)
    assert new > 1
    sync(anna, ben, carol, dana, rounds=3)
    for p in crew:
        assert level(p, old) == "none" and reader_of(p, old) == new, p.name
        assert level(p, iv) == "local" and choices(p, iv) == {fp: 0}, p.name
    k = project(anna)["canon"]
    assert k[old][1][2] == anna.id and k[old][2][3] == carol.id and k[iv][3][2] == ben.id
    with anna:
        assert not any(x["clashes"] for x in ownership.canon(anna.ws._conn()).values())


def test_i5_on_a_bare_database_three_parts_changed_unknowing_all_hold(tmp_path):
    ws = bare(tmp_path, co=(B, C))
    put_row(ws, "d1", A, 5, ai=("none", (5, A)), knew={"ai": [(1, A)]})
    put_row(ws, "d1", B, 6, blocks=({"x": [0, None]}, (6, B)), knew={"blocks": [(1, A)]})
    put_row(ws, "d1", C, 7, read=(("fp4", 4), (7, C)), knew={"read": [(1, A)]})
    k = K(ws)["d1"]
    assert (k["ai_access"], k["blocks"], k["reader"]) == ("none", {"x": [0, None]}, 4) and not k["clashes"]
    assert (k["ai_by"], k["blocks_by"], k["read_by"]) == (A, B, C)


# ---- I6 --------------------------------------------------------------------------------------------------------------
def test_i6_two_co_owners_exchange_until_nothing_comes_and_the_last_round_writes_no_row(crew, tmp_path):
    anna, ben, carol, dana = crew
    desal, jobs, grid, iv = (doc_of(anna, t) for t in ("Desalination", "jobs", "Grid", "Interview"))
    with ben:                                       # Ben: every part, offline
        ben.ws.remove_document(desal)
    leave_out(ben, jobs, 0)
    set_level(ben, grid, "local")
    move(ben, doc_of(anna, "older field report"))
    new_c = add_doc(carol, tmp_path, "note", text=NOTE)
    leave_out(carol, jobs, 2)                       # Carol: every part too, partly the same documents
    set_level(carol, grid, "none")
    set_level(carol, iv, "local")
    sync(ben, carol, rounds=2)
    sync(anna, dana, ben, carol, rounds=2)
    assert project(ben)["canon"] == project(carol)["canon"] == project(anna)["canon"] == project(dana)["canon"]
    for p in crew:
        assert not has(p, desal) and has(p, new_c) and level(p, grid) == "none", p.name
    before = {p.name: row_keys(p) for p in crew}
    sync(ben, carol, anna, dana)
    assert {p.name: row_keys(p) for p in crew} == before


# ---- I7 --------------------------------------------------------------------------------------------------------------
def test_i7_a_clash_is_shown_to_the_writers_logged_once_and_ended_by_leave_it_so(crew):
    anna, ben, carol, dana = crew
    grid = doc_of(anna, "Grid")
    set_level(ben, grid, "local")
    set_level(carol, grid, "none")
    view(ben), view(carol)
    sync(ben, carol, anna, dana, rounds=2)
    for p in crew:
        assert level(p, grid) == "none", p.name    # the stricter holds
    cl = {p.name: view(p)["clashes"] for p in crew}
    assert [(c["kind"], c["part"], c["doc"]) for c in cl["Anna"]] == [("part", "ai", grid)]
    assert [c["id"] for c in cl["Ben"]] == [c["id"] for c in cl["Carol"]] == [c["id"] for c in cl["Anna"]]
    assert cl["Dana"] == []
    assert {x["id"] for x in cl["Anna"][0]["people"]} == {ben.id, carol.id}
    sync(anna, ben, carol, dana)
    for p in (anna, ben, carol):
        assert clash_entries(p) == [cl["Anna"][0]["id"]], p.name
    assert clash_entries(dana) == []
    with ben:
        ownership.decide_again(ben.ws, cl["Ben"][0]["id"])
    sync(ben, anna, carol, dana)
    for p in crew:
        assert view(p)["clashes"] == [] and level(p, grid) == "none", p.name


def test_i7_on_a_bare_database_a_proposal_answered_both_ways_is_a_clash_and_its_change_is_void(tmp_path):
    ws = bare(tmp_path)
    with ws.connect() as cx:
        cx.execute("INSERT INTO proposals(id, kind, doc, title, by, at, detail_json) VALUES ('q1', 'remove', 'd1', "
                   "'Jobs', ?, '2026', '{}')", ("p" + "d" * 12,))
    via = {"state": {"p": "q1", "d": [B, 1], "was": "in", "was_n": 1, "was_by": A}}
    put_row(ws, "d1", B, 5, state=("removed", (5, B)), knew={"state": [(1, A)]}, via=via)
    answer(ws, "q1", B, 1, "accept")
    assert K(ws)["d1"]["state"] == "removed"
    answer(ws, "q1", C, 1, "decline")             # at the same time
    k = K(ws)["d1"]
    assert k["state"] == "in" and (5, B) in k["void"]["state"]
    cl = ownership.clashes(ws._conn())
    assert [(c["kind"], c["accepted"], c["declined"]) for c in cl] == [("answer", [B], [C])]
    answer(ws, "q1", A, 1, "decline", knew=[(B, 1), (C, 1)])   # decided again, knowing both: it counts
    assert ownership.clashes(ws._conn()) == [] and K(ws)["d1"]["state"] == "in"
    answer(ws, "q1", A, 1, "accept", knew=[(B, 1), (C, 1)])    # an accept again: the earlier change stays void
    assert K(ws)["d1"]["state"] == "in"

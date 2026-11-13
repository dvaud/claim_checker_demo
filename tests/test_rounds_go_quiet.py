"""Rounds of the shared folder go quiet after a document is read again with the new reader.

A document read by an earlier reader is moved to the current reader in one copy; the other copies follow (the word
of the owner or a Co-owner) and each writes its own research-log entry about it. Then rounds of every copy: they must end in a round
that writes no file and no row, and no research-log entry may change once a copy holds it (only new ones come in).
The randomised roles test once seemed to show two copies handing such entries back and forth for ever; it was its
own loop (a round there stopped at the first copy that wrote). These keep the real thing from happening.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from enlens_claims import ingest, ownership
from enlens_claims.sync import folder
from owner_helpers import add_doc, level, move, proposals, reader_of, set_level, set_role, sync
from owner_more_helpers import join_zip, small_project
from roles_helpers import OLD
from test_shared_projects import Person

ROUNDS = 8  # at most; four rounds of every copy are enough for what these tests do


def _team(tmp_path: Path, monkeypatch) -> tuple[Person, Person, Person, str]:
    """Anna (the owner), Ben (a Co-owner) and Carol (a Member) work through one shared folder; the project holds an
    older field report that reader 1 read."""
    shared = tmp_path / "Közös mappa"
    shared.mkdir()
    anna, ben, carol = (Person(tmp_path, n, monkeypatch) for n in ("Anna", "Ben", "Carol"))
    small_project(anna, tmp_path / "anna-project", keys=("desalination", "jobs"))
    old = add_doc(anna, tmp_path, "old", reader=1, text=OLD)
    join_zip(ben, anna, tmp_path / "ben-project")
    join_zip(carol, anna, tmp_path / "carol-project")
    for p in (anna, ben, carol):
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben, carol)
    set_role(anna, ben, "co")
    sync(anna, ben, carol)
    assert all(reader_of(p, old) == 1 for p in (anna, ben, carol))
    return anna, ben, carol, old


def _log(p: Person) -> dict[str, tuple]:
    """Every research-log entry of this copy but its own notes of rounds (`sync`, never sent), whole."""
    with p:
        return {r[0]: tuple(r) for r in p.ws.query("SELECT * FROM research_log WHERE kind != 'sync'")}


def _decided(p: Person) -> dict:
    with p:
        cx = p.ws._conn()
        return {t: sorted(tuple(r) for r in cx.execute(f"SELECT * FROM {t}")) for t in ("canon", "decisions", "roles")}


def _files(shared: Path) -> dict[str, tuple[int, int]]:
    return {str(f.relative_to(shared)): (f.stat().st_size, f.stat().st_mtime_ns) for f in shared.rglob("*")
            if f.is_file()}


def _until_quiet(team: tuple[Person, ...], shared: Path) -> int:
    """Rounds of every copy (each copy reads and writes once per round) until a round writes nothing: no bundle, no
    file in the folder (`read.json` changes while copies still take in the last bundles), no row of what decides the
    project, no research-log entry. Returns how many rounds it took. A research-log entry a copy holds never changes
    on the way."""
    held = {p.name: _log(p) for p in team}
    for n in range(1, ROUNDS + 1):
        files, decided, logs = _files(shared), {p.name: _decided(p) for p in team}, dict(held)
        wrote = []
        for p in team:
            with p:
                r = folder.sync_now(p.ws)
                assert not [x for x in r["problems"] if x["kind"] != "documents"], (p.name, r["problems"])
                for d in r.get("moves_due") or []:
                    ownership.move_now(p.ws, d)
            if (r.get("wrote") or {}).get("seq") is not None:
                wrote.append(p.name)
            now = _log(p)
            moved = {e: (held[p.name][e], now.get(e)) for e in held[p.name] if now.get(e) != held[p.name][e]}
            assert not moved, (f"round {n}: {p.name}'s research-log entries changed", moved)
            held[p.name] = now
        if not wrote and _files(shared) == files and {p.name: _decided(p) for p in team} == decided and held == logs:
            return n
    pytest.fail(f"the copies still wrote after {ROUNDS} rounds of every copy")


def _same_log(team: tuple[Person, ...]) -> None:
    """Every copy holds the same entries (the app's own and the people's), each as its author wrote it."""
    first = _log(team[0])
    for p in team[1:]:
        assert _log(p) == first, p.name


def test_the_owner_reads_a_document_again_and_the_rounds_go_quiet(tmp_path, monkeypatch):
    anna, ben, carol, old = _team(tmp_path, monkeypatch)
    shared = tmp_path / "Közös mappa"
    move(anna, old)
    n = _until_quiet((anna, ben, carol), shared)
    assert n <= 4  # their new reading, each copy's own move, the acknowledgements (`read.json`), then quiet
    assert all(reader_of(p, old) == ingest.READER for p in (anna, ben, carol))
    _same_log((anna, ben, carol))
    with anna:
        rereads = anna.ws.query("SELECT person_id FROM research_log WHERE kind='reread' AND subject_id=?", (old,))
    # one entry per copy that read it again: each person's own, as they did it in their copy
    assert sorted(r[0] for r in rereads) == sorted(p.id for p in (anna, ben, carol))
    # and once quiet, a further round stays quiet
    assert _until_quiet((anna, ben, carol), shared) == 1


def test_a_co_owner_reads_it_again_a_member_keeps_it_stricter_and_the_rounds_go_quiet(tmp_path, monkeypatch):
    """The case of the randomised roles test (seed 0): a Co-owner reads the older report again (in force without a
    proposal), the others follow; a Member keeps it from Claude meanwhile (the stricter setting holds in every copy,
    and her `ai-access` entry travels with it)."""
    anna, ben, carol, old = _team(tmp_path, monkeypatch)
    shared = tmp_path / "Közös mappa"
    move(ben, old)
    set_level(carol, old, "local")
    sync(ben, carol, anna)
    assert not proposals(anna, state="waiting")
    n = _until_quiet((anna, ben, carol), shared)
    assert n <= 4  # their new reading, each copy's own move, the acknowledgements (`read.json`), then quiet
    _same_log((anna, ben, carol))
    for p in (anna, ben, carol):
        assert reader_of(p, old) == ingest.READER and level(p, old) == "local", p.name
        with p:
            got = sorted(tuple(r) for r in p.ws.query("SELECT kind, person_id FROM research_log WHERE kind IN "
                                                       "('reread', 'ai-access') AND subject_id=?", (old,)))
        assert got == sorted([("ai-access", carol.id)] + [("reread", q.id) for q in (anna, ben, carol)]), p.name
    assert _until_quiet((carol, ben, anna), shared) == 1

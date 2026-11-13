"""Roles (DESIGN-roles §3.3, §3.5, §6.4): format 4, and what comes from a copy on format 3 (ENLENS 0.17).

- A zip of format 3 (who owns the project, proposals, answers and documents, but no roles, no pins, none of the new
  columns) comes into a new copy: the copy pins the owner as 0.17 named it, and reads the rows as the rules say (no
  grant: an owner's row; no knowledge: its own events only). Brought into an existing copy it is merged, and its
  sender, made a Co-owner, is shown as needing an update to act as one.
- A copy on format 3 refuses a bundle of format 4 in words and changes nothing.
- A zip of a project with no owner still needs only format 1.
- The upgrade of a 0.17 project changes nothing anyone sees: the owner, the proposals and the documents are as before.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, ownership, sync
from enlens_claims.store import Workspace
from enlens_claims.sync import folder, formats
from owner_helpers import add_doc, set_level, set_role, sync as rounds, view
from owner_more_helpers import as_before_018, canon_of, join_zip, send, small_project, states_of
from test_0_14_0_shared_projects import Person

_NEW_TABLES = ("roles", "owner_pins", "removed_docs", "sync_via", "sync_from", "sync_refused")
_NEW_COLS = {"ownership": ("sig",), "decisions": ("n", "grant", "knew_json", "sig"),
             "canon": ("grant", "state_by", "read_by", "ai_by", "blocks_by", "hist_json", "sig"),
             "canon_seen": ("state_by", "read_by", "ai_by", "blocks_by", "blocks_base", "ai_offer")}


def _as_format_3(db: Path) -> None:
    """A project database as ENLENS 0.17 (format 3) has it: no roles tables, none of the new columns, no marker."""
    cx = sqlite3.connect(db)
    try:
        for t in _NEW_TABLES:
            cx.execute(f"DROP TABLE IF EXISTS {t}")
        for t, cols in _NEW_COLS.items():
            for c in cols:
                cx.execute(f"ALTER TABLE {t} DROP COLUMN {c}")
        cx.execute("DELETE FROM meta WHERE key='roles_upgraded'")
        cx.commit()
        cx.execute("VACUUM")
    finally:
        cx.close()


def _zip_as_format_3(src: Path, out: Path) -> Path:
    tmp = out.with_suffix(".unpacked")
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zf:
        names = zf.namelist()
        data = {n: zf.read(n) for n in names}
    db = tmp / "enlens.sqlite"
    db.write_bytes(data["enlens.sqlite"])
    _as_format_3(db)
    data["enlens.sqlite"] = db.read_bytes()
    meta = json.loads(data["bundle.json"])
    meta.update(sync_format=3, sync_needs=1, version="0.17.1")
    data["bundle.json"] = json.dumps(meta).encode("utf-8")
    with zipfile.ZipFile(out, "w") as zf:
        for n in names:
            zf.writestr(n, data[n])
    return out


@pytest.fixture
def shared(tmp_path) -> Path:
    d = tmp_path / "Közös mappa"
    d.mkdir()
    return d


@pytest.fixture
def pair(tmp_path, monkeypatch):
    """Anna's small project (she is its owner), and Ben's copy from her zip."""
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    join_zip(ben, anna, tmp_path / "ben-project")
    return anna, ben


def test_a_format_3_zip_comes_into_a_new_copy_pinned_as_0_17_named_the_owner(pair, tmp_path, monkeypatch):
    anna, ben = pair
    jobs = next(iter(canon_of(anna)))
    set_level(anna, jobs, "none")
    view(anna)
    want = canon_of(anna)
    z = _zip_as_format_3(send(anna, scope="all"), tmp_path / "anna-017.zip")
    carol = Person(tmp_path, "Carol", monkeypatch)
    with carol:
        carol.ws = bundle.import_project(z, tmp_path / "carol-project")
        cx = carol.ws._conn()
        assert [tuple(r) for r in cx.execute("SELECT seq, by, owner, state FROM owner_pins")] == \
            [(1, anna.id, anna.id, "followed")]
        assert carol.ws.meta("roles_upgraded") == 1
        assert ownership.owner(cx) == anna.id and not ownership.owner_questions(cx)
    assert canon_of(carol) == want
    assert view(carol)["role"] == "member"


def test_a_format_3_zip_is_merged_and_its_co_owner_is_shown_as_needing_an_update(pair, tmp_path):
    anna, ben = pair
    rounds_zip = send(ben, scope="all")
    anna.bring_in(rounds_zip)
    set_role(anna, ben, "co")
    ben.bring_in(send(anna, scope="all"))              # Ben's copy knows he is a Co-owner: it writes, proposes nothing
    assert view(ben)["role"] == "co"
    doc = add_doc(ben, tmp_path, "interview")
    z = _zip_as_format_3(send(ben), tmp_path / "ben-017.zip")
    anna.bring_in(z)
    with anna:
        assert anna.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))
    v = view(anna)
    ben_row = next(x for x in v["people"] if x["id"] == ben.id)
    assert ben_row["role"] == "co" and ben_row["needs_update"]
    # a copy on 0.17 cannot act as a Co-owner: its rows have no grant, so they are read as an owner's, and Ben never
    # owned the project: his addition is not the project's (0.17 sends it as a proposal)
    assert doc not in canon_of(anna)


def test_a_copy_on_format_3_refuses_a_format_4_bundle_in_words_and_changes_nothing(pair, shared, monkeypatch):
    anna, ben = pair
    for p in (anna, ben):
        with p:
            folder.set_folder(p.ws, str(shared))
    rounds(anna, ben)
    with ben:
        before = ben.ws.counts()
    set_level(anna, next(iter(canon_of(anna))), "none")
    with anna:
        folder.sync_now(anna.ws)
    monkeypatch.setattr(formats, "FORMAT", 3)
    with ben:
        out = folder.sync_now(ben.ws)
        words = " ".join(str(x.get("text") or x.get("message") or x) for x in out["problems"])
        assert "Update ENLENS" in words and "Nothing was changed" in words
        assert ben.ws.counts() == before


def test_a_zip_needs_format_4_only_once_the_project_has_an_owner(tmp_path, monkeypatch):
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    small_project(ben, tmp_path / "ben-project")
    as_before_018(ben)                                 # exchanged before 0.18, and no owner since
    with ben:
        assert formats.zip_needs(ben.ws._conn()) == formats.ZIP_NEEDS == 1
        z = tmp_path / "ben.zip"
        bundle.export_project(ben.ws, z)
        assert not ben.ws.scalar("SELECT 1 FROM ownership")
    assert sync.peek(z)["sync_needs"] == 1            # nothing new travels: an older copy goes on reading it
    with anna:
        assert formats.zip_needs(anna.ws._conn()) == 1
        ownership.ensure_owner(anna.ws._conn(), anna.id)
        assert formats.zip_needs(anna.ws._conn()) == formats.OWNED_ZIP_NEEDS == 4


def test_the_upgrade_of_a_0_17_project_changes_nothing_anyone_sees(tmp_path, monkeypatch):
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    join_zip(ben, anna, tmp_path / "ben-project")
    docs = sorted(canon_of(anna))
    with ben:
        ben.ws.remove_document(docs[0])
    set_level(ben, docs[1], "cloud")
    set_level(anna, docs[2], "none")
    view(anna)
    anna.bring_in(send(ben, scope="all"))
    before = {p.name: (ownership.owner(p.ws._conn()), canon_of(p), states_of(p)) for p in (anna, ben)}
    for p in (anna, ben):
        p.ws.close_all()
        _as_format_3(p.ws.db_path)
        with p:
            p.ws = Workspace.open(p.ws.root)          # the update: the migration runs once
            cx = p.ws._conn()
            assert [tuple(r) for r in cx.execute("SELECT state FROM owner_pins")] == [("followed",)]
        assert (ownership.owner(p.ws._conn()), canon_of(p), states_of(p)) == before[p.name], p.name

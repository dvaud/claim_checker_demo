"""Roles (DESIGN-roles §4.11, §5.6): a second computer is its own person. A data folder copied to another computer
(with its projects) is stopped before it writes into the shared folder under the same person id; *Use both computers*
gives it an id of its own."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from enlens_claims import home, people
from enlens_claims.store import Workspace
from enlens_claims.sync import folder
from owner_helpers import add_doc
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_0_18_0_owner import shared_dir, team  # noqa: F401  (fixtures)


def _files(d: Path) -> dict[str, str]:
    return {f.relative_to(d).as_posix(): hashlib.sha1(f.read_bytes()).hexdigest() for f in sorted(d.rglob("*"))
            if f.is_file()}


def _round(p: Person) -> dict:
    with p:
        return folder.sync_now(p.ws)


def _ok(r: dict) -> None:
    assert not [x for x in r["problems"] if x["kind"] not in ("documents",)], r["problems"]


def _copy(p: Person, tmp: Path, monkeypatch, name: str) -> Person:
    """Another computer made from a copy of `p`'s data folder and project folder (not a move zip)."""
    other = Person.__new__(Person)
    other.name, other.home, other.mp = name, tmp / f"home-{name}", monkeypatch
    other.files, other.n = tmp / f"sent-{name}", 0
    other.files.mkdir()
    shutil.copytree(p.home, other.home)
    with p:
        p.ws.close_all()
    shutil.copytree(p.ws.root, tmp / f"project-{name}")
    other.ws = Workspace.open(tmp / f"project-{name}")
    other.id = p.id
    return other


def _mine(p: Person) -> Path:
    with p:
        return folder.chosen(p.ws) / folder.team_name(p.ws) / p.id


def test_each_installation_has_its_own_id_and_a_copied_data_folder_gets_a_new_one(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "a"))
    first = home.installation_id()
    assert len(first) == 16 and home.installation_id() == first
    assert home.load_settings()["installation_id"] == first
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "b"))
    second = home.installation_id()
    assert second != first and home.installation_id() == second
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "a"))
    assert home.installation_id() == first
    with pytest.raises(ValueError):
        home.update_settings({"installation_id": "not mine"})


def test_a_copied_data_folder_writes_nothing_and_deletes_nothing_under_the_same_person(team, tmp_path, monkeypatch):
    anna, ben, _carol = team
    anna2 = _copy(anna, tmp_path, monkeypatch, "Anna2")
    add_doc(anna, tmp_path, "jobs")
    _ok(_round(anna))  # the first computer goes on: its subfolder now has a bundle the copy never saw
    mine = _mine(anna)
    head = json.loads((mine / "head.json").read_text(encoding="utf-8"))
    with anna:
        assert head["installation"] == home.installation_id()
    before = _files(mine)
    add_doc(anna2, tmp_path, "grid")
    r = _round(anna2)
    kinds = [x["kind"] for x in r["problems"]]
    assert "other_computer" in kinds and r["wrote"] is None
    msg = next(x["message"] for x in r["problems"] if x["kind"] == "other_computer")
    assert "Another computer is writing into this folder under your name" in msg and "nothing is lost" in msg
    assert _files(mine) == before  # nothing written, nothing deleted (no bundle, no head.json, no read.json)
    with anna2:
        st = folder.status(anna2.ws)
    assert st["other_computer"] and st["other_computer"]["since"] == head["at"]
    assert any(x["kind"] == "other_computer" for x in st["problems"])
    with anna:
        assert folder.status(anna.ws)["other_computer"] is None
    _ok(_round(anna))  # the first computer is not held up
    assert _round(anna2)["wrote"] is None  # and the copy stays stopped, round after round

    # *Use both computers*: a person of its own; what it did so far stays under the first id
    with anna2:
        new = home.new_identity("Anna (laptop)")
        assert new != anna.id and people.me() == new and people.my_name() == "Anna (laptop)"
        assert home.load_settings()["person_id"] == new
    anna2.id = new
    r = _round(anna2)
    _ok(r)
    assert r["wrote"] and r["wrote"]["seq"]
    with anna2:
        assert folder.status(anna2.ws)["other_computer"] is None
    assert _files(mine) == before  # the first computer's subfolder is as the first computer left it
    _ok(_round(anna))
    with anna:
        names = {p["id"]: p["name"] for p in folder.status(anna.ws)["people"]}
    assert names.get(new) == "Anna (laptop)"


def test_of_two_copies_that_wrote_nothing_since_the_first_to_write_goes_on_and_the_other_stops(team, tmp_path,
                                                                                               monkeypatch):
    anna, _ben, _carol = team
    anna2 = _copy(anna, tmp_path, monkeypatch, "Anna2")  # (a data folder moved or restored is the same case)
    add_doc(anna2, tmp_path, "grid")
    r = _round(anna2)
    _ok(r)  # its record of the folder holds what the folder says: it goes on, and the folder names it now
    assert r["wrote"]["seq"]
    mine = _mine(anna)
    with anna2:
        assert json.loads((mine / "head.json").read_text(encoding="utf-8"))["installation"] == home.installation_id()
    before = _files(mine)
    add_doc(anna, tmp_path, "jobs")
    r = _round(anna)
    assert "other_computer" in [x["kind"] for x in r["problems"]] and r["wrote"] is None
    assert _files(mine) == before


def test_a_head_written_before_roles_gets_this_installation_or_stops_the_round(team, tmp_path, monkeypatch):
    anna, _ben, _carol = team
    mine = _mine(anna)
    f = mine / "head.json"
    head = json.loads(f.read_text(encoding="utf-8"))
    head.pop("installation")
    f.write_text(json.dumps(head), encoding="utf-8")  # as 0.17 wrote it
    _ok(_round(anna))  # this copy's record matches it: the round goes on, even with nothing to write
    with anna:
        assert json.loads(f.read_text(encoding="utf-8"))["installation"] == home.installation_id()
    head = json.loads(f.read_text(encoding="utf-8"))
    head.pop("installation")
    head["last"] = int(head["last"]) + 1  # another computer of 0.17 wrote one more bundle
    f.write_text(json.dumps(head), encoding="utf-8")
    before = _files(mine)
    r = _round(anna)
    assert "other_computer" in [x["kind"] for x in r["problems"]]
    assert _files(mine) == before


def test_same_as_makes_one_rater_of_two_computers(team, tmp_path, monkeypatch):
    anna, _ben, _carol = team
    from enlens_claims import ownership

    anna2 = _copy(anna, tmp_path, monkeypatch, "Anna2")
    with anna2:
        anna2.id = home.new_identity("Anna (laptop)")
    _ok(_round(anna2))
    _ok(_round(anna))
    with anna:  # roles-p1: P1's and P2's functions are real now (no skip while they were stubs)
        ownership.set_same_as(anna.ws, anna2.id, anna.id)
        assert people.group(anna.ws._conn(), anna.id) == {anna.id, anna2.id}
        assert next(x for x in ownership.view(anna.ws)["people"] if x["id"] == anna2.id)["same_as"] == anna.id
    _ok(_round(anna))
    _ok(_round(anna2))                    # the laptop's copy reads the Owner's word too
    with anna2:
        assert people.group(anna2.ws._conn(), anna2.id) == {anna.id, anna2.id}

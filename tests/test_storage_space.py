"""0.18.0rc2 (roadmap L6): a storage space of the team's own.

The owner sets up a storage space; colleagues join from an invite link; every file in the space is sealed (encrypted
with the project's key, signed by its writer) and each copy keeps a copy of the space on its computer, on which the
shared folder's rules run unchanged (sync/space.py, sync/seal.py). These tests use a space kept in a folder (the same
sealed layout as at Backblaze or Cloudflare, without a network): each person has their own ENLENS folder, keychain and
copy of the project.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enlens_claims import claimcheck, home, people, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder, seal, space
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)


def _round(p: Person, ok_kinds=("documents",)) -> dict:
    with p:
        out = folder.sync_now(p.ws)
    bad = [x for x in out["problems"] if x["kind"] not in ok_kinds]
    assert not bad, bad
    return out


def _check(p: Person, text: str) -> str:
    with p:
        return claimcheck.check_hypothesis(p.ws, text, BaselineBackend(), "baseline", k=2)


def _share(p: Person, kind: str, key: str) -> None:
    with p:
        sharing.share(p.ws, [{"kind": kind, "key": key}])


def _has(ws, hid: str) -> bool:
    return bool(ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,)))


@pytest.fixture
def store_dir(tmp_path) -> Path:
    d = tmp_path / "Tárhely" / "bucket"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def owner(anna_and_ben, store_dir):
    """Anna, the owner, with a storage space (in a folder)."""
    anna, _ben = anna_and_ben
    with anna:
        space.setup_dir(anna.ws, store_dir)
    _round(anna)
    return anna


def _join_new(p: Person, link: str) -> None:
    with p:
        name = space.join_new_project(link)
        p.ws = home.open_project(name)


@pytest.fixture
def team(owner, tmp_path, monkeypatch):
    """Anna (owner) and Carol, who joined from an invite link into a new, empty project."""
    carol = Person(tmp_path, "Carol", monkeypatch)
    with owner:
        inv = space.invite(owner.ws, "Carol")
    _join_new(carol, inv["link"])
    return owner, carol


def test_a_colleague_joins_from_a_link_and_gets_the_project(team):
    anna, carol = team
    with carol:
        assert not folder.status(carol.ws)["space"]["joined"]  # the owner's copy has not bound Carol's part yet
    with anna:
        n_docs = anna.ws.scalar("SELECT COUNT(*) FROM documents")
        hid = _check(anna, "Electrolysers create local jobs.")
    _share(anna, "check", hid)
    _round(anna)  # binds Carol, and writes the shared check
    _round(carol)
    with carol:
        assert carol.ws.scalar("SELECT COUNT(*) FROM documents") == n_docs  # every document, read and with its file
        assert _has(carol.ws, hid)
        assert carol.ws.meta("project_uid") == anna.ws.meta("project_uid")
        st = folder.status(carol.ws)
    assert st["space"]["where"].startswith("a folder on this computer") and st["space"]["joined"]
    with anna:
        st = folder.status(anna.ws)["space"]
    assert [m["name"] for m in st["members"]] == ["Anna", "Carol"] and not st["invites"]
    with carol:
        hc = _check(carol, "Hydrogen storage is cheap.")
    _share(carol, "check", hc)
    _round(carol)
    _round(anna)
    with anna:
        assert _has(anna.ws, hc)


def test_the_storage_holds_only_sealed_files(team, store_dir):
    anna, carol = team
    hid = _check(anna, "Electrolysers create local jobs.")
    _share(anna, "check", hid)
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        words = [r[0] for r in anna.ws.query("SELECT text FROM passages LIMIT 40") if r[0] and len(r[0]) > 60]
    files = [f for f in store_dir.rglob("*") if f.is_file()]
    assert len(files) > 10
    for f in files:
        b = f.read_bytes()
        assert b"Anna" not in b and b"Carol" not in b and b"Electrolysers" not in b, f
        assert not any(w[:40].encode() in b for w in words), f
        if "/parts/" in f.as_posix():
            assert b.startswith(seal.MAGIC), f
    # readings and files are stored under hidden names, not their own
    names = {f.name for f in files}
    assert not any(n.endswith(".zip") or n.endswith(".pdf") or n.endswith(".txt") for n in names)


def test_a_file_put_in_someone_elses_part_is_set_aside(team, store_dir, tmp_path, monkeypatch):
    anna, carol = team
    for p in (anna, carol, anna):
        _round(p)
    # Carol (a member, who holds the project's key) writes a bundle into Anna's part, signed with her own key
    with carol:
        desc = space.configured(carol.ws)
        ident = seal.Identity.load(space.keychain.get(space._secret_name(desc["id"], "me")))
        names, epochs = space._keys(desc["id"])
    roster = json.loads((store_dir / desc["prefix"] / "space" / "roster.json").read_bytes())
    anna_part = next(p for p, m in roster["members"].items() if m["person"] == anna.id)
    forged = seal.seal(b"not a bundle", path=f"{anna.id}/bundles/000099.zip", by=anna_part, epoch=max(epochs),
                       key=epochs[max(epochs)], ident=ident)
    (store_dir / desc["prefix"] / "parts" / anna_part / "b" / "000099").write_bytes(forged)
    dave = Person(tmp_path, "Dave", monkeypatch)
    with anna:
        inv = space.invite(anna.ws)
    _join_new(dave, inv["link"])
    out = _round(dave)
    with dave:
        st = folder.status(dave.ws)["space"]
        mirror = space.mirror_of(dave.ws) / folder.team_name(dave.ws) / anna.id / "bundles"
    assert [x["why"] for x in st["set_aside"]] == ["signature"]
    assert not (mirror / "000099.zip").exists()
    assert out["read"]  # Anna's own work still came in


def test_an_invite_used_without_its_secret_is_set_aside(owner, store_dir):
    with owner:
        inv = space.invite(owner.ws)
        desc = space.configured(owner.ws)
    payload = space.parse_link(inv["link"])
    payload["join"] = seal.b64(seal.new_key())  # someone who guessed the part but not the invite's secret
    ident = seal.Identity.new()
    k = seal.unb64(payload["keys"]["epochs"]["1"])
    blob = space._key_file(ident, payload, "p0123456789ab", 1, k)
    (store_dir / desc["prefix"] / "parts" / payload["part"] / "m").mkdir(parents=True)
    (store_dir / desc["prefix"] / "parts" / payload["part"] / "m" / "key.json").write_bytes(blob)
    _round(owner)
    with owner:
        st = folder.status(owner.ws)["space"]
    assert [i["part"] for i in st["invites"]] == [payload["part"]]   # still waiting
    assert [x["why"] for x in st["set_aside"]] == ["join"]
    assert [m["name"] for m in st["members"]] == ["Anna"]


def test_a_roster_not_signed_by_the_keeper_is_set_aside(team, store_dir):
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with carol:
        desc = space.configured(carol.ws)
        ident = seal.Identity.load(space.keychain.get(space._secret_name(desc["id"], "me")))
    f = store_dir / desc["prefix"] / "space" / "roster.json"
    obj, _by, _sig = seal.read_signed_json(f.read_bytes())
    obj["seq"] += 5
    for m in obj["members"].values():
        if m["person"] == anna.id:
            m["removed"] = "2026-11-12T00:00:00+00:00"
    f.write_bytes(seal.signed_json(ident, obj, desc["part"]))  # Carol signs a roster that removes Anna
    out = _round(carol, ok_kinds=("documents", "set_aside"))
    assert any(x["kind"] == "set_aside" for x in out["problems"])
    with carol:
        st = folder.status(carol.ws)["space"]
    assert not any(m["removed"] for m in st["members"])


def test_removing_a_colleague_replaces_the_projects_key(team, tmp_path, monkeypatch):
    anna, carol = team
    dave = Person(tmp_path, "Dave", monkeypatch)
    with anna:
        inv = space.invite(anna.ws)
    _join_new(dave, inv["link"])
    for p in (anna, carol, dave, anna, carol, dave):
        _round(p)
    with anna:
        st = folder.status(anna.ws)["space"]
        carol_part = next(m["part"] for m in st["members"] if m["name"] == "Carol")
        space.remove_member(anna.ws, carol_part)
        desc = space.configured(anna.ws)
        assert sorted(space._keys(desc["id"])[1]) == [1, 2]
    h = _check(anna, "Fuel cells need platinum.")
    _share(anna, "check", h)
    _round(anna)
    _round(dave)  # Dave stays: he gets the new key, and Anna's new work
    with dave:
        assert sorted(space._keys(space.configured(dave.ws)["id"])[1]) == [1, 2]
        assert _has(dave.ws, h)
    _round(carol)  # Carol was removed: no new key, and what Anna wrote with it does not open for her
    with carol:
        assert sorted(space._keys(space.configured(carol.ws)["id"])[1]) == [1]
        assert not _has(carol.ws, h)
    with anna:
        assert [m["name"] for m in folder.status(anna.ws)["space"]["members"] if m["removed"]] == ["Carol"]


def test_the_keeper_follows_the_owner(team):
    from enlens_claims import ownership

    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        ownership.hand_over(anna.ws, carol.id)
    _round(anna)   # Anna's copy hands the space's keys to Carol
    with anna:
        assert not folder.status(anna.ws)["space"]["keeper"]
    _round(carol)
    with carol:
        assert folder.status(carol.ws)["space"]["keeper"]
        inv = space.invite(carol.ws)  # Carol can invite now
    assert inv["link"].startswith(space.LINK)


def test_moving_to_another_space_takes_the_team_along(team, tmp_path):
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    other = tmp_path / "new-bucket"
    other.mkdir()
    with anna:
        out = space.move(anna.ws, lambda w, ident: space.setup_dir(w, other, ident=ident))
    assert out["moved"]["told"] == 1
    _round(anna)
    _round(carol)  # Carol's copy reads where the team went, and follows
    with carol:
        assert space.configured(carol.ws)["dir"] == str(other.resolve())
    _round(carol)
    _round(anna)
    h = _check(carol, "Hydrogen valleys share pipelines.")
    _share(carol, "check", h)
    _round(carol)
    _round(anna)
    with anna:
        assert _has(anna.ws, h)


def test_links_that_are_not_invites_are_refused():
    for bad in ("", "https://example.org", "enlens://join#", "enlens://join#AAAA"):
        with pytest.raises(space.SpaceProblem):
            space.parse_link(bad)


def test_the_poller_looks_at_a_space_every_ten_minutes_at_most():
    from enlens_claims.gui import poller

    assert space.MIN_EVERY == 600 and hasattr(poller.Poller, "_wait")

"""0.18.0rc2 (roadmap L6): what an independent review of the storage space found, each proven first with a failing
test and kept here the right way round: nobody joins under another's name, a keeper who handed the space over has no
say any more, a lost copy of the space loses no member, a damaged or oversized file never stops a round, a removal
that fails halfway seals nothing with a key colleagues were not given, a failed move changes nothing, and a large file
is opened without copies of it."""
from __future__ import annotations

import base64
import json
import zlib

import pytest

from enlens_claims import claimcheck, ownership, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder, seal, space
from enlens_claims.sync.storage import DirStorage, StorageProblem
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_0_18_0_storage_space import _join_new, _round, owner, store_dir, team  # noqa: F401  (fixtures)


def _rnd(p):
    with p:
        return folder.sync_now(p.ws)


def _root(p, store_dir):
    with p:
        return store_dir / space.configured(p.ws)["prefix"]


def _pending_invite(anna, store_dir):
    with anna:
        inv = space.invite(anna.ws)
    payload = space.parse_link(inv["link"])
    e = max(int(x) for x in payload["keys"]["epochs"])
    k = seal.unb64(payload["keys"]["epochs"][str(e)])
    pd = _root(anna, store_dir) / "parts" / payload["part"] / "m"
    pd.mkdir(parents=True, exist_ok=True)
    return payload, e, k, pd


def _check(p, text):
    with p:
        h = claimcheck.check_hypothesis(p.ws, text, BaselineBackend(), "baseline", k=2)
        sharing.share(p.ws, [{"kind": "check", "key": h}])
    return h


def test_nobody_joins_under_another_members_name(team, store_dir):
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    payload, e, k, pd = _pending_invite(anna, store_dir)
    (pd / "key.json").write_bytes(space._key_file(seal.Identity.new(), payload, carol.id, e, k))   # claims Carol's id
    _rnd(anna)
    roster = json.loads((_root(anna, store_dir) / "space" / "roster.json").read_bytes())
    assert [p for p, m in roster["members"].items() if m["person"] == carol.id] != [] and \
        len([p for p, m in roster["members"].items() if m["person"] == carol.id]) == 1
    with anna:
        st = folder.status(anna.ws)["space"]
    assert [i["part"] for i in st["invites"]] == [payload["part"]]   # the invite still waits
    assert any("in the team already" in x["message"] for x in st["set_aside"])


def _hand_over(anna, carol):
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        ownership.hand_over(anna.ws, carol.id)
    _round(anna)
    _round(carol)
    with carol:
        assert folder.status(carol.ws)["space"]["keeper"]


def test_a_keeper_who_handed_over_has_no_say_any_more(team, store_dir):
    anna, carol = team
    _hand_over(anna, carol)
    with anna:
        desc = space.configured(anna.ws)
        assert space._get_secret(desc["id"], "keeper") is None and not folder.status(anna.ws)["space"]["keeper"]
        ident = seal.Identity.load(space.keychain.get(space._secret_name(desc["id"], "me")))
        names, epochs = space._keys(desc["id"])
    forged = json.dumps({"project_uid": "deadbeef" * 4, "name": "Other", "folder_id": "x" * 32}).encode()
    (_root(anna, store_dir) / "space" / "project.json").write_bytes(
        seal.seal(forged, path="project.json", by=desc["part"], epoch=max(epochs), key=epochs[max(epochs)],
                  ident=ident))
    out = _rnd(carol)
    assert not any(x["kind"] == "other_project" for x in out["problems"])


def test_the_new_keeper_loses_no_member_when_its_copy_of_the_space_is_lost(team, store_dir, tmp_path, monkeypatch):
    anna, carol = team
    _hand_over(anna, carol)
    with carol:
        (space.mirror_of(carol.ws) / ".space-state.json").unlink()
    _round(carol)
    dave = Person(tmp_path, "Dave", monkeypatch)
    with carol:
        inv = space.invite(carol.ws)
    _join_new(dave, inv["link"])
    _round(carol)
    roster = json.loads((_root(carol, store_dir) / "space" / "roster.json").read_bytes())
    assert {anna.id, carol.id, dave.id} <= {m["person"] for m in roster["members"].values()}
    _round(dave)
    _round(anna)
    with anna:
        assert sorted(m["name"] for m in folder.status(anna.ws)["space"]["members"]) == ["Anna", "Carol", "Dave"]


@pytest.mark.parametrize("obj", [{"seq": "x", "sig": "a", "signed_by": "b"},
                                 {"seq": 999, "keepers": [{"n": "x"}], "sig": "a", "signed_by": "b", "space": "SPACE"}])
def test_a_damaged_roster_never_stops_a_round(team, store_dir, obj):
    anna, carol = team
    for p in (anna, carol):
        _round(p)
    with anna:
        obj = {**obj, **({"space": space.configured(anna.ws)["id"]} if obj.get("space") == "SPACE" else {})}
    (_root(anna, store_dir) / "space" / "roster.json").write_text(json.dumps(obj))
    h = _check(carol, "Hydrogen valleys share pipelines.")
    out = _rnd(carol)
    assert any(x["kind"] == "set_aside" for x in out["problems"]) and out["wrote"]["seq"]
    with carol:
        assert space.configured(carol.ws)["roster_seq"] >= 1
    assert h


def test_a_damaged_or_oversized_key_file_never_stops_the_keepers_round(owner, store_dir, monkeypatch):
    payload, e, k, pd = _pending_invite(owner, store_dir)
    (pd / "key.json").write_bytes(seal.seal(b"[1]", path="x/key.json", by=payload["part"], epoch=e, key=k,
                                            ident=seal.Identity.new()))
    assert _rnd(owner)["wrote"] is not None
    monkeypatch.setitem(space._CAP, "m", 1000)
    (pd / "key.json").write_bytes(b"x" * 5000)
    out = _rnd(owner)
    assert out["wrote"] is not None and not [x for x in out["problems"] if x["kind"] == "too_large"]


def test_an_oversized_moved_file_never_stops_a_round(team, store_dir, monkeypatch):
    anna, carol = team
    for p in (anna, carol):
        _round(p)
    monkeypatch.setitem(space._CAP, "space", 50_000)
    (_root(anna, store_dir) / "space" / "moved.json").write_bytes(b"x" * 60_000)
    for p in (anna, carol):
        out = _rnd(p)
        assert out["wrote"] is not None and any(x["kind"] == "set_aside" for x in out["problems"])


def test_a_removal_that_fails_halfway_seals_nothing_with_a_key_nobody_got(team, store_dir, tmp_path, monkeypatch):
    anna, carol = team
    dave = Person(tmp_path, "Dave", monkeypatch)
    with anna:
        inv = space.invite(anna.ws)
    _join_new(dave, inv["link"])
    for p in (anna, carol, dave, anna, carol, dave):
        _round(p)
    real_put = DirStorage.put

    def put(self, name, data):
        if name == "space/keys.json":
            raise StorageProblem("refused", "unreachable")
        return real_put(self, name, data)

    monkeypatch.setattr(DirStorage, "put", put)
    with anna:
        carol_part = next(m["part"] for m in folder.status(anna.ws)["space"]["members"] if m["name"] == "Carol")
        with pytest.raises(space.SpaceProblem):
            space.remove_member(anna.ws, carol_part)
        assert sorted(space._keys(space.configured(anna.ws)["id"])[1]) == [1]
    monkeypatch.setattr(DirStorage, "put", real_put)
    h = _check(anna, "Fuel cells need platinum.")
    _round(anna)
    _round(dave)
    with dave:
        assert dave.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h,))


def test_a_move_that_fails_changes_nothing(team, tmp_path, monkeypatch):
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        before = space.configured(anna.ws)
    monkeypatch.setattr(space, "_member_access", lambda *a, **k: (_ for _ in ()).throw(space.SpaceProblem("no", "x")))
    other = tmp_path / "new-bucket"
    other.mkdir()
    with anna:
        with pytest.raises(space.SpaceProblem):
            space.move(anna.ws, lambda w, ident: space.setup_dir(w, other, ident=ident))
        assert space.configured(anna.ws)["id"] == before["id"]
    _round(anna)
    _round(carol)


def test_the_keeper_does_not_send_project_json_again_each_round(owner, monkeypatch):
    puts = []
    real_put = DirStorage.put
    monkeypatch.setattr(DirStorage, "put", lambda self, n, d: (puts.append(n), real_put(self, n, d))[1])
    for _ in range(3):
        _round(owner)
    assert puts.count("space/project.json") == 0


def test_a_deeper_name_cannot_remove_a_colleagues_bundle(team, store_dir):
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        apart = space.configured(anna.ws)["part"]
    bdir = _root(anna, store_dir) / "parts" / apart / "b"
    real = sorted(bdir.iterdir())[0]
    nested = bdir / "a" / real.name
    nested.parent.mkdir()
    nested.write_bytes(real.read_bytes())
    _round(carol)
    nested.unlink()
    _round(carol)
    with carol:
        mirror = space.mirror_of(carol.ws) / folder.team_name(carol.ws) / anna.id / "bundles" / f"{real.name}.zip"
    assert mirror.exists()


def test_an_invite_link_that_unpacks_to_too_much_is_refused():
    bomb = zlib.compress(b"{" + b" " * (8 * 1024 ** 2) + b"}", 9)
    with pytest.raises(space.SpaceProblem):
        space.parse_link(space.LINK + base64.urlsafe_b64encode(bomb).decode().rstrip("="))


def test_a_large_sealed_file_is_opened_without_copies_of_it():
    import tracemalloc

    ident, k = seal.Identity.new(), seal.new_key()
    n = 24 * 1024 ** 2
    blob = seal.seal(b"\0" * n, path="p0123456789ab/files/x", by="m0123456789ab", epoch=1, key=k, ident=ident)
    tracemalloc.start()
    h = seal.verify(blob, ident.public()["sign"])
    data = seal.open_sealed(blob, path=h.path, by="m0123456789ab", sign_pub=ident.public()["sign"], keys={1: k}, h=h)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(data) == n and peak < 1.5 * n   # the plain text, and no copy of the sealed file

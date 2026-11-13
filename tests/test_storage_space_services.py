"""0.18.0rc2 (roadmap L6a, L6b): a storage space at Backblaze B2 or Cloudflare R2, set up from the app.

The owner pastes a key (Backblaze) or a token (Cloudflare); ENLENS makes a key of its own, a private bucket and each
colleague's keys, and the team works through it as through a shared folder. Against stand-ins of the two services
(tests/fake_b2.py, tests/fake_cloudflare.py, tests/fake_s3.py): never the network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from enlens_claims import claimcheck, home, keychain, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import b2, folder, space
from enlens_claims.sync.storage import DENIED, StorageProblem
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)

sys.path.insert(0, str(Path(__file__).parent))
import fake_b2  # noqa: E402
import fake_cloudflare  # noqa: E402


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    from enlens_claims.sync import _web

    monkeypatch.setattr(_web, "sleep", lambda s: None)


@pytest.fixture
def backblaze(monkeypatch):
    srv, url = fake_b2.start()
    monkeypatch.setenv("ENLENS_B2_API", url)
    yield srv
    fake_b2.stop(srv)


@pytest.fixture
def cloudflare(monkeypatch):
    srv, url = fake_cloudflare.start()
    monkeypatch.setenv("ENLENS_CF_API", url)
    monkeypatch.setenv("ENLENS_R2_ENDPOINT", srv.s3_url)
    yield srv
    fake_cloudflare.stop(srv)


def _round(p: Person, ok=("documents",)) -> dict:
    with p:
        out = folder.sync_now(p.ws)
    bad = [x for x in out["problems"] if x["kind"] not in ok]
    assert not bad, bad
    return out


def _work_together(anna: Person, carol: Person, tmp_path) -> None:
    with anna:
        inv = space.invite(anna.ws, "Carol")
    with carol:
        carol.ws = home.open_project(space.join_new_project(inv["link"]))
    _round(anna)   # binds Carol
    _round(carol)  # Carol gets the project
    with carol:
        assert carol.ws.scalar("SELECT COUNT(*) FROM documents") == anna.ws.scalar("SELECT COUNT(*) FROM documents")
        h = claimcheck.check_hypothesis(carol.ws, "Hydrogen storage is cheap.", BaselineBackend(), "baseline", k=2)
        sharing.share(carol.ws, [{"kind": "check", "key": h}])
    _round(carol)
    _round(anna)
    with anna:
        assert anna.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h,))


def test_backblaze_set_up_invite_and_join(anna_and_ben, backblaze, tmp_path, monkeypatch):
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    with anna:
        out = space.setup_b2(anna.ws, *backblaze.master)
        desc = space.configured(anna.ws)
        keeper = space._get_secret(desc["id"], "keeper")
    assert out["warnings"] == [] and out["region"] == "eu-central-003" and out["keeper"]
    assert desc["service"] == "b2" and desc["bucket"].startswith("enlens-")
    assert keeper["key_id"] != backblaze.master[0]   # a key of ENLENS's own; the master key is forgotten
    assert "master-secret" not in Path(anna.ws.config_path).read_text(encoding="utf-8")
    _round(anna)
    _work_together(anna, carol, tmp_path)
    # Carol's key writes only in her own part (the storage itself refuses the rest)
    with carol:
        cdesc = space.configured(carol.ws)
        store = space.storage_for(cdesc, space._get_secret(cdesc["id"], "access"))
    with pytest.raises(StorageProblem) as e:
        store.put(f"parts/{desc['part']}/b/000077", b"x")
    assert e.value.kind == DENIED
    store.put(f"parts/{cdesc['part']}/m/probe", b"x")   # her own part: allowed
    # removed, her keys stop working
    with anna:
        space.remove_member(anna.ws, cdesc["part"])
    with carol:
        out = folder.sync_now(carol.ws)
    assert [x["kind"] for x in out["problems"]] == [DENIED]


def test_backblaze_outside_the_eu_is_said(anna_and_ben, monkeypatch):
    anna, _ben = anna_and_ben
    srv, url = fake_b2.start(region="us-west-004")
    monkeypatch.setenv("ENLENS_B2_API", url)
    try:
        with anna:
            out = space.setup_b2(anna.ws, *srv.master)
        assert len(out["warnings"]) == 1 and "not in the EU" in out["warnings"][0]
    finally:
        fake_b2.stop(srv)


def test_backblaze_keeps_the_master_key_when_its_own_key_cannot_make_keys(anna_and_ben, backblaze, monkeypatch):
    anna, _ben = anna_and_ben
    real = b2.create_key

    def no_keys_from_own(acc, name, caps, bucket_id=None, name_prefix=None):
        if name == "ENLENS test":
            raise b2.B2Problem("not allowed", "not_allowed")
        return real(acc, name, caps, bucket_id=bucket_id, name_prefix=name_prefix)

    monkeypatch.setattr(b2, "create_key", no_keys_from_own)
    with anna:
        out = space.setup_b2(anna.ws, *backblaze.master)
        keeper = space._get_secret(space.configured(anna.ws)["id"], "keeper")
    assert keeper["key_id"] == backblaze.master[0]
    assert any("keeps the master key" in w for w in out["warnings"])


def test_backblaze_wrong_key_says_so_and_sets_up_nothing(anna_and_ben, backblaze):
    anna, _ben = anna_and_ben
    with anna:
        with pytest.raises(space.SpaceProblem):
            space.setup_b2(anna.ws, "nobody", "nothing")
        assert space.configured(anna.ws) is None


def test_cloudflare_set_up_invite_and_join(anna_and_ben, cloudflare, tmp_path, monkeypatch):
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    with anna:
        out = space.setup_r2(anna.ws, cloudflare.owner_token)
        desc = space.configured(anna.ws)
    assert desc["service"] == "r2" and out["in_eu"] and out["where"].startswith("Cloudflare R2")
    _round(anna)
    _work_together(anna, carol, tmp_path)
    with anna:
        assert keychain.get(space._secret_name(desc["id"], "keeper"))

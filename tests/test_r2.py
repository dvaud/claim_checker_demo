"""Cloudflare's interface for R2 (0.18.0) against the stand-in, and the colleague's token flow with S3Storage."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import fake_cloudflare  # noqa: E402
import fake_s3  # noqa: E402

from enlens_claims.sync import _web, r2  # noqa: E402
from enlens_claims.sync.storage import DENIED, S3Storage, StorageProblem  # noqa: E402


@pytest.fixture
def cf(monkeypatch):
    srv, url = fake_cloudflare.start()
    monkeypatch.setenv("ENLENS_CF_API", url)
    monkeypatch.setenv("ENLENS_R2_ENDPOINT", srv.s3_url)
    monkeypatch.setattr(_web, "sleep", lambda s: None)
    yield srv
    fake_cloudflare.stop(srv)


def test_s3_credentials_rule():
    kid, sec = r2.s3_credentials("abc123", "the-value")
    assert kid == "abc123" and sec == hashlib.sha256(b"the-value").hexdigest() and len(sec) == 64


def test_endpoint(monkeypatch):
    monkeypatch.delenv("ENLENS_R2_ENDPOINT", raising=False)
    assert r2.endpoint("acc1") == "https://acc1.eu.r2.cloudflarestorage.com"
    assert r2.endpoint("acc1", eu=False) == "https://acc1.r2.cloudflarestorage.com"
    monkeypatch.setenv("ENLENS_R2_ENDPOINT", "http://127.0.0.1:5/")
    assert r2.endpoint("acc1") == "http://127.0.0.1:5"


def test_token_links_fill_the_form():
    for link, keys in ((r2.TOKEN_LINK_R2_ONLY, ["workers_r2"]), (r2.TOKEN_LINK, ["workers_r2", "api_tokens"])):
        u = urlsplit(link)
        assert u.netloc == "dash.cloudflare.com" and u.path == "/profile/api-tokens"
        q = parse_qs(u.query)
        assert [g["key"] for g in json.loads(unquote(q["permissionGroupKeys"][0]))] == keys
        assert q["name"] == ["ENLENS"] and q["accountId"] == ["*"]


def test_verify_and_accounts(cf):
    v = r2.verify(cf.owner_token)
    assert v == {"id": "owner-token-id", "status": "active"}
    assert r2.accounts(cf.owner_token) == [{"id": cf.account_id, "name": "Test account"}]
    with pytest.raises(r2.R2Problem) as e:
        r2.verify("not-a-token")
    assert e.value.kind == r2.WRONG_TOKEN and "not-a-token" not in e.value.message
    cf.state.tokens[cf.owner_token]["status"] = "expired"
    with pytest.raises(r2.R2Problem) as e:
        r2.verify(cf.owner_token)
    assert e.value.kind == r2.WRONG_TOKEN


def test_bucket_calls_and_jurisdiction(cf):
    t, a = cf.owner_token, cf.account_id
    r2.create_bucket(t, a, "enlens-ab12cd")
    assert ("eu", "enlens-ab12cd") in cf.state.buckets_meta
    r2.create_bucket(t, a, "enlens-ab12cd", eu=False)             # another jurisdiction, another bucket
    assert ("default", "enlens-ab12cd") in cf.state.buckets_meta
    with pytest.raises(r2.R2Problem) as e:
        r2.create_bucket(t, a, "enlens-ab12cd")
    assert e.value.kind == r2.NAME_TAKEN
    fake_s3.put_object(cf.s3, "enlens-ab12cd", "x", b"1")
    with pytest.raises(r2.R2Problem) as e:
        r2.delete_bucket(t, a, "enlens-ab12cd")
    assert e.value.kind == r2.NOT_EMPTY
    cf.s3.state.buckets["enlens-ab12cd"].clear()
    r2.delete_bucket(t, a, "enlens-ab12cd")
    assert ("eu", "enlens-ab12cd") not in cf.state.buckets_meta
    r2.delete_bucket(t, a, "enlens-ab12cd")                       # gone already: fine
    assert r2.random_bucket_name().startswith("enlens-")


def test_r2_not_switched_on(cf):
    cf.state.r2_on = False
    with pytest.raises(r2.R2Problem) as e:
        r2.create_bucket(cf.owner_token, cf.account_id, "enlens-ab12cd")
    assert e.value.kind == r2.R2_OFF and "switch" in e.value.message and "dashboard" in e.value.message


def test_maintenance_and_unreachable(cf, monkeypatch):
    cf.state.maintenance = True
    with pytest.raises(r2.R2Problem) as e:
        r2.accounts(cf.owner_token)
    assert e.value.kind == r2.MAINTENANCE
    monkeypatch.setenv("ENLENS_CF_API", "http://127.0.0.1:9/client/v4")
    with pytest.raises(r2.R2Problem) as e:
        r2.verify("x")
    assert e.value.kind == r2.UNREACHABLE


def test_cannot_make_tokens(cf):
    cf.state.tokens[cf.owner_token]["can_make_tokens"] = False
    with pytest.raises(r2.R2Problem) as e:
        r2.create_member_token(cf.owner_token, cf.account_id, "bkt")
    assert e.value.kind == r2.CANNOT_MAKE_TOKENS and "right to make API tokens" in e.value.message


def test_member_token_flow_on_s3(cf):
    t, a = cf.owner_token, cf.account_id
    r2.create_bucket(t, a, "enlens-bk1")
    r2.create_bucket(t, a, "enlens-other")
    tid, value = r2.create_member_token(t, a, "enlens-bk1")
    assert cf.state.keys[tid]["bucket"] == "enlens-bk1"
    kid, sec = r2.s3_credentials(tid, value)
    mine = S3Storage(r2.endpoint(a), "auto", "enlens-bk1", *r2.s3_credentials("owner-token-id", cf.owner_token),
                     prefix="enlens/S/")
    # the owner's token reaches S3 too, in any bucket
    mine.put("parts/Q/1.bin", b"owner")
    member = S3Storage(r2.endpoint(a), "auto", "enlens-bk1", kid, sec, prefix="enlens/S/")
    member.put("parts/P/1.bin", b"member")                       # limited to the bucket, not to a part
    assert member.get("parts/Q/1.bin") == b"owner" and set(member.list()) == {"parts/Q/1.bin", "parts/P/1.bin"}
    elsewhere = S3Storage(r2.endpoint(a), "auto", "enlens-other", kid, sec)
    with pytest.raises(StorageProblem) as e:
        elsewhere.put("x", b"1")
    assert e.value.kind == DENIED
    # removing the colleague: the token is refused
    r2.delete_token(t, tid)
    r2.delete_token(t, tid)                                      # gone already: fine
    with pytest.raises(StorageProblem) as e:
        member.get("parts/Q/1.bin")
    assert e.value.kind == DENIED


def test_permission_group_is_looked_up_by_name(cf, monkeypatch):
    sent = []
    real = r2._call

    def spy(method, path, token, body=None, **k):
        sent.append((method, path, body))
        return real(method, path, token, body, **k)
    monkeypatch.setattr(r2, "_call", spy)
    r2.create_bucket(cf.owner_token, cf.account_id, "enlens-bk2")
    r2.create_member_token(cf.owner_token, cf.account_id, "enlens-bk2", name="ENLENS colleague")
    post = [s for s in sent if s[0] == "POST" and s[1] == "/user/tokens"][0][2]
    assert post["policies"][0]["resources"] == {f"com.cloudflare.edge.r2.bucket.{cf.account_id}_eu_enlens-bk2": "*"}
    assert post["policies"][0]["permission_groups"] == [{"id": "g-r2-w"}]

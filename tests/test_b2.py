"""Backblaze B2's own interface (0.18.0) against the stand-in, and the whole owner's flow with S3Storage."""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import fake_b2  # noqa: E402
import fake_s3  # noqa: E402

from enlens_claims.sync import _web, b2  # noqa: E402
from enlens_claims.sync.storage import DENIED, S3Storage, StorageProblem  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    srv, url = fake_b2.start()
    monkeypatch.setenv("ENLENS_B2_API", url)
    monkeypatch.setattr(_web, "sleep", lambda s: None)
    yield srv
    fake_b2.stop(srv)


def test_authorize_with_master_key(fake):
    acc = b2.authorize(*fake.master)
    assert acc.account_id == fake.state.account_id
    assert acc.api_url == fake.state.api_url and acc.s3_url == fake.s3_url
    assert acc.region == "eu-central-003" and b2.in_eu(acc)
    assert "writeKeys" in acc.capabilities and acc.bucket_id is None and acc.name_prefix is None
    assert acc.auth_token


def test_non_eu_region(fake):
    fake.state.region = "us-west-004"
    assert not b2.in_eu(b2.authorize(*fake.master))


def test_region_read_from_the_real_address_shape():
    assert b2._region_of("https://s3.eu-central-003.backblazeb2.com", {}) == "eu-central-003"
    assert b2._region_of("https://s3.us-west-004.backblazeb2.com/", {}) == "us-west-004"
    assert b2._region_of("https://example.com", {}) == ""


def test_authorize_reads_both_answer_shapes(monkeypatch):
    v3 = {"accountId": "a", "authorizationToken": "t", "apiInfo": {"storageApi": {
        "apiUrl": "https://api001.backblazeb2.com", "s3ApiUrl": "https://s3.eu-central-003.backblazeb2.com",
        "capabilities": ["listFiles"], "bucketId": "B1", "bucketName": "n", "namePrefix": "p/"}}}
    v4 = {"accountId": "a", "authorizationToken": "t", "apiInfo": {"storageApi": {
        "apiUrl": "https://api001.backblazeb2.com", "s3ApiUrl": "https://s3.eu-central-003.backblazeb2.com",
        "allowed": {"capabilities": ["readFiles"], "buckets": [{"id": "B2", "name": "n"}], "namePrefix": None}}}}
    import json
    for doc, caps, bid, pre in ((v3, ["listFiles"], "B1", "p/"), (v4, ["readFiles"], "B2", None)):
        monkeypatch.setattr(_web, "send", lambda *a, d=doc, **k: _web.Reply(200, {}, json.dumps(d).encode()))
        acc = b2.authorize("k", "s")
        assert (acc.capabilities, acc.bucket_id, acc.name_prefix) == (caps, bid, pre)


def test_wrong_key_in_words(fake):
    with pytest.raises(b2.B2Problem) as e:
        b2.authorize(fake.master[0], "nope")
    assert e.value.kind == b2.WRONG_KEY and "keyID" in e.value.message and "nope" not in e.value.message


def test_basic_auth_header_is_sent(fake, monkeypatch):
    seen = {}
    real = _web.send

    def spy(method, url, headers=None, *a, **k):
        seen.update(headers or {})
        return real(method, url, headers, *a, **k)
    monkeypatch.setattr(_web, "send", spy)
    b2.authorize(*fake.master)
    assert seen["Authorization"] == "Basic " + base64.b64encode(b"MASTERKEYID:master-secret").decode()


def test_maintenance_and_unreachable(fake, monkeypatch):
    fake.state.maintenance = True
    with pytest.raises(b2.B2Problem) as e:
        b2.authorize(*fake.master)
    assert e.value.kind == b2.MAINTENANCE and "maintenance" in e.value.message
    monkeypatch.setenv("ENLENS_B2_API", "http://127.0.0.1:9")
    with pytest.raises(b2.B2Problem) as e:
        b2.authorize("a", "b")
    assert e.value.kind == b2.UNREACHABLE


def test_create_and_delete_key(fake):
    acc = b2.authorize(*fake.master)
    kid, secret = b2.create_key(acc, "ENLENS own key", b2.OWN_KEY_CAPS)
    assert kid in fake.state.keys and fake.state.keys[kid]["secret"] == secret
    assert fake.state.keys[kid]["caps"] == b2.OWN_KEY_CAPS
    own = b2.authorize(kid, secret)
    assert "writeKeys" in own.capabilities
    b2.delete_key(own, kid)
    assert kid not in fake.state.keys
    b2.delete_key(acc, kid)           # gone already: fine
    with pytest.raises(b2.B2Problem) as e:
        b2.authorize(kid, secret)
    assert e.value.kind == b2.WRONG_KEY


def test_own_caps_hold_nothing_about_billing():
    assert not [c for c in b2.OWN_KEY_CAPS if re.search(r"bill|account|Retention|LegalHold|share", c, re.I)]
    assert set(b2.MEMBER_READ_CAPS) <= set(b2.MEMBER_WRITE_CAPS) <= set(b2.OWN_KEY_CAPS)


def test_key_that_cannot_make_keys(fake):
    fake.state.add_key("LIMITED", "lim", ["listBuckets", "writeBuckets", "listFiles", "readFiles", "writeFiles"])
    acc = b2.authorize("LIMITED", "lim")
    with pytest.raises(b2.B2Problem) as e:
        b2.create_key(acc, "x", ["listFiles"])
    assert e.value.kind == b2.NOT_ALLOWED and "not allowed" in e.value.message


def test_bucket_calls(fake):
    acc = b2.authorize(*fake.master)
    name = b2.random_bucket_name()
    assert re.fullmatch(r"enlens-[a-z0-9]+", name) and 6 <= len(name) <= 50
    bid = b2.create_bucket(acc, name)
    meta = fake.state.buckets_meta[name]
    assert meta["bucketType"] == "allPrivate"
    assert meta["lifecycleRules"] == [{"fileNamePrefix": "", "daysFromHidingToDeleting": 1,
                                       "daysFromUploadingToHiding": None}]
    assert [b["bucketId"] for b in b2.list_buckets(acc)] == [bid]
    with pytest.raises(b2.B2Problem) as e:
        b2.create_bucket(acc, name)
    assert e.value.kind == b2.NAME_TAKEN
    fake_s3.put_object(fake.s3, name, "x", b"1")
    with pytest.raises(b2.B2Problem) as e:
        b2.delete_bucket(acc, bid)
    assert e.value.kind == b2.NOT_EMPTY
    fake.s3.state.buckets[name].clear()
    b2.delete_bucket(acc, bid)
    assert b2.list_buckets(acc) == [] and name not in fake.s3.state.buckets
    b2.delete_bucket(acc, bid)        # gone already: fine


def test_cap_in_words(fake):
    acc = b2.authorize(*fake.master)
    fake.state.cap = True
    with pytest.raises(b2.B2Problem) as e:
        b2.list_buckets(acc)
    assert e.value.kind == b2.CAP and "Caps & Alerts" in e.value.message


def test_deleted_key_session_is_refused(fake):
    acc = b2.authorize(*fake.master)
    fake.state.tokens.clear()
    with pytest.raises(b2.B2Problem) as e:
        b2.list_buckets(acc)
    assert e.value.kind == b2.WRONG_KEY


def test_v4_sends_bucket_ids(fake, monkeypatch):
    monkeypatch.setenv("ENLENS_B2_VERSION", "v4")
    sent = []
    monkeypatch.setattr(b2, "_api", lambda acc, call, body, **k: sent.append(body) or {"applicationKeyId": "i", "applicationKey": "k"})
    acc = b2.Account("a", "u", "s", "eu-x", "t")
    b2.create_key(acc, "n", ["listFiles"], bucket_id="B", name_prefix="p/")
    assert sent[0]["bucketIds"] == ["B"] and "bucketId" not in sent[0] and sent[0]["namePrefix"] == "p/"


def test_whole_owner_flow_on_the_stand_ins(fake):
    # master key -> own key -> bucket
    master = b2.authorize(*fake.master)
    own_id, own_secret = b2.create_key(master, "ENLENS-own", b2.OWN_KEY_CAPS)
    own = b2.authorize(own_id, own_secret)            # the master key is forgotten from here
    name = b2.random_bucket_name()
    bucket_id = b2.create_bucket(own, name)
    space = "enlens/S/"
    # a test file: write, read back, delete, over S3
    mine = S3Storage(own.s3_url, own.region, name, own_id, own_secret, prefix=space)
    mine.put("test.txt", b"hello")
    assert mine.get("test.txt") == b"hello"
    mine.delete("test.txt")
    assert mine.list() == {}
    # a colleague: a write key for their part, a read key for the whole
    wid, wsec = b2.create_key(own, "member-write", b2.MEMBER_WRITE_CAPS, bucket_id, space + "parts/P/")
    rid, rsec = b2.create_key(own, "member-read", b2.MEMBER_READ_CAPS, bucket_id)
    colleague = S3Storage(own.s3_url, own.region, name, wid, wsec, prefix=space, read_key_id=rid, read_secret=rsec)
    mine.put("parts/Q/1.bin", b"owner's part")
    colleague.put("parts/P/1.bin", b"colleague's part")
    assert set(colleague.list()) == {"parts/Q/1.bin", "parts/P/1.bin"}
    assert colleague.get("parts/Q/1.bin") == b"owner's part"
    with pytest.raises(StorageProblem) as e:
        colleague.put("parts/Q/2.bin", b"x")
    assert e.value.kind == DENIED
    with pytest.raises(StorageProblem) as e:
        colleague.delete("parts/Q/1.bin")
    assert e.value.kind == DENIED
    assert fake_s3.get_object(fake.s3, name, space + "parts/Q/1.bin") == b"owner's part"
    # the read key cannot write at all
    reader = S3Storage(own.s3_url, own.region, name, rid, rsec, prefix=space)
    with pytest.raises(StorageProblem) as e:
        reader.put("parts/P/2.bin", b"x")
    assert e.value.kind == DENIED
    # removing the colleague deletes their keys; the keys are refused after that
    b2.delete_key(own, wid)
    b2.delete_key(own, rid)
    with pytest.raises(StorageProblem) as e:
        colleague.put("parts/P/3.bin", b"x")
    assert e.value.kind == DENIED and "refused" in str(e.value)
    with pytest.raises(StorageProblem) as e:
        colleague.get("parts/Q/1.bin")
    assert e.value.kind == DENIED
    # the owner's work stays
    assert mine.get("parts/P/1.bin") == b"colleague's part"

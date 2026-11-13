"""S3Storage (0.18.0): SigV4 against AWS's published examples, and the client against a stand-in service."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import fake_s3  # noqa: E402

from enlens_claims.sync import _web  # noqa: E402
from enlens_claims.sync.storage import (  # noqa: E402
    BAD_ANSWER, DENIED, FULL, MAINTENANCE, NOT_FOUND, TOO_LARGE, UNREACHABLE, S3Storage, StorageProblem, sigv4,
    uri_encode)

AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"   # AWS's documentation example key
EMPTY = hashlib.sha256(b"").hexdigest()
DATE = "20130524T000000Z"
BASE = {"host": "examplebucket.s3.amazonaws.com", "x-amz-content-sha256": EMPTY, "x-amz-date": DATE}


# ---- signature vectors (AWS: Signature Calculations for the Authorization Header, S3 examples)

def test_sigv4_get_object_with_range():
    h = dict(BASE, range="bytes=0-9")
    s = sigv4("GET", "/test.txt", [], h, EMPTY, AWS_SECRET, "us-east-1", DATE)
    assert s.signature == "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    assert s.signed_headers == "host;range;x-amz-content-sha256;x-amz-date"


def test_sigv4_put_object_with_encoded_name():
    payload = hashlib.sha256(b"Welcome to Amazon S3.").hexdigest()
    assert payload == "44ce7dd67c959e0d3524ffac1771dfbba87d2b6b4b4e99e42034a8b803f8b072"
    h = {"date": "Fri, 24 May 2013 00:00:00 GMT", "host": BASE["host"], "x-amz-date": DATE,
         "x-amz-storage-class": "REDUCED_REDUNDANCY", "x-amz-content-sha256": payload}
    s = sigv4("PUT", "/test$file.text", [], h, payload, AWS_SECRET, "us-east-1", DATE)
    assert "/test%24file.text" in s.canonical_request
    assert s.signature == "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd"


def test_sigv4_get_lifecycle_valueless_query():
    s = sigv4("GET", "/", [("lifecycle", "")], BASE, EMPTY, AWS_SECRET, "us-east-1", DATE)
    assert s.signature == "fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543"


def test_sigv4_list_with_sorted_query():
    s = sigv4("GET", "/", {"prefix": "J", "max-keys": "2"}, BASE, EMPTY, AWS_SECRET, "us-east-1", DATE)
    assert s.signature == "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7"


def test_uri_encode():
    assert uri_encode("a b/c~d-e_f.g") == "a%20b%2Fc~d-e_f.g"
    assert uri_encode("a b/c", True) == "a%20b/c"
    assert uri_encode("é+") == "%C3%A9%2B"


# ---- the client

@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(_web, "sleep", slept.append)
    return slept


@pytest.fixture
def svc():
    keys = {"KEYRW": {"secret": "secret-rw", "bucket": "bkt", "prefix": None, "can_write": True}}
    srv, url = fake_s3.start(keys=keys, buckets=["bkt"])
    yield srv, url
    fake_s3.stop(srv)


def mk(url, **kw):
    args = dict(endpoint=url, region="eu-central-003", bucket="bkt", key_id="KEYRW", secret="secret-rw")
    args.update(kw)
    return S3Storage(**args)


def test_round_trip(svc):
    srv, url = svc
    s = mk(url)
    etag = s.put("a/b-1_x.json", b"hello")
    assert etag == hashlib.md5(b"hello").hexdigest()
    assert s.get("a/b-1_x.json") == b"hello"
    ls = s.list()
    assert list(ls) == ["a/b-1_x.json"] and ls["a/b-1_x.json"].size == 5 and ls["a/b-1_x.json"].etag == etag
    s.put("a/b-1_x.json", b"hello again")
    assert s.get("a/b-1_x.json") == b"hello again"
    s.delete("a/b-1_x.json")
    s.delete("a/b-1_x.json")          # gone already: fine
    assert s.list() == {}
    assert s.describe().startswith("S3 storage at 127.0.0.1")
    assert "secret" not in s.describe()


def test_names_with_odd_characters_and_binary(svc):
    srv, url = svc
    s = mk(url)
    data = bytes(range(256)) * 10
    s.put("x-y_z.1", data)
    s.put("d.e/f-g_h/i.j", b"")
    assert s.get("x-y_z.1") == data
    assert s.get("d.e/f-g_h/i.j") == b""
    with pytest.raises(ValueError):
        s.put("a b.txt", b"x")


def test_prefix_is_added_and_stripped(svc):
    srv, url = svc
    s = mk(url, prefix="enlens/S1")
    s.put("parts/A/1.bin", b"1")
    assert set(fake_s3.objects(srv, "bkt")) == {"enlens/S1/parts/A/1.bin"}
    fake_s3.put_object(srv, "bkt", "other/x", b"nope")
    fake_s3.put_object(srv, "bkt", "enlens/S1/parts/B/2.bin", b"22")
    assert set(s.list()) == {"parts/A/1.bin", "parts/B/2.bin"}
    assert set(s.list("parts/B/")) == {"parts/B/2.bin"}
    assert s.get("parts/B/2.bin") == b"22"


def test_listing_follows_every_page(svc):
    srv, url = svc
    srv.state.page_size = 3
    s = mk(url)
    for i in range(10):
        fake_s3.put_object(srv, "bkt", f"n/{i:02d}.bin", b"x" * i)
    ls = s.list("n/")
    assert sorted(ls) == [f"n/{i:02d}.bin" for i in range(10)]
    pages = [e for e in srv.state.log if e[0] == "GET" and "list-type" in e[3]]
    assert len(pages) == 4
    assert sum(1 for e in pages if "continuation-token" in e[3]) == 3


def test_two_keys_write_key_limited_to_own_part(svc):
    srv, url = svc
    srv.state.keys["WKEY"] = {"secret": "w", "bucket": "bkt", "prefix": "enlens/S/parts/A/", "can_write": True}
    srv.state.keys["RKEY"] = {"secret": "r", "bucket": "bkt", "prefix": None, "can_write": False}
    s = mk(url, prefix="enlens/S/", key_id="WKEY", secret="w", read_key_id="RKEY", read_secret="r")
    s.put("parts/A/1.bin", b"mine")
    fake_s3.put_object(srv, "bkt", "enlens/S/parts/B/1.bin", b"theirs")
    assert s.get("parts/B/1.bin") == b"theirs"                  # read with the read key
    assert set(s.list()) == {"parts/A/1.bin", "parts/B/1.bin"}
    with pytest.raises(StorageProblem) as e:
        s.put("parts/B/x", b"nope")
    assert e.value.kind == DENIED and "not allowed to write" in str(e.value)
    with pytest.raises(StorageProblem) as e:
        s.delete("parts/B/1.bin")
    assert e.value.kind == DENIED
    assert fake_s3.get_object(srv, "bkt", "enlens/S/parts/B/1.bin") == b"theirs"
    ro = mk(url, key_id="RKEY", secret="r")
    with pytest.raises(StorageProblem) as e:
        ro.put("x", b"1")
    assert e.value.kind == DENIED


def test_wrong_secret_and_unknown_key_are_denied(svc):
    srv, url = svc
    for kw in (dict(secret="wrong"), dict(key_id="NOPE")):
        with pytest.raises(StorageProblem) as e:
            mk(url, **kw).list()
        assert e.value.kind == DENIED and "refused" in str(e.value)
        assert "wrong" not in str(e.value)


def test_retries_then_success(svc, no_sleep):
    srv, url = svc
    s = mk(url)
    srv.state.fail_next(2, 500)
    s.put("a.bin", b"1")
    assert no_sleep == [0.5, 1.0]
    srv.state.fail_next(1, 429)
    assert s.get("a.bin") == b"1"
    srv.state.fail_next(3, 503)           # a plain 503 is not a maintenance page
    assert list(s.list()) == ["a.bin"]


def test_retries_run_out_unreachable(svc, no_sleep):
    srv, url = svc
    srv.state.fail_next(50, 500)
    with pytest.raises(StorageProblem) as e:
        mk(url).list()
    assert e.value.kind == UNREACHABLE and "tries again on the next round" in str(e.value)
    assert no_sleep == [0.5, 1.0, 2.0]


def test_maintenance_is_not_retried(svc, no_sleep):
    srv, url = svc
    srv.state.maintenance = True
    with pytest.raises(StorageProblem) as e:
        mk(url).get("a")
    assert e.value.kind == MAINTENANCE and "maintenance" in str(e.value) and no_sleep == []


def test_cap_is_full_with_a_pointer(svc):
    srv, url = svc
    srv.state.cap = "transaction_cap_exceeded"
    with pytest.raises(StorageProblem) as e:
        mk(url).put("a", b"1")
    assert e.value.kind == FULL and "account" in str(e.value)


def test_unreachable_and_timeout(svc):
    srv, url = svc
    with pytest.raises(StorageProblem) as e:
        mk("http://127.0.0.1:9").list()
    assert e.value.kind == UNREACHABLE and "refused" in str(e.value)
    srv.state.delay = 1.0
    with pytest.raises(StorageProblem) as e:
        mk(url, timeout=0.2).list()
    assert e.value.kind == UNREACHABLE and "no answer in time" in str(e.value)


def test_clock_wrong(svc):
    srv, url = svc
    srv.state.check_clock = True
    s = mk(url)
    s._now = lambda: "20200101T000000Z"
    with pytest.raises(StorageProblem) as e:
        s.list()
    assert "clock is wrong" in str(e.value)


def test_not_found_and_missing_bucket(svc):
    srv, url = svc
    with pytest.raises(StorageProblem) as e:
        mk(url).get("nothing.bin")
    assert e.value.kind == NOT_FOUND
    srv.state.keys["ANY"] = {"secret": "any", "bucket": None}
    with pytest.raises(StorageProblem) as e:
        mk(url, bucket="gone", key_id="ANY", secret="any").list()
    assert e.value.kind == NOT_FOUND and "bucket" in str(e.value)


def test_too_large_by_header_and_by_reading(svc):
    srv, url = svc
    s = mk(url)
    s.put("big.bin", b"x" * 1000)
    assert s.get("big.bin", max_size=1000) == b"x" * 1000
    with pytest.raises(StorageProblem) as e:
        s.get("big.bin", max_size=999)
    assert e.value.kind == TOO_LARGE
    srv.state.chunked_get = True          # no Content-Length: the cap is enforced while reading
    with pytest.raises(StorageProblem) as e:
        s.get("big.bin", max_size=10)
    assert e.value.kind == TOO_LARGE
    assert s.get("big.bin", max_size=5000) == b"x" * 1000


def test_garbage_answers_are_bad_answer(monkeypatch, svc):
    srv, url = svc
    s = mk(url)
    monkeypatch.setattr(_web, "send", lambda *a, **k: _web.Reply(200, {}, b"<html>not a listing"))
    with pytest.raises(StorageProblem) as e:
        s.list()
    assert e.value.kind == BAD_ANSWER
    monkeypatch.setattr(_web, "send", lambda *a, **k: _web.Reply(418, {}, b"teapot"))
    with pytest.raises(StorageProblem) as e:
        s.get("a")
    assert e.value.kind == BAD_ANSWER


def test_describe_by_host():
    assert S3Storage("https://s3.eu-central-003.backblazeb2.com", "eu-central-003", "enlens-ab12cd", "k", "s").describe() \
        == "Backblaze B2, bucket enlens-ab12cd (eu-central-003)"
    assert S3Storage("https://abc123.eu.r2.cloudflarestorage.com", "auto", "bk", "k", "s").describe() \
        == "Cloudflare R2, bucket bk (EU)"
    assert "automatic" in S3Storage("https://abc123.r2.cloudflarestorage.com", "auto", "bk", "k", "s").describe()


def test_messages_hold_no_keys(svc):
    srv, url = svc
    with pytest.raises(StorageProblem) as e:
        mk(url, secret="TOPSECRETVALUE").list()
    assert "TOPSECRETVALUE" not in str(e.value) and "KEYRW" not in str(e.value)


def test_a_prefix_limited_key_finds_a_missing_file_missing_not_refused():
    """0.18.0: Backblaze answers a key limited to a name prefix (a colleague's read key) with 403 AccessDenied for a
    file that is not there. Taken as refused, every round of a colleague who had joined stopped at the first file it
    looks for (`space/moved.json`), so they never got the team's documents. The list says it is simply not there."""
    srv, url = fake_s3.start(keys={"R": {"secret": "r", "bucket": "b", "prefix": "enlens/s/", "caps": ["listFiles", "readFiles"]}},
                             buckets=["b"])
    try:
        fake_s3.put_object(srv, "b", "enlens/s/space/roster.json", b"roster")
        fake_s3.put_object(srv, "b", "other/secret.json", b"x")
        st = S3Storage(url, "eu-central-003", "b", "R", "r", prefix="enlens/s/")
        assert st.get("space/roster.json") == b"roster"
        with pytest.raises(StorageProblem) as e:
            st.get("space/moved.json")
        assert e.value.kind == NOT_FOUND
        outside = S3Storage(url, "eu-central-003", "b", "R", "r", prefix="other/")
        with pytest.raises(StorageProblem) as e:
            outside.get("secret.json")   # there, but outside the key's prefix: still refused
        assert e.value.kind == DENIED
    finally:
        fake_s3.stop(srv)

"""Backblaze B2's own interface (the native API), for the owner's set-up and for each invite (0.18.0, roadmap L6a).

Used rarely: authorise with a key the owner pasted, make ENLENS's own key, a private bucket, and a pair of keys for
each colleague (one that writes only their own part, limited by a file-name prefix; one that reads the team's).
Everything is in words a researcher can read (`B2Problem.message`, also `str(e)`); no key ever appears in a message.

Sources (read 12 November 2026):
- https://www.backblaze.com/apidocs/b2-authorize-account   (v4 page: `apiInfo.storageApi` with `apiUrl`, `s3ApiUrl`,
  `allowed.{buckets,capabilities,namePrefix}`; v3 had `bucketId`, `bucketName`, `namePrefix`, `capabilities` straight
  in `storageApi`. Both shapes are read here.)
- https://www.backblaze.com/apidocs/b2-create-key  (v4 `bucketIds`; "replaces v3's `bucketId`", so v3 takes `bucketId`)
- https://www.backblaze.com/apidocs/b2-create-bucket  (`bucketType`, `lifecycleRules`, 400 `duplicate_bucket_name`)
- https://www.backblaze.com/docs/cloud-storage-native-api-versions
- https://www.backblaze.com/docs/cloud-storage-application-keys

The API version is `v4` (the one Backblaze documents now); `ENLENS_B2_VERSION=v3` switches (the shapes of both are handled). The
address is `https://api.backblazeb2.com`, or `ENLENS_B2_API` (tests point it at `tests/fake_b2.py`).
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
from dataclasses import dataclass, field

from . import _web

DEFAULT_API = "https://api.backblazeb2.com"

# B2Problem kinds
UNREACHABLE = "unreachable"
MAINTENANCE = "maintenance"
WRONG_KEY = "wrong_key"          # the key id or key is wrong, or was removed
NOT_ALLOWED = "not_allowed"      # the key lacks the right for this
CAP = "cap"                      # a limit on the account (Caps & Alerts) is reached
NAME_TAKEN = "name_taken"        # a bucket of that name exists (names are shared by every Backblaze customer)
EXPIRED = "expired"              # the authorisation lasted its 24 hours: authorize again
NOT_EMPTY = "not_empty"          # a bucket with files cannot be deleted
BAD_ANSWER = "bad_answer"

OWN_KEY_CAPS = ["listBuckets", "readBuckets", "writeBuckets", "deleteBuckets",
                "listKeys", "writeKeys", "deleteKeys",
                "listFiles", "readFiles", "writeFiles", "deleteFiles"]
MEMBER_WRITE_CAPS = ["listFiles", "readFiles", "writeFiles", "deleteFiles"]
MEMBER_READ_CAPS = ["listFiles", "readFiles"]


class B2Problem(Exception):
    """What went wrong at Backblaze, in words for a researcher (`message`); `kind` is one of the constants above."""

    def __init__(self, message: str, kind: str = BAD_ANSWER):
        super().__init__(message)
        self.message = message
        self.kind = kind


@dataclass
class Account:
    account_id: str
    api_url: str
    s3_url: str
    region: str                      # e.g. "eu-central-003", read from the s3 address ("" if it cannot be)
    auth_token: str                  # good for 24 hours
    capabilities: list = field(default_factory=list)
    bucket_id: str | None = None     # set when the key is limited to one bucket
    name_prefix: str | None = None   # set when the key is limited to a file-name prefix


def _base() -> str:
    return (os.environ.get("ENLENS_B2_API") or DEFAULT_API).rstrip("/")


def _version() -> str:
    return os.environ.get("ENLENS_B2_VERSION") or "v4"


def random_bucket_name() -> str:
    """`enlens-` and ten random lower-case hex digits: 17 characters, valid for B2 (6 to 63: letters, digits, `-`)."""
    return "enlens-" + secrets.token_hex(5)


def in_eu(acc: Account) -> bool:
    return acc.region.lower().startswith("eu-")


def _region_of(s3_url: str, storage_api: dict) -> str:
    m = re.search(r"s3\.([a-z0-9-]+)\.backblazeb2\.com", s3_url)
    # `s3Region` does not exist at Backblaze: only the test stand-in (a local address) says its region that way
    return m.group(1) if m else str(storage_api.get("s3Region") or "")


# ---------------------------------------------------------------------------------------------------------------------

def _json(r: _web.Reply) -> dict:
    try:
        d = json.loads(r.body.decode("utf-8"))
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _call(url: str, headers: dict, body: dict | None, authorizing: bool = False, gone_ok: bool = False) -> dict:
    """One call; the answer's JSON, or a B2Problem in words."""
    data = None if body is None else json.dumps(body).encode()
    hdrs = dict(headers)
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    try:
        r = _web.send_retrying(lambda: ("GET" if body is None else "POST", url, hdrs, data), 60.0)
    except _web.NetError as e:
        raise B2Problem(f"ENLENS could not reach Backblaze ({e.reason}). Try again in a moment.", UNREACHABLE) from e
    if 200 <= r.status < 300:
        d = _json(r)
        if not d and r.body.strip() not in (b"", b"{}"):
            raise B2Problem("Backblaze answered something ENLENS does not understand.", BAD_ANSWER)
        return d
    err = _json(r)
    code, msg = str(err.get("code", "")), str(err.get("message", ""))
    if _web.is_maintenance(r):
        raise B2Problem("Backblaze is down for maintenance. Try again later; nothing was changed.", MAINTENANCE)
    if gone_ok and (r.status == 404 or (r.status == 400 and re.search(r"not found|does not exist|no such|bad_application_key_id|bad_bucket_id",
                                                                     code + " " + msg, re.I))):
        return {}
    if r.status == 403 and (code.endswith("cap_exceeded") or "cap" in code):
        raise B2Problem("Backblaze refuses this because a limit on the account is reached. Look at Caps & Alerts in "
                        "the Backblaze dashboard.", CAP)
    if code == "duplicate_bucket_name":
        raise B2Problem("A bucket with that name exists already (bucket names are shared by all Backblaze customers).",
                        NAME_TAKEN)
    if code == "cannot_delete_non_empty_bucket":
        raise B2Problem("The bucket still holds files, so it cannot be deleted.", NOT_EMPTY)
    if r.status == 401 and code == "expired_auth_token":
        raise B2Problem("ENLENS's sign-in at Backblaze ran out (it lasts 24 hours). It signs in again.", EXPIRED)
    if r.status == 401 and authorizing:
        raise B2Problem("Backblaze did not accept this key. Check that the keyID and the applicationKey are both pasted "
                        "whole, and that the key was not deleted.", WRONG_KEY)
    if r.status in (401, 403):
        if code in ("bad_auth_token",):
            raise B2Problem("Backblaze no longer accepts ENLENS's key (it may have been deleted).", WRONG_KEY)
        raise B2Problem("This key is not allowed to do that at Backblaze (it lacks a right, such as making keys or "
                        "buckets).", NOT_ALLOWED)
    if r.status == 429 or r.status >= 500:
        raise B2Problem(f"Backblaze had a problem (HTTP {r.status}). Try again in a moment.", UNREACHABLE)
    raise B2Problem(f"Backblaze did not accept the request ({code or 'HTTP ' + str(r.status)}"
                    f"{': ' + msg if msg else ''}).", BAD_ANSWER)


def _api(acc: Account, call: str, body: dict, **kw) -> dict:
    url = f"{acc.api_url.rstrip('/')}/b2api/{_version()}/{call}"
    return _call(url, {"Authorization": acc.auth_token}, body, **kw)


# ---------------------------------------------------------------------------------------------------------------------

def authorize(key_id: str, app_key: str) -> Account:
    """Sign in with a key (b2_authorize_account, HTTP Basic). Not allowed with a key of the wrong kind: B2Problem."""
    basic = base64.b64encode(f"{key_id}:{app_key}".encode()).decode()
    d = _call(f"{_base()}/b2api/{_version()}/b2_authorize_account", {"Authorization": f"Basic {basic}"}, None,
              authorizing=True)
    try:
        sa = d["apiInfo"]["storageApi"]
        allowed = sa.get("allowed") or {}
        buckets = allowed.get("buckets") or []
        bucket_id = (buckets[0].get("id") if buckets else None) or sa.get("bucketId")
        prefix = allowed.get("namePrefix") if "namePrefix" in allowed else sa.get("namePrefix")
        caps = allowed.get("capabilities") or sa.get("capabilities") or []
        s3 = str(sa["s3ApiUrl"]).rstrip("/")
        return Account(account_id=str(d["accountId"]), api_url=str(sa["apiUrl"]).rstrip("/"), s3_url=s3,
                       region=_region_of(s3, sa), auth_token=str(d["authorizationToken"]), capabilities=list(caps),
                       bucket_id=bucket_id or None, name_prefix=prefix or None)
    except (KeyError, TypeError, AttributeError) as e:
        raise B2Problem("Backblaze's sign-in answer could not be understood.", BAD_ANSWER) from e


def create_key(acc: Account, name: str, capabilities: list, bucket_id: str | None = None,
               name_prefix: str | None = None) -> tuple[str, str]:
    """A new application key: returns `(keyId, applicationKey)`; the key is shown only now. `bucket_id` and
    `name_prefix` limit it to that bucket and to files whose names start so."""
    body: dict = {"accountId": acc.account_id, "capabilities": list(capabilities),
                  "keyName": re.sub(r"[^A-Za-z0-9-]", "-", name)[:100] or "enlens"}
    if bucket_id:
        if _version() in ("v2", "v3"):
            body["bucketId"] = bucket_id         # v4 replaced the single id with a list, `bucketIds`
        else:
            body["bucketIds"] = [bucket_id]
    if name_prefix:
        body["namePrefix"] = name_prefix
    d = _api(acc, "b2_create_key", body)
    try:
        return str(d["applicationKeyId"]), str(d["applicationKey"])
    except KeyError as e:
        raise B2Problem("Backblaze's answer to making a key could not be understood.", BAD_ANSWER) from e


def delete_key(acc: Account, key_id: str) -> None:
    """Delete a key; one that is gone already is no problem."""
    _api(acc, "b2_delete_key", {"applicationKeyId": key_id}, gone_ok=True)


def create_bucket(acc: Account, name: str) -> str:
    """A private bucket keeping only the last version of a file (a hidden old version is deleted after a day); returns
    its bucketId. A name in use: B2Problem(kind `name_taken`)."""
    d = _api(acc, "b2_create_bucket", {
        "accountId": acc.account_id, "bucketName": name, "bucketType": "allPrivate",
        "lifecycleRules": [{"fileNamePrefix": "", "daysFromHidingToDeleting": 1, "daysFromUploadingToHiding": None}]})
    try:
        return str(d["bucketId"])
    except KeyError as e:
        raise B2Problem("Backblaze's answer to making a bucket could not be understood.", BAD_ANSWER) from e


def delete_bucket(acc: Account, bucket_id: str) -> None:
    """Delete an empty bucket (one with files, or old versions of them, is refused: kind `not_empty`)."""
    _api(acc, "b2_delete_bucket", {"accountId": acc.account_id, "bucketId": bucket_id}, gone_ok=True)


def list_buckets(acc: Account) -> list[dict]:
    d = _api(acc, "b2_list_buckets", {"accountId": acc.account_id})
    b = d.get("buckets")
    if not isinstance(b, list):
        raise B2Problem("Backblaze's list of buckets could not be understood.", BAD_ANSWER)
    return b

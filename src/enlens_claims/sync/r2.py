"""Cloudflare's own interface (API v4) for R2: the owner's set-up and each invite (0.18.0, roadmap L6b).

The owner pastes an API token made from `TOKEN_LINK`. ENLENS checks it, finds the account, makes a bucket in the EU
jurisdiction, and for each colleague makes a token limited to that bucket. R2 speaks S3 as well: a token's S3 access
key id is the token's id and its secret key the SHA-256 (hex) of the token's value, so no second sign-up is needed.

Sources (read 12 November 2026):
- https://developers.cloudflare.com/r2/api/tokens/   (access key id = token `id`; secret = SHA-256 of the token
  `value`; permission groups "Workers R2 Storage Bucket Item Write/Read"; bucket resource
  `com.cloudflare.edge.r2.bucket.<ACCOUNT_ID>_<JURISDICTION>_<BUCKET_NAME>`, jurisdiction `default` when none)
- https://developers.cloudflare.com/api/resources/r2/subresources/buckets/methods/create/  (POST
  /accounts/{id}/r2/buckets, body `name`, header `cf-r2-jurisdiction`: default, eu, fedramp ...)
- https://developers.cloudflare.com/fundamentals/api/how-to/create-via-api/   (POST /user/tokens body: name,
  policies[{effect, resources, permission_groups[{id}]}]; GET /user/tokens/permission_groups)
- https://developers.cloudflare.com/api/resources/user/subresources/tokens/methods/verify/  (GET /user/tokens/verify)
- https://developers.cloudflare.com/fundamentals/api/how-to/account-owned-token-template/  (the pre-filled link)
- https://developers.cloudflare.com/r2/api/error-codes/   (10073 BucketConflict 409, 10042 NotEntitled 403,
  10008 BucketNotEmpty 409, 10006 NoSuchBucket 404)

The address is `https://api.cloudflare.com/client/v4`, or `ENLENS_CF_API` (tests point it at
`tests/fake_cloudflare.py`). `ENLENS_R2_ENDPOINT` replaces what `endpoint()` returns (tests, the stand-in's S3).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from urllib.parse import quote

from . import _web

DEFAULT_API = "https://api.cloudflare.com/client/v4"

# The token form, filled in: name "ENLENS", Workers R2 Storage: Edit (confirmed on 12 November 2026, roadmap L6b).
TOKEN_LINK_R2_ONLY = ("https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys="
                      + quote(json.dumps([{"key": "workers_r2", "type": "edit"}], separators=(",", ":")), safe="")
                      + "&accountId=*&name=ENLENS")
# Also asks for the right to make API tokens (what an invite needs). The key `api_tokens` is NOT confirmed: Cloudflare
# drops a key it does not know without a word, so at worst the form shows only R2.
TOKEN_LINK = ("https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys="
              + quote(json.dumps([{"key": "workers_r2", "type": "edit"}, {"key": "api_tokens", "type": "edit"}],
                                 separators=(",", ":")), safe="")
              + "&accountId=*&name=ENLENS")

# R2Problem kinds
UNREACHABLE = "unreachable"
MAINTENANCE = "maintenance"
WRONG_TOKEN = "wrong_token"             # not a token, expired, disabled, or deleted
NOT_ALLOWED = "not_allowed"             # the token lacks a right for this
NAME_TAKEN = "name_taken"
R2_OFF = "r2_off"                       # R2 is not switched on for the account (it asks for a card)
CANNOT_MAKE_TOKENS = "cannot_make_tokens"
NOT_EMPTY = "not_empty"
NOT_FOUND = "not_found"
BAD_ANSWER = "bad_answer"


class R2Problem(Exception):
    """What went wrong at Cloudflare, in words for a researcher (`message`); `kind` is one of the constants above."""

    def __init__(self, message: str, kind: str = BAD_ANSWER):
        super().__init__(message)
        self.message = message
        self.kind = kind


def _base() -> str:
    return (os.environ.get("ENLENS_CF_API") or DEFAULT_API).rstrip("/")


def random_bucket_name() -> str:
    """`enlens-` and ten random lower-case hex digits (R2 wants 3 to 63 of a-z, 0-9, `-`)."""
    return "enlens-" + secrets.token_hex(5)


def s3_credentials(token_id: str, token_value: str) -> tuple[str, str]:
    """The S3 access key id and secret access key of an API token: its id, and the SHA-256 (hex) of its value."""
    return token_id, hashlib.sha256(token_value.encode("utf-8")).hexdigest()


def endpoint(account_id: str, eu: bool = True) -> str:
    """R2's S3 address for the account (`ENLENS_R2_ENDPOINT` replaces it)."""
    if os.environ.get("ENLENS_R2_ENDPOINT"):
        return os.environ["ENLENS_R2_ENDPOINT"].rstrip("/")
    return f"https://{account_id}{'.eu' if eu else ''}.r2.cloudflarestorage.com"


def _jur(eu: bool) -> str:
    return "eu" if eu else "default"


def _errors(d: dict) -> tuple[int, str]:
    errs = d.get("errors") or []
    e = errs[0] if errs and isinstance(errs[0], dict) else {}
    try:
        code = int(e.get("code") or 0)
    except (TypeError, ValueError):
        code = 0
    return code, str(e.get("message") or "")


def _call(method: str, path: str, token: str, body: dict | None = None, eu: bool | None = None, gone_ok: bool = False,
          denied_kind: str = NOT_ALLOWED):
    """One call; the `result` of the answer (None when `gone_ok` and it was not there), or an R2Problem."""
    hdrs = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    if eu is not None:
        hdrs["cf-r2-jurisdiction"] = _jur(eu)
    try:
        r = _web.send_retrying(lambda: (method, _base() + path, hdrs, data), 60.0)
    except _web.NetError as e:
        raise R2Problem(f"ENLENS could not reach Cloudflare ({e.reason}). Try again in a moment.", UNREACHABLE) from e
    try:
        d = json.loads(r.body.decode("utf-8")) if r.body.strip() else {}
        if not isinstance(d, dict):
            raise ValueError
    except ValueError:
        d = {}
        if r.status < 300:
            raise R2Problem("Cloudflare answered something ENLENS does not understand.", BAD_ANSWER) from None
    if r.status < 300 and d.get("success", True):
        return d.get("result")
    code, msg = _errors(d)
    if _web.is_maintenance(r) or r.status == 503:
        raise R2Problem("Cloudflare is not available just now (maintenance or a fault). Try again later.", MAINTENANCE)
    if code == 10042 or re.search(r"enable R2", msg, re.I):
        raise R2Problem("R2 is not switched on for this Cloudflare account yet. In the Cloudflare dashboard, open "
                        "R2 and switch it on (Cloudflare asks for a card; nothing is charged within the free tier), "
                        "then try again.", R2_OFF)
    if code == 10073 or r.status == 409 and code != 10008:
        raise R2Problem("A bucket with that name exists already in this account.", NAME_TAKEN)
    if code == 10008:
        raise R2Problem("The bucket still holds files, so it cannot be deleted.", NOT_EMPTY)
    if gone_ok and (r.status == 404 or code in (10006, 10007)):
        return None
    if r.status == 404 or code == 10006:
        raise R2Problem("Cloudflare says that does not exist (any more).", NOT_FOUND)
    if r.status == 401 or code in (10000, 9103, 9106, 6003, 6111, 10002):
        raise R2Problem("Cloudflare did not accept this token. Check that it was pasted whole and was not deleted or "
                        "expired.", WRONG_TOKEN)
    if r.status == 403:
        raise R2Problem("This token is not allowed to do that at Cloudflare."
                        + (" It needs the right to make API tokens." if denied_kind == CANNOT_MAKE_TOKENS else ""),
                        denied_kind)
    if r.status == 429 or r.status >= 500:
        raise R2Problem(f"Cloudflare had a problem (HTTP {r.status}). Try again in a moment.", UNREACHABLE)
    raise R2Problem(f"Cloudflare did not accept the request ({code or 'HTTP ' + str(r.status)}"
                    f"{': ' + msg if msg else ''}).", BAD_ANSWER)


# ---------------------------------------------------------------------------------------------------------------------

def verify(token: str) -> dict:
    """Is this a working token? Returns `{"id", "status"}` (status `active`); a wrong one is R2Problem `wrong_token`."""
    res = _call("GET", "/user/tokens/verify", token)
    if not isinstance(res, dict) or "id" not in res:
        raise R2Problem("Cloudflare's answer about the token could not be understood.", BAD_ANSWER)
    if res.get("status") != "active":
        raise R2Problem("This Cloudflare token is not active (it expired or was disabled).", WRONG_TOKEN)
    return {"id": str(res["id"]), "status": str(res["status"])}


def accounts(token: str) -> list[dict]:
    """The accounts the token reaches: `[{"id", "name"}]`."""
    res = _call("GET", "/accounts", token)
    if not isinstance(res, list):
        raise R2Problem("Cloudflare's list of accounts could not be understood.", BAD_ANSWER)
    return [{"id": str(a["id"]), "name": str(a.get("name", ""))} for a in res if isinstance(a, dict) and "id" in a]


def create_bucket(token: str, account_id: str, name: str, eu: bool = True) -> None:
    """A private bucket (R2 buckets are private unless made public) in the EU jurisdiction (`eu`) or the default."""
    _call("POST", f"/accounts/{account_id}/r2/buckets", token, {"name": name}, eu=eu)


def delete_bucket(token: str, account_id: str, name: str, eu: bool = True) -> None:
    """Delete an empty bucket; one that is gone already is no problem."""
    _call("DELETE", f"/accounts/{account_id}/r2/buckets/{quote(name, safe='')}", token, eu=eu, gone_ok=True)


def create_member_token(token: str, account_id: str, bucket: str, eu: bool = True,
                        name: str = "ENLENS colleague") -> tuple[str, str]:
    """A token limited to one bucket, with read and write of its files; returns `(token id, value)`. The value is shown
    only now; `s3_credentials` turns the pair into S3 keys. Without the right to make tokens: `cannot_make_tokens`."""
    groups = _call("GET", "/user/tokens/permission_groups", token, denied_kind=CANNOT_MAKE_TOKENS)
    want = "Workers R2 Storage Bucket Item Write"
    gid = next((g["id"] for g in groups or [] if isinstance(g, dict) and g.get("name") == want), None)
    if not gid:
        raise R2Problem(f"Cloudflare's list of rights has no “{want}”.", BAD_ANSWER)
    res = _call("POST", "/user/tokens", token, {
        "name": name,
        "policies": [{"effect": "allow",
                      "resources": {f"com.cloudflare.edge.r2.bucket.{account_id}_{_jur(eu)}_{bucket}": "*"},
                      "permission_groups": [{"id": gid}]}]}, denied_kind=CANNOT_MAKE_TOKENS)
    if not isinstance(res, dict) or "id" not in res or "value" not in res:
        raise R2Problem("Cloudflare's answer to making a token could not be understood.", BAD_ANSWER)
    return str(res["id"]), str(res["value"])


def delete_token(token: str, token_id: str) -> None:
    """Delete a token (a colleague's, when they are removed); one that is gone already is no problem."""
    _call("DELETE", f"/user/tokens/{quote(token_id, safe='')}", token, gone_ok=True, denied_kind=CANNOT_MAKE_TOKENS)

"""Where a team's shared work is kept (0.18.0rc2, roadmap L6): the storage layer under the shared folder.

A *storage* holds files under names: list, read, write a file whole, remove. It knows nothing of ENLENS's work: the
storage space (`space.py`) seals every file before it is written (`seal.py`) and opens it after it is read, and the
shared folder's rules (`folder.py`) run unchanged on a copy of the space kept on this computer.

Names are `/`-separated, relative to the storage's root (a bucket, or a folder), never start with `/` and never hold
`..`. A file is written whole or not at all: a reader never sees half of one under its name.

Kinds of storage:
- `DirStorage`: a folder on this computer (tests, and the shared folder seen as a storage);
- `S3Storage`: a storage space at an online service that speaks S3 (Backblaze B2, Cloudflare R2), over HTTPS with the
  standard library only (`urllib`, AWS Signature Version 4).

Every problem is a `StorageProblem` with a kind and words for a researcher; the round that met it says it in the Team
tab and tries again next time.

Sources for `S3Storage` (read 12 November 2026):
- AWS Signature Version 4 for S3, with the published examples the tests check against:
  https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html
  https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-authenticating-requests.html
- ListObjectsV2: https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html
- Backblaze B2's S3-compatible API: https://www.backblaze.com/docs/cloud-storage-s3-compatible-api
- Cloudflare R2's S3 API: https://developers.cloudflare.com/r2/api/s3/api/
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import namedtuple
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

# StorageProblem kinds
UNREACHABLE = "unreachable"   # no connection, the service did not answer, a time-out
DENIED = "denied"             # the key was refused (wrong, removed, or not allowed this name)
NOT_FOUND = "not_found"       # no file of that name
TOO_LARGE = "too_large"       # larger than the caller reads
MAINTENANCE = "maintenance"   # the service says it is down for maintenance
BAD_ANSWER = "bad_answer"     # the service answered something ENLENS does not understand
FULL = "full"                 # the service refuses more data (a cap, an unpaid account)

_NAME = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")


class StorageProblem(Exception):
    """Why a storage could not be used just now, in words for a researcher (`str(e)`); `kind` is one of the constants
    above."""

    def __init__(self, message: str, kind: str = UNREACHABLE):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Obj:
    """A file in a storage, as a listing shows it."""
    name: str
    size: int
    etag: str        # changes whenever the file is written again (S3's ETag; a folder: size and time)


def check_name(name: str) -> str:
    """A name a storage takes: letters, digits, `.`, `_`, `-`, in parts joined by `/`; no part is `.` or `..`."""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or any(p in (".", "..") for p in name.split("/")):
        raise ValueError(f"not a storage name: {name!r}")
    return name


class Storage:
    """The four things a storage does. Subclasses implement them; each raises StorageProblem."""

    def list(self, prefix: str = "") -> dict[str, Obj]:
        """Every file whose name starts with `prefix` (all pages of the listing), by name."""
        raise NotImplementedError

    def get(self, name: str, max_size: int | None = None) -> bytes:
        """The whole file. StorageProblem(NOT_FOUND) when there is none; (TOO_LARGE) when it is larger than
        `max_size` (checked before it is read whole, where the service says the size)."""
        raise NotImplementedError

    def put(self, name: str, data: bytes) -> str:
        """Write the file whole (replacing one of that name); returns its new etag."""
        raise NotImplementedError

    def delete(self, name: str) -> None:
        """Remove the file; a file that is not there is no problem."""
        raise NotImplementedError

    def describe(self) -> str:
        """Where it is, in a few words for the Team tab (no keys)."""
        return type(self).__name__


class DirStorage(Storage):
    """A folder on this computer as a storage: names are paths below `root`. Half-written files (`.part`) are never
    listed."""

    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        return self.root / check_name(name)

    def list(self, prefix: str = "") -> dict[str, Obj]:
        out: dict[str, Obj] = {}
        if not self.root.is_dir():
            raise StorageProblem(f"The folder {self.root} cannot be reached.", UNREACHABLE)
        for dirpath, _dirs, files in os.walk(self.root):
            for f in files:
                p = Path(dirpath) / f
                rel = p.relative_to(self.root).as_posix()
                if f.endswith(".part") or not rel.startswith(prefix) or not _NAME.fullmatch(rel):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                out[rel] = Obj(rel, st.st_size, f"{st.st_size}-{st.st_mtime_ns}")
        return out

    def get(self, name: str, max_size: int | None = None) -> bytes:
        p = self._path(name)
        try:
            if max_size is not None and p.stat().st_size > max_size:
                raise StorageProblem(f"{name} is larger than ENLENS reads.", TOO_LARGE)
            return p.read_bytes()
        except FileNotFoundError as e:
            raise StorageProblem(f"There is no file {name}.", NOT_FOUND) from e
        except IsADirectoryError as e:
            raise StorageProblem(f"There is no file {name}.", NOT_FOUND) from e
        except OSError as e:
            raise StorageProblem(f"ENLENS could not read {name} ({e.strerror or e}).", UNREACHABLE) from e

    def put(self, name: str, data: bytes) -> str:
        p = self._path(name)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            part = p.with_name(p.name + ".part")
            part.write_bytes(data)
            os.replace(part, p)
            st = p.stat()
        except OSError as e:
            raise StorageProblem(f"ENLENS could not write {name} ({e.strerror or e}).", UNREACHABLE) from e
        return f"{st.st_size}-{st.st_mtime_ns}"

    def delete(self, name: str) -> None:
        try:
            self._path(name).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            raise StorageProblem(f"ENLENS could not remove {name} ({e.strerror or e}).", UNREACHABLE) from e

    def describe(self) -> str:
        return str(self.root)


# ---------------------------------------------------------------------------------------------------------------------
# AWS Signature Version 4 (a pure function, checked against AWS's published examples in the tests)

Signed = namedtuple("Signed", "signature signed_headers scope canonical_request string_to_sign")


def uri_encode(text: str, keep_slash: bool = False) -> str:
    """Percent-encode every byte but `A-Z a-z 0-9 - _ . ~` (and `/` when asked), with upper-case hex."""
    return quote(text, safe="/-_.~" if keep_slash else "-_.~")


def canonical_query(query) -> str:
    """The query string AWS signs: names and values encoded, sorted by name, then value. `query` is a dict or pairs."""
    pairs = query.items() if isinstance(query, dict) else query
    return "&".join(f"{k}={v}" for k, v in sorted((uri_encode(str(k)), uri_encode(str(v))) for k, v in pairs))


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sigv4(method: str, path: str, query, headers: dict, payload_hash: str, secret: str, region: str,
          amz_date: str, service: str = "s3") -> Signed:
    """Sign a request. `path` is the raw (not yet encoded) absolute path; `headers` are the ones to sign (including
    `host` and `x-amz-date`); `amz_date` like `20130524T000000Z`. S3 style: the path is encoded once."""
    items = sorted((k.lower().strip(), " ".join(str(v).split())) for k, v in headers.items())
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in items)
    signed_headers = ";".join(k for k, _ in items)
    canonical_request = "\n".join([method.upper(), uri_encode(path, True), canonical_query(query),
                                   canonical_headers, signed_headers, payload_hash])
    day = amz_date[:8]
    scope = f"{day}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
    key = _hmac(("AWS4" + secret).encode("utf-8"), day)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return Signed(signature, signed_headers, scope, canonical_request, string_to_sign)


# ---------------------------------------------------------------------------------------------------------------------
# S3Storage

_LIST_CAP = 16 * 1024 * 1024        # a listing page is read up to this much
_PAGE = 1000
_CAP_WORDS = re.compile(r"cap[_ ]exceeded|\bcaps?\b|billing|suspended|AccountProblem|payment|quota", re.I)
_EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_fields(body: bytes) -> dict[str, str]:
    """Code and Message of an S3 error document ({} when it is not one)."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return {}
    return {_local(c.tag): (c.text or "") for c in root}


class S3Storage(Storage):
    """A bucket at an S3-speaking service as a storage (path-style URLs, SigV4, standard library only).

    `prefix` is put before every name and taken off listed ones. With `read_key_id`, `list` and `get` are signed with
    the read key and `put` and `delete` with `key_id` (a colleague writes only their own part and reads the whole)."""

    def __init__(self, endpoint: str, region: str, bucket: str, key_id: str, secret: str, prefix: str = "",
                 read_key_id: str | None = None, read_secret: str | None = None, timeout: float = 60.0):
        parts = urlsplit(endpoint)
        self.scheme, self.host = parts.scheme or "https", parts.netloc or parts.path
        self.endpoint = f"{self.scheme}://{self.host}"
        self.region, self.bucket = region, bucket
        self.prefix = prefix if (not prefix or prefix.endswith("/")) else prefix + "/"
        self._write = (key_id, secret)
        self._read = (read_key_id, read_secret) if read_key_id and read_secret is not None else self._write
        self.timeout = timeout

    # -- words
    def _service(self) -> str:
        h = self.host.lower()
        if h.endswith("backblazeb2.com"):
            return "Backblaze"
        if h.endswith("cloudflarestorage.com"):
            return "Cloudflare"
        return "The storage service"

    def describe(self) -> str:
        h = self.host.lower().split(":")[0]
        if h.endswith("backblazeb2.com"):
            m = re.match(r"s3\.([a-z0-9-]+)\.backblazeb2\.com$", h)
            return f"Backblaze B2, bucket {self.bucket}" + (f" ({m.group(1)})" if m else "")
        if h.endswith("r2.cloudflarestorage.com"):
            where = {"eu": "EU", "fedramp": "FedRAMP"}.get(h.split(".")[-4] if h.count(".") >= 4 else "", "automatic location")
            return f"Cloudflare R2, bucket {self.bucket} ({where})"
        return f"S3 storage at {self.host}, bucket {self.bucket}" + (f" ({self.region})" if self.region else "")

    def _now(self) -> str:
        return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    # -- requests
    def _request(self, method: str, key: str | None, query=(), body: bytes | None = None, write: bool = False,
                 read_cap: int | None = None):
        from . import _web

        key_id, secret = self._write if write else self._read
        path = f"/{self.bucket}" + (f"/{key}" if key is not None else "")
        qs = canonical_query(query)

        def build():
            amz_date = self._now()
            payload = body if body is not None else b""
            phash = hashlib.sha256(payload).hexdigest()
            headers = {"host": self.host, "x-amz-content-sha256": phash, "x-amz-date": amz_date}
            if method == "PUT":
                headers["content-md5"] = base64.b64encode(hashlib.md5(payload).digest()).decode()
            s = sigv4(method, path, query, headers, phash, secret, self.region, amz_date)
            out = dict(headers)
            out["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={key_id}/{s.scope}, "
                                    f"SignedHeaders={s.signed_headers}, Signature={s.signature}")
            if method == "PUT":
                out["Content-Type"] = "application/octet-stream"
            url = self.endpoint + uri_encode(path, True) + (f"?{qs}" if qs else "")
            return method, url, out, body

        try:
            return _web.send_retrying(build, self.timeout, read_cap)
        except _web.NetError as e:
            raise StorageProblem(f"ENLENS could not reach the storage space ({e.reason}). "
                                 "It tries again on the next round.", UNREACHABLE) from e

    def _problem(self, r, what: str, write: bool) -> StorageProblem:
        """The StorageProblem for an answer that is not a success."""
        from . import _web

        f = _xml_fields(r.body)
        code, msg = f.get("Code", ""), f.get("Message", "")
        text = r.body[:4000].decode("utf-8", "replace")
        svc = self._service()
        if _web.is_maintenance(r):
            return StorageProblem(f"{svc} is down for maintenance; ENLENS tries again later.", MAINTENANCE)
        if code == "RequestTimeTooSkewed":
            return StorageProblem("The storage service refused the request because this computer's clock is wrong. "
                                  "Set the clock (and its time zone) right; ENLENS then tries again.", UNREACHABLE)
        if r.status == 402 or (r.status == 403 and _CAP_WORDS.search(code + " " + msg + " " + text)):
            return StorageProblem(f"{svc} refuses more because a limit on the account is reached or a payment is "
                                  "missing. The owner of the storage space can look at the account's caps and billing "
                                  "page at the service (for Backblaze: Caps & Alerts).", FULL)
        if r.status in (401, 403):
            if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken", "InvalidToken") or r.status == 401:
                return StorageProblem("The storage space refused ENLENS's key (it may have been removed or changed). "
                                      "The owner can invite you again.", DENIED)
            return StorageProblem(f"This key is not allowed to {'write' if write else 'read'} {what} in the storage "
                                  "space.", DENIED)
        if r.status == 404 and code == "NoSuchBucket":
            return StorageProblem("The storage space's bucket does not exist (any more).", NOT_FOUND)
        if r.status == 404:
            return StorageProblem(f"There is no file {what}.", NOT_FOUND)
        if r.status == 413 or code == "EntityTooLarge":
            return StorageProblem(f"{what} is too large for the storage service.", TOO_LARGE)
        if r.status in (301, 307, 308) or code in ("PermanentRedirect", "AuthorizationHeaderMalformed"):
            return StorageProblem("The storage service says the bucket is at another address or region than ENLENS "
                                  "has noted.", BAD_ANSWER)
        if r.status == 429 or r.status >= 500:
            return StorageProblem(f"ENLENS could not reach the storage space ({svc} had a problem, HTTP {r.status}). "
                                  "It tries again on the next round.", UNREACHABLE)
        return StorageProblem(f"The storage service answered something ENLENS does not understand "
                              f"(HTTP {r.status}{', ' + code if code else ''}).", BAD_ANSWER)

    # -- the four things
    def list(self, prefix: str = "") -> dict[str, Obj]:
        out: dict[str, Obj] = {}
        token = None
        seen = set()
        while True:
            q = [("list-type", "2"), ("max-keys", str(_PAGE)), ("prefix", self.prefix + prefix)]
            if token:
                q.append(("continuation-token", token))
            r = self._request("GET", None, q, read_cap=_LIST_CAP)
            if r.too_big:
                raise StorageProblem("The storage service's file list is far larger than ENLENS reads.", TOO_LARGE)
            if r.status != 200:
                raise self._problem(r, "the list of files", False)
            try:
                root = ET.fromstring(r.body)
                if _local(root.tag) != "ListBucketResult":
                    raise ValueError(root.tag)
                truncated, token = False, None
                for el in root:
                    t = _local(el.tag)
                    if t == "IsTruncated":
                        truncated = (el.text or "").strip().lower() == "true"
                    elif t == "NextContinuationToken":
                        token = el.text or None
                    elif t == "Contents":
                        c = {_local(x.tag): (x.text or "") for x in el}
                        key = c["Key"]
                        if not key.startswith(self.prefix):
                            continue
                        name = key[len(self.prefix):]
                        if name.endswith("/") or not _NAME.fullmatch(name):
                            continue
                        out[name] = Obj(name, int(c.get("Size", "0")), c.get("ETag", "").strip('"'))
            except (ET.ParseError, ValueError, KeyError) as e:
                raise StorageProblem("The storage service's list of files could not be understood.", BAD_ANSWER) from e
            if not truncated:
                return out
            if not token or token in seen:
                raise StorageProblem("The storage service's list of files could not be understood.", BAD_ANSWER)
            seen.add(token)

    def get(self, name: str, max_size: int | None = None) -> bytes:
        key = self.prefix + check_name(name)
        r = self._request("GET", key, (), read_cap=max_size)
        if r.too_big:
            raise StorageProblem(f"{name} is larger than ENLENS reads.", TOO_LARGE)
        if r.status != 200:
            raise self._problem(r, name, False)
        return r.body

    def put(self, name: str, data: bytes) -> str:
        key = self.prefix + check_name(name)
        r = self._request("PUT", key, (), body=bytes(data), write=True)
        if r.status not in (200, 201):
            raise self._problem(r, name, True)
        etag = r.headers.get("etag", "").strip('"')
        return etag or hashlib.md5(data).hexdigest()

    def delete(self, name: str) -> None:
        key = self.prefix + check_name(name)
        r = self._request("DELETE", key, (), write=True)
        if r.status not in (200, 202, 204, 404):
            raise self._problem(r, name, True)

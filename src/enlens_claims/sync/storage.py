"""Where a team's shared work is kept (0.18.0rc2, roadmap L6): the storage layer under the shared folder.

A *storage* holds files under names: list, read, write a file whole, remove. It knows nothing of ENLENS's work: the
storage space (`space.py`) seals every file before it is written (`seal.py`) and opens it after it is read, and the
shared folder's rules (`folder.py`) run unchanged on a copy of the space kept on this computer.

Names are `/`-separated, relative to the storage's root (a bucket, or a folder), never start with `/` and never hold
`..`. A file is written whole or not at all: a reader never sees half of one under its name.

Kinds of storage:
- `DirStorage`: a folder on this computer (tests, and the shared folder seen as a storage);
- `S3Storage`: a storage space at an online service that speaks S3 (Backblaze B2, Cloudflare R2), over HTTPS with the
  standard library only (`urllib`, AWS Signature Version 4);
- `WebDAVStorage`: a folder in a drive that speaks WebDAV (SURFdrive, SURF Research Drive, a university's Nextcloud or
  ownCloud), over HTTPS with Basic authentication and an app password, standard library only (14 November 2026).

Every problem is a `StorageProblem` with a kind and words for a researcher; the round that met it says it in the Team
tab and tries again next time.

Sources for `S3Storage` (read 12 November 2026):
- AWS Signature Version 4 for S3, with the published examples the tests check against:
  https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html
  https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-authenticating-requests.html
- ListObjectsV2: https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html
- Backblaze B2's S3-compatible API: https://www.backblaze.com/docs/cloud-storage-s3-compatible-api
- Cloudflare R2's S3 API: https://developers.cloudflare.com/r2/api/s3/api/

Sources for `WebDAVStorage` (read 14 November 2026):
- WebDAV itself, RFC 4918: PROPFIND with Depth 1 (9.1), MKCOL (9.3; 405 when the folder is there already, 409 when its
  parent is missing), PUT (9.7; 409 when the parent folder is missing), MOVE with Destination and Overwrite: T (9.9),
  507 Insufficient Storage (11.5), 423 Locked (11.3): https://www.rfc-editor.org/rfc/rfc4918
- Nextcloud's WebDAV for clients (PROPFIND properties getetag, getcontentlength, resourcetype; Depth infinity is off
  by default, so folders are walked one level at a time):
  https://docs.nextcloud.com/server/latest/developer_manual/client_apis/WebDAV/basic.html
- Nextcloud (and ownCloud, from which it came) writes an upload to a part file and renames it when it is whole; other
  WebDAV servers need not. So `put` writes under a hidden temporary name in the same folder and MOVEs it into place:
  a reader never sees half a file under its name, on any server.
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
            problem = self._problem(r, name, False)
            if problem.kind == DENIED and r.status == 403 and _xml_fields(r.body).get("Code", "") == "AccessDenied":
                # Backblaze answers a key limited to a name prefix (a colleague's read key) with 403 AccessDenied, not
                # 404, for a file that is not there (seen 13 November 2026 on the user's own bucket: every round of a
                # colleague who had joined stopped at `space/moved.json`). The list, which that key may read, says
                # which it is.
                try:
                    there = name in self.list(name)
                except StorageProblem:
                    there = True
                if not there:
                    raise StorageProblem(f"There is no file {name}.", NOT_FOUND)
            raise problem
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



# ---------------------------------------------------------------------------------------------------------------------
# WebDAVStorage

_DAV = "{DAV:}"
_PROPFIND = (b'<?xml version="1.0" encoding="utf-8"?>\n<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/>'
             b'<d:getcontentlength/><d:getetag/><d:getlastmodified/></d:prop></d:propfind>')
_MAX_FOLDERS = 20000                # a listing walks at most this many folders
_PATH_SAFE = "/@:~-._!$&'()*+,;="  # kept as they are in a URL's path (a user name like anna@uva.nl stays readable)
_TMP = ".enlens-"                   # a file being written starts so (never listed: ENLENS's names never start with .)
TEST_PLAIN_HTTP = "ENLENS_TEST_PLAIN_HTTP"   # "1": the tests' stand-in drive on this computer, over plain http


def is_loopback(host: str) -> bool:
    return (host or "").split(":")[0].strip("[]").lower() in ("127.0.0.1", "localhost", "::1")


def plain_http_allowed(host: str) -> bool:
    """Plain http (no encryption) is never used for a password, except to the tests' stand-in on this computer: only
    when the tests set ENLENS_TEST_PLAIN_HTTP=1, never in normal use."""
    return is_loopback(host) and os.environ.get(TEST_PLAIN_HTTP) == "1"


def _http_time(text: str) -> float | None:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(text.strip()).timestamp()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


class WebDAVStorage(Storage):
    """A folder in a WebDAV drive as a storage. `root_url` is the folder's address (with or without a final `/`;
    spaces and other characters as they read, or percent-encoded); `prefix` is put before every name. Basic
    authentication with `user` and an app password, over HTTPS only (plain HTTP only to the tests' stand-in,
    `plain_http_allowed`)."""

    def __init__(self, root_url: str, user: str, password: str, prefix: str = "", timeout: float = 60.0):
        from urllib.parse import unquote

        parts = urlsplit(root_url.strip())
        if parts.scheme not in ("https", "http") or not parts.netloc:
            raise StorageProblem("The drive's address must start with https://.", BAD_ANSWER)
        if parts.scheme == "http" and not plain_http_allowed(parts.hostname or ""):
            raise StorageProblem("ENLENS sends a password only over a secure connection: the drive's address must "
                                 "start with https://.", BAD_ANSWER)
        self.scheme, self.host = parts.scheme, parts.netloc
        self.root = unquote(parts.path or "/").rstrip("/") + "/"
        self.prefix = prefix if (not prefix or prefix.endswith("/")) else prefix + "/"
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        self._auth = f"Basic {token}"
        self.timeout = timeout
        self._made: set[str] = set()   # folders known to be there
        self.temporaries: dict[str, float | None] = {}   # hidden files being written, seen by `list`: name -> time

    def describe(self) -> str:
        return f"WebDAV at {self.host.split('@')[-1]}, folder {self.root}"

    # -- addresses
    def _url(self, rel: str) -> str:
        """The address of `rel` (below the root, already prefixed; a folder ends with `/`)."""
        return f"{self.scheme}://{self.host}{quote(self.root + rel, safe=_PATH_SAFE)}"

    def _rel(self, href: str) -> str | None:
        """A PROPFIND answer's href back to a name below the root (None when it is outside it)."""
        from urllib.parse import unquote

        path = unquote(urlsplit(href).path or href)
        if path + "/" == self.root:   # (the root itself, written without its final /)
            return ""
        if not path.startswith(self.root):
            return None
        return path[len(self.root):]

    # -- requests
    def _request(self, method: str, rel: str, body: bytes | None = None, headers: dict | None = None,
                 read_cap: int | None = None):
        from . import _web

        url = self._url(rel)

        def build():
            h = {"Authorization": self._auth, **(headers or {})}
            if body is not None and "Content-Type" not in h:
                h["Content-Type"] = "application/octet-stream"
            return method, url, h, body

        try:
            return _web.send_retrying(build, self.timeout, read_cap)
        except _web.NetError as e:
            raise StorageProblem(f"ENLENS could not reach the drive ({e.reason}). It tries again on the next round.",
                                 UNREACHABLE) from e

    def _problem(self, r, what: str, write: bool) -> StorageProblem:
        from . import _web

        if _web.is_maintenance(r):
            return StorageProblem("The drive is down for maintenance; ENLENS tries again later.", MAINTENANCE)
        if r.status == 401:
            return StorageProblem("The drive refused the user name or app password (the app password may have been "
                                  "removed). Make a new app password in the drive's settings and enter it in the Team "
                                  "tab.", DENIED)
        if r.status == 403:
            return StorageProblem(f"The drive does not let you {'write' if write else 'read'} {what} in the shared "
                                  "folder (the folder may no longer be shared with you, or only for reading).", DENIED)
        if r.status == 404:
            return StorageProblem(f"There is no file {what}.", NOT_FOUND)
        if r.status == 507:
            return StorageProblem("The drive is full: its storage quota is reached. The person who owns the shared "
                                  "folder can make room, or ask their institution for more space.", FULL)
        if r.status == 413:
            return StorageProblem(f"{what} is too large for the drive.", TOO_LARGE)
        if 300 <= r.status < 400:   # (never followed: the password would go along to the other address)
            return StorageProblem("The drive answered from another address: check the WebDAV address in the drive's "
                                  "settings.", BAD_ANSWER)
        if r.status == 423:
            return StorageProblem(f"{what} is locked in the drive just now. ENLENS tries again on the next round.",
                                  UNREACHABLE)
        if r.status == 429 or r.status >= 500:
            return StorageProblem(f"ENLENS could not reach the drive (it had a problem, HTTP {r.status}). It tries "
                                  "again on the next round.", UNREACHABLE)
        return StorageProblem(f"The drive answered something ENLENS does not understand (HTTP {r.status}).",
                              BAD_ANSWER)

    def _propfind(self, rel: str, depth: str) -> tuple[tuple, list[tuple]] | None:
        """(the entry asked for, the entries in it): each (name below the root, is a folder, size, etag, time written
        or None). None when there is no such file or folder. An answer about other files than the one asked for is
        StorageProblem(BAD_ANSWER), never an empty folder."""
        r = self._request("PROPFIND", rel, _PROPFIND, {"Depth": depth,
                                                       "Content-Type": "application/xml; charset=utf-8"},
                          read_cap=_LIST_CAP)
        if r.status == 404:
            return None
        if r.too_big:
            raise StorageProblem("The drive's list of files is far larger than ENLENS reads.", TOO_LARGE)
        if r.status != 207:
            raise self._problem(r, "the list of files", False)
        try:
            root = ET.fromstring(r.body)
            if root.tag != _DAV + "multistatus":
                raise ValueError(root.tag)
        except (ET.ParseError, ValueError) as e:
            raise StorageProblem("The drive's list of files could not be understood.", BAD_ANSWER) from e
        itself, out = None, []
        for resp in root.findall(_DAV + "response"):
            href = (resp.findtext(_DAV + "href") or "").strip()
            name = self._rel(href)
            if name is None:
                continue
            is_dir, size, etag, when = False, 0, "", None
            for ps in resp.findall(_DAV + "propstat"):
                if " 200 " not in f" {(ps.findtext(_DAV + 'status') or '')} ":
                    continue
                prop = ps.find(_DAV + "prop")
                if prop is None:
                    continue
                rt = prop.find(_DAV + "resourcetype")
                if rt is not None and rt.find(_DAV + "collection") is not None:
                    is_dir = True
                try:
                    size = int((prop.findtext(_DAV + "getcontentlength") or "0").strip() or 0)
                except ValueError:
                    size = 0
                etag = (prop.findtext(_DAV + "getetag") or etag).strip().strip('"')
                when = _http_time(prop.findtext(_DAV + "getlastmodified") or "") or when
            name = name.rstrip("/")
            entry = (name, is_dir, size, etag, when)
            if name == rel.rstrip("/"):
                itself = entry
            else:
                out.append(entry)
        if itself is None:
            raise StorageProblem("The drive answered with the files of another folder than the one ENLENS asked for, "
                                 "so ENLENS could not see what is in the shared folder. Check the WebDAV address in the "
                                 "drive's settings; nothing was changed.", BAD_ANSWER)
        return itself, out

    def propfind(self, rel: str, depth: str = "1") -> list[tuple[str, bool, int, str]] | None:
        """One folder's entries (Depth 1), the folder itself left out: [(name below the root, is a folder, size,
        etag)]; None when there is no such folder. With depth "0", only whether it is there ([] or None)."""
        got = self._propfind(rel, depth)
        if got is None:
            return None
        return [(n, d, s, e) for n, d, s, e, _w in got[1]]

    def stat(self, rel: str) -> tuple[int, str] | None:
        """(size, etag) of one file below the root (already prefixed), or None when there is none."""
        got = self._propfind(rel, "0")
        if got is None or got[0][1]:
            return None
        return got[0][2], got[0][3]

    # -- the four things
    def list(self, prefix: str = "") -> dict[str, Obj]:
        out: dict[str, Obj] = {}
        start = prefix.rsplit("/", 1)[0] + "/" if "/" in prefix else ""
        folders, walked = [start], 0
        while folders:
            sub = folders.pop()
            walked += 1
            if walked > _MAX_FOLDERS:
                raise StorageProblem("The drive's shared folder holds far more folders than ENLENS reads.", TOO_LARGE)
            got = self._propfind(self.prefix + sub, "1")
            if got is None:
                if sub == start:
                    if self.propfind("", "0") is None:   # (the shared folder itself is gone, or no longer shared)
                        raise StorageProblem("The shared folder is not in the drive (any more), or no longer shared "
                                             "with you. The owner can share it with you again.", NOT_FOUND)
                    return out   # (no such folder: nothing in it)
                continue
            self._made.add(self.prefix + sub)
            for full, is_dir, size, etag, when in got[1]:
                if not full.startswith(self.prefix):
                    continue
                name = full[len(self.prefix):]
                leaf = name.rsplit("/", 1)[-1]
                if leaf.startswith(_TMP) and not is_dir:
                    self.temporaries[full] = when
                if not name or leaf.startswith("."):
                    continue
                try:   # (a name ENLENS never writes, such as one with `..` in it, is left out: the round goes on)
                    check_name(name)
                except ValueError:
                    continue
                if is_dir:
                    d = name + "/"
                    if d.startswith(prefix) or prefix.startswith(d):
                        folders.append(d)
                elif name.startswith(prefix):
                    out[name] = Obj(name, size, etag or f"{size}")
        return out

    def clean_temporaries(self, older_than: float = 86400.0, at_most: int = 5) -> int:
        """Remove hidden temporary files (`.enlens-…`) that `list` saw and that are older than `older_than` seconds:
        what a write cut off halfway left behind. At most `at_most` per call (a round), best effort. Returns how many
        went."""
        cutoff, gone = time.time() - older_than, 0
        for full, when in sorted(self.temporaries.items(), key=lambda x: x[1] or 0):
            if gone >= at_most:
                break
            if when is None or when > cutoff:
                continue
            try:
                r = self._request("DELETE", full)
            except StorageProblem:
                break
            if r.status in (200, 202, 204, 404):
                gone += 1
                self.temporaries.pop(full, None)
        return gone

    def get(self, name: str, max_size: int | None = None) -> bytes:
        r = self._request("GET", self.prefix + check_name(name), read_cap=max_size)
        if r.too_big:
            raise StorageProblem(f"{name} is larger than ENLENS reads.", TOO_LARGE)
        if r.status != 200:
            raise self._problem(r, name, False)
        return r.body

    def make_folder(self, rel_folder: str) -> bool:
        """Make one new folder below the root: True when it was made, False when something of that name is there
        already (405), even when the listing did not show it."""
        r = self._request("MKCOL", rel_folder.strip("/") + "/")
        if r.status == 201:
            self._made.add(rel_folder.strip("/") + "/")
            return True
        if r.status == 405:
            return False
        raise self._problem(r, f"the folder {rel_folder.strip('/')}", True)

    def mkdirs(self, rel_folder: str) -> None:
        """Make a folder (below the root) and every folder above it that is not there yet."""
        path = ""
        for part in [p for p in rel_folder.split("/") if p]:
            path += part + "/"
            if path in self._made:
                continue
            r = self._request("MKCOL", path)
            if r.status == 409 and path.count("/") == 1:   # (the folder above it, the shared one, is not there)
                raise StorageProblem("The shared folder is not in the drive (any more), or not shared with you. The "
                                     "owner can share it with you again.", NOT_FOUND)
            if r.status not in (201, 405):   # (405: there already)
                raise self._problem(r, f"the folder {path.rstrip('/')}", True)
            self._made.add(path)

    def put(self, name: str, data: bytes) -> str:
        rel = self.prefix + check_name(name)
        folder, leaf = rel.rsplit("/", 1) if "/" in rel else ("", rel)
        tmp = (folder + "/" if folder else "") + f"{_TMP}{os.urandom(4).hex()}-{leaf}"
        body = bytes(data)
        r = self._request("PUT", tmp, body)
        if r.status in (404, 409):   # (the folder is not there yet)
            self._made.difference_update({p for p in self._made if (rel + "/").startswith(p)})
            self.mkdirs(folder)
            r = self._request("PUT", tmp, body)
        if r.status not in (200, 201, 204):
            raise self._problem(r, name, True)
        m = self._request("MOVE", tmp, headers={"Destination": self._url(rel), "Overwrite": "T"})
        etag = ""
        if m.status == 404:
            # a MOVE tried again (the first one's answer was lost, or a 5xx after it was done): the temporary file is
            # gone; it counts when the file is now there whole
            there = self.stat(rel)
            if there is None or there[0] != len(body) or self.stat(tmp) is not None:
                raise self._problem(m, name, True)
            etag = there[1]
        elif m.status not in (201, 204):
            self._request("DELETE", tmp)   # (best effort: a hidden temporary file is never listed)
            raise self._problem(m, name, True)
        etag = etag or (m.headers.get("etag") or r.headers.get("etag") or "").strip('"')
        return etag or hashlib.md5(body).hexdigest()

    def delete(self, name: str) -> None:
        r = self._request("DELETE", self.prefix + check_name(name))
        if r.status not in (200, 202, 204, 404):
            raise self._problem(r, name, True)

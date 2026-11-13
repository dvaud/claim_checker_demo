"""A stand-in for an S3-speaking storage service (Backblaze B2's or Cloudflare R2's S3 API), for tests. Path-style,
in memory, on 127.0.0.1; it VERIFIES each request's Signature Version 4 with the secrets it was given.

    srv, url = start(keys={"KEYID": {"secret": "s", "bucket": "b", "prefix": "parts/A/", "can_write": True}})
    put_object(srv, "b", "x.txt", b"data"); get_object(srv, "b", "x.txt"); objects(srv, "b")

Keys: id -> {"secret", "bucket" (None: any), "prefix" (None: any name), "can_write" (default True)}; a key with a
"caps" list (B2 capability names: listFiles, readFiles, writeFiles, deleteFiles) is governed by that instead. A key
limited to a bucket and a name prefix is refused (403 AccessDenied) outside them, as B2 does, and so is its GET of a
file that is not there (B2 answers a prefix-limited key so, not with 404).

Knobs on `srv.state`: `fail_next(n, status)`, `maintenance`, `cap` (a cap message), `delay`, `page_size`,
`chunked_get` (answer GET without Content-Length), `check_clock`. `state.log` lists (method, key id, path, query).
"""
from __future__ import annotations

import hashlib
import base64
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit
from xml.sax.saxutils import escape

from enlens_claims.sync.storage import sigv4

NS = "http://s3.amazonaws.com/doc/2006-03-01/"
_AUTH = re.compile(r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/s3/aws4_request, SignedHeaders=([^,]+), "
                   r"Signature=([0-9a-f]{64})$")


class QuickServer(ThreadingHTTPServer):
    """Starts without Python's slow full-name lookup (see gui/server.py QuickServer)."""
    daemon_threads = True

    def server_bind(self) -> None:
        import socketserver

        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), port


class State:
    def __init__(self, keys=None, page_size: int = 1000):
        self.lock = threading.RLock()
        self.keys: dict = keys if keys is not None else {}
        self.buckets: dict[str, dict[str, bytes]] = {}
        self.page_size = page_size
        self.maintenance = False
        self.cap: str | None = None          # e.g. "transaction_cap_exceeded"
        self.delay = 0.0
        self.chunked_get = False
        self.check_clock = False
        self.log: list = []
        self._fail: list = []

    def fail_next(self, n: int, status: int = 500) -> None:
        with self.lock:
            self._fail += [status] * n

    def make_bucket(self, name: str) -> None:
        with self.lock:
            self.buckets.setdefault(name, {})


def _etag(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: State

    def log_message(self, *a):  # quiet
        pass

    def _send(self, status: int, body: bytes = b"", headers: dict | None = None, ctype: str = "application/xml"):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def _error(self, status: int, code: str, message: str):
        body = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Error><Code>{code}</Code><Message>{escape(message)}</Message></Error>"
        self._send(status, body.encode())

    def do_GET(self): self._handle()
    def do_PUT(self): self._handle()
    def do_DELETE(self): self._handle()
    def do_HEAD(self): self._handle()

    def _handle(self):
        st = self.state
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if st.delay:
            time.sleep(st.delay)
        parts = urlsplit(self.path)
        query = parse_qsl(parts.query, keep_blank_values=True)
        q = dict(query)
        raw_path = unquote(parts.path)
        with st.lock:
            fail = st._fail.pop(0) if st._fail else None
        if fail:
            return self._send(fail, b"internal trouble", ctype="text/plain")
        if st.maintenance:
            return self._send(503, b"<html><body><h1>Down for maintenance</h1></body></html>", ctype="text/html")
        # --- who
        m = _AUTH.match(self.headers.get("Authorization", ""))
        if not m:
            return self._error(403, "AccessDenied", "Missing or malformed Authorization")
        key_id, day, region, signed, sig = m.groups()
        key = st.keys.get(key_id)
        if not key:
            return self._error(403, "InvalidAccessKeyId", "The access key ID you provided does not exist")
        amz_date = self.headers.get("x-amz-date", "")
        hdrs = {h: self.headers.get(h, "") for h in signed.split(";")}
        good = sigv4(self.command, raw_path, query, hdrs, self.headers.get("x-amz-content-sha256", ""), key["secret"],
                     region, amz_date)
        if not hmac_eq(good.signature, sig):
            return self._error(403, "SignatureDoesNotMatch", "The request signature we calculated does not match")
        if self.headers.get("x-amz-content-sha256") != hashlib.sha256(body).hexdigest():
            return self._error(400, "XAmzContentSHA256Mismatch", "The provided x-amz-content-sha256 does not match")
        if st.check_clock:
            try:
                t = time.mktime(time.strptime(amz_date, "%Y%m%dT%H%M%SZ")) - time.timezone
            except ValueError:
                t = 0
            if abs(t - time.time()) > 900:
                return self._error(403, "RequestTimeTooSkewed", "The difference between the request time and the "
                                   "current time is too large.")
        with st.lock:
            st.log.append((self.command, key_id, raw_path, parts.query))
        segs = raw_path.lstrip("/").split("/", 1)
        bucket, name = segs[0], (segs[1] if len(segs) > 1 else "")
        # --- what it may do
        if key.get("bucket") not in (None, bucket):
            return self._error(403, "AccessDenied", "Access Denied")
        op = {"GET": "listFiles" if not name else "readFiles", "PUT": "writeFiles", "DELETE": "deleteFiles",
              "HEAD": "readFiles"}[self.command]
        if "caps" in key:
            allowed = op in key["caps"]
        else:
            allowed = key.get("can_write", True) or op in ("listFiles", "readFiles")
        if not allowed:
            return self._error(403, "AccessDenied", "Access Denied")
        pre = key.get("prefix")
        if pre and not (q.get("prefix", "") if not name else name).startswith(pre):
            return self._error(403, "AccessDenied", "Access Denied")
        if st.cap:
            return self._error(403, "AccessDenied", f"Cannot do this: {st.cap}. The account has reached a cap.")
        with st.lock:
            objs = st.buckets.get(bucket)
        if objs is None:
            return self._error(404, "NoSuchBucket", "The specified bucket does not exist")
        if self.command == "GET" and not name:
            return self._list(objs, q)
        if not name:
            return self._error(400, "InvalidRequest", "No key")
        if self.command == "PUT":
            md5 = self.headers.get("Content-MD5")
            if md5 and md5 != base64.b64encode(hashlib.md5(body).digest()).decode():
                return self._error(400, "BadDigest", "The Content-MD5 you specified did not match what we received.")
            with st.lock:
                objs[name] = body
            return self._send(200, b"", {"ETag": f'"{_etag(body)}"'})
        if self.command == "DELETE":
            with st.lock:
                objs.pop(name, None)
            return self._send(204)
        with st.lock:
            data = objs.get(name)
        if data is None:
            if key.get("prefix"):   # as Backblaze does for a key limited to a name prefix (13 November 2026)
                return self._error(403, "AccessDenied", "Access Denied")
            return self._error(404, "NoSuchKey", "The specified key does not exist.")
        if st.chunked_get:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass
            self.close_connection = True
            return
        self._send(200, data, {"ETag": f'"{_etag(data)}"'}, "application/octet-stream")

    def _list(self, objs: dict, q: dict):
        st = self.state
        pre = q.get("prefix", "")
        limit = min(int(q.get("max-keys", "1000")), st.page_size)
        after = unquote(q["continuation-token"][4:]) if q.get("continuation-token", "").startswith("tok:") else ""
        with st.lock:
            names = sorted(k for k in objs if k.startswith(pre) and k > after)
            page = names[:limit]
            more = len(names) > limit
            rows = "".join(f"<Contents><Key>{escape(k)}</Key><LastModified>2026-11-12T00:00:00.000Z</LastModified>"
                           f"<ETag>&quot;{_etag(objs[k])}&quot;</ETag><Size>{len(objs[k])}</Size>"
                           f"<StorageClass>STANDARD</StorageClass></Contents>" for k in page)
        nxt = f"<NextContinuationToken>tok:{escape(page[-1])}</NextContinuationToken>" if more else ""
        xml = (f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="{NS}"><Name>b</Name>'
               f"<Prefix>{escape(pre)}</Prefix><KeyCount>{len(page)}</KeyCount><MaxKeys>{limit}</MaxKeys>"
               f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>{rows}{nxt}</ListBucketResult>")
        self._send(200, xml.encode())


def hmac_eq(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)


def start(keys: dict | None = None, page_size: int = 1000, buckets=()):
    """Start the stand-in on a free port: returns `(server, url)`. `server.state` holds the knobs; stop it with
    `server.shutdown(); server.server_close()` (or `stop(server)`). `keys` may be a dict you share with another
    stand-in (fake_b2, fake_cloudflare)."""
    state = State(keys, page_size)
    for b in buckets:
        state.make_bucket(b)
    handler = type("BoundHandler", (Handler,), {"state": state})
    srv = QuickServer(("127.0.0.1", 0), handler)
    srv.state = state
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def stop(srv) -> None:
    srv.shutdown()
    srv.server_close()


def put_object(srv, bucket: str, name: str, data: bytes) -> None:
    srv.state.make_bucket(bucket)
    with srv.state.lock:
        srv.state.buckets[bucket][name] = data


def get_object(srv, bucket: str, name: str) -> bytes | None:
    return srv.state.buckets.get(bucket, {}).get(name)


def objects(srv, bucket: str) -> dict[str, bytes]:
    return dict(srv.state.buckets.get(bucket, {}))

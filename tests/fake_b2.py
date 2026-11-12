"""A stand-in for Backblaze B2's native API (v3) that shares its keys and buckets with `fake_s3`: a key made here is
usable there, limited to its bucket and name prefix.

    b2, url = start()                      # also starts a fake S3: b2.s3 (server), b2.s3_url
    monkeypatch.setenv("ENLENS_B2_API", url)
    acc = enlens_claims.sync.b2.authorize(*b2.master)      # the master key: ("MASTERKEYID", "master-secret")

Knobs on `b2.state`: `maintenance`, `region` (default "eu-central-003"; any other, such as "us-west-004", for the
non-EU case), `cap` (403 transaction_cap_exceeded). A key that may not make keys (the "own key cannot make keys" case):
`b2.state.add_key("ID", "secret", ["listBuckets", "writeBuckets", "listFiles", "readFiles", "writeFiles"])`. `b2.state.buckets_meta` holds each bucket's type
and lifecycle rules; `b2.state.calls` the names of the calls made.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fake_s3  # noqa: E402

ALL_CAPS = ["listKeys", "writeKeys", "deleteKeys", "listAllBucketNames", "listBuckets", "readBuckets", "writeBuckets",
            "deleteBuckets", "listFiles", "readFiles", "shareFiles", "writeFiles", "deleteFiles"]
_BUCKET = re.compile(r"[A-Za-z0-9-]{6,63}")


class B2State:
    def __init__(self, s3, region: str = "eu-central-003"):
        self.s3 = s3
        self.keys = s3.state.keys                     # shared with the fake S3
        self.lock = threading.RLock()
        self.region = region
        self.maintenance = False
        self.cap = False
        self.account_id = "acc" + secrets.token_hex(5)
        self.tokens: dict[str, str] = {}              # auth token -> key id
        self.bucket_ids: dict[str, str] = {}          # bucketId -> name
        self.buckets_meta: dict[str, dict] = {}
        self.calls: list[str] = []
        self.s3_url = ""
        self.api_url = ""

    def add_key(self, key_id: str, secret: str, caps: list, bucket: str | None = None, prefix: str | None = None):
        with self.lock:
            self.keys[key_id] = {"secret": secret, "bucket": bucket, "prefix": prefix, "caps": list(caps)}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: B2State

    def log_message(self, *a):
        pass

    def _send(self, status, obj=None, raw: bytes | None = None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _err(self, status, code, message):
        self._send(status, {"status": status, "code": code, "message": message})

    def do_GET(self): self._handle(b"")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self._handle(self.rfile.read(n) if n else b"")

    def _handle(self, raw: bytes):
        st = self.state
        m = re.fullmatch(r"/b2api/(v\d)/(b2_\w+)", self.path.split("?")[0])
        if not m:
            return self._err(404, "not_found", "no such call")
        call = m.group(2)
        st.calls.append(call)
        if st.maintenance:
            return self._send(503, raw=b"<html><body>Backblaze is down for maintenance</body></html>", ctype="text/html")
        auth = self.headers.get("Authorization", "")
        if call == "b2_authorize_account":
            return self._authorize(auth)
        key_id = st.tokens.get(auth)
        key = st.keys.get(key_id) if key_id else None
        if not key:
            return self._err(401, "bad_auth_token", "Invalid authorization token")
        if st.cap:
            return self._err(403, "transaction_cap_exceeded", "Transaction cap exceeded")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._err(400, "bad_request", "bad json")
        need = {"b2_create_key": "writeKeys", "b2_delete_key": "deleteKeys", "b2_create_bucket": "writeBuckets",
                "b2_delete_bucket": "deleteBuckets", "b2_list_buckets": "listBuckets"}.get(call)
        if need is None:
            return self._err(404, "not_found", "no such call")
        if need not in key["caps"]:
            return self._err(401, "unauthorized", f"app key is not authorized: missing capability {need}")
        getattr(self, "_" + call)(key_id, key, body)

    def _authorize(self, auth: str):
        st = self.state
        try:
            kid, sec = base64.b64decode(auth.split(" ", 1)[1]).decode().split(":", 1)
        except Exception:  # noqa: BLE001
            return self._err(401, "unauthorized", "bad credentials")
        key = st.keys.get(kid)
        if not key or key["secret"] != sec:
            return self._err(401, "unauthorized", "Invalid credentials")
        tok = "tok" + secrets.token_hex(12)
        st.tokens[tok] = kid
        sa = {"absoluteMinimumPartSize": 5000000, "apiUrl": st.api_url, "downloadUrl": st.api_url,
              "capabilities": key["caps"], "bucketId": None, "bucketName": None, "namePrefix": key.get("prefix"),
              "infoType": "storageApi", "recommendedPartSize": 100000000, "s3ApiUrl": st.s3_url,
              "s3Region": st.region}     # `s3Region`: only here, since a local address names no region
        if key.get("bucket"):
            sa["bucketName"] = key["bucket"]
            sa["bucketId"] = next((i for i, n in st.bucket_ids.items() if n == key["bucket"]), None)
        self._send(200, {"accountId": st.account_id, "authorizationToken": tok, "apiInfo": {"storageApi": sa}})

    def _b2_create_key(self, key_id, key, body):
        st = self.state
        caps = body.get("capabilities") or []
        if not set(caps) <= set(key["caps"]):
            return self._err(401, "unauthorized", "cannot grant capabilities the creating key lacks")
        bucket = None
        v4 = "/b2api/v4/" in self.path
        if (body.get("bucketIds") if not v4 else body.get("bucketId")):   # v4 takes a list, v3 one id
            return self._err(400, "bad_request", "bucketId is v3, bucketIds is v4")
        bid = (body.get("bucketIds") or [None])[0] if v4 else body.get("bucketId")
        if bid:
            bucket = st.bucket_ids.get(bid)
            if bucket is None:
                return self._err(400, "bad_bucket_id", "no such bucket")
        if body.get("accountId") != st.account_id or not body.get("keyName"):
            return self._err(400, "bad_request", "accountId/keyName wrong")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", body["keyName"]):
            return self._err(400, "bad_request", "bad keyName")
        kid, sec = "003" + secrets.token_hex(10), "K003" + secrets.token_urlsafe(24)
        st.add_key(kid, sec, caps, bucket, body.get("namePrefix") or None)
        out = {"keyName": body["keyName"], "applicationKeyId": kid, "applicationKey": sec, "capabilities": caps,
               "accountId": st.account_id, "namePrefix": body.get("namePrefix"),
               **({"bucketIds": [bid] if bid else None} if v4 else {"bucketId": bid})}
        self._send(200, out)

    def _b2_delete_key(self, key_id, key, body):
        st = self.state
        kid = body.get("applicationKeyId")
        with st.lock:
            gone = st.keys.pop(kid, None)
            for t in [t for t, k in st.tokens.items() if k == kid]:
                del st.tokens[t]
        if gone is None:
            return self._err(400, "bad_request", "applicationKeyId does not exist")
        self._send(200, {"applicationKeyId": kid})

    def _b2_create_bucket(self, key_id, key, body):
        st = self.state
        name = body.get("bucketName", "")
        if not _BUCKET.fullmatch(name) or name.startswith("b2-") or body.get("bucketType") not in ("allPrivate", "allPublic"):
            return self._err(400, "bad_request", "bad bucket name or type")
        with st.lock:
            if name in st.s3.state.buckets:
                return self._err(400, "duplicate_bucket_name", "Bucket name is already in use.")
            bid = secrets.token_hex(12)
            st.bucket_ids[bid] = name
            st.s3.state.make_bucket(name)
            st.buckets_meta[name] = {"bucketType": body["bucketType"], "lifecycleRules": body.get("lifecycleRules")}
        self._send(200, {"accountId": st.account_id, "bucketId": bid, "bucketName": name,
                         "bucketType": body["bucketType"], "lifecycleRules": body.get("lifecycleRules")})

    def _b2_delete_bucket(self, key_id, key, body):
        st = self.state
        name = st.bucket_ids.get(body.get("bucketId"))
        if name is None:
            return self._err(400, "bad_bucket_id", "no such bucket")
        if st.s3.state.buckets.get(name):
            return self._err(400, "cannot_delete_non_empty_bucket", "bucket not empty")
        with st.lock:
            st.s3.state.buckets.pop(name, None)
            del st.bucket_ids[body["bucketId"]]
        self._send(200, {"bucketId": body["bucketId"], "bucketName": name})

    def _b2_list_buckets(self, key_id, key, body):
        st = self.state
        self._send(200, {"buckets": [{"bucketId": i, "bucketName": n, "accountId": st.account_id,
                                      **st.buckets_meta.get(n, {})} for i, n in st.bucket_ids.items()]})


def start(s3=None, master=("MASTERKEYID", "master-secret"), region: str = "eu-central-003"):
    """Start the stand-in: returns `(server, url)`. `server.s3` is the fake S3 it shares (started here unless you give
    `s3` as a `fake_s3.start()` server), `server.s3_url` its address, `server.master` the master key `(id, secret)`,
    `server.state` the knobs. Stop with `stop(server)`."""
    own = s3 is None
    if own:
        s3, s3_url = fake_s3.start()
    else:
        s3_url = f"http://127.0.0.1:{s3.server_address[1]}"
    state = B2State(s3, region)
    state.add_key(master[0], master[1], ALL_CAPS)
    handler = type("BoundHandler", (Handler,), {"state": state})
    srv = fake_s3.QuickServer(("127.0.0.1", 0), handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    state.s3_url, state.api_url = s3_url, url
    srv.state, srv.s3, srv.s3_url, srv.master, srv._own_s3 = state, s3, s3_url, master, own
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    return srv, url


def stop(srv) -> None:
    srv.shutdown()
    srv.server_close()
    if srv._own_s3:
        fake_s3.stop(srv.s3)

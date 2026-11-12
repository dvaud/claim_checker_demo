"""A stand-in for Cloudflare's API v4 (the R2 and API-token calls ENLENS makes), sharing its tokens and buckets with
`fake_s3`: a member token made here works there through `r2.s3_credentials`, limited to its bucket.

    cf, url = start()                       # also starts a fake S3: cf.s3, cf.s3_url
    monkeypatch.setenv("ENLENS_CF_API", url)           # the stand-in serves under /client/v4
    monkeypatch.setenv("ENLENS_R2_ENDPOINT", cf.s3_url)
    token = cf.owner_token                  # the value a test "pastes"; cf.owner_token_id is its id

Knobs on `cf.state`: `r2_on` (False: bucket calls answer 403 code 10042, "Please enable R2 ..."),
`can_make_tokens` (False: POST /user/tokens and the permission list answer 403), `maintenance`.
`cf.state.buckets_meta[(jurisdiction, name)]`, `cf.state.calls` ("METHOD path"), `cf.state.tokens` (value -> info).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fake_s3  # noqa: E402

GROUPS = [{"id": "g-r2-w", "name": "Workers R2 Storage Bucket Item Write", "scopes": ["com.cloudflare.edge.r2.bucket"]},
          {"id": "g-r2-r", "name": "Workers R2 Storage Bucket Item Read", "scopes": ["com.cloudflare.edge.r2.bucket"]},
          {"id": "g-acc-w", "name": "Workers R2 Storage Write", "scopes": ["com.cloudflare.api.account"]}]
_BUCKET = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")


class CFState:
    def __init__(self, s3, account_id: str):
        self.s3 = s3
        self.keys = s3.state.keys
        self.lock = threading.RLock()
        self.account_id = account_id
        self.r2_on = True
        self.can_make_tokens = True
        self.maintenance = False
        self.tokens: dict[str, dict] = {}          # value -> {"id", "status", "bucket"}
        self.buckets_meta: dict[tuple, dict] = {}  # (jurisdiction, name) -> {}
        self.calls: list[str] = []

    def add_token(self, value: str, token_id: str | None = None, can_make_tokens: bool = True) -> str:
        tid = token_id or secrets.token_hex(16)
        with self.lock:
            self.tokens[value] = {"id": tid, "status": "active", "bucket": None, "can_make_tokens": can_make_tokens}
            self.keys[tid] = {"secret": hashlib.sha256(value.encode()).hexdigest(), "bucket": None, "prefix": None,
                              "can_write": True}
        return tid


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: CFState

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

    def _ok(self, result):
        self._send(200, {"success": True, "errors": [], "messages": [], "result": result})

    def _err(self, status, code, message):
        self._send(status, {"success": False, "errors": [{"code": code, "message": message}], "messages": [],
                            "result": None})

    def do_GET(self): self._handle()
    def do_POST(self): self._handle()
    def do_DELETE(self): self._handle()

    def _handle(self):
        st = self.state
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        path = self.path.split("?")[0]
        if not path.startswith("/client/v4/"):
            return self._err(404, 7003, "no route")
        path = path[len("/client/v4"):]
        st.calls.append(f"{self.command} {path}")
        if st.maintenance:
            return self._send(503, raw=b"<html>Cloudflare maintenance</html>", ctype="text/html")
        tok = st.tokens.get(self.headers.get("Authorization", "").removeprefix("Bearer ").strip())
        if not tok or tok["status"] != "active":
            return self._err(401, 1000, "Invalid API Token")
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            return self._err(400, 1001, "bad json")
        jur = self.headers.get("cf-r2-jurisdiction", "default")
        if path == "/user/tokens/verify" and self.command == "GET":
            return self._ok({"id": tok["id"], "status": tok["status"]})
        if path == "/accounts" and self.command == "GET":
            return self._ok([{"id": st.account_id, "name": "Test account"}])
        if path == "/user/tokens/permission_groups" and self.command == "GET":
            if not tok["can_make_tokens"]:
                return self._err(403, 9109, "Unauthorized to access requested resource")
            return self._ok(GROUPS)
        if path == "/user/tokens" and self.command == "POST":
            return self._make_token(tok, body)
        m = re.fullmatch(r"/user/tokens/([^/]+)", path)
        if m and self.command == "DELETE":
            if not tok["can_make_tokens"]:
                return self._err(403, 9109, "Unauthorized to access requested resource")
            with st.lock:
                val = next((v for v, t in st.tokens.items() if t["id"] == m.group(1)), None)
                if val is None:
                    return self._err(404, 1003, "token not found")
                del st.tokens[val]
                st.keys.pop(m.group(1), None)
            return self._ok({"id": m.group(1)})
        m = re.fullmatch(r"/accounts/([^/]+)/r2/buckets(?:/([^/]+))?", path)
        if m:
            if m.group(1) != st.account_id:
                return self._err(403, 10003, "Access denied")
            if not st.r2_on:
                return self._err(403, 10042, "Please enable R2 through the Cloudflare Dashboard.")
            if self.command == "POST" and not m.group(2):
                name = body.get("name", "")
                if not _BUCKET.fullmatch(name):
                    return self._err(400, 10005, "The specified bucket name is not valid.")
                with st.lock:
                    if (jur, name) in st.buckets_meta:
                        return self._err(409, 10073, "The bucket you tried to create already exists, and you own it.")
                    st.buckets_meta[(jur, name)] = {}
                    st.s3.state.make_bucket(name)
                return self._ok({"name": name, "jurisdiction": jur})
            if self.command == "DELETE" and m.group(2):
                name = m.group(2)
                with st.lock:
                    if (jur, name) not in st.buckets_meta:
                        return self._err(404, 10006, "The specified bucket does not exist.")
                    if st.s3.state.buckets.get(name):
                        return self._err(409, 10008, "The bucket you tried to delete is not empty.")
                    del st.buckets_meta[(jur, name)]
                    st.s3.state.buckets.pop(name, None)
                return self._ok({})
        self._err(404, 7003, "no route")

    def _make_token(self, tok, body):
        st = self.state
        if not tok["can_make_tokens"]:
            return self._err(403, 9109, "Unauthorized to access requested resource")
        try:
            pol = body["policies"][0]
            (res_key,) = pol["resources"].keys()
            gids = [g["id"] for g in pol["permission_groups"]]
            mm = re.fullmatch(rf"com\.cloudflare\.edge\.r2\.bucket\.{st.account_id}_(\w+)_([a-z0-9-]+)", res_key)
            assert mm and pol["effect"] == "allow" and gids and all(g in {x["id"] for x in GROUPS} for g in gids)
        except Exception:  # noqa: BLE001
            return self._err(400, 1001, "Invalid request: policies")
        value = secrets.token_urlsafe(32)
        tid = st.add_token(value, can_make_tokens=False)
        with st.lock:
            st.keys[tid].update(bucket=mm.group(2), can_write="g-r2-w" in gids)
            st.tokens[value]["bucket"] = mm.group(2)
        self._ok({"id": tid, "name": body.get("name"), "status": "active", "value": value})


def start(s3=None, account_id: str = "0123456789abcdef0123456789abcdef", owner_token: str = "owner-token-value"):
    """Start the stand-in: returns `(server, url)`, `url` ending in `/client/v4` (what `ENLENS_CF_API` takes).
    `server.s3` / `server.s3_url` the fake S3 it shares, `server.owner_token` / `server.owner_token_id`,
    `server.account_id`, `server.state` the knobs. Stop with `stop(server)`."""
    own = s3 is None
    if own:
        s3, s3_url = fake_s3.start()
    else:
        s3_url = f"http://127.0.0.1:{s3.server_address[1]}"
    state = CFState(s3, account_id)
    handler = type("BoundHandler", (Handler,), {"state": state})
    srv = fake_s3.QuickServer(("127.0.0.1", 0), handler)
    srv.state, srv.s3, srv.s3_url, srv.account_id, srv._own_s3 = state, s3, s3_url, account_id, own
    srv.owner_token = owner_token
    srv.owner_token_id = state.add_token(owner_token, "owner-token-id")
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/client/v4"


def stop(srv) -> None:
    srv.shutdown()
    srv.server_close()
    if srv._own_s3:
        fake_s3.stop(srv.s3)

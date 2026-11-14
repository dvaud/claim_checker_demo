"""A stand-in for a Nextcloud-like drive (14 November 2026): WebDAV under `/remote.php/dav/files/<user>/` (and
`/remote.php/webdav/`, the signed-in user's own files, as SURFdrive's and ownCloud's addresses work), and the OCS Share
API. Several users, each with an app password; a folder shared with a user shows in their own files under its name
(`name (2)` when they have one of that name), or inside `Shared/` with `state.shares_in = "Shared"`.

    srv, url = start({"anna": "pw-a", "carol": "pw-c"})   # url: http://127.0.0.1:<port>
    address = f"{url}/remote.php/dav/files/anna/"
    ...
    stop(srv)

Knobs on `srv.state`: `ocs` (False: no sharing interface, 404 without JSON), `maintenance` (503 "maintenance"),
`quota` (bytes in all; a PUT beyond it answers 507), `fail` ({"PUT": 401, ...}: every such request answers that),
`calls` ("METHOD path"). `files` (owner path -> bytes), `dirs`, `shares` (id -> dict) are the drive's contents.
Since the review of 14 November 2026: `href_base` (PROPFIND answers name their files under this path instead),
`extra_hrefs` (more hrefs, as they are, in every PROPFIND answer), `redirect` ((status, location): every WebDAV request
answers so), `move_then` (statuses a MOVE answers after it was done, one per MOVE), `unlisted` (owner paths a listing
leaves out), `mtimes` (owner path -> seconds; getlastmodified), `auth_to` (paths asked with an Authorization header).
A second share of a folder with the same user is refused (403), as Nextcloud does; GET `…/shares?path=` lists them.
Since the audit of 14 November 2026: `names` (user -> display name: a share's answer and the list of shares give
`share_with_displayname`, the user name itself when there is none, as Nextcloud does), a share's `permissions` are kept
(writing through a share without 2|4 answers 403, deleting without 8 too), `fail_headers` (headers sent with a `fail`
answer, such as Retry-After), `doctype` (text put before every PROPFIND answer's root, such as a DOCTYPE) and
`no_etag` (listings give no getetag, as some WebDAV servers do not).
"""
from __future__ import annotations

import base64
import json
import sys
import threading
import time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).parent))
from fake_s3 import QuickServer  # noqa: E402

DAV = "/remote.php/dav/files/"
OLD_DAV = "/remote.php/webdav/"
OCS = "/ocs/v2.php/apps/files_sharing/api/v1/shares"


class State:
    def __init__(self, users: dict[str, str]):
        self.users = dict(users)
        self.lock = threading.RLock()
        self.files: dict[str, bytes] = {}          # "anna/ENLENS - X/enlens/…" -> bytes
        self.etags: dict[str, int] = {}
        self.dirs: set[str] = {u for u in users}   # "anna", "anna/ENLENS - X"
        self.shares: dict[str, dict] = {}          # id -> {"owner", "path", "with", "mount"}
        self.ocs = True
        self.maintenance = False
        self.quota: int | None = None
        self.fail: dict[str, int] = {}
        self.shares_in = ""                        # "" (the root) or "Shared"
        self.calls: list[str] = []
        self.href_base: str | None = None
        self.extra_hrefs: list[str] = []
        self.redirect: tuple[int, str] | None = None
        self.move_then: list[int] = []
        self.unlisted: set[str] = set()
        self.mtimes: dict[str, float] = {}
        self.auth_to: list[str] = []
        self.names: dict[str, str] = {}
        self.fail_headers: dict[str, str] = {}
        self.doctype: str | None = None
        self.no_etag = False
        self._n = 0

    # -- where a user's path is in its owner's files
    def resolve(self, user: str, rel: str) -> str:
        rel = rel.strip("/")
        for sh in self.shares.values():
            if sh["with"] != user:
                continue
            m = sh["mount"]
            if rel == m or rel.startswith(m + "/"):
                return f"{sh['owner']}/{sh['path']}{rel[len(m):]}"
        return f"{user}/{rel}" if rel else user

    def children(self, user: str, rel: str) -> list[tuple[str, bool]]:
        """(name, is a folder) of a user's folder, as they see it (their shares mounted)."""
        real = self.resolve(user, rel)
        out = {}
        for d in self.dirs:
            if d in self.unlisted:
                continue
            if d.startswith(real + "/") and "/" not in d[len(real) + 1:]:
                out[d[len(real) + 1:]] = True
        for f in self.files:
            if f.startswith(real + "/") and "/" not in f[len(real) + 1:]:
                out[f[len(real) + 1:]] = False
        here = rel.strip("/")
        for sh in self.shares.values():
            if sh["with"] == user:
                parent, _, leaf = sh["mount"].rpartition("/")
                if parent == here:
                    out[leaf] = True
        return sorted(out.items())

    def share_of(self, user: str, rel: str) -> dict | None:
        """The share through which a user reaches this path of theirs (None: their own files)."""
        rel = rel.strip("/")
        for sh in self.shares.values():
            if sh["with"] == user and (rel == sh["mount"] or rel.startswith(sh["mount"] + "/")):
                return sh
        return None

    def mount_name(self, user: str, name: str) -> str:
        base = f"{self.shares_in}/" if self.shares_in else ""
        if self.shares_in and self.shares_in not in self.dirs_of(user, ""):
            self.dirs.add(f"{user}/{self.shares_in}")
        taken = set(self.dirs_of(user, self.shares_in))
        cand, i = name, 2
        while cand in taken:
            cand, i = f"{name} ({i})", i + 1
        return base + cand

    def dirs_of(self, user: str, rel: str) -> list[str]:
        return [n for n, _d in self.children(user, rel)]

    def is_dir(self, user: str, rel: str) -> bool:
        return self.resolve(user, rel) in self.dirs

    def used(self) -> int:
        return sum(len(v) for v in self.files.values())


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: State

    def log_message(self, *a):
        pass

    # -- plumbing
    def _send(self, status: int, body: bytes = b"", headers: dict | None = None, ctype: str = "text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _user(self) -> str | None:
        a = self.headers.get("Authorization") or ""
        if not a.startswith("Basic "):
            return None
        try:
            u, _, p = base64.b64decode(a[6:]).decode("utf-8").partition(":")
        except ValueError:
            return None
        return u if self.state.users.get(u) == p else None

    def _where(self, raw_path: str, user: str) -> tuple[str, str] | None:
        """(the base as the client sees it, the path below the user's root), or None when not a WebDAV path."""
        path = unquote(urlsplit(raw_path).path)
        if path.startswith(DAV):
            rest = path[len(DAV):]
            owner, _, rel = rest.partition("/")
            if owner != user:
                return ("forbidden", "")
            return DAV + owner + "/", rel
        if path.startswith(OLD_DAV):
            return OLD_DAV, path[len(OLD_DAV):]
        return None

    def _all(self):
        st = self.state
        self._body_cache = self._body()
        with st.lock:
            st.calls.append(f"{self.command} {unquote(urlsplit(self.path).path)}")
            if self.headers.get("Authorization"):
                st.auth_to.append(unquote(urlsplit(self.path).path))
            if st.maintenance:
                return self._send(503, b"Nextcloud is in maintenance mode")
            if self.command in st.fail:
                return self._send(st.fail[self.command], b"refused", dict(st.fail_headers))
            user = self._user()
            if user is None:
                return self._send(401, b"", {"WWW-Authenticate": 'Basic realm="Nextcloud"'})
            if urlsplit(self.path).path.startswith(OCS):
                return self._ocs(user)
            w = self._where(self.path, user)
            if w is None:
                return self._send(404, b"not here")
            if w[0] == "forbidden":
                return self._send(403, b"not your files")
            if st.redirect:
                return self._send(st.redirect[0], b"moved", {"Location": st.redirect[1]})
            base, rel = w
            sh = st.share_of(user, rel)   # (a share's rights: 1 read, 2 update, 4 create, 8 delete)
            if sh is not None:
                need = {"PUT": 2 | 4, "MKCOL": 4, "MOVE": 2 | 4, "DELETE": 8}.get(self.command, 0)
                if need and not sh["permissions"] & need:
                    return self._send(403, b"not allowed to write here")
            return getattr(self, "_dav_" + self.command.lower())(user, base, rel.rstrip("/"))

    do_GET = do_PUT = do_DELETE = do_POST = do_PROPFIND = do_MKCOL = do_MOVE = _all

    # -- WebDAV
    def _dav_propfind(self, user, base, rel):
        st = self.state
        real = st.resolve(user, rel)
        if real not in st.dirs and real not in st.files:
            return self._send(404, b"")
        entries = [(rel, real in st.dirs)]
        if real in st.dirs and self.headers.get("Depth", "infinity") == "1":
            entries += [((rel + "/" if rel else "") + n, d) for n, d in st.children(user, rel)]
        out = ['<?xml version="1.0"?>' + (st.doctype or "") + '<d:multistatus xmlns:d="DAV:">']
        hrefs = []
        for name, is_dir in entries:
            href = quote((st.href_base or base) + name + ("/" if is_dir and name else ""), safe="/@")
            hrefs.append((href, name, is_dir))
        hrefs += [(h, rel, False) for h in st.extra_hrefs]
        for href, name, is_dir in hrefs:
            r = st.resolve(user, name)
            size = len(st.files.get(r, b""))
            etag = f'"{st.etags.get(r, 0)}-{size}"'
            rt = "<d:collection/>" if is_dir else ""
            cl = "" if is_dir else f"<d:getcontentlength>{size}</d:getcontentlength>"
            lm = f"<d:getlastmodified>{formatdate(st.mtimes.get(r, time.time()), usegmt=True)}</d:getlastmodified>"
            out.append(f"<d:response><d:href>{href}</d:href><d:propstat><d:prop><d:resourcetype>{rt}</d:resourcetype>"
                       f"{cl}{'' if st.no_etag else f'<d:getetag>{etag}</d:getetag>'}{lm}</d:prop>"
                       "<d:status>HTTP/1.1 200 OK</d:status>"
                       "</d:propstat></d:response>")
        out.append("</d:multistatus>")
        return self._send(207, "".join(out).encode(), ctype="application/xml; charset=utf-8")

    def _dav_get(self, user, base, rel):
        real = self.state.resolve(user, rel)
        if real not in self.state.files:
            return self._send(404, b"")
        return self._send(200, self.state.files[real], {"ETag": f'"{self.state.etags[real]}"'},
                          "application/octet-stream")

    def _parent_ok(self, real: str) -> bool:
        return real.rpartition("/")[0] in self.state.dirs

    def _dav_put(self, user, base, rel):
        st = self.state
        real = st.resolve(user, rel)
        data = self._body_cache
        if not self._parent_ok(real):
            return self._send(409, b"parent missing")
        if real.rsplit("/", 1)[-1].endswith(".part"):
            return self._send(403, b"part files are not allowed")
        if st.quota is not None and st.used() - len(st.files.get(real, b"")) + len(data) > st.quota:
            return self._send(507, b"quota")
        st._n += 1
        st.files[real], st.etags[real] = data, st._n
        st.mtimes[real] = time.time()
        return self._send(201, b"", {"ETag": f'"{st._n}"'})

    def _dav_mkcol(self, user, base, rel):
        st = self.state
        real = st.resolve(user, rel)
        if real in st.dirs or real in st.files:
            return self._send(405, b"exists")
        if not self._parent_ok(real):
            return self._send(409, b"parent missing")
        st.dirs.add(real)
        return self._send(201, b"")

    def _dav_delete(self, user, base, rel):
        st = self.state
        real = st.resolve(user, rel)
        if real in st.files:
            del st.files[real]
            return self._send(204, b"")
        if real in st.dirs:
            st.dirs = {d for d in st.dirs if d != real and not d.startswith(real + "/")}
            for f in [f for f in st.files if f.startswith(real + "/")]:
                del st.files[f]
            return self._send(204, b"")
        return self._send(404, b"")

    def _dav_move(self, user, base, rel):
        st = self.state
        src = st.resolve(user, rel)
        w = self._where(self.headers.get("Destination") or "", user)
        if w is None or w[0] == "forbidden":
            return self._send(502, b"bad destination")
        dst = st.resolve(user, w[1].rstrip("/"))
        if src not in st.files:
            return self._send(404, b"")
        if not self._parent_ok(dst):
            return self._send(409, b"")
        there = dst in st.files
        if there and (self.headers.get("Overwrite") or "T") == "F":
            return self._send(412, b"")
        st.files[dst], st.etags[dst] = st.files.pop(src), st.etags.pop(src)
        st.mtimes[dst] = st.mtimes.pop(src, time.time())
        if st.move_then:   # (done, but the answer says otherwise: the client tries again)
            return self._send(st.move_then.pop(0), b"gateway problem")
        return self._send(204 if there else 201, b"")

    def _dav_post(self, user, base, rel):
        return self._send(405, b"")

    # -- OCS
    def _ocs_answer(self, status: int, code: int, data=None, message: str = ""):
        body = json.dumps({"ocs": {"meta": {"status": "ok" if code == 200 else "failure", "statuscode": code,
                                            "message": message}, "data": data or {}}}).encode()
        return self._send(status, body, ctype="application/json")

    def _ocs(self, user):
        st = self.state
        if not st.ocs:
            return self._send(404, b"<html>Not found</html>", ctype="text/html")
        if self.headers.get("OCS-APIRequest") != "true":
            return self._send(400, b"CSRF check failed")
        path = urlsplit(self.path).path
        if self.command == "POST" and path == OCS:
            form = {k: v[0] for k, v in parse_qs(self._body_cache.decode()).items()}
            folder = (form.get("path") or "").strip("/")
            with_user = form.get("shareWith") or ""
            if with_user not in st.users or with_user == user:
                return self._ocs_answer(404, 404, message="Please specify a valid user")
            real = st.resolve(user, folder)
            if real not in st.dirs or not real.startswith(user + "/"):
                return self._ocs_answer(404, 404, message="Wrong path, file/folder does not exist")
            if any(sh["owner"] == user and sh["path"] == real[len(user) + 1:] and sh["with"] == with_user
                   for sh in st.shares.values()):
                return self._ocs_answer(403, 403, message=f"Path is already shared with {with_user}")
            st._n += 1
            sid = str(st._n)
            st.shares[sid] = {"owner": user, "path": real[len(user) + 1:], "with": with_user,
                              "permissions": int(form.get("permissions") or 31),
                              "mount": st.mount_name(with_user, real.rsplit("/", 1)[-1])}
            return self._ocs_answer(200, 200, {"id": int(sid), "share_type": 0, "share_with": with_user,
                                               "share_with_displayname": st.names.get(with_user, with_user)})
        if self.command == "GET" and path == OCS:
            q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
            real = st.resolve(user, (q.get("path") or "").strip("/"))
            if real not in st.dirs:
                return self._ocs_answer(404, 404, message="Wrong path, file/folder does not exist")
            found = [{"id": int(i), "share_type": 0, "share_with": sh["with"], "path": "/" + sh["path"],
                      "share_with_displayname": st.names.get(sh["with"], sh["with"]),
                      "permissions": sh["permissions"]} for i, sh in st.shares.items()
                     if sh["owner"] == user and f"{user}/{sh['path']}" == real]
            return self._ocs_answer(200, 200, found)
        if self.command == "DELETE" and path.startswith(OCS + "/"):
            sid = path[len(OCS) + 1:]
            sh = st.shares.get(sid)
            if sh is None or sh["owner"] != user:
                return self._ocs_answer(404, 404, message="Wrong share ID, share does not exist")
            del st.shares[sid]
            return self._ocs_answer(200, 200)
        return self._ocs_answer(400, 400, message="unknown call")


def start(users: dict[str, str]):
    """Start the stand-in on a free port: `(server, url)`; `server.state` holds the knobs. Stop with `stop`."""
    state = State(users)
    handler = type("BoundHandler", (Handler,), {"state": state})
    srv = QuickServer(("127.0.0.1", 0), handler)
    srv.state = state
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def stop(srv) -> None:
    srv.shutdown()
    srv.server_close()

"""Your institution's drive over WebDAV as the team's storage space (14 November 2026, roadmap L6): SURFdrive, SURF
Research Drive, a university's Nextcloud or ownCloud. The per-service part, as `b2.py` and `r2.py` are for theirs.

WebDAV has no keys ENLENS could make for others. So each person uses their own account at the drive, with an **app
password** (made in the drive's settings, never their main password), and the owner shares the project's folder with
each colleague. Where the drive offers the OCS Share API (Nextcloud and ownCloud do), ENLENS shares the folder with a
colleague's user name when inviting and stops sharing it when they are removed; elsewhere, or when that fails, the
owner does it in the drive's website. As on Cloudflare R2, the drive cannot limit a colleague to their own part of the
folder: the signatures keep each part its writer's (`seal.py`).

Addresses (read 14 November 2026):
- SURFdrive: `https://surfdrive.surf.nl/files/remote.php/nonshib-webdav/`, with the user name and a password made under
  Settings → Security → WebDAV passwords (SURF's wiki, "Accessing files via WebDAV",
  https://wiki.surfnet.nl/display/SURFdrive/Accessing+files+via+WebDAV; the same address in Utrecht University's
  rclone guide, https://utrechtuniversity.github.io/vre-docs/docs/manuals/rclone-config.html).
- SURF Research Drive: each institution has its own address, such as `https://<institution>.data.surf.nl/remote.php/
  dav/files/<user>/` or `…/remote.php/webdav/`; the WebDAV user name and password are made under Settings → Security
  (SURF's wiki, "Getting your WebDAV credentials", https://wiki.surfnet.nl/display/RDRIVE/How+to+get+your+WebDAV+credentials).
- Nextcloud: `https://<host>/remote.php/dav/files/<user>/`, shown under Files → Files settings → WebDAV; an app
  password under Personal settings → Security → Devices & sessions → Create new app password
  (https://docs.nextcloud.com/server/latest/user_manual/en/files/access_webdav.html,
  https://docs.nextcloud.com/server/latest/user_manual/en/session_management.html).
- The OCS Share API: POST `<base>/ocs/v2.php/apps/files_sharing/api/v1/shares` with `path` (from the user's root),
  `shareType` 0 (a user), `shareWith`, `permissions` (1 read + 2 update + 4 create + 8 delete = 15; no resharing);
  DELETE `…/shares/<id>`; every call with the header `OCS-APIRequest: true`; `?format=json` answers in JSON with
  `ocs.meta.statuscode` 200 (v2) and the share's `ocs.data.id`
  (https://docs.nextcloud.com/server/latest/developer_manual/client_apis/OCS/ocs-share-api.html; ownCloud's is the
  same, https://doc.owncloud.com/server/next/developer_manual/core/apis/ocs-share-api.html).
- A folder shared with a user lands in their own files under its name (renamed when they have one of that name
  already), or inside the folder an administrator chose for shares (often `Shared`).
"""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import quote, unquote, urlencode, urlsplit

from . import _web
from .storage import BAD_ANSWER, DENIED, NOT_FOUND, StorageProblem, WebDAVStorage, is_loopback

SURFDRIVE = "https://surfdrive.surf.nl/files/remote.php/nonshib-webdav/"
NEXTCLOUD_FORM = "https://<host>/remote.php/dav/files/<user>/"
SHARE_PERMISSIONS = 15                   # read, update, create, delete; no resharing
_SHARE_PATH = "/ocs/v2.php/apps/files_sharing/api/v1/shares"
_FOLDER_SAFE = re.compile(r"[^\w .,()&+-]+", re.UNICODE)


class WebDAVProblem(Exception):
    """What went wrong at the drive, in words for a researcher; `kind` as StorageProblem's or "no_share_api"."""

    def __init__(self, message: str, kind: str = BAD_ANSWER):
        super().__init__(message)
        self.kind = kind


def normalise(address: str, user: str = "") -> str:
    """The drive's WebDAV address as ENLENS keeps it: https:// added when it is missing, `<user>` filled in, one final
    `/`. Raises WebDAVProblem for what cannot be one."""
    a = str(address or "").strip()
    if not a:
        raise WebDAVProblem("Enter the drive's WebDAV address.", "input")
    if "://" not in a:
        a = "https://" + a
    if user:
        a = a.replace("<user>", quote(user, safe="@")).replace("%3Cuser%3E", quote(user, safe="@"))
    parts = urlsplit(a)
    if parts.scheme not in ("https", "http") or not parts.hostname or "<" in a:
        raise WebDAVProblem("This does not look like a WebDAV address. It starts with https:// and is shown in the "
                            "drive's settings.", "input")
    if parts.scheme == "http" and not is_loopback(parts.hostname):
        raise WebDAVProblem("ENLENS sends a password only over a secure connection: use the address that starts with "
                            "https://.", "input")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}/"


def member_address(owner_address: str, user: str) -> str:
    """The address a colleague most likely uses at the same drive: Nextcloud's `…/dav/files/<owner>/` with their own
    user name; SURFdrive's and ownCloud's `…/webdav/` addresses are the same for everyone."""
    m = re.match(r"(.*/remote\.php/dav/files/)[^/]+/?$", owner_address)
    if m and user:
        return f"{m.group(1)}{quote(user, safe='@')}/"
    return owner_address


def in_eu(address: str) -> bool | None:
    """True for SURF's drives (in the Netherlands); None when ENLENS cannot tell."""
    h = (urlsplit(address).hostname or "").lower()
    return True if h.endswith(("surf.nl", "surfsara.nl")) else None


def folder_url(address: str, folder: str) -> str:
    return address.rstrip("/") + "/" + quote(folder.strip("/"), safe="/@")


def storage(address: str, user: str, password: str, folder: str = "", prefix: str = "") -> WebDAVStorage:
    try:
        return WebDAVStorage(folder_url(address, folder) if folder else address, user, password, prefix=prefix)
    except StorageProblem as e:
        raise WebDAVProblem(str(e), e.kind) from e


def folder_name(project: str) -> str:
    """A readable folder name for the project in the drive: `ENLENS – <project>`, without characters drives refuse."""
    clean = _FOLDER_SAFE.sub(" ", str(project or "")).strip(" .")[:60].strip() or "project"
    return f"ENLENS - {clean}"


def check(address: str, user: str, password: str) -> None:
    """The drive answers this address with this user name and app password (one PROPFIND of its root)."""
    try:
        if storage(address, user, password).propfind("") is None:
            raise WebDAVProblem("The drive has no folder at this address. Copy the WebDAV address from the drive's "
                                "settings.", NOT_FOUND)
    except StorageProblem as e:
        if e.kind == DENIED:
            raise WebDAVProblem("The drive refused this user name and app password. Check the user name the drive's "
                                "settings show (it is not always your e-mail address), and make a new app password if "
                                "needed.", DENIED) from e
        raise WebDAVProblem(str(e), e.kind) from e


def make_folder(address: str, user: str, password: str, project: str) -> str:
    """A new folder for the project at the root of the owner's drive; returns its name (`ENLENS - X`, or `… 2` when
    that is taken)."""
    store = storage(address, user, password)
    try:
        there = {n for n, _d, _s, _e in store.propfind("") or []}
        base = folder_name(project)
        name = next(n for n in [base] + [f"{base} {i}" for i in range(2, 1000)] if n not in there)
        store.mkdirs(name)
    except StorageProblem as e:
        raise WebDAVProblem(f"ENLENS could not make a folder in the drive: {e}", e.kind) from e
    return name


def find_shared(address: str, user: str, password: str, folder: str, space_id: str) -> tuple[str | None, list[str]]:
    """Where the project's folder is in a colleague's drive: (its path from their root, or None; the folders at their
    root, to choose from when it was not found). A folder counts when it holds the team's list of members for this
    space. Looks under the folder's own name first, then in every folder at the root and in `Shared`."""
    store = storage(address, user, password)
    marker = f"enlens/{space_id}/space/roster.json"

    def holds(path: str) -> bool:
        try:
            storage(address, user, password, folder=path).get(marker, max_size=16 * 1024 ** 2)
            return True
        except StorageProblem as e:
            if e.kind in (NOT_FOUND, DENIED):
                return False
            raise

    try:
        top = [n for n, d, _s, _e in store.propfind("") or [] if d and "/" not in n]
        if folder in top and holds(folder):
            return folder, top
        candidates = [n for n in top if n != folder]
        for shared in ("Shared", "Gedeeld", "Shared with me"):
            if shared in top:
                candidates += [n for n, d, _s, _e in store.propfind(shared + "/") or [] if d]
        for c in sorted(candidates, key=lambda n: (not n.startswith(folder.split(" (")[0]), n))[:200]:
            if holds(c):
                return c, top
    except StorageProblem as e:
        raise WebDAVProblem(f"ENLENS could not look in your drive: {e}", e.kind) from e
    return None, top


# ---------------------------------------------------------------------------------------------
# the OCS Share API (Nextcloud, ownCloud)
# ---------------------------------------------------------------------------------------------
def _ocs_base(address: str) -> str:
    """The drive's own address (before `/remote.php/`), where its OCS interface is."""
    p = urlsplit(address)
    path = p.path.split("/remote.php/")[0] if "/remote.php/" in p.path else ""
    return f"{p.scheme}://{p.netloc}{path.rstrip('/')}"


def _user_root_path(address: str, folder: str) -> str:
    """The folder's path as the OCS Share API names it: from the user's own root (which the WebDAV address is)."""
    return "/" + unquote(folder).strip("/")


def _ocs(method: str, url: str, user: str, password: str, form: dict | None = None) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {token}", "OCS-APIRequest": "true", "Accept": "application/json"}
    body = None
    if form is not None:
        body = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        r = _web.send_retrying(lambda: (method, url, headers, body), 30.0, 1024 ** 2)
    except _web.NetError as e:
        raise WebDAVProblem(f"ENLENS could not reach the drive ({e.reason}).", "unreachable") from e
    try:
        doc = json.loads(r.body or b"{}")
        meta = (doc.get("ocs") or {}).get("meta") or {}
    except (ValueError, AttributeError):
        doc, meta = {}, {}
    if r.status in (401,):
        raise WebDAVProblem("The drive refused the user name and app password.", DENIED)
    if r.status == 404 and not meta:
        raise WebDAVProblem("This drive does not let ENLENS share folders (it has no sharing interface ENLENS knows).",
                            "no_share_api")
    code = meta.get("statuscode")
    if r.status >= 300 or code not in (100, 200):
        said = str(meta.get("message") or "").strip()[:200]
        raise WebDAVProblem(f"The drive did not share the folder{': ' + said if said else ''} (HTTP {r.status}).",
                            NOT_FOUND if r.status == 404 or code == 404 else BAD_ANSWER)
    return doc["ocs"].get("data") or {}


def share(address: str, user: str, password: str, folder: str, with_user: str) -> str:
    """Share the project's folder with a colleague's user name at the same drive; returns the share's id."""
    data = _ocs("POST", _ocs_base(address) + _SHARE_PATH + "?format=json", user, password,
                {"path": _user_root_path(address, folder), "shareType": "0", "shareWith": with_user.strip(),
                 "permissions": str(SHARE_PERMISSIONS)})
    sid = data.get("id") if isinstance(data, dict) else None
    if sid is None:
        raise WebDAVProblem("The drive's answer to sharing the folder could not be understood.", BAD_ANSWER)
    return str(sid)


def unshare(address: str, user: str, password: str, share_id: str) -> None:
    """Stop sharing (a share that is not there any more is no problem)."""
    try:
        _ocs("DELETE", _ocs_base(address) + _SHARE_PATH + f"/{quote(str(share_id), safe='')}?format=json", user,
             password)
    except WebDAVProblem as e:
        if e.kind != NOT_FOUND:
            raise

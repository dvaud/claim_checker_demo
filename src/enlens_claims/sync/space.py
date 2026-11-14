"""A storage space of the team's own (0.18.0rc2, roadmap L6): the shared folder's work, through an online storage
service (Backblaze B2, Cloudflare R2), or a folder in the institution's drive over WebDAV (SURFdrive, SURF Research
Drive, a Nextcloud; 14 November 2026), sealed.

The team rents a private storage space (an S3 *bucket*), free at a team's size. ENLENS puts the team's shared work
there and fetches colleagues' work from it by itself: nobody installs a sync app or looks for a folder. The owner sets
it up once (`setup_b2`, `setup_r2`, `setup_webdav`); colleagues join from an invite link (`invite`, `join`).

**A drive over WebDAV** (`webdav.py`) has no keys ENLENS could make for others: each person uses their own account and
app password (in their keychain, `access`), the owner shares the project's folder with each colleague (by ENLENS
through the drive's sharing interface when it has one, otherwise in the drive's website), and the invite carries the
drive and the folder, not keys. As on Cloudflare, the drive cannot keep a colleague to their own part: the signatures
do. A hand-over to a new owner never passes the old owner's app password on.

**How a round works.** This copy keeps a copy of the space on this computer (the *mirror*, `<ENLENS folder>/spaces/
<space id>/`), laid out exactly as a shared folder (`folder.py`). A round (`sync_now`):
1. brings what changed in the space into the mirror (`_pull`): the team's roster and keys, then each colleague's files,
   each one opened and checked (`seal.py`): written by the member whose part it is in, for that very place, with a key
   this copy holds. A file that fails is *set aside*: never in the mirror, listed in the Team tab;
2. runs the shared folder's round on the mirror (`folder._sync_now`), with every rule of a merge, of roles and of
   privacy that the folder has;
3. sends what this copy wrote in its own part of the mirror to the space (`_push`), sealed, `head.json` last.
So the storage only ever holds sealed files, and the folder's rules are not written twice.

**In the space** (names below its prefix `enlens/<space id>/`):

    space/roster.json      who is in the team: each part's member and public keys, the keeper (signed, `_roster`)
    space/keys.json        the project's key of each epoch, sealed to each member (signed by the keeper)
    space/project.json     the folder's project.json, sealed by the keeper
    space/keeper.json      the keeper's keys, sealed to the next keeper (when the owner changed)
    space/moved.json       where the team moved to, each member's new keys sealed to them (`move`)
    parts/<part>/m/...     a member's person.json, head.json, read.json, waiting.json, and key.json (their public keys)
    parts/<part>/b/NNNNNN  their bundles
    parts/<part>/d/<hash>  readings of documents, f/<hash> original files, under a keyed hash of their names

Each member writes only in their own part: on Backblaze the storage itself enforces it (each colleague's key is
limited to their part); everywhere (Cloudflare, a WebDAV drive) the signatures do. The *keeper* (the owner who set
the space up, or to whom the owner's role passed, roadmap L2) holds the keys that make keys (`keychain`, never in a
project or the space), binds each new member to their part (`_bind_joins`), removes members (`remove_member`: their
keys go, and the project's key is replaced for those who stay), and moves the team (`move`).

Secrets live in the system's keychain (`keychain.py`): this copy's own keys in each space, the project's keys, the
storage keys. The project's `config.json` (`shared_space`) says where the space is, never a key.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
import uuid
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .. import __version__, keychain, people
from ..store import Workspace, now
from . import folder, seal
from .seal import Identity, SealProblem
from .storage import NOT_FOUND, Storage, StorageProblem

CONFIG = "shared_space"                 # config.json: where this project's storage space is (no keys)
LINK = "enlens://join#"                 # an invite link: the rest, after the #, is never sent to any server
MIN_EVERY = 10 * 60                     # a space is looked at every 10 minutes at most (calls cost; speed is no goal)
FOLLOW_SEARCH_EVERY = 30 * 60           # a copy waiting to follow a move to a drive searches it whole this seldom
_PART = re.compile(r"m[0-9a-f]{12}")
_SPACE = re.compile(r"[0-9a-f]{16}")
_M_FILES = ("person.json", "head.json", "read.json", "waiting.json")
# the most of a file read from the space, by kind (a colleague's file never fills this computer's memory)
_CAP = {"m": 64 * 1024 ** 2, "b": 1024 ** 3, "d": 320 * 1024 ** 2, "f": seal.MAX_SEALED + 64 * 1024,
        "space": 16 * 1024 ** 2}

Progress = Callable[[str, str, dict], None]


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_LOCK = threading.Lock()


@contextmanager
def _locked(ws: Workspace):
    """One thing at a time per project's space: a round, an invite, removing a colleague, a move (each reads and
    writes the roster, the keys and the project's description)."""
    with _LOCKS_LOCK:
        lock = _LOCKS.setdefault(str(Path(ws.root).resolve()), threading.RLock())
    with lock:
        yield


class SpaceProblem(ValueError):
    """Why the storage space cannot be used now, in words for a researcher; `extra`: what the Team tab needs to go on
    (the folders to choose from when a shared folder was not found)."""

    def __init__(self, message: str, kind: str = "space", extra: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.extra = extra or {}

SERVICES = ("dir", "b2", "r2", "webdav")


# ---------------------------------------------------------------------------------------------
# where a space is: the project's config, the keychain, the mirror
# ---------------------------------------------------------------------------------------------
def configured(ws: Workspace) -> dict | None:
    v = ws.config.get(CONFIG)
    return v if isinstance(v, dict) and isinstance(v.get("id"), str) and _SPACE.fullmatch(v["id"]) else None


def mirror_of(ws: Workspace) -> Path | None:
    """The copy of the space on this computer, which the shared folder's rules work on (`folder.chosen`)."""
    d = configured(ws)
    if d is None:
        return None
    from ..home import home

    p = home() / "spaces" / d["id"]
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save(ws: Workspace, desc: dict | None) -> None:
    folder._set_config(ws, **{CONFIG: desc})


def _secret_name(space_id: str, what: str) -> str:
    return f"space:{space_id}:{what}"


def _get_secret(space_id: str, what: str) -> Any:
    raw = keychain.get(_secret_name(space_id, what))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _put_secret(space_id: str, what: str, value: Any) -> None:
    keychain.put(_secret_name(space_id, what), json.dumps(value))


def _forget_secrets(space_id: str, parts: list[str] = ()) -> None:
    for what in ("me", "keys", "access", "keeper", *[f"invite:{p}" for p in parts]):
        keychain.delete(_secret_name(space_id, what))


def _keys(space_id: str) -> tuple[bytes, dict[int, bytes]]:
    k = _get_secret(space_id, "keys") or {}
    try:
        return seal.unb64(k["names"]), {int(e): seal.unb64(v) for e, v in (k.get("epochs") or {}).items()}
    except (KeyError, ValueError, TypeError) as e:
        raise SpaceProblem("The keys of this project's storage space are not on this computer any more (the keychain "
                           "was cleared, or the project was copied from another computer). Ask the owner for a new "
                           "invite link.", "no_keys") from e


def _put_keys(space_id: str, names: bytes, epochs: dict[int, bytes]) -> None:
    _put_secret(space_id, "keys", {"names": seal.b64(names), "epochs": {str(e): seal.b64(k) for e, k in epochs.items()}})


def storage_for(desc: dict, access: dict | None) -> Storage:
    """The storage of a space, opened with this copy's keys (`access`: the S3 keys; a drive's user name and app
    password; none for a folder)."""
    access = access or {}
    if desc.get("service") == "dir":
        from .storage import DirStorage

        return DirStorage(Path(desc["dir"]) / desc["prefix"])
    if desc.get("service") == "webdav":
        from . import webdav
        from .storage import WebDAVStorage

        return WebDAVStorage(webdav.folder_url(desc["endpoint"], desc["folder"]), access.get("user") or "",
                             access.get("password") or "", prefix=desc["prefix"])
    from .storage import S3Storage

    return S3Storage(desc["endpoint"], desc.get("region") or "auto", desc["bucket"], access.get("key_id") or "",
                     access.get("secret") or "", prefix=desc["prefix"], read_key_id=access.get("read_key_id"),
                     read_secret=access.get("read_secret"))


def _new_part() -> str:
    return "m" + uuid.uuid4().hex[:12]


def _reset_written(ws: Workspace) -> None:
    """A new place to write to: this copy writes everything it shares there once more (the folder's snapshot), as
    when a shared folder is chosen (`folder.set_folder`)."""
    with ws.connect() as cx:
        cx.execute("UPDATE sync_written SET fp='' WHERE kind='head' AND key=''")


def _note(ws: Workspace, kind: str, text: str) -> None:
    folder._note(ws, kind, text)


# ---------------------------------------------------------------------------------------------
# the roster: who is in the team, signed by the keeper; trust moves only along the keepers' hand-overs
# ---------------------------------------------------------------------------------------------
def _keeper_cert(ident: Identity, space_id: str, n: int, to_part: str, to_sign: str, by: str, seq: int) -> dict:
    """The keeper `by` hands the space to `to_part` in the roster numbered `seq` (the n-th hand-over)."""
    body = {"space": space_id, "n": n, "part": to_part, "sign": to_sign, "by": by, "seq": seq}
    return {**body, "sig": seal.sign_bytes(ident, seal.canonical(body))}


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _history(desc: dict) -> list[list]:
    """The keepers this copy trusts, in order: [[part, public key, the roster number from which they kept the space]].
    Kept in the project's description (not the copy of the space, which may be lost), from the invite or the set-up."""
    h = desc.get("keepers")
    if isinstance(h, list) and h and all(isinstance(x, list) and len(x) == 3 for x in h):
        return [list(x) for x in h]
    return [[desc["keeper_part"], desc["keeper_sign"], 0]]


def _keepers_chain(desc: dict, roster: dict) -> list[list] | None:
    """The keepers this copy trusts, extended along the roster's hand-overs it has not seen yet, or None when the chain
    breaks (a hand-over not signed by the keeper before it, or not readable)."""
    chain = _history(desc)
    seen_n = _as_int(desc.get("keeper_n")) or 0
    certs = [c for c in roster.get("keepers") or [] if isinstance(c, dict)]
    if any(_as_int(c.get("n")) is None for c in certs):
        return None
    for c in sorted(certs, key=lambda c: _as_int(c.get("n"))):
        if _as_int(c.get("n")) <= seen_n:
            continue
        body = {k: c.get(k) for k in ("space", "n", "part", "sign", "by", "seq")}
        part, sign = chain[-1][0], chain[-1][1]
        if body["space"] != desc["id"] or body["by"] != part or _as_int(body["seq"]) is None or not \
                isinstance(body["part"], str) or not isinstance(body["sign"], str) or \
                not seal.verify_bytes(sign, seal.canonical(body), str(c.get("sig") or "")):
            return None
        chain.append([body["part"], body["sign"], _as_int(body["seq"])])
        seen_n = _as_int(c["n"])
    return chain


def _roster_trusted(desc: dict, obj: dict, by: str, sig: str) -> list[list] | None:
    """The keepers' chain, when the roster is signed by the keeper of its time: the keeper who kept the space at its
    number, or, in the very roster that hands the space over (its number is the hand-over's), the keeper who handed it
    over. A keeper who handed the space over signs no later roster."""
    chain = _keepers_chain(desc, obj)
    seq = _as_int(obj.get("seq"))
    if chain is None or seq is None:
        return None
    i = max(j for j, k in enumerate(chain) if (k[2] or 0) <= seq) if any((k[2] or 0) <= seq for k in chain) else 0
    signer = chain[i - 1] if i > 0 and chain[i][2] == seq else chain[i]
    if by == signer[0] and seal.check_signed(obj, sig, signer[1]):
        return chain
    return None


def _signed_roster(ctx: "_Ctx", roster: dict) -> bytes:
    return seal.signed_json(ctx.ident, {**roster, "space": ctx.desc["id"]}, ctx.desc["part"])


# ---------------------------------------------------------------------------------------------
# one round's context
# ---------------------------------------------------------------------------------------------
class _Ctx:
    def __init__(self, ws: Workspace, desc: dict):
        self.ws, self.desc = ws, dict(desc)
        self.id = desc["id"]
        self.me = people.me()
        raw = keychain.get(_secret_name(self.id, "me"))
        if raw is None:
            raise SpaceProblem("This copy's own keys for the storage space are not on this computer any more. Ask the "
                               "owner for a new invite link.", "no_keys")
        self.ident = Identity.load(raw)
        self.names, self.epochs = _keys(self.id)
        self.access = _get_secret(self.id, "access") or {}
        self.store = storage_for(desc, self.access)
        self.base = mirror_of(ws)
        self.team = self.base / folder.team_name(ws)
        self.state_path = self.base / ".space-state.json"
        try:
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.state = {}
        for k in ("remote", "pushed", "aside"):
            self.state.setdefault(k, {})
        self.problems: list[dict] = []
        self.changed_desc = False

    @property
    def roster(self) -> dict:
        return self.state.get("roster") or {}

    @property
    def epoch(self) -> int:
        return max(self.epochs)

    def save(self) -> None:
        import time

        part = self.state_path.with_name(self.state_path.name + ".part")
        part.write_text(json.dumps(self.state), encoding="utf-8")
        for i in range(20):   # (Windows: a reader that has the file open makes the replace wait a moment)
            try:
                os.replace(part, self.state_path)
                break
            except PermissionError:
                if i == 19:
                    raise
                time.sleep(0.05)
        if self.changed_desc:
            _save(self.ws, self.desc)

    def problem(self, kind: str, message: str, person: dict | None = None) -> None:
        self.problems.append({"kind": kind, "person": person, "message": message, "seq": None})

    def set_aside(self, name: str, etag: str, part: str, why: str, message: str) -> None:
        had = self.state["aside"].get(name)
        self.state["aside"][name] = {"etag": etag, "part": part, "why": why, "message": message,
                                     "at": (had or {}).get("at") or now()}

    def sealed(self, data: bytes, path: str) -> bytes:
        return seal.seal(data, path=path, by=self.desc["part"], epoch=self.epoch, key=self.epochs[self.epoch],
                         ident=self.ident)

    @property
    def keeper(self) -> bool:
        return self.desc.get("keeper_part") == self.desc.get("part")


def _start_space(ws: Workspace, desc: dict, access: dict, keeper_secret: dict | None,
                 ident: Identity | None = None) -> dict:
    """A new space, set up by this copy, which becomes its keeper: its keys, the first roster and keys, a test file
    written, read back and removed. `desc` says where the space is (service, endpoint, region, bucket, prefix).
    Returns the description kept in `config.json`. `ident`: this copy's keys, when it moves the team (colleagues know
    it by them)."""
    ident = ident or Identity.new()
    names, k1 = seal.new_key(), seal.new_key()
    part = _new_part()
    desc = {**desc, "part": part, "keeper_part": part, "keeper_sign": ident.public()["sign"], "keeper_n": 0,
            "keepers": [[part, ident.public()["sign"], 0]],
            "roster_seq": 1, "joined_at": now(), "invites": [], "access_ids": {}}
    store = storage_for(desc, access)
    probe = f"space/test-{uuid.uuid4().hex[:8]}"
    try:
        store.put(probe, b"ENLENS")
        if store.get(probe) != b"ENLENS":
            raise SpaceProblem("The storage space gave back something else than ENLENS wrote. Nothing was set up.",
                               "bad_answer")
        store.delete(probe)
    except StorageProblem as e:
        raise SpaceProblem(f"ENLENS could not write a test file in the storage space: {e}", e.kind) from e
    roster = {"v": 1, "seq": 1, "epoch": 1, "keepers": [],
              "members": {part: {"person": people.me(), **ident.public(), "since": now(), "removed": None}}}
    store.put("space/roster.json", seal.signed_json(ident, {**roster, "space": desc["id"]}, part))
    sealed = {"1": {part: seal.seal_key(ident.public()["box"], names + k1, f"{desc['id']} epoch 1 part {part}")}}
    store.put("space/keys.json", seal.signed_json(ident, {"space": desc["id"], "epochs": sealed}, part))
    keychain.put(_secret_name(desc["id"], "me"), ident.dump())
    _put_keys(desc["id"], names, {1: k1})
    _put_secret(desc["id"], "access", access)
    if keeper_secret is not None:
        _put_secret(desc["id"], "keeper", keeper_secret)
    return desc


def _connect(ws: Workspace, desc: dict, note: str) -> None:
    """Use this space for the project from now on (the shared folder, if any, is left: the space takes its place)."""
    folder._set_config(ws, **{folder.FOLDER: None, CONFIG: desc})
    _reset_written(ws)
    _note(ws, "space-chosen", note)


def _setup_dir_unlocked(ws: Workspace, path: str | os.PathLike, ident: Identity | None = None) -> dict:
    """A space in a folder on this computer (tests, and trying the set-up without an account): the same sealed
    layout. Returns `status`."""
    desc = {"id": uuid.uuid4().hex[:16], "service": "dir", "dir": str(Path(path).resolve()), "region": None,
            "bucket": None, "endpoint": None}
    desc["prefix"] = f"enlens/{desc['id']}"
    Path(desc["dir"], desc["prefix"]).mkdir(parents=True, exist_ok=True)
    desc = _start_space(ws, desc, {}, None, ident)
    _connect(ws, desc, f"Set up a storage space in the folder {desc['dir']} for working together.")
    return status(ws)


# ---------------------------------------------------------------------------------------------
# the owner's set-up at a service
# ---------------------------------------------------------------------------------------------
def _setup_b2_unlocked(ws: Workspace, key_id: str, app_key: str, progress: Progress | None = None,
                       ident: Identity | None = None) -> dict:
    """Backblaze B2 (roadmap L6a): the owner pasted a master application key. ENLENS checks where the data is, makes a
    key of its own with only the rights it needs (buckets, keys and files: never billing), keeps it in the keychain and
    forgets the master key, makes a private bucket that keeps only the latest version of each file, and writes, reads
    and removes a test file. Returns `status` with "warnings" (not in the EU; the master key kept because a key of
    ENLENS's own could not make keys)."""
    from . import b2

    say = progress or (lambda *_a: None)
    key_id, app_key = (key_id or "").strip(), (app_key or "").strip()
    if not key_id or not app_key:
        raise SpaceProblem("Paste both the keyID and the applicationKey that Backblaze showed.", "input")
    warnings: list[str] = []
    say("check", "Checking the key with Backblaze", {})
    master = _b2(lambda: b2.authorize(key_id, app_key))
    if not b2.in_eu(master):
        warnings.append(f"Your storage is in {master.region}, not in the EU. If your institution needs the data in "
                        "the EU, make a new Backblaze account and choose EU Central when you sign up.")
    say("key", "Making a key of ENLENS's own", {})
    own_id, own_secret = _b2(lambda: b2.create_key(master, f"ENLENS {uuid.uuid4().hex[:6]}", b2.OWN_KEY_CAPS))
    own = _b2(lambda: b2.authorize(own_id, own_secret))
    keeper = {"service": "b2", "key_id": own_id, "app_key": own_secret}
    try:  # can ENLENS's own key make keys? (Backblaze's documents do not say: try one, and remove it)
        tid, _ts = b2.create_key(own, "ENLENS test", b2.MEMBER_READ_CAPS)
        b2.delete_key(own, tid)
    except Exception:  # noqa: BLE001 - any refusal: keep the master key instead
        keeper = {"service": "b2", "key_id": key_id, "app_key": app_key}
        own = master
        warnings.append("Backblaze did not let a key of ENLENS's own make keys for your colleagues, so ENLENS keeps "
                        "the master key you pasted, in this computer's keychain only. Do not generate a new master key "
                        "while your team uses this storage space.")
    say("bucket", "Making a private storage space", {})
    name = b2.random_bucket_name()
    bucket_id = _b2(lambda: b2.create_bucket(own, name))
    sid = uuid.uuid4().hex[:16]
    desc = {"id": sid, "service": "b2", "endpoint": own.s3_url, "region": own.region, "bucket": name,
            "bucket_id": bucket_id, "prefix": f"enlens/{sid}/", "in_eu": b2.in_eu(own)}
    say("test", "Writing a test file", {})
    desc = _start_space(ws, desc, {"key_id": keeper["key_id"], "secret": keeper["app_key"]}, keeper, ident)
    _connect(ws, desc, f"Set up a storage space at Backblaze (bucket {name}, {own.region}) for working together.")
    out = status(ws)
    out["warnings"] = warnings
    return out


def _b2(call):
    from . import b2

    try:
        return call()
    except b2.B2Problem as e:
        raise SpaceProblem(str(e), getattr(e, "kind", "b2")) from e
    except StorageProblem as e:
        raise SpaceProblem(str(e), e.kind) from e


def _setup_r2_unlocked(ws: Workspace, token: str, account_id: str | None = None, progress: Progress | None = None,
                       ident: Identity | None = None) -> dict:
    """Cloudflare R2 (roadmap L6b): the owner pasted an API token made from ENLENS's link. ENLENS checks it, makes a
    bucket in Cloudflare's EU jurisdiction, and tests it. The token is kept in the keychain: it makes a token for each
    colleague, limited to the bucket. Returns `status` (with "accounts" to choose from when the token reaches several
    and none was named)."""
    from . import r2

    say = progress or (lambda *_a: None)
    token = (token or "").strip()
    if not token:
        raise SpaceProblem("Paste the token Cloudflare showed after Create Token.", "input")
    say("check", "Checking the token with Cloudflare", {})
    info = _r2(lambda: r2.verify(token))
    accts = _r2(lambda: r2.accounts(token))
    if account_id is None:
        if len(accts) != 1:
            if not accts:
                raise SpaceProblem("The token reaches no Cloudflare account. Make it again from ENLENS's link.",
                                   "no_account")
            out = status(ws)
            out["accounts"] = accts
            return out
        account_id = accts[0]["id"]
    say("bucket", "Making a private storage space in the EU", {})
    name = "enlens-" + uuid.uuid4().hex[:12]
    _r2(lambda: r2.create_bucket(token, account_id, name, eu=True))
    key_id, secret = r2.s3_credentials(info["id"], token)
    sid = uuid.uuid4().hex[:16]
    desc = {"id": sid, "service": "r2", "endpoint": r2.endpoint(account_id, eu=True), "region": "auto",
            "bucket": name, "account_id": account_id, "prefix": f"enlens/{sid}/", "in_eu": True}
    say("test", "Writing a test file", {})
    desc = _start_space(ws, desc, {"key_id": key_id, "secret": secret},
                        {"service": "r2", "token": token, "token_id": info["id"], "account_id": account_id}, ident)
    _connect(ws, desc, f"Set up a storage space at Cloudflare (bucket {name}, EU) for working together.")
    out = status(ws)
    out["warnings"] = []
    return out


def _r2(call):
    from . import r2

    try:
        return call()
    except r2.R2Problem as e:
        raise SpaceProblem(str(e), getattr(e, "kind", "r2")) from e
    except StorageProblem as e:
        raise SpaceProblem(str(e), e.kind) from e


def _setup_webdav_unlocked(ws: Workspace, address: str, user: str, password: str, progress: Progress | None = None,
                           ident: Identity | None = None) -> dict:
    """Your institution's drive over WebDAV (SURFdrive, SURF Research Drive, a Nextcloud): the owner gave the drive's
    WebDAV address, their user name and an app password. ENLENS checks them, makes a folder for the project at the
    root of the owner's drive (`ENLENS - <project>`), and writes, reads back and removes a test file in it. The app
    password is kept in this computer's keychain; it is this copy's own access, never handed to anyone. Returns
    `status` with "warnings" (none so far)."""
    from . import webdav

    say = progress or (lambda *_a: None)
    user, password = (user or "").strip(), (password or "").strip()
    if not user or not password:
        raise SpaceProblem("Enter your user name at the drive and an app password.", "input")
    address = _dav(lambda: webdav.normalise(address, user))
    say("check", "Checking the user name and app password with the drive", {})
    _dav(lambda: webdav.check(address, user, password))
    say("folder", "Making a folder for the project in your drive", {})
    folder_name = _dav(lambda: webdav.make_folder(address, user, password, Path(ws.root).name))
    sid = uuid.uuid4().hex[:16]
    host = (urlsplit(address).hostname or "").lower()
    desc = {"id": sid, "service": "webdav", "endpoint": address, "host": host, "folder": folder_name, "region": None,
            "bucket": None, "prefix": f"enlens/{sid}/", "in_eu": webdav.in_eu(address), "drive_users": {},
            "user": user, "drive_owner": {"user": user, "name": people.my_name() or None}}
    say("test", "Writing a test file", {})
    desc = _start_space(ws, desc, {"user": user, "password": password}, None, ident)
    desc["drive_users"] = {desc["part"]: user}   # (handed on with the owner's role: a later move shares by itself)
    webdav.remember(address)
    _connect(ws, desc, f"Set up a storage space in the drive at {host} (folder “{folder_name}”) for working "
                       "together.")
    out = status(ws)
    out["warnings"] = []
    return out


def _dav(call):
    from . import webdav

    try:
        return call()
    except webdav.WebDAVProblem as e:
        raise SpaceProblem(str(e), getattr(e, "kind", "webdav")) from e
    except StorageProblem as e:
        raise SpaceProblem(str(e), e.kind) from e


def _folder_holder(desc: dict, access: dict | None = None) -> tuple[bool, str]:
    """Whose drive holds the space's folder: (it is this person's own, the holder's name for messages). Only the
    holder can share the folder or stop sharing it, also after handing the owner's role over."""
    holder = desc.get("drive_owner") if isinstance(desc.get("drive_owner"), dict) else {}
    hu = str(holder.get("user") or "").strip().lower()
    mine = str((access or {}).get("user") or desc.get("user") or "").strip().lower()
    if not hu or hu == mine:
        return True, "you"
    name = str(holder.get("name") or "").strip()[:80]
    return False, f"{name} ({holder['user']})" if name else str(holder["user"])[:200]


def _drive_share(desc: dict, access: dict, with_user: str) -> tuple[str | None, str | None]:
    """Share the space's folder with a colleague's user name at the drive: (the share's id, or None and the words that
    tell the owner to share it in the drive's website). One share per user name: an earlier one is used again. When
    the folder is in someone else's drive (the owner's role was handed over), only they can share it: the words say
    so."""
    from . import webdav

    mine, holder = _folder_holder(desc, access)
    if not mine:
        return None, (f"The folder “{desc.get('folder')}” is in the drive of {holder}: only they can share it. Ask "
                      f"them to share it with {with_user or 'your colleague'} in the drive's website (allow them to "
                      "edit), then send the invite. To share it yourself, move the team to a folder in your own drive "
                      "(Move to another storage space).")
    by_hand = (f"Share the folder “{desc.get('folder')}” with {with_user or 'your colleague'} in the drive's website "
               "(allow them to edit), then send the invite.")
    if not with_user:
        return None, by_hand
    try:
        return webdav.share(desc["endpoint"], access.get("user") or "", access.get("password") or "",
                            desc["folder"], with_user), None
    except webdav.WebDAVProblem as e:
        return None, f"ENLENS could not share the folder: {e} {by_hand}"


# ---------------------------------------------------------------------------------------------
# invites and joining
# ---------------------------------------------------------------------------------------------
def _member_access(desc: dict, keeper: dict | None, part: str) -> tuple[dict, list[str]]:
    """The storage keys of a new member for their part: (access, ids to delete when they leave)."""
    service = desc.get("service")
    if service in ("dir", "webdav"):   # (a drive: each colleague uses their own account; the folder is shared)
        return {}, []
    if keeper is None:
        raise SpaceProblem("Only the copy that keeps the storage space's keys can invite: the owner's.", "not_keeper")
    if service == "b2":
        from . import b2

        acc = _b2(lambda: b2.authorize(keeper["key_id"], keeper["app_key"]))
        prefix = f"{desc['prefix']}parts/{part}/"
        wid, wkey = _b2(lambda: b2.create_key(acc, f"ENLENS {part} write", b2.MEMBER_WRITE_CAPS,
                                               bucket_id=desc.get("bucket_id"), name_prefix=prefix))
        try:
            rid, rkey = _b2(lambda: b2.create_key(acc, f"ENLENS {part} read", b2.MEMBER_READ_CAPS,
                                                   bucket_id=desc.get("bucket_id"), name_prefix=desc["prefix"]))
        except SpaceProblem:
            b2.delete_key(acc, wid)
            raise
        return {"key_id": wid, "secret": wkey, "read_key_id": rid, "read_secret": rkey}, [wid, rid]
    if service == "r2":
        from . import r2

        tid, tval = _r2(lambda: r2.create_member_token(keeper["token"], desc["account_id"], desc["bucket"], eu=True,
                                                        name=f"ENLENS {part}"))
        kid, sec = r2.s3_credentials(tid, tval)
        return {"key_id": kid, "secret": sec}, [tid]
    raise SpaceProblem("This kind of storage space is not known to this ENLENS.", "service")


def _drop_access(desc: dict, keeper: dict | None, ids: list[str], part: str | None = None,
                 others: set[str] | None = None) -> list[str]:
    """Delete a member's storage keys (they can no longer read or write the space). Best effort per key. On a drive,
    stop sharing the folder with them (`part`; `others`: the parts that stay, members and invites waiting); returns
    what the owner must still do by hand (words), if anything."""
    if desc.get("service") == "webdav":
        return _drive_unshare(desc, ids, part, others)
    if not ids or desc.get("service") == "dir" or keeper is None:
        return []
    if desc.get("service") == "b2":
        from . import b2

        acc = _b2(lambda: b2.authorize(keeper["key_id"], keeper["app_key"]))
        for i in ids:
            _b2(lambda i=i: b2.delete_key(acc, i))
    elif desc.get("service") == "r2":
        from . import r2

        for i in ids:
            _r2(lambda i=i: r2.delete_token(keeper["token"], i))
    return []


def _drive_unshare(desc: dict, ids: list[str], part: str | None = None, others: set[str] | None = None) -> list[str]:
    """Stop sharing a drive's folder with a colleague (the shares ENLENS made: `share:<id>`), unless a member who
    stays or an invite still waiting uses the same account at the drive (one share per user name). Returns the words
    for the owner when something is left to do in the drive's website."""
    from . import webdav

    users = desc.get("drive_users") or {}
    user = str(users.get(part) or "").strip() if part else ""
    shares = [i.split(":", 1)[1] for i in ids or [] if isinstance(i, str) and i.startswith("share:")]
    rest = {p for p in (others if others is not None else set(users) | set(desc.get("access_ids") or {})) if p != part}
    if any((user and str(users.get(p) or "").strip().lower() == user.lower())
           or any(f"share:{sid}" in ((desc.get("access_ids") or {}).get(p) or []) for sid in shares) for p in rest):
        return [f"The folder “{desc.get('folder')}” stays shared with {user or 'their account at the drive'}: another "
                "member of the team, or an invite not used yet, uses the same account."]
    who = user or "them"
    access = _get_secret(desc["id"], "access") or {}
    mine, holder = _folder_holder(desc, access)
    if not mine:
        return [f"The folder “{desc.get('folder')}” is in the drive of {holder}: only they can stop sharing it. Ask "
                f"them to stop sharing it with {who} in the drive's website, so {who} can no longer read or write it."]
    by_hand = (f"Stop sharing the folder “{desc.get('folder')}” with {who} in the drive's website, so they can no "
               "longer read or write it.")
    if not shares:
        return [by_hand]
    for sid in shares:
        try:
            webdav.unshare(desc["endpoint"], access.get("user") or "", access.get("password") or "", sid)
        except webdav.WebDAVProblem as e:
            return [f"ENLENS could not stop sharing the folder ({e}). {by_hand}"]
    return []


def _public_desc(desc: dict) -> dict:
    return {k: desc.get(k) for k in ("id", "service", "endpoint", "region", "bucket", "bucket_id", "account_id",
                                     "prefix", "dir", "in_eu", "host", "folder", "drive_owner")}


def _link(payload: dict) -> str:
    raw = zlib.compress(seal.canonical(payload), 9)
    return LINK + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_link(text: str) -> dict:
    """What an invite link holds (checked for shape; nothing is trusted until the space answers)."""
    t = "".join(str(text or "").split())
    i = t.find("#")
    if not t.startswith("enlens://join") or i < 0:
        raise SpaceProblem("This is not an ENLENS invite link. It starts with enlens://join#: copy the whole link "
                           "your colleague sent.", "link")
    body = t[i + 1:]
    try:
        if len(body) > 64 * 1024:
            raise ValueError("too long")
        z = zlib.decompressobj()
        raw = z.decompress(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)), 256 * 1024)
        if z.unconsumed_tail or not z.eof:   # (more than an invite ever holds, or cut off)
            raise ValueError("not an invite")
        payload = json.loads(raw)
    except (ValueError, zlib.error) as e:
        raise SpaceProblem("This invite link is cut off or damaged: copy the whole link again.", "link") from e
    sp = payload.get("space") if isinstance(payload, dict) else None
    ok = (isinstance(sp, dict) and isinstance(sp.get("id"), str) and _SPACE.fullmatch(sp["id"])
          and _PART.fullmatch(str(payload.get("part") or "")) and isinstance(payload.get("keys"), dict)
          and isinstance(payload.get("keeper"), dict) and isinstance(payload.get("project"), dict)
          and payload.get("v") == 1)
    if not ok:
        raise SpaceProblem("This invite link is cut off, damaged, or made by a newer ENLENS.", "link")
    if sp.get("service") == "webdav":   # (the drive's name shown is the one the password goes to, never another)
        from . import webdav

        try:
            endpoint = webdav.normalise(str(sp.get("endpoint") or ""))
        except webdav.WebDAVProblem as e:
            raise SpaceProblem("This invite link names a drive ENLENS cannot use safely. Ask the owner for a new "
                               "invite link.", "link") from e
        host = (urlsplit(endpoint).hostname or "").lower()
        if sp.get("host") is not None and str(sp.get("host")).strip().lower().rstrip(".") != host:
            raise SpaceProblem(f"This invite link names the drive at {str(sp.get('host'))[:100]} but would send your "
                               f"password to {host}. Do not use it: ask the owner for a new invite link.", "link")
        if not isinstance(sp.get("folder"), str) or not sp["folder"].strip():
            raise SpaceProblem("This invite link is cut off, damaged, or made by a newer ENLENS.", "link")
        sp.update(endpoint=endpoint, host=host)
        if not isinstance(sp.get("drive_owner"), dict):
            sp["drive_owner"] = None
    return payload


def _invite_unlocked(ws: Workspace, label: str | None = None, drive_user: str | None = None) -> dict:
    """*Invite a colleague*: a new part in the space with its own storage keys, and a link holding them, the project's
    keys and a one-time secret that binds the part to whoever uses it first. Returns {"link", "part", "message"}; on a
    drive also "shared" (ENLENS shared the folder with `drive_user`, the colleague's user name there) and "share_note"
    (what the owner must do in the drive's website instead)."""
    desc = configured(ws)
    if desc is None:
        raise SpaceProblem("Set up a storage space for this project first.", "no_space")
    if desc.get("keeper_part") != desc.get("part"):
        raise SpaceProblem("Only the owner's copy keeps the keys that make invites. Ask the owner to invite your "
                           "colleague.", "not_keeper")
    keeper = _get_secret(desc["id"], "keeper")
    part = _new_part()
    access, ids = _member_access(desc, keeper, part)
    share_note, drive_user = None, (drive_user or "").strip()[:200] or None
    if desc.get("service") == "webdav":   # (one share per user name at the drive: `webdav.share` finds an earlier one)
        share_id, share_note = _drive_share(desc, _get_secret(desc["id"], "access") or {}, drive_user or "")
        ids = [f"share:{share_id}"] if share_id else []
        if drive_user:
            desc = {**desc, "drive_users": {**(desc.get("drive_users") or {}), part: drive_user}}
    join = seal.new_key()
    names, epochs = _keys(desc["id"])
    _put_secret(desc["id"], f"invite:{part}", {"join": seal.b64(join)})
    desc = {**desc, "invites": [*(desc.get("invites") or []),
                                {"part": part, "made_at": now(), "label": (label or "").strip()[:80] or None}],
            "access_ids": {**(desc.get("access_ids") or {}), part: ids}}
    _save(ws, desc)
    project_name = Path(ws.root).name
    payload = {"v": 1, "space": _public_desc(desc), "part": part, "access": access, "join": seal.b64(join),
               "keys": {"names": seal.b64(names), "epochs": {str(e): seal.b64(k) for e, k in epochs.items()}},
               "keeper": {"part": desc["keeper_part"], "sign": desc["keeper_sign"], "n": desc.get("keeper_n") or 0},
               "keepers": _history(desc),
               "project": {"uid": ws.project_uid(), "name": project_name},
               "from": {"name": people.my_name() or None}}
    link = _link(payload)
    who = people.my_name() or "A colleague"
    drive = ""
    if desc.get("service") == "webdav":
        drive = (f"3. ENLENS asks for your user name at {desc.get('host')} and an app password: make one in the "
                 "drive's settings, under Security (never your main password). The folder "
                 f"“{desc.get('folder')}” is shared with you.\n\n")
    message = (f"{who} invites you to work together on the ENLENS project “{project_name}”.\n\n"
               f"1. Open ENLENS (version {__version__} or later).\n"
               "2. Under Projects, choose Join a team, and paste this link:\n\n"
               f"{link}\n\n" + drive +
               "The link holds the keys to the team's storage space: keep it to yourself, and use it once.")
    _note(ws, "space-invite", f"Made an invite link to the storage space{f' for {label.strip()[:80]}' if label else ''}.")
    out = {"link": link, "part": part, "message": message}
    if desc.get("service") == "webdav":
        out.update(shared=bool(ids), share_note=share_note)
    return out


def _cancel_invite_unlocked(ws: Workspace, part: str) -> dict:
    """An invite not used yet is withdrawn: its storage keys are deleted, so the link opens nothing."""
    desc = configured(ws)
    if desc is None or not any(i.get("part") == part for i in desc.get("invites") or []):
        raise SpaceProblem("There is no such invite waiting.", "no_invite")
    keeper = _get_secret(desc["id"], "keeper")
    ids = (desc.get("access_ids") or {}).get(part) or []
    left_to_do = _drop_access(desc, keeper, ids, part, _staying_parts(ws, desc, part))
    desc = {**desc, "invites": [i for i in desc.get("invites") or [] if i.get("part") != part],
            "access_ids": {k: v for k, v in (desc.get("access_ids") or {}).items() if k != part},
            "drive_users": {k: v for k, v in (desc.get("drive_users") or {}).items() if k != part}}
    keychain.delete(_secret_name(desc["id"], f"invite:{part}"))
    _save(ws, desc)
    base = mirror_of(ws)
    try:   # (a note that a key file for it was set aside goes with it)
        st = json.loads((base / ".space-state.json").read_text(encoding="utf-8"))
        if st.get("aside", {}).pop(f"parts/{part}/m/key.json", None) is not None:
            (base / ".space-state.json").write_text(json.dumps(st), encoding="utf-8")
    except (OSError, ValueError, AttributeError):
        pass
    out = status(ws)
    out["warnings"] = left_to_do
    return out


def _staying_parts(ws: Workspace, desc: dict, leaving: str) -> set[str]:
    """The parts that stay when one goes: the active members (as the last roster read says) and the invites
    waiting."""
    try:
        st = json.loads((mirror_of(ws) / ".space-state.json").read_text(encoding="utf-8"))
        roster = st.get("roster") or {}
    except (OSError, ValueError, AttributeError, TypeError):
        roster = {}
    parts = set(_active(roster)) | {i.get("part") for i in desc.get("invites") or []}
    return {p for p in parts if isinstance(p, str) and p != leaving}


def _key_file(ident: Identity, payload: dict, person: str, epoch: int, key: bytes) -> bytes:
    public = ident.public()
    body = {"part": payload["part"], "person": person, **public, "name": people.my_name() or None, "at": now(),
            "proof": seal.join_proof(seal.unb64(payload["join"]), payload["part"], person, public)}
    return seal.seal(seal.canonical(body), path=f"{person}/key.json", by=payload["part"], epoch=epoch, key=key,
                     ident=ident)


def peek(link: str) -> dict:
    """What the Team tab shows before joining: {"service", "host", "folder", "address" (the drive's address this
    person most likely uses: the inviter's, which `join` adapts to their user name; its host is always "host"),
    "known" (a drive of SURF's, or one this person has used on this computer: otherwise the dialog asks them to
    confirm it is their institution's before the app password is sent), "project", "from"}. Nothing in it is a
    key."""
    from . import webdav

    payload = parse_link(link)
    sp = payload["space"]
    dav = sp.get("service") == "webdav"
    return {"service": sp.get("service"), "host": sp.get("host"), "folder": sp.get("folder"),
            "address": sp.get("endpoint") if dav else None,
            "known": webdav.known(sp["endpoint"]) if dav else None,
            "project": str(payload["project"].get("name") or "")[:80],
            "from": str((payload.get("from") or {}).get("name") or "")[:80] or None}


def _drive_for_join(sp: dict, drive: dict | None, full: bool = True) -> tuple[dict, dict]:
    """A colleague joining (or following) a team in a drive: their own address, folder and access. `drive`:
    {"user", "password", "address"?, "folder"?, "confirmed"?}. Raises SpaceProblem "drive_needed" without a user name
    and app password; "drive_confirm" (with "address" and "host") before anything is sent to a drive that is neither
    SURF's nor one this person has used on this computer, unless they confirmed it is their institution's; and
    "folder_not_found" (with "folders" to choose from) when the shared folder is not in their drive. `full` False: the
    folder is looked for under its own name only (`webdav.find_shared`)."""
    from . import webdav

    drive = drive or {}
    user, password = str(drive.get("user") or "").strip(), str(drive.get("password") or "").strip()
    if not user or not password:
        raise SpaceProblem(f"This team works in a drive at {sp.get('host') or 'your institution'}. Enter your user "
                           "name there and an app password.", "drive_needed")
    address = str(drive.get("address") or "").strip()
    address = _dav(lambda: webdav.normalise(address, user) if address else
                   webdav.normalise(webdav.member_address(sp["endpoint"], user), user))
    host = (urlsplit(address).hostname or "").lower()
    if drive.get("confirmed") is not True and not webdav.known(address):
        raise SpaceProblem(f"ENLENS has not used the drive at {host} on this computer before. Check that {address} is "
                           "your institution's drive (its WebDAV address is in the drive's settings), and confirm it: "
                           "your app password is sent there.", "drive_confirm", {"address": address, "host": host})
    _dav(lambda: webdav.check(address, user, password))
    chosen = str(drive.get("folder") or "").strip().strip("/")
    found, folders = _dav(lambda: webdav.find_shared(address, user, password, chosen or sp.get("folder") or "",
                                                     sp["id"], full=full or bool(chosen)))
    if found is None:
        if chosen:
            raise SpaceProblem(f"The folder “{chosen}” does not hold this team's work. Choose another, or ask the "
                               "owner to share the folder with you again.", "folder_not_found", {"folders": folders})
        raise SpaceProblem(f"ENLENS did not find the shared folder “{sp.get('folder')}” in your drive. If the owner "
                           "has shared it with you, choose it below (it may have another name in your drive); if not, "
                           "ask them to share it.", "folder_not_found", {"folders": folders})
    return ({"endpoint": address, "folder": found, "host": host, "user": user}, {"user": user, "password": password})


def _join_unlocked(ws: Workspace, link: str, drive: dict | None = None) -> dict:
    """Join the team's storage space from an invite link, in this project (a new, empty project made for it, or a copy
    of the same project). Writes this copy's public keys into its part, with the proof that it holds the invite; the
    owner's copy binds the part to it at its next round. `drive`: in a team that works in a drive (WebDAV), this
    person's own user name and app password there (`_drive_for_join`). Returns `status`."""
    payload = parse_link(link)
    if payload["space"].get("service") == "webdav":   # (checked before anything of this project changes)
        drive_desc, drive_access = _drive_for_join(payload["space"], drive)
    proj = payload["project"]
    mine, known = ws.meta("project_uid"), set(ws.meta("project_uids_known") or [])
    if mine and mine != proj.get("uid") and proj.get("uid") not in known:
        has_docs = ws._conn().execute("SELECT 1 FROM documents LIMIT 1").fetchone()
        if has_docs:
            raise SpaceProblem(f"This invite is for the project “{str(proj.get('name') or '?')[:80]}”, not this one. "
                               "Join it under Projects → Join a team, which makes a new project for it.", "other_project")
    if not mine or (mine != proj.get("uid") and proj.get("uid") not in known):
        with ws.connect() as cx:
            ws.set_meta("project_uid", proj["uid"], cx)
    sp = payload["space"]
    desc = {**{k: v for k, v in sp.items() if v is not None}, "prefix": sp.get("prefix") or f"enlens/{sp['id']}/",
            "part": payload["part"], "keeper_part": payload["keeper"]["part"], "keeper_sign": payload["keeper"]["sign"],
            "keeper_n": _as_int(payload["keeper"].get("n")) or 0,
            "keepers": _valid_keepers(payload.get("keepers")) or [[payload["keeper"]["part"], payload["keeper"]["sign"],
                                                                    0]],
            "roster_seq": 0, "joined_at": now(), "invites": [],
            "access_ids": {}}
    if desc.get("service") not in SERVICES:
        raise SpaceProblem("This invite is for a kind of storage space this ENLENS does not know. Update ENLENS.",
                           "service")
    access = payload.get("access") or {}
    if desc.get("service") == "webdav":
        desc.update(drive_desc)
        access = drive_access
    try:
        names = seal.unb64(payload["keys"]["names"])
        epochs = {int(e): seal.unb64(k) for e, k in (payload["keys"].get("epochs") or {}).items()}
    except (KeyError, ValueError, TypeError) as e:
        raise SpaceProblem("This invite link is damaged: copy the whole link again.", "link") from e
    if not epochs:
        raise SpaceProblem("This invite link is damaged: copy the whole link again.", "link")
    ident = Identity.new()
    store = storage_for(desc, access)
    e = max(epochs)
    try:
        store.put(f"parts/{desc['part']}/m/key.json", _key_file(ident, payload, people.me(), e, epochs[e]))
    except StorageProblem as ex:
        raise SpaceProblem(f"ENLENS could not reach the team's storage space with this link: {ex}", ex.kind) from ex
    keychain.put(_secret_name(desc["id"], "me"), ident.dump())
    _put_keys(desc["id"], names, epochs)
    _put_secret(desc["id"], "access", access)
    if desc.get("service") == "webdav":
        from . import webdav

        webdav.remember(desc["endpoint"])
    who = (payload.get("from") or {}).get("name")
    _connect(ws, desc, f"Joined the team's storage space{f' from {who}' if who else ''}.")
    return status(ws)


def join_new_project(link: str, name: str | None = None, drive: dict | None = None) -> str:
    """*Join a team* under Projects: a new project for the invite (named as the inviter's, or `name`), joined. Returns
    the project's name. `drive`: as for `join`."""
    from .. import home

    payload = parse_link(link)
    if payload["space"].get("service") == "webdav":   # (no project is made before the drive is found)
        _drive_for_join(payload["space"], drive)
    n = home.unique_project_name(home.safe_name(name or payload["project"].get("name") or "") or "Team project")
    ws = home.create_project(n)
    try:
        join(ws, link, drive)
    except Exception:
        ws.close_all()
        import shutil

        shutil.rmtree(ws.root, ignore_errors=True)
        raise
    return n


def _bind_joins(ctx: _Ctx) -> bool:
    """The keeper's copy: each invite whose colleague has written their key file is bound to them (the roster names
    their keys; the project's keys are sealed to them). A key file without the invite's proof, or for a part bound
    already to someone else, is set aside. Returns whether the roster changed."""
    if ctx.desc["part"] not in (ctx.roster.get("members") or {}):
        return False  # (the list of members could not be read this round: nobody is let in from a list without them)
    changed = False
    roster = json.loads(json.dumps(ctx.roster))
    members = roster.setdefault("members", {})
    left = []
    for inv in ctx.desc.get("invites") or []:
        part = inv.get("part")
        name = f"parts/{part}/m/key.json"
        try:
            blob = ctx.store.get(name, max_size=_CAP["m"])
        except StorageProblem as e:
            if e.kind not in (NOT_FOUND, "too_large"):
                raise
            if e.kind == "too_large":
                ctx.set_aside(name, "", part, "join", "A key file for an invite was larger than ENLENS reads. It was "
                                                      "set aside; the invite still waits.")
            left.append(inv)
            continue
        sec = _get_secret(ctx.id, f"invite:{part}") or {}
        held = {m.get("person") for m in members.values() if isinstance(m, dict) and not m.get("removed")}
        why = "A key file for an invite did not hold that invite's proof. It was set aside; the invite still waits."
        try:
            h, data = seal.open_unverified(blob, ctx.epochs)
            body = json.loads(data)
            if not isinstance(body, dict):
                raise ValueError("not a key file")
            person = str(body.get("person") or "")
            public = {"sign": body.get("sign"), "box": body.get("box")}
            ok = bool(people.ID_RE.fullmatch(person) and h.by == part and h.path == f"{person}/key.json"
                      and isinstance(public["sign"], str) and isinstance(public["box"], str)
                      and seal.check_join_proof(seal.unb64(sec.get("join") or ""), part, person, public,
                                                str(body.get("proof") or "")))
            if ok:
                seal.verify(blob, public["sign"])
            if ok and person in held:   # someone in the team already: nobody joins under another's name
                ok = False
                why = ("A key file for an invite named a person who is in the team already. It was set aside; the "
                       "invite still waits.")
        except (SealProblem, ValueError, TypeError, AttributeError):
            ok = False
        if not ok:
            ctx.set_aside(name, "", part, "join", why)
            left.append(inv)
            continue
        members[part] = {"person": person, **public, "since": now(), "removed": None}
        if str(body.get("name") or "").strip():
            ctx.state.setdefault("names", {})[person] = str(body["name"]).strip()[:80]
        ctx.state["aside"].pop(name, None)
        changed = True
        _note(ctx.ws, "space-joined", f"{str(body.get('name') or 'A colleague')[:60]} joined the storage space.")
    if changed:
        _write_roster(ctx, roster, rekey=False)
        for inv in ctx.desc.get("invites") or []:
            if inv not in left:
                keychain.delete(_secret_name(ctx.id, f"invite:{inv.get('part')}"))
        ctx.desc["invites"] = left
        ctx.changed_desc = True
    return changed


def _seal_all_keys(ctx: _Ctx, roster: dict) -> bytes:
    sealed: dict[str, dict] = {}
    for e, k in sorted(ctx.epochs.items()):
        sealed[str(e)] = {p: seal.seal_key(m["box"], ctx.names + k, f"{ctx.id} epoch {e} part {p}")
                          for p, m in (roster.get("members") or {}).items() if not m.get("removed") and m.get("box")}
    return seal.signed_json(ctx.ident, {"space": ctx.id, "epochs": sealed}, ctx.desc["part"])


def _write_roster(ctx: _Ctx, roster: dict, rekey: bool) -> None:
    """The keeper writes the roster (and the keys sealed to each member), keys first: a member that reads the new
    roster finds its keys there already. `rekey`: a new project key (a new epoch) for those still in the team, kept
    here only once both files are written, so this copy never seals with a key its colleagues were not given."""
    if ctx.desc["part"] not in (roster.get("members") or {}):
        raise SpaceProblem("The list of the team's members could not be read just now; nothing was changed. Try again "
                           "after the next round.", "no_roster")
    epochs = dict(ctx.epochs)
    if rekey:
        e = max(epochs) + 1
        epochs[e] = seal.new_key()
        roster["epoch"] = e
    roster["seq"] = (_as_int(ctx.desc.get("roster_seq")) or 0) + 1
    roster["v"] = 1
    keep, ctx.epochs = ctx.epochs, epochs
    try:
        ctx.store.put("space/keys.json", _seal_all_keys(ctx, roster))
        ctx.store.put("space/roster.json", _signed_roster(ctx, roster))
    except BaseException:
        ctx.epochs = keep
        raise
    if rekey:
        _put_keys(ctx.id, ctx.names, ctx.epochs)
    ctx.desc["roster_seq"] = roster["seq"]
    ctx.changed_desc = True
    ctx.state["roster"] = roster


# ---------------------------------------------------------------------------------------------
# reading the space into the mirror
# ---------------------------------------------------------------------------------------------
def _space_file(ctx: _Ctx, name: str) -> bytes | None:
    """One of the space's own files (`space/…`), or None when it is not there, or too large: a file in the space never
    stops a round (only a space that cannot be reached does)."""
    try:
        return ctx.store.get(name, max_size=_CAP["space"])
    except StorageProblem as e:
        if e.kind == NOT_FOUND:
            return None
        if e.kind == "too_large":
            ctx.problem("set_aside", f"A file of the storage space ({name.rsplit('/', 1)[-1]}) is larger than ENLENS "
                                     "reads. It was set aside.")
            return None
        raise


def _read_roster(ctx: _Ctx) -> None:
    data = _space_file(ctx, "space/roster.json")
    if data is None:
        return
    said = ("The list of the team's members in the storage space is not signed by the owner who keeps it, or is "
            "damaged. It was set aside; ENLENS goes on with the list it read last.")
    try:
        obj, by, sig = seal.read_signed_json(data)
        seq = _as_int(obj.get("seq"))
        if seq is None or obj.get("space") != ctx.id or not isinstance(obj.get("members"), dict):
            raise ValueError("not a roster")
        if seq < (_as_int(ctx.desc.get("roster_seq")) or 0):
            return  # (an older list: nothing new)
        if seq == (_as_int(ctx.desc.get("roster_seq")) or 0) and ctx.state.get("roster"):
            return
        chain = _roster_trusted(ctx.desc, obj, by, sig)
        if chain is None:
            ctx.problem("set_aside", said)
            return
        members = obj["members"]
        if not all(isinstance(m, dict) and isinstance(m.get("person"), str) for m in members.values()):
            raise ValueError("not a roster")
    except (SealProblem, ValueError, TypeError, AttributeError, KeyError):
        ctx.problem("set_aside", said)
        return
    ctx.desc["keepers"] = chain
    ctx.desc["keeper_part"], ctx.desc["keeper_sign"] = chain[-1][0], chain[-1][1]
    ctx.desc["keeper_n"] = max([_as_int(c.get("n")) or 0 for c in obj.get("keepers") or [] if isinstance(c, dict)] +
                               [_as_int(ctx.desc.get("keeper_n")) or 0])
    ctx.desc["roster_seq"] = seq
    ctx.changed_desc = True
    ctx.state["roster"] = obj


def _active(roster: dict) -> dict[str, dict]:
    """The members still in the team, each person once: a person id held by two parts (a forged join, which the keeper
    refuses, `_bind_joins`) counts for neither."""
    members = {p: m for p, m in (roster.get("members") or {}).items()
               if isinstance(m, dict) and not m.get("removed") and _PART.fullmatch(str(p))}
    held: dict[str, int] = {}
    for m in members.values():
        held[m.get("person")] = held.get(m.get("person"), 0) + 1
    return {p: m for p, m in members.items() if held[m.get("person")] == 1}


def _read_keys(ctx: _Ctx) -> None:
    data = _space_file(ctx, "space/keys.json")
    if data is None:
        return
    try:
        obj, by, sig = seal.read_signed_json(data)
        if obj.get("space") != ctx.id or by != ctx.desc["keeper_part"] or not seal.check_signed(obj, sig,
                                                                                                 ctx.desc["keeper_sign"]):
            return
        epochs = obj.get("epochs") or {}
        if not isinstance(epochs, dict):
            return
    except (SealProblem, ValueError, TypeError, AttributeError):
        return
    got = False
    for e, per in epochs.items():
        e = _as_int(e)
        sealed = per.get(ctx.desc["part"]) if isinstance(per, dict) else None
        if e is None or e in ctx.epochs or not isinstance(sealed, str):
            continue
        try:
            both = seal.open_key(ctx.ident, sealed, f"{ctx.id} epoch {e} part {ctx.desc['part']}")
        except SealProblem:
            continue
        if both[:32] == ctx.names:
            ctx.epochs[e] = both[32:]
            got = True
    if got:
        _put_keys(ctx.id, ctx.names, ctx.epochs)


def _mirror_put(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)


def _logical(kind: str, pid: str, leaf: str) -> str | None:
    """Where a file of a part's kind goes in the mirror (relative to the team folder), from its name in the space;
    None for the hidden names of readings and files (their place is in their sealed header)."""
    if kind == "m" and leaf in _M_FILES:
        return f"{pid}/{leaf}"
    if kind == "b" and re.fullmatch(r"\d{6,}", leaf):
        return f"{pid}/bundles/{leaf}.zip"
    return None


def _expected_hidden(kind: str, pid: str, path: str, names: bytes, leaf: str) -> bool:
    sub = {"d": "docs", "f": "files"}[kind]
    rest = path[len(pid) + 1:] if path.startswith(pid + "/") else ""
    name = rest[len(sub) + 1:] if rest.startswith(sub + "/") else ""
    pat = folder._READING if kind == "d" else folder._FILE
    return bool(name) and "/" not in name and bool(pat.fullmatch(name)) and seal.hidden_name(names, path) == leaf


def _pull_part(ctx: _Ctx, part: str, m: dict, deep: bool) -> None:
    """One colleague's part into the mirror: their small files and bundles every round; their readings and files when
    something new came (a new head), or when `deep`."""
    pid = m["person"]
    remote = ctx.state["remote"]
    kinds = ["m", "b"]
    listed: dict[str, dict] = {}
    got_m = ctx.store.list(f"parts/{part}/m/")
    head = f"parts/{part}/m/head.json"
    new_head = head in got_m and (remote.get(head) or {}).get("etag") != got_m[head].etag
    if new_head or deep or not any(k.startswith(f"parts/{part}/d/") for k in remote):
        kinds += ["d", "f"]
    listed.update({k: {"etag": o.etag, "size": o.size} for k, o in got_m.items()})
    for k in kinds[1:]:
        listed.update({n: {"etag": o.etag, "size": o.size} for n, o in ctx.store.list(f"parts/{part}/{k}/").items()})
    # only names of exactly the shape ENLENS writes (parts/<part>/<kind>/<leaf>): a deeper name could stand for the
    # same file in the copy here, and its removal remove that file
    listed = {n: v for n, v in listed.items() if len(n.split("/")) == 4}
    # head.json first: what it says is there is there (the writer sends it last)
    order = sorted(listed, key=lambda n: (n != head, n))
    for name in order:
        info = listed[name]
        kind, leaf = name.split("/")[2], name.split("/")[-1]
        if kind == "m" and leaf not in _M_FILES:
            continue
        if (remote.get(name) or {}).get("etag") == info["etag"]:
            continue
        aside = ctx.state["aside"].get(name)
        if aside and aside.get("etag") == info["etag"]:
            continue
        try:
            blob = ctx.store.get(name, max_size=_CAP[kind])
        except StorageProblem as e:
            if e.kind == NOT_FOUND:
                continue
            if e.kind == "too_large":
                ctx.set_aside(name, info["etag"], part, "too_large", "A colleague's file in the storage space is "
                                                                     "larger than ENLENS reads.")
                continue
            raise
        try:
            want = _logical(kind, pid, leaf)
            if want is not None:
                data = seal.open_sealed(blob, path=want, by=part, sign_pub=m["sign"], keys=ctx.epochs)
            else:
                h = seal.verify(blob, m["sign"])
                if h.by != part or not _expected_hidden(kind, pid, h.path, ctx.names, leaf):
                    raise SealProblem("A file in the storage space says it belongs elsewhere.", "place")
                want = h.path
                data = seal.open_sealed(blob, path=want, by=part, sign_pub=m["sign"], keys=ctx.epochs, h=h)
        except SealProblem as e:
            if e.why == "key":  # sealed with a newer key this copy has not got yet: tried again next round
                continue
            ctx.set_aside(name, info["etag"], part, e.why, str(e))
            continue
        if leaf == "head.json" and _older_head(ctx.team / want, data):
            ctx.set_aside(name, info["etag"], part, "older", "A colleague's head.json in the storage space is older "
                                                             "than the one this copy has: it was set aside.")
            continue
        _mirror_put(ctx.team / want, data)
        remote[name] = {"etag": info["etag"], "logical": want}
        ctx.state["aside"].pop(name, None)
    # what went from the space goes from the mirror (a colleague started afresh, pruned bundles, took words out)
    looked = [f"parts/{part}/{k}/" for k in kinds]
    for name in [n for n in remote if any(n.startswith(p) for p in looked) and n not in listed]:
        logical = remote.pop(name).get("logical")
        if logical:
            try:
                (ctx.team / logical).unlink()
            except OSError:
                pass


def _older_head(have: Path, new: bytes) -> bool:
    """Whether a colleague's head.json put back in the space says less than the one this copy has, in the same epoch
    (an older file restored: a copy never goes back)."""
    old = folder._json(have)
    try:
        nh = json.loads(new)
    except ValueError:
        return False
    if not isinstance(old, dict) or not isinstance(nh, dict) or old.get("epoch") != nh.get("epoch"):
        return False
    a, b = _as_int(old.get("last")), _as_int(nh.get("last"))
    return a is not None and b is not None and b < a


def _pull(ctx: _Ctx, deep: bool = False) -> dict | None:
    """Everything new in the space into the mirror. Returns where the team moved to, when it did (`moved.json`)."""
    moved = _read_moved(ctx)
    if moved is not None:
        return moved
    _read_roster(ctx)
    _read_keys(ctx)
    _read_keeper_handover(ctx)
    if ctx.keeper:
        _bind_joins(ctx)
    ctx.team.mkdir(parents=True, exist_ok=True)
    _read_project_json(ctx)
    for part, m in sorted(_active(ctx.roster).items()):
        if part == ctx.desc["part"] or m.get("person") == ctx.me:
            continue
        if not (people.ID_RE.fullmatch(str(m.get("person") or "")) and isinstance(m.get("sign"), str)):
            continue
        _pull_part(ctx, part, m, deep)
    return None


def _read_project_json(ctx: _Ctx) -> None:
    """The folder's project.json, as the keeper of the space wrote it (the keeper now: one who handed the space over
    writes none any more); written here only when it changed."""
    data = _space_file(ctx, "space/project.json")
    m = (ctx.roster.get("members") or {}).get(ctx.desc["keeper_part"])
    if data is None or not isinstance(m, dict) or not isinstance(m.get("sign"), str):
        return
    try:
        plain = seal.open_sealed(data, path="project.json", by=ctx.desc["keeper_part"], sign_pub=m["sign"],
                                 keys=ctx.epochs)
    except SealProblem:
        return
    f = ctx.team / "project.json"
    try:
        same = f.read_bytes() == plain
    except OSError:
        same = False
    if not same:
        _mirror_put(f, plain)


# ---------------------------------------------------------------------------------------------
# sending this copy's part
# ---------------------------------------------------------------------------------------------
def _mine_files(mine: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for f in _M_FILES:
        p = mine / f
        if p.is_file():
            out[f] = p
    for sub, pat in (("bundles", folder._BUNDLE), ("docs", folder._READING), ("files", folder._FILE)):
        try:
            for p in (mine / sub).iterdir():
                if p.is_file() and pat.fullmatch(p.name):
                    out[f"{sub}/{p.name}"] = p
        except OSError:
            continue
    return out


def _remote_name(ctx: _Ctx, rel: str) -> str:
    part = ctx.desc["part"]
    if rel in _M_FILES:
        return f"parts/{part}/m/{rel}"
    sub, leaf = rel.split("/", 1)
    if sub == "bundles":
        return f"parts/{part}/b/{leaf[:-4]}"
    return f"parts/{part}/{sub[0]}/{seal.hidden_name(ctx.names, f'{ctx.me}/{rel}')}"


def _push(ctx: _Ctx) -> int:
    """What this copy wrote in its part of the mirror, to the space: new and changed files sealed, files it removed
    removed, `head.json` last. Returns how many files were sent."""
    mine = ctx.team / ctx.me
    pushed = ctx.state["pushed"]
    files = _mine_files(mine)
    sent = 0

    def send(rel: str, p: Path) -> None:
        nonlocal sent
        try:
            st = p.stat()
        except OSError:
            return
        sig = [st.st_size, st.st_mtime_ns]
        if (pushed.get(rel) or {}).get("sig") == sig:
            return
        if st.st_size > seal.MAX_SEALED:   # (an original file too large to send: colleagues add it themselves)
            if (pushed.get(rel) or {}).get("too_large") != sig:
                ctx.problem("too_large", f"The file {rel.rsplit('/', 1)[-1]} is larger than ENLENS sends to the "
                                         f"storage space ({seal.MAX_SEALED // 1024 ** 2} MB); your colleagues add it "
                                         "themselves.")
            return
        name = _remote_name(ctx, rel)
        ctx.store.put(name, ctx.sealed(p.read_bytes(), f"{ctx.me}/{rel}"))
        pushed[rel] = {"sig": sig, "remote": name}
        sent += 1

    for rel, p in sorted(files.items()):
        if rel != "head.json":
            send(rel, p)
    if "head.json" in files:
        send("head.json", files["head.json"])
    # what this copy removed from its part goes last: a colleague reading meanwhile finds the new head and the new
    # bundles first (a copy that starts afresh removes its old bundles), never a head without its bundles
    for rel in [r for r in pushed if r not in files]:
        ctx.store.delete(pushed[rel]["remote"])
        pushed.pop(rel)
    if ctx.keeper and (ctx.team / "project.json").is_file():
        import hashlib

        data = (ctx.team / "project.json").read_bytes()
        sig = [hashlib.sha256(data).hexdigest(), ctx.desc["part"]]   # (by its words: reading it back changes nothing)
        if ctx.state.get("project_sent") != sig:
            ctx.store.put("space/project.json", ctx.sealed(data, "project.json"))
            ctx.state["project_sent"] = sig
    return sent


# ---------------------------------------------------------------------------------------------
# the keeper's role follows the owner's (roadmap L2)
# ---------------------------------------------------------------------------------------------
def _owner_part(ctx: _Ctx) -> str | None:
    from .. import ownership

    try:
        owner = ownership.owner(ctx.ws._conn())
    except Exception:  # noqa: BLE001
        return None
    if not owner:
        return None
    return next((part for part, m in _active(ctx.roster).items() if m.get("person") == owner), None)


def _hand_over_if_owner_changed(ctx: _Ctx) -> None:
    """The keeper's copy hands the space's keys to the project's new owner (when the owner is a member of the space):
    sealed to them in `space/keeper.json`, and a roster signed by this keeper naming them. This copy then forgets the
    keys that make invites and remove colleagues; it keeps its own storage key, to go on writing its part. (The
    storage account itself stays whoever's it is: for a hand-over in full, the new owner moves the team to a storage
    space of their own.)"""
    if not ctx.keeper or ctx.desc["part"] not in (ctx.roster.get("members") or {}):
        return
    to = _owner_part(ctx)
    if to is None or to == ctx.desc["part"]:
        return
    m = ctx.roster["members"][to]
    if not isinstance(m.get("box"), str) or not isinstance(m.get("sign"), str):
        return
    invites = ctx.desc.get("invites") or []
    # (a drive: the access is this person's own account and app password, never handed on; the new keeper uses theirs)
    secret = {"keeper": _get_secret(ctx.id, "keeper"),
              "access": {} if ctx.desc.get("service") == "webdav" else ctx.access,
              "access_ids": ctx.desc.get("access_ids") or {}, "invites": invites,
              "drive_users": ctx.desc.get("drive_users") or {},
              "invite_secrets": {i["part"]: _get_secret(ctx.id, f"invite:{i['part']}") for i in invites}}
    n = (_as_int(ctx.desc.get("keeper_n")) or 0) + 1
    seq = (_as_int(ctx.desc.get("roster_seq")) or 0) + 1   # the roster `_write_roster` writes next
    sealed = seal.seal_key(m["box"], json.dumps(secret).encode("utf-8"), f"{ctx.id} keeper {n} part {to}")
    ctx.store.put("space/keeper.json", seal.signed_json(ctx.ident, {"space": ctx.id, "n": n, "to": to,
                                                                    "sealed": sealed}, ctx.desc["part"]))
    roster = json.loads(json.dumps(ctx.roster))
    roster.setdefault("keepers", []).append(_keeper_cert(ctx.ident, ctx.id, n, to, m["sign"], ctx.desc["part"], seq))
    _write_roster(ctx, roster, rekey=False)
    ctx.desc.update(keeper_part=to, keeper_sign=m["sign"], keeper_n=n, invites=[], access_ids={}, drive_users={},
                    keepers=_history(ctx.desc) + [[to, m["sign"], seq]])
    ctx.changed_desc = True
    keychain.delete(_secret_name(ctx.id, "keeper"))
    for i in invites:
        keychain.delete(_secret_name(ctx.id, f"invite:{i['part']}"))
    _note(ctx.ws, "space-handed-over", "Handed the keys of the storage space to the project's new owner.")


def _read_keeper_handover(ctx: _Ctx) -> None:
    """This copy was made the keeper (the roster says so): it takes the keys sealed to it."""
    n_now = _as_int(ctx.desc.get("keeper_n")) or 0
    if not ctx.keeper or n_now == 0 or (_as_int(ctx.state.get("keeper_taken")) or 0) >= n_now:
        return  # (the first keeper, or the keys taken already)
    data = _space_file(ctx, "space/keeper.json")
    if data is None:
        return
    try:
        obj, by, sig = seal.read_signed_json(data)
        n = _as_int(obj.get("n"))
        cert = next((c for c in ctx.roster.get("keepers") or [] if isinstance(c, dict) and _as_int(c.get("n")) == n),
                    None)
        if n is None or cert is None or obj.get("to") != ctx.desc["part"] or by != cert.get("by"):
            return
        by_m = (ctx.roster.get("members") or {}).get(by) or {}
        if not seal.check_signed(obj, sig, by_m.get("sign") or ""):
            return
        secret = json.loads(seal.open_key(ctx.ident, obj["sealed"], f"{ctx.id} keeper {n} part {ctx.desc['part']}"))
        if not isinstance(secret, dict):
            return
    except (SealProblem, ValueError, KeyError, TypeError, AttributeError):
        return
    if secret.get("keeper") is not None:
        _put_secret(ctx.id, "keeper", secret["keeper"])
    if isinstance(secret.get("access"), dict) and secret["access"]:   # the keeper's key reaches the whole space
        _put_secret(ctx.id, "access", secret["access"])
        ctx.access = secret["access"]
        ctx.store = storage_for(ctx.desc, ctx.access)
    ctx.desc["access_ids"] = secret.get("access_ids") if isinstance(secret.get("access_ids"), dict) else {}
    if isinstance(secret.get("drive_users"), dict):   # (a drive: the user names, so a later move shares by itself)
        ctx.desc["drive_users"] = {p: str(u)[:200] for p, u in secret["drive_users"].items()
                                   if _PART.fullmatch(str(p)) and isinstance(u, str) and u.strip()}
    ctx.desc["invites"] = [i for i in secret.get("invites") or [] if isinstance(i, dict) and
                           _PART.fullmatch(str(i.get("part")))]
    for part, sec in (secret.get("invite_secrets") or {}).items():
        if sec and _PART.fullmatch(str(part)):
            _put_secret(ctx.id, f"invite:{part}", sec)
    ctx.state["keeper_taken"] = n
    ctx.changed_desc = True
    _note(ctx.ws, "space-keeper", "This copy now keeps the keys of the storage space, as the project's owner.")


# ---------------------------------------------------------------------------------------------
# removing a colleague, moving the team
# ---------------------------------------------------------------------------------------------
def _remove_member_unlocked(ws: Workspace, part: str) -> dict:
    """The keeper removes a colleague from the storage space: their storage keys are deleted (they can no longer read
    or write it), and the project's key is replaced for those who stay. What the colleague already has stays with
    them, and what they shared stays in the project. Returns `status`."""
    desc = configured(ws)
    if desc is None:
        raise SpaceProblem("Set up a storage space for this project first.", "no_space")
    ctx = _Ctx(ws, desc)
    if not ctx.keeper:
        raise SpaceProblem("Only the owner's copy can remove a colleague from the storage space.", "not_keeper")
    try:
        _read_roster(ctx)
        roster = json.loads(json.dumps(ctx.roster))
        m = (roster.get("members") or {}).get(part)
        if m is None or m.get("removed") or part == ctx.desc["part"]:
            raise SpaceProblem("There is no such colleague in the storage space.", "no_member")
        others = {p for p in _active(roster) if p != part} | {i.get("part") for i in ctx.desc.get("invites") or []}
        left_to_do = _drop_access(ctx.desc, _get_secret(ctx.id, "keeper"),
                                  (ctx.desc.get("access_ids") or {}).get(part) or [], part, others)
        m["removed"] = now()
        _write_roster(ctx, roster, rekey=True)
        ctx.desc["access_ids"] = {k: v for k, v in (ctx.desc.get("access_ids") or {}).items() if k != part}
        ctx.desc["drive_users"] = {k: v for k, v in (ctx.desc.get("drive_users") or {}).items() if k != part}
        ctx.changed_desc = True
    except StorageProblem as e:
        raise SpaceProblem(f"ENLENS could not reach the storage space: {e}", e.kind) from e
    finally:
        ctx.save()
    name = _member_name(ws, m.get("person"))
    _note(ws, "space-removed", f"Removed {name} from the storage space; the project's key was replaced.")
    out = status(ws)
    out["warnings"] = [w.replace("with them", f"with {name}") for w in left_to_do or []]
    return out


def _move_unlocked(ws: Workspace, start: Callable[[Workspace, Identity], dict]) -> dict:
    """*Move to another storage space*: the keeper sets up a new space (`start(ws, ident)`, e.g. `lambda w, i:
    setup_b2(w, …, ident=i)`, with this copy's own keys), every member of the old one gets a part and keys there, and
    the old space says where the team went (sealed to each member: their copies follow by themselves at their next
    round). Nothing changes when any of it fails before the old space is told: the project stays with the old space,
    and the keys made in the new one are deleted. When the old space cannot be reached any more, the owner sends the
    colleagues new invites.

    To a drive (WebDAV): colleagues who already work in a drive at the same address follow with their own account, once
    the new folder is shared with them (ENLENS shares it with the user names it was given at their invites; otherwise
    the owner does, in the drive's website). Colleagues coming from elsewhere have no account ENLENS knows of there:
    their copies stop using the old space and ask them for a new invite. Returns `status` with "moved": {"told": n,
    "not_told": [names], "invite_again": [names], "share_by_hand": [names]}."""
    old = configured(ws)
    if old is None:
        raise SpaceProblem("Set up a storage space for this project first.", "no_space")
    octx = _Ctx(ws, old)
    if not octx.keeper:
        raise SpaceProblem("Only the owner's copy can move the team to another storage space.", "not_keeper")
    try:
        _read_roster(octx)
    except StorageProblem:
        pass
    members = {p: m for p, m in _active(octx.roster).items() if p != octx.desc["part"]
               and isinstance(m.get("box"), str) and isinstance(m.get("sign"), str)}
    start(ws, octx.ident)   # (connects the project to the new space)
    new = configured(ws)
    keeper = _get_secret(new["id"], "keeper")
    made: list[list[str]] = []
    to_drive = new.get("service") == "webdav"
    follows = not to_drive or (old.get("service") == "webdav" and old.get("host") == new.get("host"))
    again: list[str] = []
    by_hand: list[str] = []
    try:
        nctx = _Ctx(ws, new)
        _read_roster(nctx)   # (the list the set-up wrote: this copy alone)
        roster = json.loads(json.dumps(nctx.roster))
        if nctx.desc["part"] not in (roster.get("members") or {}):
            raise SpaceProblem("The new storage space could not be read back. Nothing was moved.", "bad_answer")
        sealed: dict[str, str] = {}
        for p, m in members.items():
            if not follows:   # (no account at the new drive this copy knows of: they join it from a new invite)
                sealed[p] = seal.seal_key(m["box"], seal.canonical({"invite_again": True, "where": describe(new)}),
                                          f"{old['id']} moved part {p}")
                again.append(_member_name(ws, m.get("person")))
                continue
            part = _new_part()
            access, ids = _member_access(new, keeper, part)
            if to_drive:
                user = (old.get("drive_users") or {}).get(p)
                share_id, note = _drive_share(new, _get_secret(new["id"], "access") or {}, user or "")
                ids = [f"share:{share_id}"] if share_id else []
                if user:
                    nctx.desc.setdefault("drive_users", {})[part] = user
                if note:
                    by_hand.append(_member_name(ws, m.get("person")))
            made.append(ids)
            nctx.desc.setdefault("access_ids", {})[part] = ids
            roster["members"][part] = {"person": m["person"], "sign": m["sign"], "box": m["box"], "since": now(),
                                       "removed": None}
            payload = {"part": part, "access": access, "space": _public_desc(new),
                       "keeper": {"part": new["part"], "sign": nctx.desc["keeper_sign"], "n": 0},
                       "keepers": _history(nctx.desc),
                       "keys": {"names": seal.b64(nctx.names),
                                "epochs": {str(e): seal.b64(k) for e, k in nctx.epochs.items()}}}
            sealed[p] = seal.seal_key(m["box"], seal.canonical(payload), f"{old['id']} moved part {p}")
        if len(roster["members"]) > 1:
            _write_roster(nctx, roster, rekey=False)
        # the folder's project.json goes along as it is (the same folder_id: no copy starts over), in the new space
        # before anyone is told: a colleague who follows before this copy's next round finds it there, and this copy,
        # with a colleague's part in its new mirror already, does not wait for it for ever (`folder._open_team`)
        pj = octx.team / "project.json"
        if pj.is_file():
            data = pj.read_bytes()
            _mirror_put(nctx.team / "project.json", data)
            nctx.store.put("space/project.json", nctx.sealed(data, "project.json"))
            nctx.state["project_sent"] = [hashlib.sha256(data).hexdigest(), nctx.desc["part"]]
        nctx.save()
    except BaseException:
        for ids in made:
            try:
                _drop_access(new, keeper, ids)
            except Exception:  # noqa: BLE001 - best effort: the new space is left as it is
                pass
        _save(ws, old)                       # back to the old space, whose keys are all still here
        _forget_secrets(new["id"])
        raise
    told, not_told = 0, []
    try:
        octx.store.put("space/moved.json", seal.signed_json(octx.ident, {"space": old["id"], "to": new["id"],
                                                                         "sealed": sealed}, old["part"]))
        told = len(sealed)
    except StorageProblem:
        not_told = [_member_name(ws, m.get("person")) for m in members.values()]
    _note(ws, "space-moved", f"Moved the team to another storage space ({describe(new)}).")
    out = status(ws)
    out["moved"] = {"told": told, "not_told": not_told, "invite_again": again if told else [],
                    "share_by_hand": by_hand}
    return out


def _read_moved(ctx: _Ctx) -> dict | None:
    """The team moved (`move`): this copy's new part and keys, sealed to it in the old space, signed by its keeper.
    The copy then uses the new space; what it shares is written there once more."""
    data = _space_file(ctx, "space/moved.json")
    if data is None:
        return None
    try:
        obj, by, sig = seal.read_signed_json(data)
        if obj.get("space") != ctx.id or by != ctx.desc["keeper_part"] or not seal.check_signed(
                obj, sig, ctx.desc["keeper_sign"]):
            return None
        mine = (obj.get("sealed") or {}).get(ctx.desc["part"])
        if not isinstance(mine, str):
            return None
        payload = json.loads(seal.open_key(ctx.ident, mine, f"{ctx.id} moved part {ctx.desc['part']}"))
        if isinstance(payload, dict) and payload.get("invite_again") is True:
            return _moved_away(ctx, str(payload.get("where") or "another storage space")[:200])
        sp = payload["space"]
        if not (isinstance(sp, dict) and _SPACE.fullmatch(str(sp.get("id"))) and _PART.fullmatch(str(payload["part"]))
                and sp.get("service") in SERVICES):
            return None
        new = {**{k: v for k, v in sp.items() if v is not None}, "part": payload["part"],
               "keeper_part": payload["keeper"]["part"], "keeper_sign": payload["keeper"]["sign"], "keeper_n": 0,
               "keepers": _valid_keepers(payload.get("keepers")) or [[payload["keeper"]["part"],
                                                                      payload["keeper"]["sign"], 0]],
               "roster_seq": 0, "joined_at": now(), "invites": [], "access_ids": {}}
        names = seal.unb64(payload["keys"]["names"])
        epochs = {int(e): seal.unb64(k) for e, k in payload["keys"]["epochs"].items()}
    except (SealProblem, ValueError, KeyError, TypeError, AttributeError):
        return None
    access = payload.get("access") or {}
    if new.get("service") == "webdav":   # (this person's own account at the drive; the new folder shared with them)
        # waiting for the new folder to be shared: its own name each round, the whole drive every half hour at most
        last = ctx.state.get("follow_search_at")
        full = not isinstance(last, (int, float)) or not 0 <= time.time() - last < FOLLOW_SEARCH_EVERY
        if full:
            ctx.state["follow_search_at"] = time.time()
        try:
            drive_desc, access = _drive_for_join(sp, {**(ctx.access or {}), "address": ctx.desc.get("endpoint"),
                                                      "confirmed": True}, full=full)
        except SpaceProblem as e:
            ctx.problem("moved", f"The team moved to a folder in the drive at {sp.get('host')} (“{sp.get('folder')}”), "
                                 f"and your copy follows once it can open it: {e} Until then it works with the old "
                                 "storage space.")
            return None
        new.update(drive_desc)
    keychain.put(_secret_name(new["id"], "me"), ctx.ident.dump())
    _put_keys(new["id"], names, epochs)
    _put_secret(new["id"], "access", access)
    _connect(ctx.ws, new, f"The team moved to another storage space ({describe(new)}); this copy followed.")
    ctx.changed_desc = False   # (the old description is not written back)
    return new


def _moved_away(ctx: _Ctx, where: str) -> dict:
    """The team moved where this copy cannot follow by itself (a drive it has no account for): it stops using the old
    space, and the Team tab asks its person to join the new one from a new invite."""
    _forget_secrets(ctx.id, [i.get("part") for i in ctx.desc.get("invites") or []])
    folder._set_config(ctx.ws, **{CONFIG: None})
    ctx.changed_desc = False
    _note(ctx.ws, "space-moved-away", f"The team moved to {where}. Ask the owner for a new invite link to follow.")
    return {"invite_again": True, "where": where}


def _valid_keepers(v: Any) -> list[list] | None:
    """A keepers' history from an invite or a move: [[part, public key, roster number]], or None."""
    if not isinstance(v, list) or not v:
        return None
    out = []
    for x in v:
        if not (isinstance(x, list) and len(x) == 3 and _PART.fullmatch(str(x[0])) and isinstance(x[1], str)
                and _as_int(x[2]) is not None):
            return None
        out.append([x[0], x[1], _as_int(x[2])])
    return out


def _leave_unlocked(ws: Workspace) -> dict:
    """Stop using the storage space on this computer: nothing in the space is removed (it is the team's), what came in
    stays, and this copy's keys for it are forgotten. Returns `status`."""
    desc = configured(ws)
    if desc is None:
        return status(ws)
    _forget_secrets(desc["id"], [i.get("part") for i in desc.get("invites") or []])
    folder._set_config(ws, **{CONFIG: None})
    _note(ws, "space-left", f"Stopped working together through the storage space ({describe(desc)}).")
    return status(ws)


# ---------------------------------------------------------------------------------------------
# one round, and what the Team tab shows
# ---------------------------------------------------------------------------------------------
def _sync_now_unlocked(ws: Workspace, progress: Progress | None = None, should_stop: Callable[[], bool] | None = None,
             deep: bool = False) -> dict:
    """One round through the storage space: bring its news into the mirror, the shared folder's round on the mirror,
    then send this copy's part. Returns the folder round's report (`folder.sync_now`) with "space": `describe`. A
    space that cannot be reached is a problem of kind "unreachable" (the poller waits longer before the next try)."""
    desc = configured(ws)
    out: dict[str, Any] = {"at": now(), "folder": None, "space": describe(desc) if desc else None, "wrote": None,
                           "read": [], "files": 0, "problems": [], "stopped": False}
    say = progress or (lambda *_a: None)
    try:
        ctx = _Ctx(ws, desc)
    except SpaceProblem as e:
        out["problems"].append({"kind": e.kind, "person": None, "message": str(e), "seq": None})
        return out

    def storage_problem(e: StorageProblem, doing: str) -> None:
        kind = "unreachable" if e.kind in ("unreachable", "maintenance") else e.kind
        out["problems"].append({"kind": kind, "person": None, "seq": None,
                                "message": f"ENLENS could not {doing} the storage space: {e}"})

    try:
        say("space", "Looking in the storage space", {})
        moved = _pull(ctx, deep)
    except StorageProblem as e:
        storage_problem(e, "read")
        ctx.save()
        return out
    except (ValueError, TypeError, AttributeError, KeyError) as e:   # (a file of a shape no check foresaw: the copy
        import traceback                                             # here stays as it was; the round goes on)

        traceback.print_exc()
        ctx.problem("set_aside", f"Something in the storage space could not be read ({type(e).__name__}); it was "
                                 "left aside. Your work and your colleagues' is safe.")
        moved = None
    if moved is not None and moved.get("invite_again"):
        out["moved_away"] = moved["where"]
        out["problems"].append({"kind": "moved_away", "person": None, "seq": None,
                                "message": f"The team moved to {moved['where']}, where your copy cannot follow by "
                                           "itself. Ask the owner for a new invite link, then choose Join with an "
                                           "invite link on the Team page. Your work stays in this project."})
        return out
    if moved is not None:
        out["moved"] = describe(moved)
        return out
    ctx.save()
    res = folder._sync_now(ws, progress, should_stop)
    for k in ("wrote", "read", "files", "stopped", "moves_due"):
        if k in res:
            out[k] = res[k]
    out["problems"] += res.get("problems") or []
    try:
        if not any(x.get("person") is None and x.get("kind") != "set_aside" for x in out["problems"]):
            say("space", "Sending your shared work to the storage space", {})
            out["sent"] = _push(ctx)
            _hand_over_if_owner_changed(ctx)
            _clean_temporaries(ctx)
    except StorageProblem as e:
        storage_problem(e, "write to")
    finally:
        ctx.save()
    out["problems"] += [p for p in ctx.problems if p not in out["problems"]]
    return out


def _clean_temporaries(ctx: _Ctx) -> None:
    """The keeper's round on a drive removes what writes cut off halfway left behind (hidden `.enlens-…` files older
    than a day): the whole space is looked through once a day, a handful of files removed per round, best effort."""
    from .storage import WebDAVStorage

    if not ctx.keeper or not isinstance(ctx.store, WebDAVStorage):
        return
    last = ctx.state.get("temporaries_at")
    if isinstance(last, (int, float)) and 0 <= time.time() - last < 86400:
        return
    try:
        ctx.store.list("")
        if ctx.store.clean_temporaries(86400, 5) < 5:   # (more left: the next round goes on)
            ctx.state["temporaries_at"] = time.time()
    except StorageProblem:
        pass


def describe(desc: dict | None) -> str | None:
    if not desc:
        return None
    service = desc.get("service")
    if service == "b2":
        return f"Backblaze B2, {desc.get('bucket')} ({desc.get('region')})"
    if service == "r2":
        return f"Cloudflare R2, {desc.get('bucket')} (EU)"
    if service == "dir":
        return f"a folder on this computer ({desc.get('dir')})"
    if service == "webdav":
        return f"the drive at {desc.get('host')}, folder “{desc.get('folder')}”"
    return "a storage space"


def _member_name(ws: Workspace, pid: str | None, state: dict | None = None) -> str:
    """A member's name: as the project knows it, as their person.json in the mirror says, or as they gave it when
    they joined (`_bind_joins` keeps it, on this computer only)."""
    if not pid:
        return "a colleague"
    row = ws._conn().execute("SELECT name FROM people WHERE person_id=?", (pid,)).fetchone()
    if row and row[0]:
        return row[0]
    base = mirror_of(ws)
    if base is not None:
        pj = folder._json(base / folder.team_name(ws) / pid / "person.json") or {}
        if str(pj.get("name") or "").strip():
            return str(pj["name"]).strip()[:80]
    return str(((state or {}).get("names") or {}).get(pid) or "").strip()[:80] or "a colleague"


def status(ws: Workspace) -> dict | None:
    """What the Team tab shows of the storage space (None: the project has none): {"id", "service", "where", "region",
    "in_eu", "keeper" (this copy keeps its keys), "joined": whether the owner's copy has bound this copy's part yet,
    "members": [{"part", "person", "name", "me", "keeper", "removed", "since"}], "invites": [{"part", "made_at",
    "label"}], "set_aside": [{"part", "why", "message", "at"}], "keychain"}."""
    desc = configured(ws)
    if desc is None:
        return None
    base = mirror_of(ws)
    try:
        state = json.loads((base / ".space-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    roster = state.get("roster") or {}
    me = people.me()
    members = []
    for part, m in sorted((roster.get("members") or {}).items(), key=lambda x: str(x[1].get("since") or "")):
        members.append({"part": part, "person": m.get("person"), "name": _member_name(ws, m.get("person"), state)
                        if m.get("person") != me else (people.my_name() or "You"), "me": part == desc.get("part"),
                        "keeper": part == desc.get("keeper_part"), "removed": m.get("removed"),
                        "since": m.get("since")})
    return {"id": desc["id"], "service": desc.get("service"), "where": describe(desc), "region": desc.get("region"),
            "in_eu": desc.get("in_eu"), "keeper": desc.get("keeper_part") == desc.get("part"),
            "joined": desc.get("part") in (roster.get("members") or {}), "members": members,
            "invites": [{k: i.get(k) for k in ("part", "made_at", "label")} for i in desc.get("invites") or []],
            "set_aside": [{k: v.get(k) for k in ("part", "why", "message", "at")}
                          for v in (state.get("aside") or {}).values()],
            "keychain": keychain.backend(),
            "drive": _drive_status(desc) if desc.get("service") == "webdav" else None}


def _drive_status(desc: dict) -> dict:
    """The Team tab's lines about a drive: where, as whom, and whose drive holds the folder ("mine": this person's;
    "holder": the name to show otherwise, who alone can share the folder or stop sharing it)."""
    mine, holder = _folder_holder(desc)
    return {"host": desc.get("host"), "folder": desc.get("folder"), "address": desc.get("endpoint"),
            "user": desc.get("user"), "mine": mine, "holder": None if mine else holder}


def _set_drive_password_unlocked(ws: Workspace, user: str, password: str) -> dict:
    """A new app password for the drive (the old one was removed or expired): checked on the project's folder, then
    kept in the keychain in place of the old. Returns `status`."""
    from . import webdav

    desc = configured(ws)
    if desc is None or desc.get("service") != "webdav":
        raise SpaceProblem("This project does not work through a drive.", "no_space")
    user, password = (user or "").strip(), (password or "").strip()
    if not user or not password:
        raise SpaceProblem("Enter your user name at the drive and an app password.", "input")
    _dav(lambda: webdav.check(desc["endpoint"], user, password))
    try:
        if webdav.storage(desc["endpoint"], user, password, folder=desc["folder"]).propfind("") is None:
            raise SpaceProblem(f"The folder “{desc['folder']}” is not in this account's drive.", "folder_not_found")
    except StorageProblem as e:
        raise SpaceProblem(str(e), e.kind) from e
    _put_secret(desc["id"], "access", {"user": user, "password": password})
    _save(ws, {**desc, "user": user})
    webdav.remember(desc["endpoint"])
    _note(ws, "space-password", "Entered a new app password for the drive.")
    return status(ws)


# ---------------------------------------------------------------------------------------------
# the public calls, one at a time per project (`_locked`)
# ---------------------------------------------------------------------------------------------
def invite(ws: Workspace, label: str | None = None, drive_user: str | None = None) -> dict:
    with _locked(ws):
        return _invite_unlocked(ws, label, drive_user)
invite.__doc__ = _invite_unlocked.__doc__


def cancel_invite(ws: Workspace, part: str) -> dict:
    with _locked(ws):
        return _cancel_invite_unlocked(ws, part)
cancel_invite.__doc__ = _cancel_invite_unlocked.__doc__


def remove_member(ws: Workspace, part: str) -> dict:
    with _locked(ws):
        return _remove_member_unlocked(ws, part)
remove_member.__doc__ = _remove_member_unlocked.__doc__


def move(ws: Workspace, start: Callable[[Workspace, Identity], dict]) -> dict:
    with _locked(ws):
        return _move_unlocked(ws, start)
move.__doc__ = _move_unlocked.__doc__


def leave(ws: Workspace) -> dict:
    with _locked(ws):
        return _leave_unlocked(ws)
leave.__doc__ = _leave_unlocked.__doc__


def sync_now(ws: Workspace, progress: Progress | None = None, should_stop: Callable[[], bool] | None = None,
             deep: bool = False) -> dict:
    with _locked(ws):
        return _sync_now_unlocked(ws, progress, should_stop, deep)
sync_now.__doc__ = _sync_now_unlocked.__doc__


def setup_dir(ws: Workspace, path: str | os.PathLike, ident: Identity | None = None) -> dict:
    with _locked(ws):
        return _setup_dir_unlocked(ws, path, ident)
setup_dir.__doc__ = _setup_dir_unlocked.__doc__


def setup_b2(ws: Workspace, key_id: str, app_key: str, progress: Progress | None = None,
             ident: Identity | None = None) -> dict:
    with _locked(ws):
        return _setup_b2_unlocked(ws, key_id, app_key, progress, ident)
setup_b2.__doc__ = _setup_b2_unlocked.__doc__


def setup_r2(ws: Workspace, token: str, account_id: str | None = None, progress: Progress | None = None,
             ident: Identity | None = None) -> dict:
    with _locked(ws):
        return _setup_r2_unlocked(ws, token, account_id, progress, ident)
setup_r2.__doc__ = _setup_r2_unlocked.__doc__


def setup_webdav(ws: Workspace, address: str, user: str, password: str, progress: Progress | None = None,
                 ident: Identity | None = None) -> dict:
    with _locked(ws):
        return _setup_webdav_unlocked(ws, address, user, password, progress, ident)
setup_webdav.__doc__ = _setup_webdav_unlocked.__doc__


def set_drive_password(ws: Workspace, user: str, password: str) -> dict:
    with _locked(ws):
        return _set_drive_password_unlocked(ws, user, password)
set_drive_password.__doc__ = _set_drive_password_unlocked.__doc__


def join(ws: Workspace, link: str, drive: dict | None = None) -> dict:
    with _locked(ws):
        return _join_unlocked(ws, link, drive)
join.__doc__ = _join_unlocked.__doc__

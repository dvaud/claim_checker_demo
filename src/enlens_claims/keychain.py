"""Secrets kept in the system's keychain (0.18.0rc2, roadmap L6): the keys of a team's storage space, the project's
key and this copy's own signing keys. Never in a project's database, its config.json, a zip or the shared folder.

    put(name, secret)    keep a secret under a name (replacing one of that name)
    get(name)            the secret, or None
    delete(name)         forget it (none there: no error)
    backend()            where secrets are kept: "macos", "windows", "secret-tool" or "file"

All secrets are kept under the service name "ENLENS". `ENLENS_KEYCHAIN=file` keeps them in files in ENLENS's own
folder instead (`<home>/keys/`, readable by this user only): tests always use it (tests/conftest.py), and so does a
computer without a keychain ENLENS can use.

The system keychains: macOS through `security` (the secret goes in on its standard input, never on a command line,
where other users' `ps` would show it), Windows through the Credential Manager (ctypes, advapi32), Linux through
`secret-tool` when it is there and answers. A secret is stored in the keychain as base64 text, so no character in it
can upset a program's parser (macOS prints a secret with an accent as hex). When the keychain refuses a secret
(locked, no access, no D-Bus) it is kept in the file instead, never lost; `get` finds it there (a file's copy is the newer one: a put that
reaches the keychain removes it). Programs can be pointed elsewhere for tests: ENLENS_SECURITY and ENLENS_SECRET_TOOL.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from .procs import no_window

SERVICE = "ENLENS"
PREFIX = "b64:"
TIMEOUT = 20.0
MAX_WINDOWS_BYTES = 2560   # the Credential Manager's limit for one blob


def _security() -> str:
    return os.environ.get("ENLENS_SECURITY") or "security"


def _secret_tool() -> str:
    return os.environ.get("ENLENS_SECRET_TOOL") or "secret-tool"


_tool_answers: dict[str, bool] = {}


def _secret_tool_answers() -> bool:
    """Whether secret-tool is there and a keyring answers (asked once per program path)."""
    prog = _secret_tool()
    if prog not in _tool_answers:
        import shutil

        ok = False
        if shutil.which(prog):
            try:
                r = subprocess.run([prog, "lookup", "service", SERVICE, "account", "__probe__"], capture_output=True,
                                   text=True, timeout=TIMEOUT, **no_window())
                ok = r.returncode in (0, 1) and not r.stderr.strip()
            except (OSError, subprocess.SubprocessError):
                ok = False
        _tool_answers[prog] = ok
    return _tool_answers[prog]


def backend() -> str:
    forced = os.environ.get("ENLENS_KEYCHAIN", "").strip().lower()
    if forced == "file":
        return "file"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if _secret_tool_answers():
        return "secret-tool"
    return "file"


def _encode(secret: str) -> str:
    return PREFIX + base64.b64encode(secret.encode("utf-8")).decode("ascii")


def _decode(text: str) -> str | None:
    if not text.startswith(PREFIX):
        return None
    try:
        return base64.b64decode(text[len(PREFIX):].encode("ascii"), validate=True).decode("utf-8")
    except (ValueError, UnicodeError):
        return None


class _Refused(Exception):
    """The system keychain did not take, or give, the secret."""


def _quote(text: str) -> str:
    """A word for `security -i`'s parser: double quotes, backslash before a quote or a backslash."""
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise _Refused("a control character in a name")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---- macOS ----------------------------------------------------------------------------------------------
def _mac_put(name: str, secret: str) -> None:
    line = f"add-generic-password -U -s {SERVICE} -a {_quote(name)} -w {_quote(_encode(secret))}\n"
    try:
        r = subprocess.run([_security(), "-i"], input=line, capture_output=True, text=True, timeout=TIMEOUT, **no_window())
    except (OSError, subprocess.SubprocessError) as e:
        raise _Refused(str(e)) from e
    if r.returncode != 0 or r.stderr.strip():   # `security -i` says what went wrong on stderr and may still exit 0
        raise _Refused("security refused")


def _mac_get(name: str) -> str | None:
    try:
        r = subprocess.run([_security(), "find-generic-password", "-s", SERVICE, "-a", name, "-w"], capture_output=True,
                           text=True, timeout=TIMEOUT, **no_window())
    except (OSError, subprocess.SubprocessError):
        return None
    return _decode(r.stdout.strip()) if r.returncode == 0 else None


def _mac_delete(name: str) -> None:
    try:
        subprocess.run([_security(), "delete-generic-password", "-s", SERVICE, "-a", name], capture_output=True,
                       timeout=TIMEOUT, **no_window())
    except (OSError, subprocess.SubprocessError):
        pass


# ---- Linux ----------------------------------------------------------------------------------------------
def _tool_put(name: str, secret: str) -> None:
    try:
        r = subprocess.run([_secret_tool(), "store", f"--label={SERVICE}: {name}", "service", SERVICE, "account", name],
                           input=_encode(secret), capture_output=True, text=True, timeout=TIMEOUT, **no_window())
    except (OSError, subprocess.SubprocessError) as e:
        raise _Refused(str(e)) from e
    if r.returncode != 0:
        raise _Refused("secret-tool refused")


def _tool_get(name: str) -> str | None:
    try:
        r = subprocess.run([_secret_tool(), "lookup", "service", SERVICE, "account", name], capture_output=True,
                           text=True, timeout=TIMEOUT, **no_window())
    except (OSError, subprocess.SubprocessError):
        return None
    return _decode(r.stdout.strip()) if r.returncode == 0 else None


def _tool_delete(name: str) -> None:
    try:
        subprocess.run([_secret_tool(), "clear", "service", SERVICE, "account", name], capture_output=True,
                       timeout=TIMEOUT, **no_window())
    except (OSError, subprocess.SubprocessError):
        pass


# ---- Windows: the Credential Manager --------------------------------------------------------------------
def _win_api():
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    adv.CredWriteW.restype = wintypes.BOOL
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    adv.CredReadW.restype = wintypes.BOOL
    adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    adv.CredDeleteW.restype = wintypes.BOOL
    adv.CredFree.argtypes = [ctypes.c_void_p]
    adv.CredFree.restype = None
    return ctypes, CREDENTIAL, adv


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


def _win_put(name: str, secret: str) -> None:
    blob = secret.encode("utf-8")
    if len(blob) > MAX_WINDOWS_BYTES:
        raise ValueError(f"A secret can be at most {MAX_WINDOWS_BYTES} bytes in the Windows Credential Manager.")
    ctypes, CREDENTIAL, adv = _win_api()
    buf = (ctypes.c_ubyte * max(len(blob), 1)).from_buffer_copy(blob or b"\0")
    cred = CREDENTIAL()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = f"{SERVICE}:{name}"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = SERVICE
    if not adv.CredWriteW(ctypes.byref(cred), 0):
        raise _Refused("CredWriteW failed")


def _win_get(name: str) -> str | None:
    ctypes, CREDENTIAL, adv = _win_api()
    out = ctypes.POINTER(CREDENTIAL)()
    if not adv.CredReadW(f"{SERVICE}:{name}", CRED_TYPE_GENERIC, 0, ctypes.byref(out)):
        return None
    try:
        c = out.contents
        data = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize) if c.CredentialBlobSize else b""
    finally:
        adv.CredFree(out)
    try:
        return data.decode("utf-8")
    except UnicodeError:
        return None


def _win_delete(name: str) -> None:
    ctypes, CREDENTIAL, adv = _win_api()
    adv.CredDeleteW(f"{SERVICE}:{name}", CRED_TYPE_GENERIC, 0)


_SYSTEM = {"macos": (_mac_put, _mac_get, _mac_delete), "windows": (_win_put, _win_get, _win_delete),
           "secret-tool": (_tool_put, _tool_get, _tool_delete)}


def _file(name: str) -> Path:
    from .home import home

    return home() / "keys" / (hashlib.sha256(f"{SERVICE}:{name}".encode()).hexdigest()[:32] + ".json")


def _file_put(name: str, secret: str) -> None:
    f = _file(name)
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(f.parent, 0o700)
    except OSError:
        pass
    part = f.with_name(f.name + ".part")
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump({"name": name, "secret": secret}, out)
    os.replace(part, f)


def _file_get(name: str) -> str | None:
    try:
        data = json.loads(_file(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("secret") if isinstance(data, dict) and data.get("name") == name else None


def _file_delete(name: str) -> None:
    try:
        _file(name).unlink()
    except FileNotFoundError:
        pass


def put(name: str, secret: str) -> None:
    """Keep `secret` under `name`: in the system keychain, or, when that refuses it (or it is too long for the Windows
    Credential Manager), in the file (never lost)."""
    kind = backend()
    if kind != "file":
        try:
            _SYSTEM[kind][0](name, secret)
        except (_Refused, ValueError):
            _SYSTEM[kind][2](name)   # an older secret in the keychain must not outrank the newer one in the file
            _file_put(name, secret)
            return
        _file_delete(name)   # an older copy in the file must not outlive the one in the keychain
        return
    _file_put(name, secret)


def get(name: str) -> str | None:
    """The secret. A file's copy is looked at first: it exists only while the keychain refused the secret (a put that
    reaches the keychain removes it), so it is the newer one."""
    kind = backend()
    kept = _file_get(name)
    if kept is not None:
        return kept
    if kind != "file":
        found = _SYSTEM[kind][1](name)
        if found is not None:
            return found
    return None


def delete(name: str) -> None:
    kind = backend()
    if kind != "file":
        _SYSTEM[kind][2](name)
    _file_delete(name)

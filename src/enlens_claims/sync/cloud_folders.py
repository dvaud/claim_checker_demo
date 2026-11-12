"""The cloud folders this computer already has, offered by name (0.18.0rc2, roadmap L7), so a shared folder is chosen
from a short list, and a colleague's ENLENS can find the team's folder among them.

    offered(home=None, platform=None)      [{"name", "path", "service"}]: OneDrive, Google Drive, Box, Dropbox and the like
    find_team(team_name, depth=3, ...)     the folders among them that hold a folder named `team_name`

macOS: every folder in ~/Library/CloudStorage/ and ~/Dropbox; Windows: the folders %OneDrive%, %OneDriveCommercial% and
%OneDriveConsumer% name, and Dropbox's (info.json); Linux: ~/Dropbox and Dropbox's info.json. For tests the home folder
can be given (a function argument, or the environment variable ENLENS_CLOUD_HOME), and the system too (`platform`).
Standard library only; nothing here reads a file's content."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SEARCH_SECONDS = 2.0   # find_team stops looking after this long (a cloud folder can be slow to list)
DASH = "–"


def _home(home: str | os.PathLike | None) -> Path:
    return Path(home or os.environ.get("ENLENS_CLOUD_HOME") or Path.home())


def _service(folder_name: str) -> str:
    low = folder_name.lower().replace(" ", "")
    for key, service in (("onedrive", "onedrive"), ("googledrive", "googledrive"), ("box", "box"), ("dropbox", "dropbox"),
                         ("surfdrive", "surfdrive"), ("syncthing", "syncthing")):
        if low.startswith(key):
            return service
    return "other"


def _display(folder_name: str) -> str:
    """A plain name from a folder's name: "OneDrive-UniversityofAmsterdam" -> "OneDrive – UniversityofAmsterdam",
    "GoogleDrive-anna@x.org" -> "Google Drive – anna@x.org", "Box-Box" -> "Box"."""
    name = folder_name.strip()
    for old, new in (("GoogleDrive", "Google Drive"), ("ProtonDrive", "Proton Drive"), ("SynologyDrive", "Synology Drive")):
        if name.startswith(old):
            name = new + name[len(old):]
    head, sep, tail = name.partition("-")
    if sep and tail and tail.lower() != head.lower():
        return f"{head.strip()} {DASH} {tail.strip()}"
    if sep and tail:
        return head.strip()
    return name.replace(" - ", f" {DASH} ")


def _dropbox_info(home: Path, platform: str) -> list[tuple[str, str]]:
    """(label, path) from Dropbox's own info.json: "personal" and "business"."""
    places = [home / ".dropbox" / "info.json"]
    if platform == "win32":
        places = [Path(os.environ[k]) / "Dropbox" / "info.json" for k in ("APPDATA", "LOCALAPPDATA") if os.environ.get(k)]
    out: list[tuple[str, str]] = []
    for f in places:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for kind in ("personal", "business"):
            entry = data.get(kind)
            if isinstance(entry, dict) and isinstance(entry.get("path"), str) and entry["path"]:
                out.append(("Dropbox" if kind == "personal" else f"Dropbox {DASH} business", entry["path"]))
    return out


def offered(home: str | os.PathLike | None = None, platform: str | None = None) -> list[dict]:
    """The cloud folders this computer has, as {"name", "path", "service"}, each folder once, the ones named first
    (OneDrive, Google Drive, Box, Dropbox) before others."""
    h = _home(home)
    system = platform or sys.platform
    found: list[tuple[str, Path]] = []   # (display name, folder)
    if system == "darwin":
        root = h / "Library" / "CloudStorage"
        try:
            kids = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            kids = []
        found += [(_display(k.name), k) for k in kids if not k.name.startswith(".") and k.is_dir()]
    if system == "win32":
        for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
            value = os.environ.get(var)
            if value:
                p = Path(value)
                found.append((_display(p.name) or "OneDrive", p))
    found.append(("Dropbox", h / "Dropbox"))
    found += [(label, Path(path)) for label, path in _dropbox_info(h, system)]
    out: list[dict] = []
    seen: set[str] = set()
    for name, p in found:
        try:
            if not p.is_dir():
                continue
            key = os.path.normcase(os.path.realpath(p))
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "path": str(p), "service": _service(name)})
    order = {"onedrive": 0, "googledrive": 1, "box": 2, "dropbox": 3}
    out.sort(key=lambda f: (order.get(f["service"], 9), f["name"].lower()))
    return out


def find_team(team_name: str, depth: int = 3, home: str | os.PathLike | None = None, platform: str | None = None,
              budget: float = SEARCH_SECONDS) -> list[str]:
    """The folders (paths) that hold a folder named `team_name`, among the cloud folders and up to `depth` levels below
    them (the cloud folder itself counts), skipping hidden folders and stopping after `budget` seconds. These are the
    shared folders to choose: the team's own folder is inside them. A folder that holds it is not searched further."""
    if not team_name:
        return []
    stop = time.monotonic() + budget
    found: list[str] = []
    for cloud in offered(home, platform):
        level = [cloud["path"]]
        for _ in range(max(depth, 0) + 1):
            nxt: list[str] = []
            for d in level:
                if time.monotonic() > stop:
                    return found
                try:
                    with os.scandir(d) as it:
                        kids = [e for e in it if not e.name.startswith(".") and e.is_dir()]
                except OSError:
                    continue
                if any(e.name == team_name for e in kids):
                    if d not in found:
                        found.append(d)
                else:
                    nxt += [e.path for e in kids]
            level = nxt
    return found

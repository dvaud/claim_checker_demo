"""How this ENLENS was installed, and what follows from it (0.10).

ENLENS can be installed in three ways, and updating, the help text and the Claude Code plugin depend on which:

- ``git``: a git copy installed editable (clone, venv, ``pip install -e .``): the developer's route. ``enlens update``
  pulls the new version (update.py).
- ``script``: the one-line install (``install.sh`` / ``install.ps1`` from a GitHub Release). It fetches uv, which
  brings its own Python, and installs the release wheel with ``uv tool install``: no git, no venv, no pip.
  ``enlens update`` installs the newest release the same way; running the line again does the same.
- ``package``: a packaged app with its own Python (dmg, setup.exe, AppImage; planned for 0.11).

Anything else (``pip install`` of the wheel, say) is ``pip``. The installers write a marker next to the Python they
installed into, ``<sys.prefix>/enlens-install.json``; a git copy needs none (update.source_root() finds it).

``enlens post-install`` is what the installers run last: it writes the marker, makes the ENLENS icon, repairs the
Claude Code plugin when the Python it names has moved, and (with ``--open``) starts the app.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import __version__

REPO = "dvaud/claim_checker_demo"
MARKER = "enlens-install.json"
KINDS = ("git", "script", "package", "pip")
EXTRAS = ("connector", "fast", "pdfminer", "ocr")   # what the one-line install and the packages bring


def marker_path(prefix: str | Path | None = None) -> Path:
    return Path(prefix or sys.prefix) / MARKER


def read_marker(prefix: str | Path | None = None) -> dict:
    try:
        data = json.loads(marker_path(prefix).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_marker(kind: str, prefix: str | Path | None = None, **extra) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unknown kind of installation: {kind!r} (one of {', '.join(KINDS)})")
    p = marker_path(prefix)
    p.write_text(json.dumps({"kind": kind, "version": __version__, "installed": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "repo": REPO, "python": sys.executable, **extra}, indent=2), encoding="utf-8")
    return p


def kind() -> str:
    """git, script, package or pip (see the module's notes)."""
    from . import update

    if update.source_root() is not None:
        return "git"
    k = read_marker().get("kind")
    return k if k in KINDS and k != "git" else "pip"


def system() -> str:
    return "windows" if os.name == "nt" else "mac" if sys.platform == "darwin" else "linux"


def install_line(sys_name: str | None = None) -> str:
    """The one line that installs (or updates) ENLENS on this kind of computer."""
    base = f"https://github.com/{REPO}/releases/latest/download"
    if (sys_name or system()) == "windows":
        return f'powershell -ExecutionPolicy Bypass -c "irm {base}/install.ps1 | iex"'
    return f"curl -fsSL {base}/install.sh | sh"


def double_click_file(sys_name: str | None = None) -> str:
    """0.14.5: where the latest release's install file to double-click is, for this kind of computer ("" on Linux)."""
    name = {"windows": "Install-ENLENS-Windows.cmd", "mac": "Install-ENLENS-macOS.zip"}.get(sys_name or system(), "")
    return f"https://github.com/{REPO}/releases/latest/download/{name}" if name else ""


def info() -> dict:
    """For the app's Settings → Technical and `enlens update`: how this copy was installed and how it updates."""
    k = kind()
    how = {
        "git": "a git copy (developer): `enlens update` fetches the new version into it",
        "script": "the one-line install: `enlens update`, or running the install line again, installs the newest release",
        "package": "the ENLENS download for this system: download the newest one from the releases page",
        "pip": "pip: `pip install --upgrade` the newest wheel from the releases page",
    }[k]
    return {"kind": k, "version": __version__, "python": sys.executable, "marker": read_marker(),
            "updates": how, "install_line": install_line(), "releases": f"https://github.com/{REPO}/releases"}


def technical_details(settings: dict | None = None, local_only: bool | None = None) -> str:
    """0.15: a short plain-text block a person pastes into a problem report (Settings → Technical → Copy technical
    details). The version, how ENLENS was installed, the operating system, Python, the AI route, whether
    --local-only is on and the update channel. Never a path, a project or document name, a user name or a key."""
    import platform

    from . import home

    s = settings if settings is not None else home.load_settings()
    off = home.local_only() if local_only is None else local_only
    route = home.BACKEND_LABELS.get(s.get("backend", ""), str(s.get("backend", "")))
    if kind() == "git":
        channel = "follows main (git copy)"
    else:
        channel = "early (release candidates too)" if s.get("update_channel") == "early" else "stable"
    shown = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[system()]
    return "\n".join([
        f"ENLENS version: {__version__}",
        f"Installed: {kind()}",
        f"System: {shown} {platform.release()} ({platform.machine()})",
        f"Python: {platform.python_version()}",
        f"AI route: {route}",
        f"Local only: {'yes' if off else 'no'}",
        f"Update channel: {channel}",
    ])


def printable_streams() -> None:
    """0.15.2: on Windows, when what ENLENS prints goes to a pipe (an installer reading it, say), Python writes it in
    the computer's code page, and a letter that page lacks ("ő" in C:\\Users\\Gergő, on an English Windows) stopped
    the command with an error after its work was done. Such a letter is now written as an escape instead."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and (stream.encoding or "").lower().replace("-", "") != "utf8":
                stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def post_install(by: str | None = "script", icon: bool = True, open_app: bool = False, home: str | None = None,
                 local_only: bool | None = None) -> dict:
    """What an installer does last (`enlens post-install`). Returns what was done, with a message to print."""
    from . import claude_setup
    from . import home as core

    out: dict = {"version": __version__, "marker": "", "icons": [], "plugin": {}, "running": None, "opened": False}
    if by:
        out["marker"] = str(write_marker(by))
    lo = core.local_only() if local_only is None else local_only
    if icon:
        from .gui.launcher import make_launcher

        try:
            out["icons"] = [str(p) for p in make_launcher(home, lo)]
        except OSError as e:
            out["icon_error"] = str(e)
    out["plugin"] = claude_setup.repair(run_claude=True)
    try:
        from .gui import launcher

        out["running"] = launcher.running()
    except Exception:  # noqa: BLE001
        out["running"] = None
    if open_app:
        out["opened"] = _open(out["running"], home, lo)
    lines = [f"ENLENS {__version__} is installed."]
    if out["icons"]:
        lines.append("Start it from its icon: " + "; ".join(out["icons"]))
    if out["plugin"].get("repaired"):
        lines.append("The Claude Code plugin now uses this installation.")
    if out["running"] and out["running"].get("version") not in (None, __version__):
        lines.append(f"ENLENS {out['running'].get('version')} is still running: choose Quit ENLENS in it, then open "
                     "ENLENS again from its icon.")
    elif out["opened"]:
        lines.append("ENLENS is opening in your browser.")
    out["message"] = "\n".join(lines)
    return out


def _open(running: dict | None, home: str | None, local_only: bool) -> bool:
    """Open the app as its icon would: show the running copy, or start one in the background."""
    import subprocess

    if running:
        if running.get("version") == __version__:
            from .gui.launcher import browse, open_link

            browse(open_link(running))  # 0.17.2: with its token (the page has none)
            return True
        return False  # an older copy runs: it has to be quit first
    from .gui.launcher import _args

    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    cmd = [str(pyw if os.name == "nt" and pyw.exists() else exe), *_args(home, local_only)]
    kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000008 | 0x00000200}
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **kwargs)  # console: Windows starts pythonw, a program without one, detached
    except OSError:
        return False
    return True

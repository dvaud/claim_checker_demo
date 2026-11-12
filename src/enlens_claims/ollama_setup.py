"""0.15.6: Ollama installed from the app with one button, as Claude Code is.

The card for a model on this computer said "Get Ollama" and linked to ollama.com, and promised no terminal. But
ollama.com's download page now leads with a line to type in a terminal (`irm https://ollama.com/install.ps1 | iex`,
`curl -fsSL https://ollama.com/install.sh | sh`), with "Download manually" in small print. Those lines only download
Ollama's own installer, check that it is Ollama's, install it for this user and start it hidden. ENLENS does the same
here, after the person has seen how big the download is on their kind of computer (1.7 GB for Windows, 230 MB for
macOS in November 2026) and how much free space it needs, with its progress and a Stop button:

- Windows: OllamaSetup.exe, which must be signed by Ollama Inc. (checked as install.ps1 checks it), installed with its
  silent per-user mode into %LOCALAPPDATA%\\Programs\\Ollama (no administrator rights). The installer starts Ollama
  itself; the "upgraded" marker install.ps1 leaves makes it start hidden, in the tray.
- macOS: Ollama-darwin.zip, unpacked with ditto (which keeps the app's links and permissions), checked with codesign
  against Ollama's Developer ID team, moved to /Applications (or ~/Applications when that cannot be written) and
  opened hidden, as install.sh does. ENLENS needs no `ollama` command, so it adds none: that is the step for which
  install.sh asks for a password.
- Linux: Ollama's installer needs the administrator password (it installs for everyone and sets up a service), so
  ENLENS opens a terminal window running Ollama's own line, where the person types it.

An Ollama that is on the computer but not running is started with one button instead. Nothing of the person's is
sent: the download comes from ollama.com (which hands it over from Ollama's releases on GitHub)."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import __version__
from . import home as core
from .installation import system
from .procs import no_window

SITE = "https://ollama.com/download"
FILES = {"windows": "OllamaSetup.exe", "mac": "Ollama-darwin.zip"}
# the sizes in November 2026 (Ollama 0.40), shown as "about" when ollama.com cannot be asked
APPROX = {"windows": 1_700_000_000, "mac": 230_000_000, "linux": 1_600_000_000}
LINUX_LINE = "curl -fsSL https://ollama.com/install.sh | sh"
# Ollama's Developer ID on macOS: "Developer ID Application: Infra Technologies, Inc (3MU9H2V9Y9)". The requirement
# asks for a Developer ID certificate (not a development one) of that team, and Apple's notarisation: a file fetched
# by ENLENS carries no quarantine flag, so Gatekeeper never looks at it. Ollama staples the ticket to the app, so this
# holds offline too.
MAC_TEAM = "3MU9H2V9Y9"
MAC_REQUIREMENT = ("anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] exists and "
                   f'certificate leaf[field.1.2.840.113635.100.6.1.13] exists and certificate leaf[subject.OU] = "{MAC_TEAM}" '
                   "and notarized")
# install.ps1's own test of OllamaSetup.exe's signer, anchored so "O=Not Ollama Inc." does not pass
WIN_SIGNER = re.compile(r"(^|, )O=Ollama Inc\.(,|$)")
# free space asked for, as a multiple of the download: the file itself and Ollama unpacked (on macOS the 230 MB zip
# becomes a 693 MB app)
ROOM = 4
DEFAULT_URL = "http://localhost:11434"
UA = f"enlens/{__version__}"

Progress = Callable[[dict], None]


def base() -> str:
    """Where the installers come from. ENLENS_OLLAMA_DOWNLOAD replaces it (for the tests)."""
    return (os.environ.get("ENLENS_OLLAMA_DOWNLOAD") or SITE).rstrip("/")


def download_url(sys_name: str | None = None) -> str:
    name = sys_name or system()
    if name == "linux":   # what install.sh downloads, for the size only: on Linux the installer itself downloads it
        arch = "arm64" if platform.machine().lower() in ("aarch64", "arm64") else "amd64"
        return f"{base()}/ollama-linux-{arch}.tar.zst"
    return f"{base()}/{FILES[name]}"


def manual_url(sys_name: str | None = None) -> str:
    """The installer itself, for doing it by hand: not the download page, which leads with a line for a terminal."""
    name = sys_name or system()
    return {"windows": f"{SITE}/OllamaSetup.exe", "mac": f"{SITE}/Ollama.dmg"}.get(name, f"{SITE}/linux")


def mac_folders() -> list[Path]:
    return [Path("/Applications"), Path.home() / "Applications"]


def _on_path(name: str) -> str | None:
    return shutil.which(name)


def app_path(sys_name: str | None = None) -> Path | None:
    """Ollama on this computer (running or not), or None: the Ollama app (Windows' "ollama app.exe", macOS'
    Ollama.app), else the `ollama` program alone (Linux, or Homebrew's on a Mac), which start() runs as `ollama serve`."""
    name = sys_name or system()
    found: list[Path] = []
    exe = _on_path("ollama")
    if name == "windows":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            found.append(Path(local) / "Programs" / "Ollama" / "ollama app.exe")
        if exe:
            found.append(Path(exe).parent / "ollama app.exe")
    elif name == "mac":
        found = [d / "Ollama.app" for d in mac_folders()]
    if exe:
        found.append(Path(exe))
    return next((p for p in found if p.exists()), None)


def serves(path: Path) -> bool:
    """Whether `path` is the `ollama` program alone (started as `ollama serve`) rather than the Ollama app."""
    return path.suffix.lower() != ".app" and path.name.lower() != "ollama app.exe"


def status(sys_name: str | None = None) -> dict:
    """For the page (cheap: it is asked every few seconds): whether Ollama is on this computer, and how the app gets
    it here ("app": ENLENS downloads and installs it; "terminal": a terminal window runs Ollama's own line)."""
    name = sys_name or system()
    path = app_path(name)
    return {"installed": bool(path), "path": str(path or ""), "system": name,
            "how": "terminal" if name == "linux" else "app", "line": LINUX_LINE if name == "linux" else "",
            "manual": manual_url(name)}


_SIZE: dict[str, tuple[float, dict]] = {}


def download_size(sys_name: str | None = None) -> dict:
    """{"bytes", "exact"}: the size of Ollama's download for this kind of computer, as ollama.com says it now (kept an
    hour), else the size known in November 2026 ("exact": False)."""
    from urllib.request import Request, urlopen

    name = sys_name or system()
    url = download_url(name)
    hit = _SIZE.get(url)
    if hit and time.time() - hit[0] < 3600:
        return dict(hit[1])
    try:
        # a HEAD request follows ollama.com's redirects to the file on GitHub, whose answer gives the size
        with urlopen(Request(url, method="HEAD", headers={"User-Agent": UA}), timeout=8) as r:
            n = int(r.headers.get("Content-Length") or 0)
        if n > 0:
            _SIZE[url] = (time.time(), {"bytes": n, "exact": True})
            return {"bytes": n, "exact": True}
    except (OSError, ValueError):
        pass
    return {"bytes": APPROX.get(name, 0), "exact": False}


def downloads() -> Path:
    """Where the installer is downloaded and unpacked: a folder of ENLENS's own, emptied when an install begins and
    when the app starts (an install cut short by quitting the app leaves its file here, up to 1.7 GB)."""
    return core.home() / "downloads" / "ollama"


def clear_downloads() -> None:
    shutil.rmtree(downloads(), ignore_errors=True)


def free_space(where: Path | None = None) -> int:
    try:
        return shutil.disk_usage(where or core.home()).free
    except OSError:
        return 0


def plan(sys_name: str | None = None) -> dict:
    """What the page shows before anything is downloaded: the size, the room it needs and the room there is."""
    name = sys_name or system()
    size = download_size(name)
    return {**status(name), "size": size, "needs": size["bytes"] * ROOM, "free": free_space(), "from": download_url(name)}


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(1, round(n / 1e6))} MB"


def _room(total: int, where: Path) -> None:
    need, free = total * ROOM, free_space(where)
    if free and free < need:
        raise ValueError(f"There is not enough free disk space for Ollama: it needs about {gb(need)}, and {gb(free)} "
                         "is free. Make room and try again.")


def _download(url: str, dest: Path, on_progress: Progress, should_stop: Callable[[], bool]) -> bool:
    """Download `url` to `dest`, reporting {"step": "download", "done", "total"}. False when stopped."""
    from urllib.request import Request, urlopen

    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            if total:
                _room(total, dest.parent)
            done, last = 0, 0.0
            on_progress({"step": "download", "done": 0, "total": total})
            while True:
                if should_stop():
                    return False
                chunk = r.read1(1 << 16)   # what has arrived: a Stop is not kept waiting on a slow connection
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if time.time() - last > 0.25:
                    on_progress({"step": "download", "done": done, "total": total})
                    last = time.time()
            on_progress({"step": "download", "done": done, "total": total or done})
    except OSError as e:
        raise ValueError(f"Ollama could not be downloaded from ollama.com. Is this computer online? ({e})") from e
    if total and done != total:
        raise ValueError("The download of Ollama was cut short. Try again.")
    return True


# ---------------------------------------------------------------------------------------------- is it Ollama's?
def check_windows(path: Path) -> str:
    """"" when the installer is signed by Ollama Inc. and Windows calls the signature valid; else why not."""
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:ENLENS_OLLAMA_FILE; "
              "'{0}|{1}' -f $s.Status, $s.SignerCertificate.Subject")
    try:   # the path goes in the environment: no quoting, and a user folder such as C:\\Users\\Dávid stays whole
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                           text=True, errors="replace", timeout=180, stdin=subprocess.DEVNULL,
                           env={**os.environ, "ENLENS_OLLAMA_FILE": str(path)}, **no_window())
    except (OSError, subprocess.SubprocessError) as e:
        return f"its signature could not be checked ({type(e).__name__}: {e})"
    lines = (r.stdout or "").strip().splitlines()
    state, _, subject = (lines[-1] if lines else "").partition("|")
    if state.strip() != "Valid":
        return f"Windows does not call its signature valid ({state.strip() or (r.stderr or '').strip()[-200:] or 'none'})"
    if not WIN_SIGNER.search(subject.strip()):
        return f"it is signed by someone other than Ollama ({subject.strip()})"
    return ""


def check_mac(app: Path) -> str:
    """"" when Ollama.app is signed, whole, by Ollama's Developer ID team; else why not."""
    try:
        r = subprocess.run(["codesign", "--verify", "--deep", "--strict", f"-R={MAC_REQUIREMENT}", str(app)],
                           capture_output=True, text=True, errors="replace", timeout=300, **no_window())
    except (OSError, subprocess.SubprocessError) as e:
        return f"its signature could not be checked ({type(e).__name__}: {e})"
    if r.returncode:
        return f"its signature is not Ollama's ({((r.stderr or '') + (r.stdout or '')).strip()[-300:]})"
    return ""


# ---------------------------------------------------------------------------------------------- installing
def _hidden_marker() -> Path:
    """The file install.ps1 leaves so that Ollama starts hidden in the tray (Ollama removes it when it starts)."""
    marker = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Ollama" / "upgraded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    return marker


def _install_windows(setup: Path) -> Path:
    marker = _hidden_marker()
    try:   # only the installer is waited for: it starts Ollama and leaves it running
        r = subprocess.run([str(setup), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800, **no_window())
    except (OSError, subprocess.SubprocessError) as e:
        marker.unlink(missing_ok=True)
        raise ValueError(f"Ollama's installer could not run ({type(e).__name__}: {e}).") from e
    if r.returncode:
        marker.unlink(missing_ok=True)
        raise ValueError(f"Ollama's installer stopped (code {r.returncode}). Nothing else was changed.")
    path = app_path("windows")
    if not path:
        raise ValueError("Ollama's installer finished, but ENLENS cannot find Ollama on this computer.")
    return path


def _unpack_mac(zip_path: Path, work: Path) -> Path:
    out = work / "unpacked"
    out.mkdir()
    try:   # ditto, not zipfile: an app keeps its links and the permissions that let it run
        r = subprocess.run(["ditto", "-x", "-k", str(zip_path), str(out)], capture_output=True, text=True,
                           errors="replace", timeout=900, **no_window())
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(f"The Ollama download could not be unpacked ({type(e).__name__}: {e}).") from e
    if r.returncode:
        raise ValueError(f"The Ollama download could not be unpacked ({(r.stderr or '').strip()[-300:]}). Try again.")
    app = out / "Ollama.app"
    if not app.is_dir():
        raise ValueError("The Ollama download holds no Ollama.app.")
    return app


def _install_mac(app: Path) -> Path:
    for parent in mac_folders():
        try:
            parent.mkdir(parents=True, exist_ok=True)
            if not os.access(parent, os.W_OK):
                continue
            dest = parent / "Ollama.app"
            if dest.exists():   # it arrived meanwhile: keep that one
                return dest
            shutil.move(str(app), str(dest))
            return dest
        except OSError:
            continue
    raise ValueError("ENLENS could not put Ollama in Applications. Download Ollama's installer and open it instead.")


def start(sys_name: str | None = None) -> dict:
    """Start the Ollama that is on this computer, hidden; it keeps running when ENLENS quits. Also what the icon does
    when Ollama is the AI and not running (launcher.start_ollama)."""
    name = sys_name or system()
    path = app_path(name)
    if not path:
        raise ValueError("Ollama is not on this computer.")
    try:
        if serves(path):
            # 0.15.3: without a window on Windows: from the icon's pythonw it had one of its own for as long as it ran
            subprocess.Popen([str(path), "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=os.name == "posix", **no_window())
        elif name == "windows":
            _hidden_marker()   # in the tray, without its window
            subprocess.Popen([str(path)], cwd=str(path.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=0x00000008 | 0x00000200)  # detached, own group (a GUI)
        else:   # -g: in the background, without taking the focus; "hidden": in the menu bar only, as install.sh opens it
            r = subprocess.run(["open", "-g", "-a", str(path), "--args", "hidden"], capture_output=True, text=True,
                               errors="replace", timeout=60, **no_window())
            if r.returncode:
                raise ValueError(f"macOS did not open Ollama ({(r.stderr or '').strip()[-200:]}).")
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(f"Ollama could not be started ({type(e).__name__}: {e}).") from e
    return {"started": True, "path": str(path), "serve": serves(path)}


def answers(url: str | None = None) -> bool:
    """Whether an Ollama answers at `url` (by default where Ollama listens)."""
    from .llm import ollama_version

    return ollama_version(url or DEFAULT_URL, 1.5) is not None


def _wait(is_running: Callable[[], bool], seconds: float, should_stop: Callable[[], bool] = lambda: False) -> bool:
    deadline = time.time() + seconds
    while True:
        if is_running():
            return True
        if time.time() >= deadline or should_stop():
            return False
        time.sleep(1)


def install(on_progress: Progress = lambda p: None, should_stop: Callable[[], bool] = lambda: False,
            is_running: Callable[[], bool] | None = None, sys_name: str | None = None) -> dict:
    """Download Ollama's installer, check that it is Ollama's, install it for this user and start it (Windows and
    macOS). {"stopped": True} when stopped before anything was installed; else {"path", "running"}. Raises
    ValueError with what to do when it fails; nothing is installed from a file that is not Ollama's."""
    name = sys_name or system()
    is_running = is_running or answers
    if name not in FILES:
        raise ValueError("On Linux, Ollama's installer asks for your password: ENLENS opens it in a terminal window.")
    if app_path(name):   # on this computer already, but not running: start it, download nothing
        on_progress({"step": "start"})
        started = start(name)
        return {"path": started["path"], "running": _wait(is_running, 60, should_stop), "already": True}
    clear_downloads()
    work = downloads()
    work.mkdir(parents=True, exist_ok=True)
    try:
        file = work / FILES[name]
        if not _download(download_url(name), file, on_progress, should_stop):
            return {"stopped": True}
        on_progress({"step": "check"})
        app = _unpack_mac(file, work) if name == "mac" else file
        why = check_mac(app) if name == "mac" else check_windows(file)
        if why:
            raise ValueError(f"ENLENS did not install what it downloaded: {why}. Nothing was installed. Download "
                             "Ollama's installer from ollama.com yourself instead.")
        if should_stop():
            return {"stopped": True}
        on_progress({"step": "install"})
        path = _install_mac(app) if name == "mac" else _install_windows(file)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # Ollama is installed: from here on a Stop (or quitting the app) no longer cuts anything short or starts anything
    on_progress({"step": "start"})
    if name == "mac":
        start(name)
    # Windows' installer starts Ollama itself, which install.ps1 relies on too: a second start here would only race it
    # (and an antivirus scanning the new files can keep it from answering for a while)
    return {"path": str(path), "running": _wait(is_running, 60)}


def open_terminal() -> dict:
    """Linux: open a terminal window running Ollama's own install line, which asks for the password there."""
    from .claude_setup import _open_window

    script = core.home() / "ollama-install.sh"
    script.write_text("#!/bin/sh\n"
                      "echo 'ENLENS: installing Ollama with its own installer, from ollama.com.'\n"
                      "echo 'It asks for your password: it installs Ollama for everyone on this computer.'\n"
                      "echo\n"
                      f"{LINUX_LINE}\n"
                      "echo\n"
                      "echo 'You can close this window: ENLENS notices Ollama by itself.'\n"
                      "read _\n", encoding="utf-8")
    script.chmod(0o755)
    window = _open_window(script)
    return {"opened": bool(window), "window": window, "command": LINUX_LINE}

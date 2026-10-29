"""Start ENLENS without the terminal: an icon to double-click, one running copy, and a way to quit from the app.

Whoever installs ENLENS runs once

    enlens-gui --make-launcher                 # (add --home D:/enlens or --local-only if the app is used that way)

which puts an ENLENS icon on the Desktop (macOS: also an app in ~/Applications; Windows: also in the Start menu;
Linux: also in the applications menu). The icon calls this Python directly, so another `enlens-gui` earlier on the
PATH (an old install in Anaconda, say) cannot get in the way.

Double-clicking the icon runs `enlens-gui --launcher`:
- if ENLENS is already running, the browser opens on it and nothing else starts;
- otherwise the app starts in the background, with no terminal window, and opens in the browser; what it would print
  goes to `logs/enlens.log` in the data folder;
- if the model service is Ollama on this computer and it is not running, the Ollama app is started too;
- the app is stopped with "Quit ENLENS" in the app (`POST /api/quit`).
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = "ENLENS"
LOG_MAX = 5 * 1024 ** 2


# ---------------------------------------------------------------------------------------------
# one running copy
# ---------------------------------------------------------------------------------------------
def info_path() -> Path:
    from .. import home

    return home.home() / "app.json"


def running(timeout: float = 1.5) -> dict | None:
    """The ENLENS app already running for this data folder ({"url", "port", "pid", …}), or None."""
    from urllib.request import urlopen

    p = info_path()
    try:
        info = json.loads(p.read_text(encoding="utf-8"))
        url = str(info["url"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not url.startswith("http://127.0.0.1:"):
        return None
    try:
        with urlopen(url, timeout=timeout) as r:
            page = r.read(4096).decode("utf-8", errors="replace")
    except OSError:
        return None
    return info if 'name="enlens-version"' in page else None


def write_info(url: str, port: int) -> None:
    from .. import __version__

    info_path().write_text(json.dumps({"url": url, "port": port, "pid": os.getpid(), "version": __version__,
                                       "started": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8")


def clear_info() -> None:
    p = info_path()
    try:
        if json.loads(p.read_text(encoding="utf-8")).get("pid") == os.getpid():
            p.unlink()
    except (OSError, ValueError):
        pass


def log_to_file() -> Path:
    """Send what the app prints to logs/enlens.log in the data folder (a launched app has no terminal; with pythonw
    on Windows there is not even a place to print to)."""
    from .. import home

    folder = home.home() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "enlens.log"
    try:
        if log.exists() and log.stat().st_size > LOG_MAX:
            log.replace(folder / "enlens.log.1")
    except OSError:
        pass
    f = open(log, "a", encoding="utf-8", buffering=1)
    f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ENLENS started by the launcher ---\n")
    sys.stdout = sys.stderr = f
    return log


def detach() -> None:
    """Leave the session of whatever started us (the icon's little script), so closing it does not stop the app."""
    if os.name == "posix":
        try:
            os.setsid()
        except OSError:
            pass  # already a session leader


# ---------------------------------------------------------------------------------------------
# the model service
# ---------------------------------------------------------------------------------------------
def start_ollama(settings: dict) -> str | None:
    """Start the Ollama app when the model service is Ollama on this computer and it is not running. Returns what
    was started, or None (nothing needed, or Ollama is not installed)."""
    from urllib.parse import urlparse
    from urllib.request import urlopen

    if settings.get("backend") not in ("auto", "ollama"):
        return None
    url = (settings.get("ollama_url") or "http://localhost:11434").rstrip("/")
    if urlparse(url if "//" in url else "http://" + url).hostname not in ("localhost", "127.0.0.1", "::1"):
        return None
    try:
        with urlopen(f"{url}/api/version", timeout=1.0):
            return None  # running
    except OSError:
        pass
    try:
        if sys.platform == "darwin":
            for app in (Path("/Applications/Ollama.app"), Path.home() / "Applications" / "Ollama.app"):
                if app.exists():
                    subprocess.Popen(["open", "-g", "-a", str(app)])
                    return "Ollama app"
        elif os.name == "nt":
            exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
            if exe.exists():
                subprocess.Popen([str(exe)], creationflags=0x00000008 | 0x00000200)  # detached, own group
                return "Ollama app"
        exe = shutil.which("ollama")
        if exe:
            subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=os.name == "posix")
            return "ollama serve"
    except OSError:
        return None
    return None


# ---------------------------------------------------------------------------------------------
# making the icon
# ---------------------------------------------------------------------------------------------
def _args(home: str | None, local_only: bool) -> list[str]:
    out = ["-m", "enlens_claims.gui.launch", "--launcher"]
    if home:
        out += ["--home", str(Path(home).expanduser().resolve())]
    if local_only:
        out.append("--local-only")
    return out


def draw_icon(size: int = 512):
    """The ENLENS logo (static/logo.svg) drawn with Pillow, for the icon files; None without Pillow."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s = size / 64
    big = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    for i in range(56, 0, -1):  # the gradient disc, from the edge inwards
        t = i / 56
        c = tuple(int(a + (b - a) * (1 - t)) for a, b in zip((0x0d, 0x5c, 0x5a), (0x1c, 0x8c, 0x86)))
        r = 28 * s * t
        d.ellipse([32 * s - r, 32 * s - r, 32 * s + r, 32 * s + r], fill=c + (255,))
    cream = (0xf6, 0xf3, 0xec, 255)
    r = 18.5 * s
    d.ellipse([32 * s - r, 32 * s - r, 32 * s + r, 32 * s + r], outline=cream, width=max(1, round(3.5 * s)))
    for y, x2 in ((24.5, 41), (32, 41), (39.5, 34)):
        d.line([(23 * s, y * s), (x2 * s, y * s)], fill=cream, width=max(1, round(3 * s)))
    d.line([(37.5 * s, 38.5 * s), (40.5 * s, 41.5 * s), (46.5 * s, 35.5 * s)], fill=(0xff, 0xd3, 0x6a, 255),
           width=max(1, round(3.2 * s)), joint="curve")
    return big


def _desktop() -> Path:
    if os.name == "nt":
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                return Path(r.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip() and Path(r.stdout.strip()) != Path.home():
            return Path(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def _mac_app(folder: Path, python: str, args: list[str]) -> Path:
    import plistlib

    app = folder / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    plist = {"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME, "CFBundleIdentifier": "org.enlens.launcher",
             "CFBundleExecutable": APP_NAME, "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
             "CFBundleShortVersionString": "1", "LSUIElement": True,  # no Dock icon for the little starter
             "NSHighResolutionCapable": True}
    icon = draw_icon()
    if icon is not None:
        try:
            icon.save(app / "Contents" / "Resources" / "ENLENS.icns")
            plist["CFBundleIconFile"] = "ENLENS"
        except (OSError, ValueError):
            pass
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(plist, f)
    script = app / "Contents" / "MacOS" / APP_NAME
    cmd = " ".join(shlex.quote(x) for x in [python, *args])
    script.write_text("#!/bin/sh\n"
                      "# Starts ENLENS in the background and opens it in the browser (made by enlens-gui --make-launcher).\n"
                      f"nohup {cmd} </dev/null >/dev/null 2>&1 &\n"
                      "exit 0\n", encoding="utf-8")
    script.chmod(0o755)
    return app


def _windows_shortcut(folder: Path, python: str, args: list[str]) -> Path:
    exe = Path(python)
    pyw = exe.with_name("pythonw.exe")
    target = pyw if pyw.exists() else exe   # pythonw: no console window
    icon_path = ""
    img = draw_icon(256)
    if img is not None:
        try:
            from .. import home

            ico = home.home() / "ENLENS.ico"
            img.save(ico, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
            icon_path = str(ico)
        except (OSError, ValueError):
            icon_path = ""
    link = folder / f"{APP_NAME}.lnk"
    arg_line = subprocess.list2cmdline(args)

    def ps(s: str) -> str:
        return "'" + s.replace("'", "''") + "'"

    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({ps(str(link))}); "
              f"$s.TargetPath = {ps(str(target))}; $s.Arguments = {ps(arg_line)}; "
              f"$s.WorkingDirectory = {ps(str(Path.home()))}; $s.Description = 'Start ENLENS'; "
              + (f"$s.IconLocation = {ps(icon_path)}; " if icon_path else "") + "$s.Save()")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                           text=True, timeout=60)
        if r.returncode == 0 and link.exists():
            return link
    except (OSError, subprocess.SubprocessError):
        pass
    cmd = folder / f"{APP_NAME}.cmd"  # no PowerShell: a command file that starts it without waiting
    cmd.write_text("@echo off\r\nrem Starts ENLENS and opens it in the browser (made by enlens-gui --make-launcher).\r\n"
                   f'start "" {subprocess.list2cmdline([str(target)])} {arg_line}\r\n', encoding="utf-8")
    return cmd


def _desktop_entry(path: Path, python: str, args: list[str]) -> Path:
    def q(a: str) -> str:  # quoting of the freedesktop Exec key
        if not any(c in a for c in ' \t\n"\'\\><~|&;$*?#()`'):
            return a
        return '"' + a.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'

    icon = Path(__file__).with_name("static") / "logo.svg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[Desktop Entry]\nType=Application\nName=ENLENS\nComment=Check hypotheses against your documents\n"
                    f"Exec={' '.join(q(x) for x in [python, *args])}\nIcon={icon}\nTerminal=false\n"
                    "Categories=Education;Science;Office;\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def make_launcher(home: str | None = None, local_only: bool = False, folders: list[Path] | None = None,
                  python: str | None = None, platform: str | None = None) -> list[Path]:
    """Create the ENLENS icon(s) and return where they are. `folders` replaces the usual places."""
    # absolute, but not resolved: a virtual environment's python is a link to the base interpreter, which does not
    # have ENLENS installed
    python = os.path.abspath(python or sys.executable)
    platform = platform or sys.platform
    args = _args(home, local_only)
    made: list[Path] = []
    if platform == "darwin":
        for folder in folders or [_desktop(), Path.home() / "Applications"]:
            folder.mkdir(parents=True, exist_ok=True)
            made.append(_mac_app(folder, python, args))
    elif platform.startswith("win"):
        start_menu = Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        for folder in folders or [_desktop(), start_menu]:
            folder.mkdir(parents=True, exist_ok=True)
            made.append(_windows_shortcut(folder, python, args))
    else:
        if folders:
            made += [_desktop_entry(f / "enlens.desktop", python, args) for f in folders]
        else:
            made.append(_desktop_entry(Path.home() / ".local" / "share" / "applications" / "enlens.desktop", python, args))
            desk = _desktop()
            if desk.is_dir():
                made.append(_desktop_entry(desk / "enlens.desktop", python, args))
    return made

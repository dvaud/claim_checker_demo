"""Start ENLENS without the terminal: an icon to double-click, one running copy, and a way to quit from the app.

Whoever installs ENLENS runs once

    enlens-gui --make-launcher                 # (add --home D:/enlens or --local-only if the app is used that way)

which puts an ENLENS icon on the Desktop (macOS: also an app in ~/Applications; Windows: also in the Start menu;
Linux: also in the applications menu). The icon calls this Python directly, so another `enlens-gui` earlier on the
PATH (an old install in Anaconda, say) cannot get in the way.

Double-clicking the icon runs `enlens-gui --launcher`:
- if ENLENS is already running, the browser opens on it and nothing else starts; 0.10.2: unless the running copy is
  an older version (ENLENS was updated while it ran): then it is quit first, when nothing is running in it, and this
  version starts instead;
- otherwise the app starts in the background, with no terminal window, and opens in the browser; what it would print
  goes to `logs/enlens.log` in the data folder;
- if the model service is Ollama on this computer and it is not running, the Ollama app is started too;
- the app is stopped with "Quit ENLENS" in the app (`POST /api/quit`).

The icon's picture ships with ENLENS (0.10.2: `gui/icons/ENLENS.icns` and `ENLENS.ico`, drawn by
tools/make_icons.py), so it no longer needs Pillow; an icon made without a picture before is given one when ENLENS
starts (`repair_icons`).
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..procs import no_window

APP_NAME = "ENLENS"
LOG_MAX = 5 * 1024 ** 2
ICONS = Path(__file__).with_name("icons")  # 0.10.2: the icon files that ship with ENLENS
BUNDLE_ID = "org.enlens.launcher"


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


# 0.17.2: the page no longer carries the access token (another account on the same computer could read it there). The
# app opens its link with the token after `#`, which never reaches a server or a log, and keeps the token in a file
# only this account can read, so a second double-click on the icon, `enlens post-install --open` and the quitting of
# an older copy can open or reach it. On macOS and Linux the file is mode 0600 (home._write_whole, put in place whole).
# Windows has no mode bits: there the file relies on the person's own profile folder (C:\Users\<name>), which other
# accounts cannot read; with a data folder outside it (--home D:/enlens, where every account may read new folders) the
# file goes to the profile's AppData\Local\ENLENS instead (token_dir).
def token_dir(home_dir: Path, windows: bool | None = None, profile: str | None = None,
              local_appdata: str | None = None) -> Path:
    """Where the token files go: the data folder, except on Windows when the data folder is outside the person's
    profile."""
    if not (os.name == "nt" if windows is None else windows):
        return home_dir
    profile = profile if profile is not None else os.environ.get("USERPROFILE", "")
    local = local_appdata if local_appdata is not None else os.environ.get("LOCALAPPDATA", "")
    try:
        inside = bool(profile) and os.path.normcase(os.path.abspath(home_dir)).startswith(
            os.path.normcase(os.path.abspath(profile)).rstrip("\\/") + os.sep)
    except (OSError, ValueError):
        inside = False
    if inside or not local:
        return home_dir
    return Path(local) / "ENLENS"


def token_path(port: int) -> Path:
    """The token file of the app on `port` (one per port: a copy started from the terminal can run beside the icon's;
    a port is this computer's, so the name says which app it is wherever the file is)."""
    from .. import home

    folder = token_dir(home.home())
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"app-token-{int(port)}.json"


def write_token(url: str, port: int, token: str) -> Path:
    from .. import home

    p = token_path(port)
    home._write_whole(p, json.dumps({"url": url, "port": int(port), "pid": os.getpid(), "token": token}), private=True)
    return p


def read_token(port) -> str | None:
    """The token of the app running on `port`, from its file; None when there is none."""
    try:
        tok = json.loads(token_path(int(port)).read_text(encoding="utf-8")).get("token")
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return tok if isinstance(tok, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,}", tok) else None


def clear_token(port: int) -> None:
    p = token_path(port)
    try:
        if json.loads(p.read_text(encoding="utf-8")).get("pid") == os.getpid():
            p.unlink()
            p.with_name(f"open-{int(port)}.html").unlink(missing_ok=True)
    except (OSError, ValueError, AttributeError):
        pass


def browse(target: str) -> None:
    """Open the app's link in the browser. On Linux (and other systems that are not macOS or Windows) Python hands the
    address to a program (xdg-open, the browser) on its command line, which every account can read (/proc, ps), and a
    browser it starts keeps it there while it runs: so the browser is given a file only this account can read, which
    sends it on to the link (as Jupyter does). macOS passes the address on the input of osascript; Windows shows a
    program's command line to its own account and administrators only."""
    import webbrowser

    if "#token=" in target and os.name == "posix" and sys.platform != "darwin":
        port = _port_of(target)
        page = token_path(port).with_name(f"open-{port}.html")
        from .. import home

        home._write_whole(page, "<!doctype html><meta charset=utf-8><title>ENLENS</title><script>location.replace("
                          + json.dumps(target) + ")</script><a href=" + json.dumps(target) + ">Open ENLENS</a>\n",
                          private=True)
        target = page.resolve().as_uri()
    webbrowser.open(target)


def link(url: str, token: str | None) -> str:
    """The address that opens the app: `url` with the token after `#` (the page keeps it for the tab and takes it out
    of the address bar). Without a token, the bare address, which shows how to open ENLENS."""
    base = url.split("#", 1)[0]
    return f"{base}#token={token}" if token else base


def open_link(live: dict) -> str:
    """The link that opens the running copy `live` (as running() gives it)."""
    return link(str(live["url"]), read_token(live.get("port") or _port_of(str(live["url"]))))


def _port_of(url: str) -> int:
    from urllib.parse import urlparse

    try:
        return int(urlparse(url).port or 0)
    except ValueError:
        return 0


# 0.10.2: after an update, the copy still running is the old version, and double-clicking the icon showed it again
def is_older(live: dict) -> bool:
    """Whether the running copy is an older version than this one (a copy that does not say counts as older, and so
    does a withdrawn version above this one, 0.13.6; 0.15: the same number released for real is not older)."""
    from .. import __version__
    from ..update import WITHDRAWN, version_tuple

    v = str(live.get("version") or "")
    have, mine = version_tuple(v), version_tuple(__version__)
    return not have or have < mine or (v in WITHDRAWN and have > mine)


def stop_older(live: dict, wait: float = 25.0, fetch=None) -> str:
    """Quit the running copy so this version can start, as "Quit ENLENS" would. Returns "stopped"; "busy" when a
    check or another job runs in it (it is left alone: quitting would stop that work); "failed" otherwise."""
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    def call(method: str, path: str, token: str | None = None) -> bytes:
        req = Request(live["url"].rstrip("/") + path, method=method, data=b"{}" if method == "POST" else None,
                      headers={"X-Enlens-Token": token, "Content-Type": "application/json"} if token else {})
        with urlopen(req, timeout=5) as r:
            return r.read()

    call = fetch or call

    def from_page() -> str | None:  # a copy older than 0.17.2 writes no token file, but its page carries the token
        m = re.search(r'name="enlens-token" content="([^"]+)"', call("GET", "/").decode("utf-8", errors="replace"))
        return m.group(1) if m else None

    try:
        # 0.17.2: from the token file; refused (a file left by a copy that could not write its own), from the page
        token = read_token(live.get("port") or _port_of(str(live["url"]))) or from_page()
        if not token:
            return "failed"
        try:
            got = call("GET", "/api/jobs", token)
        except HTTPError as e:
            if e.code != 401 or not (token := from_page()):
                return "failed"
            got = call("GET", "/api/jobs", token)
        jobs = json.loads(got).get("jobs", [])
        if any(j.get("state") in ("queued", "running") for j in jobs):
            return "busy"
        call("POST", "/api/quit", token)
    except (OSError, ValueError):
        return "failed"
    t0 = time.time()
    while time.time() - t0 < wait:
        if running(timeout=0.5) is None:
            return "stopped"
        time.sleep(0.2)
    return "failed"


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

    from ..llm import ollama_version

    # the main AI, the local model for restricted documents (0.11) or search by meaning may be Ollama (0.11.1: with
    # Claude as the main AI, Ollama was not started, so "Only a local AI" excerpts fell to the person's judgement)
    uses = (settings.get("backend") in ("auto", "ollama") or settings.get("restricted_server") == "ollama"
            or (settings.get("embed_backend") == "ollama" and settings.get("embed_model")))
    if not uses:
        return None
    url = (settings.get("ollama_url") or "http://localhost:11434").rstrip("/")
    if urlparse(url if "//" in url else "http://" + url).hostname not in ("localhost", "127.0.0.1", "::1"):
        return None
    if ollama_version(url, 1.0) is not None:   # 0.17.2: the one probe (llm.ollama_version)
        return None  # running
    from .. import ollama_setup   # 0.15.6: the same start as the page's Start Ollama button

    if not ollama_setup.app_path():
        return None
    try:
        return "ollama serve" if ollama_setup.start()["serve"] else "Ollama app"
    except ValueError:
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
    k = 4  # 0.13.5: drawn 4 times larger, then scaled down: smooth edges
    s = size * k / 64
    big = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
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
    return big.resize((size, size), Image.LANCZOS)


def _put_icon(dest: Path, ext: str) -> bool:
    """Write the icon file `dest` (ENLENS.icns or ENLENS.ico): the one that ships with ENLENS, else drawn (Pillow)."""
    shipped = ICONS / f"ENLENS.{ext}"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if shipped.is_file():
            shutil.copyfile(shipped, dest)
            return True
        img = draw_icon(512 if ext == "icns" else 256)
        if img is None:
            return False
        if ext == "ico":
            img.save(dest, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
        else:
            img.save(dest)
        return True
    except (OSError, ValueError):
        return False


def _start_menu() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


FOLDERID_DESKTOP = "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"
CLSID_SHELLLINK = "00021401-0000-0000-C000-000000000046"
IID_ISHELLLINKW = "000214F9-0000-0000-C000-000000000046"
IID_IPERSISTFILE = "0000010B-0000-0000-C000-000000000046"


def _guid(text: str):
    """A Windows GUID structure (for ctypes) from its text."""
    import ctypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                    ("Data4", ctypes.c_ubyte * 8)]

    return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


def _windows_desktop() -> Path | None:
    """0.15.2: the Desktop folder as Windows itself names it (moved to OneDrive or elsewhere too), from the
    Known Folder API in UTF-16. Before, PowerShell printed it and Python read that in another code page: in
    C:\\Users\\Dávid the "á" came back as a no-break space, so the icon went to a folder that does not exist (or none
    was made at all)."""
    import ctypes

    try:
        shell32, ole32 = ctypes.WinDLL("shell32"), ctypes.WinDLL("ole32")
        get = shell32.SHGetKnownFolderPath
        get.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        get.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        guid = _guid(FOLDERID_DESKTOP)
        buf = ctypes.c_void_p()
        hr = get(ctypes.byref(guid), 0, None, ctypes.byref(buf))
        try:
            return Path(ctypes.wstring_at(buf.value)) if hr == 0 and buf.value else None
        finally:
            if buf.value:
                ole32.CoTaskMemFree(buf)
    except (OSError, AttributeError, ValueError):
        return None


def _com_shortcut(link: Path, target: str, arguments: str, workdir: str, description: str, icon: str) -> bool:
    """0.15.2: write a shortcut with the Shell's own IShellLinkW, in UTF-16 throughout. WScript.Shell, which PowerShell
    used, goes through the computer's ANSI code page, so a folder with a letter that page lacks (C:\\Users\\Gergő on
    an English Windows) got a command file instead of an icon. Returns whether the shortcut was saved."""
    import ctypes

    if os.name != "nt":
        return False
    try:
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitialize.argtypes = [ctypes.c_void_p]
        ole32.CoInitialize.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                           ctypes.POINTER(ctypes.c_void_p)]
        ole32.CoCreateInstance.restype = ctypes.c_long
    except (OSError, AttributeError):
        return False

    def method(obj: ctypes.c_void_p, index: int, *argtypes):
        """Method `index` of a COM object's table of methods, as a function of the remaining arguments."""
        table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])
        return lambda *a: fn(obj, *a)

    wstr, release = ctypes.c_wchar_p, 2
    started = ole32.CoInitialize(None) in (0, 1)  # S_OK, S_FALSE; otherwise COM is already set up differently
    shell_link, persist = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        hr = ole32.CoCreateInstance(ctypes.byref(_guid(CLSID_SHELLLINK)), None, 1,  # CLSCTX_INPROC_SERVER
                                    ctypes.byref(_guid(IID_ISHELLLINKW)), ctypes.byref(shell_link))
        if hr < 0 or not shell_link.value:
            return False
        calls = [method(shell_link, 20, wstr)(target),           # SetPath
                 method(shell_link, 11, wstr)(arguments),        # SetArguments
                 method(shell_link, 9, wstr)(workdir),           # SetWorkingDirectory
                 method(shell_link, 7, wstr)(description)]       # SetDescription
        if icon:
            calls.append(method(shell_link, 17, wstr, ctypes.c_int)(icon, 0))  # SetIconLocation
        if any(hr < 0 for hr in calls):
            return False
        hr = method(shell_link, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(  # QueryInterface
            ctypes.byref(_guid(IID_IPERSISTFILE)), ctypes.byref(persist))
        if hr < 0 or not persist.value:
            return False
        return method(persist, 6, wstr, ctypes.c_int)(str(link), 1) >= 0  # IPersistFile::Save, remember it
    except (OSError, AttributeError, ValueError, TypeError):
        return False
    finally:
        for obj in (persist, shell_link):
            if obj.value:
                method(obj, release)()
        if started:
            ole32.CoUninitialize()


def _ps_quote(s: str) -> str:
    """A PowerShell string literal that holds `s` as it is. PowerShell also ends a quoted string at the typographic
    single quotes (as in O’Brien), so those are doubled as well."""
    return "'" + re.sub("(['\u2018\u2019\u201a\u201b])", r"\1\1", s) + "'"


# What PowerShell writes back is only looked at for its exit code, and it is in the console's code page: read it so
# that a byte this Python's code page does not have can never stop the icon being made (0.15.2). 0.15.3: and it runs
# without a window (procs).
_PS_TEXT = {"capture_output": True, "text": True, "errors": "replace", **no_window()}


def _desktop() -> Path:
    if os.name == "nt":
        found = _windows_desktop()
        if found:
            return found
    try:
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5, **no_window())
        if r.returncode == 0 and r.stdout.strip() and Path(r.stdout.strip()) != Path.home():
            return Path(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def _mac_app(folder: Path, python: str, args: list[str]) -> Path:
    app = folder / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    plist = {"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME, "CFBundleIdentifier": BUNDLE_ID,
             "CFBundleExecutable": APP_NAME, "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
             "CFBundleShortVersionString": "1", "LSUIElement": True,  # no Dock icon for the little starter
             "NSHighResolutionCapable": True}
    if _put_icon(app / "Contents" / "Resources" / "ENLENS.icns", "icns"):
        plist["CFBundleIconFile"] = "ENLENS"
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
    from .. import home

    ico = home.home() / "ENLENS.ico"  # beside the data, so the shortcut keeps its picture when ENLENS is reinstalled
    icon_path = str(ico) if _put_icon(ico, "ico") else ""
    link = folder / f"{APP_NAME}.lnk"
    arg_line = subprocess.list2cmdline(args)
    if _com_shortcut(link, str(target), arg_line, str(Path.home()), "Start ENLENS", icon_path) and link.exists():
        return link
    ps = _ps_quote  # without the Shell's interface: WScript.Shell, through PowerShell
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({ps(str(link))}); "
              f"$s.TargetPath = {ps(str(target))}; $s.Arguments = {ps(arg_line)}; "
              f"$s.WorkingDirectory = {ps(str(Path.home()))}; $s.Description = 'Start ENLENS'; "
              + (f"$s.IconLocation = {ps(icon_path)}; " if icon_path else "") + "$s.Save()")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=60,
                           **_PS_TEXT)
        if r.returncode == 0 and link.exists():
            return link
    except (OSError, subprocess.SubprocessError):
        pass
    cmd = folder / f"{APP_NAME}.cmd"  # no PowerShell: a command file that starts it without waiting
    # 0.14.3: cmd.exe reads a command file in the computer's OEM code page, so a path with an accent (C:\Users\Kovács)
    # was misread; the file is UTF-8, and its second line switches cmd.exe to UTF-8 for the rest
    cmd.write_text("@echo off\r\nchcp 65001 >nul\r\n"
                   "rem Starts ENLENS and opens it in the browser (made by enlens-gui --make-launcher).\r\n"
                   f'start "" {subprocess.list2cmdline([str(target)])} {arg_line}\r\n', encoding="utf-8",
                   newline="")  # 0.15.7: the line ends as written (Windows turned "\r\n" into "\r\r\n")
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
        for folder in folders or [_desktop(), _start_menu()]:
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


def repair_icons(folders: list[Path] | None = None, platform: str | None = None, run=subprocess.run) -> list[Path]:
    """0.10.2: give the ENLENS icons made without a picture (before 0.10.2, Pillow missing) the one that ships now.
    macOS: an ENLENS app made by --make-launcher without ENLENS.icns gets it, and its Info.plist names it. Windows:
    when the data folder has no ENLENS.ico, it is written and the ENLENS shortcuts are pointed at it. Nothing else of
    the icon changes. Returns what was repaired."""
    platform = platform or sys.platform
    fixed: list[Path] = []
    if platform == "darwin":
        for folder in folders or [_desktop(), Path.home() / "Applications"]:
            app = folder / f"{APP_NAME}.app"
            plist_path = app / "Contents" / "Info.plist"
            try:
                info = plistlib.loads(plist_path.read_bytes())
            except (OSError, ValueError):
                continue
            icns = app / "Contents" / "Resources" / "ENLENS.icns"
            if info.get("CFBundleIdentifier") != BUNDLE_ID or (info.get("CFBundleIconFile") and icns.is_file()):
                continue
            if not _put_icon(icns, "icns"):
                continue
            info["CFBundleIconFile"] = "ENLENS"
            try:
                plist_path.write_bytes(plistlib.dumps(info))
                os.utime(app)  # Finder shows the new picture when the app's date changes
            except OSError:
                continue
            fixed.append(app)
    elif platform.startswith("win"):
        from .. import home

        ico = home.home() / "ENLENS.ico"
        links = [f / f"{APP_NAME}.lnk" for f in (folders or [_desktop(), _start_menu()])]
        links = [p for p in links if p.is_file()]
        if ico.is_file() or not links or not _put_icon(ico, "ico"):
            return fixed

        ps = _ps_quote
        script = "; ".join(f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({ps(str(p))}); "
                           f"$s.IconLocation = {ps(str(ico))}; $s.Save()" for p in links)
        try:
            r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=60, **_PS_TEXT)
            if r.returncode == 0:
                fixed += links
        except (OSError, subprocess.SubprocessError):
            pass
    return fixed

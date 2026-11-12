"""The system's own folder picker (0.18.0rc2, roadmap L7), so nobody pastes a path.

    available()                          whether this computer has a picker ENLENS can open
    choose_folder(prompt, start, timeout) the folder chosen, or None (cancelled, no picker, closed too late, failed)

macOS: `osascript` (`choose folder`); Windows: PowerShell in STA mode with a Windows Forms folder dialog (its answer is
printed as UTF-8, so a path such as C:\\Users\\Dávid comes back intact); Linux: `zenity` or `kdialog`. The dialog opens
in front of the browser. One dialog at a time: a second call while one is open raises `Busy`. Programs can be pointed
elsewhere for tests with ENLENS_OSASCRIPT, ENLENS_POWERSHELL, ENLENS_ZENITY and ENLENS_KDIALOG.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import threading

from ..procs import no_window

_lock = threading.Lock()

MAC_SCRIPT = """on run argv
    set promptText to item 1 of argv
    tell current application to activate
    if (count of argv) > 1 then
        set startAt to item 2 of argv
        return POSIX path of (choose folder with prompt promptText default location (POSIX file startAt))
    end if
    return POSIX path of (choose folder with prompt promptText)
end run
"""

# the prompt and the start folder come in the environment, not in the script, so no quotation can break it
WINDOWS_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.StartPosition = 'CenterScreen'
$owner.Size = New-Object System.Drawing.Size(0, 0)
$owner.Opacity = 0
$owner.Show()
$owner.Activate()
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = $env:ENLENS_PICK_PROMPT
$d.ShowNewFolderButton = $true
if ($env:ENLENS_PICK_START -and (Test-Path -LiteralPath $env:ENLENS_PICK_START)) { $d.SelectedPath = $env:ENLENS_PICK_START }
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($d.SelectedPath) }
$owner.Close()
"""


class Busy(Exception):
    """A folder dialog is already open."""


def _program(env: str, *names: str) -> str | None:
    forced = os.environ.get(env)
    if forced:
        return forced if os.path.isfile(forced) else None
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    return None


def _kind() -> tuple[str, str] | None:
    """(which picker, its program) for this computer, or None."""
    if sys.platform == "darwin":
        p = _program("ENLENS_OSASCRIPT", "osascript")
        return ("mac", p) if p else None
    if sys.platform == "win32":
        p = _program("ENLENS_POWERSHELL", "powershell.exe", "powershell", "pwsh")
        return ("windows", p) if p else None
    for env, name, kind in (("ENLENS_ZENITY", "zenity", "zenity"), ("ENLENS_KDIALOG", "kdialog", "kdialog")):
        p = _program(env, name)
        if p and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.environ.get(env)):
            return (kind, p)
    return None


def available() -> bool:
    return _kind() is not None


def _command(kind: str, program: str, prompt: str, start: str | None) -> tuple[list[str], dict]:
    """The command and extra environment variables for one dialog."""
    if kind == "mac":
        return [program, "-e", MAC_SCRIPT, prompt] + ([start] if start else []), {}
    if kind == "windows":
        encoded = base64.b64encode(WINDOWS_SCRIPT.encode("utf-16-le")).decode("ascii")
        return ([program, "-NoProfile", "-NonInteractive", "-STA", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
                {"ENLENS_PICK_PROMPT": prompt, "ENLENS_PICK_START": start or ""})
    if kind == "zenity":
        return [program, "--file-selection", "--directory", f"--title={prompt}"] + ([f"--filename={start.rstrip('/')}/"] if start else []), {}
    return [program, "--getexistingdirectory", start or os.path.expanduser("~"), "--title", prompt], {}


def choose_folder(prompt: str, start: str | None = None, timeout: float = 600) -> str | None:
    """Open the picker and wait. The chosen folder, or None when it was cancelled, there is no picker, nothing was
    chosen within `timeout` seconds or the program failed. Raises Busy when a dialog is already open."""
    found = _kind()
    if found is None:
        return None
    if not _lock.acquire(blocking=False):
        raise Busy("A folder dialog is already open.")
    try:
        kind, program = found
        if start and not os.path.isdir(start):
            start = None
        cmd, extra = _command(kind, program, prompt or "Choose a folder", start)
        env = {**os.environ, **extra}
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL, **no_window())
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None   # cancelled (macOS -128, zenity and kdialog 1) or failed
        text = r.stdout.decode("utf-8", errors="replace").strip("\r\n")
        if len(text) > 1 and text.endswith(("/", "\\")) and not (len(text) == 3 and text[1] == ":"):
            text = text[:-1]   # "/Users/anna/Dropbox/" -> "/Users/anna/Dropbox" ("C:\" stays)
        return text or None
    finally:
        _lock.release()

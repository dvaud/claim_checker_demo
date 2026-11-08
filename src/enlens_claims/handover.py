"""Finishing an update on Windows after the app has quit (0.15.4, the hand-over).

Windows does not let a program's files be replaced while it runs, so the app cannot install a new version over itself
as it does on macOS and Linux. Its *Update* button on Windows therefore downloads the new version and checks it there
as well, writes what is left to do into a job file, starts this script and quits. The script runs with the Python
that uv installed, outside ENLENS's own folder, so the update replaces nothing it uses. It:

1. waits until the app has quit (at most `wait` seconds; if it has not, nothing is installed and the app runs on);
2. waits until no other program runs from ENLENS's own folder (`env_dir`, at most `free_wait` seconds): most often
   the ENLENS connector of an open Claude Code window. While one does, uv removes part of the folder and then stops,
   leaving an ENLENS that cannot start, so if one stays nothing is installed and the app starts as it was;
3. installs the new version with uv, trying again a few times while Windows still holds a file (an antivirus
   reading it);
4. finishes the update with the new version's `enlens post-install` (the marker and the Claude Code plugin);
5. starts the app again on the same address, whether the install worked or not (the open page reloads itself);
6. writes what happened to the result file (the app shows a failure once, update_note()) and to the log;
7. if no app comes back within `come_back` seconds, opens a PowerShell window that says so and runs the install
   line of the new version, so the person is never left without ENLENS.

It imports nothing from ENLENS, only Python's standard library: it is copied next to the job file and run from there.
The programs it starts get no console window of their own (procs.py), except the PowerShell window of step 7."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NEW_CONSOLE = 0x00000010
IN_USE = ("os error 5", "os error 32", "access is denied", "being used by another process")


def _log(job: dict, text: str) -> None:
    try:
        Path(job["log"]).parent.mkdir(parents=True, exist_ok=True)
        with open(job["log"], "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text.rstrip()}\n")
    except OSError:
        pass


def no_window() -> dict:
    """As procs.no_window(), which this script cannot import."""
    return {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}


def _wait_gone(pids: list[int], seconds: float) -> bool:
    """Whether every process in `pids` has ended within `seconds`. On Windows each process is opened once, at the
    start, and waited on by its handle, so a number Windows gives to another program meanwhile cannot confuse it."""
    deadline = time.time() + seconds
    if os.name == "nt":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handles = [h for h in (k32.OpenProcess(0x00100000, False, p) for p in pids) if h]  # SYNCHRONIZE; 0: gone
        try:
            for h in handles:
                left = max(0, int((deadline - time.time()) * 1000))
                if k32.WaitForSingleObject(h, left) != 0:  # WAIT_OBJECT_0: it ended
                    return False
            return True
        finally:
            for h in handles:
                k32.CloseHandle(h)
    while time.time() < deadline:
        alive = []
        for p in pids:
            try:
                os.kill(p, 0)
                alive.append(p)
            except ProcessLookupError:
                pass
            except PermissionError:
                alive.append(p)
        if not alive:
            return True
        time.sleep(0.2)
    return False


def programs_in(folder: str) -> list[str]:
    """The programs running from `folder` ("python.exe (process 1234)"), on Windows; [] elsewhere. Claude Code's
    ENLENS connector is one: it runs ENLENS's own Python. (A folder in use can still be renamed on Windows, so that is
    no test; uv found it out by removing what it could and stopping, which left an ENLENS that could not start.)"""
    if os.name != "nt" or not folder:
        return []
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):  # PROCESSENTRY32W
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    prefix = os.path.normcase(os.path.abspath(folder)).rstrip("\\") + "\\"
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    found = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        more = k32.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            pid = entry.th32ProcessID
            h = k32.OpenProcess(0x1000, False, pid) if pid and pid != os.getpid() else None  # QUERY_LIMITED_INFO
            if h:
                buf, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) and \
                        os.path.normcase(buf.value).startswith(prefix):
                    found.append(f"{entry.szExeFile} (process {pid})")
                k32.CloseHandle(h)
            more = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return found


def _in_use(folder: str) -> list[str]:
    return programs_in(folder)


def _wait_free(job: dict) -> bool:
    """Whether ENLENS's own folder is free within `free_wait` seconds."""
    deadline = time.time() + job.get("free_wait", 60)
    said = False
    while users := _in_use(job.get("env_dir", "")):
        if not said:
            _log(job, f"these programs still run from {job.get('env_dir')}: {', '.join(users)}; waiting for them")
            said = True
        if time.time() >= deadline:
            return False
        time.sleep(2)
    return True


def _run(job: dict, args: list[str], env: dict | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, cwd=job["folder"], env=env, timeout=job.get("timeout", 900),
                           **no_window())
    except (OSError, subprocess.SubprocessError) as e:
        return 1, f"{type(e).__name__}: {e}"
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _start(args: list[str], folder: str) -> int:
    """Start a program that outlives this script; returns its process number."""
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                "close_fds": True, "cwd": folder}
    if os.name != "nt":
        return subprocess.Popen(args, start_new_session=True, **kw).pid  # console: not on Windows
    flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    try:  # out of a job that would end it with this script (CREATE_BREAKAWAY_FROM_JOB), where the job allows it
        return subprocess.Popen(args, creationflags=flags | 0x01000000, **kw).pid
    except OSError:
        return subprocess.Popen(args, creationflags=flags, **kw).pid


def _came_back(job: dict, before: int, seconds: float) -> bool:
    """Whether the app started again: its address file names a new process that runs."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            pid = int(json.loads(Path(job["info"]).read_text(encoding="utf-8")).get("pid") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            pid = 0
        if pid and pid != before and not _wait_gone([pid], 0):
            return True
        time.sleep(0.5)
    return False


def _rescue(job: dict) -> None:
    """A PowerShell window that says ENLENS did not come back and runs the install line (Windows only)."""
    if os.name != "nt" or not job.get("install_url"):
        return
    import base64

    script = ("Write-Host 'ENLENS could not start again after its update. This window installs it again.'; "
              "Write-Host 'Your projects and results are kept.'; Write-Host ''; "
              f"irm '{job['install_url']}' | iex")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-EncodedCommand",
                          encoded], creationflags=CREATE_NEW_CONSOLE, close_fds=True)
    except OSError as e:
        _log(job, f"could not open the PowerShell window: {e}")


def _finish(job: dict, result: dict) -> dict:
    result = {"from": job.get("from", ""), "version": job.get("version", ""), "log": job["log"],
              "at": time.strftime("%Y-%m-%d %H:%M:%S"), **result}
    try:
        Path(job["result"]).write_text(json.dumps(result, indent=1), encoding="utf-8")
    except OSError as e:
        _log(job, f"could not write the result: {e}")
    _log(job, "result: " + json.dumps(result))
    return result


def run(job: dict) -> dict:
    """Carry out the job (see the module's notes). Returns what was written to the result file."""
    _log(job, f"updating ENLENS {job.get('from')} to {job.get('version')} (this script runs with {sys.executable}): "
              "waiting for the app to quit")
    if not _wait_gone(job["pids"], job.get("wait", 120)):
        return _finish(job, {"ok": False, "installed": False, "hint": "not_quit",
                             "error": "ENLENS did not quit, so the new version was not installed."})
    time.sleep(job.get("settle", 1.0))  # the venv's own launcher ends just after the app
    env = {**os.environ, **job.get("env", {})}
    out, ok, tries = "", False, max(1, int(job.get("tries", 4)))
    try:
        free = _wait_free(job)
    except OSError as e:  # Windows would not say: try, as before this check
        _log(job, f"could not see which programs run: {e}")
        free = True
    if not free:
        tries, out = 0, "another program still uses ENLENS's folder (os error 32)"
        _log(job, "it is still in use: nothing is installed, ENLENS starts as it was")
    for attempt in range(1, tries + 1):
        code, out = _run(job, job["install"], env)
        _log(job, f"install, try {attempt}: exit {code}\n{out[-3000:]}")
        if code == 0:
            ok = True
            break
        if attempt < tries:
            time.sleep(job.get("retry_after", 5) * attempt)
    result: dict = {"ok": ok, "installed": ok}
    if ok and job.get("post"):
        code, post = _run(job, job["post"], env)
        _log(job, f"post-install: exit {code}\n{post[-3000:]}")
        if code != 0:
            result.update(ok=False, hint="post_install", error=post[-1500:])
    elif not ok:
        low = out.lower()
        result.update(hint="in_use" if any(s in low for s in IN_USE) else "install", error=out[-1500:])
    try:
        before = int(job["pids"][0]) if job.get("pids") else 0
        pid = _start(job["start"], job["folder"])
        _log(job, f"started ENLENS again (process {pid})")
        result["restarted"] = _came_back(job, before, job.get("come_back", 60))
    except (OSError, KeyError) as e:
        _log(job, f"could not start ENLENS again: {e}")
        result["restarted"] = False
    if not result["restarted"]:
        _rescue(job)
    return _finish(job, result)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    job = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    return 0 if run(job).get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

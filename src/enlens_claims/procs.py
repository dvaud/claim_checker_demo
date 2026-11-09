"""0.15.3: other programs start without a window on Windows.

The app runs without a console on Windows: its icon starts it with pythonw.exe, and the connector that Claude Code
starts is written for the same Python. A console program started from a process without a console is given a console
window of its own, which opens, takes the focus from what the person is doing and closes again. While a task queue
page was open, the app's check of Claude Code ran `claude` three times every half minute, and each run flashed a
window; Tesseract flashed one for each scanned page and git and uv for each update.

So every program ENLENS starts goes through `no_window()` (a test holds every call in the package to it). The program
still has a console, one that is never shown, so what it writes can be read as before. On macOS and Linux nothing
changes."""
from __future__ import annotations

import os

CREATE_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW, which only Windows' Python has


def no_window() -> dict:
    """The keyword arguments for subprocess.run and subprocess.Popen that start a console program without a window
    on Windows; none elsewhere."""
    return {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}


# 0.15.7: a Claude Code run left going is recognised on Windows by its command line, as on macOS and Linux (`ps`).
# Before, Windows checked the process number alone (tasklist), so a record whose number Windows had since given to
# another program counted as a run, and Stop could end that program; the test run on Windows stopped part way for the
# same reason (a test recording its own number had pytest ended).
GONE = None  # windows_command_line: the process has ended, or is not this user's to look into


def windows_command_line(pid: int) -> str | None:
    """The command line process `pid` was started with, on Windows (NtQueryInformationProcess with
    ProcessCommandLineInformation, Windows 8.1 and later). None when it has ended or is not ours to read; "" when it
    runs but its command line cannot be read."""
    import ctypes
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
                                                ctypes.POINTER(ctypes.c_ulong)]
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return GONE  # no such process (87), or another user's (5)
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
            return GONE  # ended; a handle someone still holds keeps its number taken
        size = ctypes.c_ulong(0)
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(size))  # 60: ProcessCommandLineInformation
        if not size.value:
            return ""
        buf = ctypes.create_string_buffer(size.value)
        if ntdll.NtQueryInformationProcess(handle, 60, buf, size, ctypes.byref(size)) != 0:
            return ""
        s = UnicodeString.from_buffer(buf)
        return ctypes.wstring_at(s.Buffer, s.Length // 2) if s.Buffer and s.Length else ""
    finally:
        k32.CloseHandle(handle)

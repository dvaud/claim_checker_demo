"""Whether a running ENLENS is the one a test started (0.18.1).

On Windows, the `python.exe` of a virtual environment made by uv (which CI uses since 0.18.1, as the one-line install
always has) is a small launcher: it starts the real interpreter as its child and waits for it. ENLENS then records
the child's process id, not the one `subprocess.Popen` gave the test. So a copy counts as the test's own when its id
is the started process's, or, on Windows, when the started process is its parent.
"""
from __future__ import annotations

import os


def parent_of(pid: int) -> int | None:
    """The parent process id of `pid` on Windows (None elsewhere, or when it is not found)."""
    if os.name != "nt":
        return None
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
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return None
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        more = k32.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            if entry.th32ProcessID == pid:
                return int(entry.th32ParentProcessID)
            more = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return None


def is_started(live_pid: int | None, started_pid: int) -> bool:
    """True when the copy with `live_pid` is the process the test started (or its interpreter, on Windows)."""
    return bool(live_pid) and (live_pid == started_pid or parent_of(live_pid) == started_pid)

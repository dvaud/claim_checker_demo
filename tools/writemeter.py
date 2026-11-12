"""How much a test writes (2026-11-12): bytes written by this process, per test, on macOS, Linux and Windows.

The test suite once wrote ~25 GB per full run (the random runs of the 0.18 roles alone ~5.5 GB), which wore the SSD
and, with several runs at once, overheated the Mac. tests/conftest.py loads this file as a pytest plugin, so every run
measures each test (one system call before and after it, ~microseconds):

- a test that writes more than `ENLENS_WRITE_BUDGET_MB` (default 200) warns (`WriteBudgetWarning`) unless it is marked
  `heavy`, so a new heavy test is caught the day it is added;
- `ENLENS_WRITES=15` lists the 15 tests that wrote the most at the end of the run (works with pytest-xdist: the numbers
  travel with each test's report);
- `ENLENS_WRITES_JSON=<file>` keeps every test's number in a file, to compare two runs.

`written()` is also used by tests that check that something writes little (tests/test_idle_writes.py).

What is counted: what the process asked to write (macOS `ri_logical_writes`, Linux `wchar`, Windows
`WriteTransferCount`), including files that are deleted again before they reach the disk; not what child processes
write. On Linux `wchar` also counts pipes and sockets.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

__all__ = ["written", "WriteBudgetWarning"]


class WriteBudgetWarning(UserWarning):
    """A test not marked `heavy` wrote more than ENLENS_WRITE_BUDGET_MB."""


def _macos():
    import ctypes

    lib = ctypes.CDLL("/usr/lib/libproc.dylib")

    class RUsageInfoV4(ctypes.Structure):  # <sys/resource.h> rusage_info_v4: a uuid, then 64-bit counters
        _fields_ = [("uuid", ctypes.c_uint8 * 16), ("f", ctypes.c_uint64 * 40)]

    pid = os.getpid()

    def written() -> int:
        ru = RUsageInfoV4()
        if lib.proc_pid_rusage(pid, 4, ctypes.byref(ru)) != 0:  # RUSAGE_INFO_V4
            return 0
        return int(ru.f[27])  # ri_logical_writes

    return written


def _linux():
    def written() -> int:
        try:
            with open("/proc/self/io", encoding="ascii") as f:
                for line in f:
                    if line.startswith("wchar:"):
                        return int(line.split()[1])
        except OSError:
            pass
        return 0

    return written


def _windows():
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                                                      "OtherOperationCount", "ReadTransferCount",
                                                      "WriteTransferCount", "OtherTransferCount")]

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    # the pseudo-handle of this process is -1 as a pointer: without argtypes ctypes passes it as an int and overflows
    kernel32.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IoCounters)]
    kernel32.GetProcessIoCounters.restype = wintypes.BOOL

    def written() -> int:
        c = IoCounters()
        if not kernel32.GetProcessIoCounters(kernel32.GetCurrentProcess(), ctypes.byref(c)):
            return 0
        return int(c.WriteTransferCount)

    return written


def _pick():
    try:
        if sys.platform == "darwin":
            return _macos()
        if sys.platform.startswith("linux"):
            return _linux()
        if sys.platform == "win32":
            return _windows()
    except (OSError, AttributeError):
        pass
    return lambda: 0


_measure = _pick()


def written() -> int:
    """Bytes this process has asked to write so far (0 where it cannot be measured: a meter never fails a test)."""
    try:
        return _measure()
    except Exception:  # noqa: BLE001
        return 0


def _budget() -> int:
    try:
        return int(float(os.environ.get("ENLENS_WRITE_BUDGET_MB") or 200) * 1_000_000)
    except ValueError:
        return 200_000_000


_START = pytest.StashKey[int]()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    item.stash[_START] = written()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    if call.when == "teardown" and _START in item.stash:
        n = written() - item.stash[_START]
        rep.user_properties.append(("bytes_written", n))
        budget = _budget()
        if budget and n > budget and item.get_closest_marker("heavy") is None:
            item.warn(WriteBudgetWarning(
                f"this test wrote {n / 1e6:.0f} MB (budget {budget / 1e6:.0f} MB, ENLENS_WRITE_BUDGET_MB): make it "
                "write less (a smaller project, fewer copies, the shared `loaded` file), or mark it heavy"))
    return rep


_ROWS: list[tuple[int, str]] = []


def pytest_runtest_logreport(report):
    if report.when == "teardown":
        for k, v in report.user_properties:
            if k == "bytes_written":
                _ROWS.append((int(v), report.nodeid))


def pytest_terminal_summary(terminalreporter):
    if hasattr(terminalreporter.config, "workerinput") or not _ROWS:  # a pytest-xdist worker: the controller says it
        return
    out = os.environ.get("ENLENS_WRITES_JSON")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump([{"id": i, "bytes": n} for n, i in _ROWS], f)
    try:
        top = int(os.environ.get("ENLENS_WRITES") or 0)
    except ValueError:
        top = 0
    if top > 0:
        total = sum(n for n, _ in _ROWS)
        terminalreporter.section(f"{top} tests that wrote the most (all {len(_ROWS)}: {total / 1e9:.2f} GB)")
        for n, nodeid in sorted(_ROWS, reverse=True)[:top]:
            terminalreporter.write_line(f"{n / 1e6:9.1f} MB  {nodeid}")


if __name__ == "__main__":  # python tools/writemeter.py: whether this computer can measure it
    import tempfile

    with tempfile.TemporaryFile() as f:
        a = written()
        f.write(b"x" * 4_000_000)
        f.flush()
        os.fsync(f.fileno())
        n = written() - a
    print(f"{sys.platform}: a 4 MB write counted as {n} bytes ({'works' if n >= 4_000_000 else 'NOT measured'})")

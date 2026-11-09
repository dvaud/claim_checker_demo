"""0.16 (H3): a process that reads files for `ingest`, one at a time, so that several files are read at once.

`ingest._Readings` starts it (through `procs.no_window()`, so no window opens on Windows) with the same Python and the
app's own `sys.path`, so it reads with exactly the modules the app would. It takes tasks on its standard input and
answers on its standard output, each one a length (8 bytes, big-endian) followed by a pickle. A task is (path,
OcrOptions, max_chars, min_chars, stop file, checksums of files already stored); its answer is what
`ingest._read_whole` gives for it, or ("redo",) when that cannot be sent back (`ingest` then reads the file itself).
Anything else written to standard output goes nowhere: the answers have a copy of it to themselves. The stop file
appears when the person presses Stop, and the text recognition of a scanned PDF looks for it between pages. The
process ends when its input closes, and at once when the program that started it (`ENLENS_READ_PARENT`) is gone: a
crash or a forced quit of the app leaves no reading behind.

Nothing is stored here: reading a file is pure (`ingest.read_document` stores nothing either), so a file read in this
process gives exactly the reading the app would make of it.
"""
from __future__ import annotations

import os
import pickle
import struct
import sys

HEAD = struct.Struct(">Q")


def read_exact(f, n: int) -> bytes | None:
    """n bytes from a pipe, or None when it closes first."""
    buf = bytearray()
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def send(f, obj) -> None:
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    f.write(HEAD.pack(len(data)) + data)
    f.flush()


def receive(f):
    """The next message, or None when the pipe closes."""
    head = read_exact(f, HEAD.size)
    if head is None:
        return None
    data = read_exact(f, HEAD.unpack(head)[0])
    return None if data is None else pickle.loads(data)


def watch(parent: int) -> None:
    """End this process at once when `parent` ends (a thread: Windows waits on the process, POSIX looks every half
    second whether this process was handed to another parent)."""
    if os.name == "nt":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        handle = k32.OpenProcess(0x00100000, False, parent)  # SYNCHRONIZE
        if not handle:
            return  # not ours to watch (or already gone): the end of the input still ends this process
        k32.WaitForSingleObject(handle, 0xFFFFFFFF)  # INFINITE: returns when the parent ends
        os._exit(0)
    import time

    if os.getppid() != parent:  # started through another program: look at the parent itself
        while True:
            try:
                os.kill(parent, 0)
            except ProcessLookupError:
                os._exit(0)
            except OSError:
                pass
            time.sleep(0.5)
    while os.getppid() == parent:
        time.sleep(0.5)
    os._exit(0)


def main() -> int:
    inp = os.fdopen(os.dup(0), "rb")
    out = os.fdopen(os.dup(1), "wb")
    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, 0)
    os.dup2(null, 1)  # a library that prints cannot mix its words into the answers
    sys.stdin = sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - for the life of the process
    parent = os.environ.get("ENLENS_READ_PARENT", "")
    if parent.isdigit():
        import threading

        threading.Thread(target=watch, args=(int(parent),), name="enlens-read-watch", daemon=True).start()
    from . import ingest

    while True:
        task = receive(inp)
        if task is None:
            return 0
        path, ocr, max_chars, min_chars, stop_file, known = task
        result = ingest._read_whole(path, ocr, max_chars, min_chars,
                                    lambda: bool(stop_file) and os.path.exists(stop_file), known)
        try:
            send(out, result)
        except (pickle.PicklingError, TypeError, AttributeError, RecursionError):
            send(out, ("redo",))


if __name__ == "__main__":
    sys.exit(main())

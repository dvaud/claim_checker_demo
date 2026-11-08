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

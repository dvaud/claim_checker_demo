"""0.16.0rc2: the scratch copy of a project (model tests and label comparisons with Claude Code) is removed even when a
helper reads it just then.

Claude Code answers such tasks from a copy of the project, which is removed afterwards. Every connection to it is
closed first, as Windows cannot remove an open database; but a helper that reads the copy at that moment (the
connector in the middle of a call) opens it again before it is gone, and on Windows the copy stayed behind. On
Windows the closing and removing are now tried again for a few seconds. This Mac and Linux remove an open file, so the
held file is played here by a removal that fails the first times.
"""
from __future__ import annotations

import shutil


def _held(monkeypatch, fails: int) -> list[int]:
    """shutil.rmtree that leaves the folder `fails` times (a file in it held open), then removes it."""
    real, calls = shutil.rmtree, []

    def rmtree(path, ignore_errors=False, **kw):
        calls.append(1)
        if len(calls) > fails:
            real(path, ignore_errors=ignore_errors, **kw)

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    return calls


def test_the_copy_is_removed_again_on_windows_while_a_helper_holds_it(monkeypatch, tmp_path):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    from enlens_claims import home, taskqueue

    copy = home.create_project("C model test")
    closed = []
    real_close = copy.close_all
    monkeypatch.setattr(copy, "close_all", lambda: (closed.append(1), real_close()))
    calls = _held(monkeypatch, fails=2)
    assert taskqueue.remove_copy(copy, windows=True) is True
    assert not copy.root.exists() and "C model test" not in home.list_projects()
    assert len(calls) == 3 and len(closed) == 3            # closed again before each removal


def test_elsewhere_and_when_it_stays_held_it_is_tried_once_or_given_up(monkeypatch, tmp_path):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    from enlens_claims import home, taskqueue

    monkeypatch.setattr(taskqueue.time, "sleep", lambda s: None)
    copy = home.create_project("C model test")
    calls = _held(monkeypatch, fails=99)
    assert taskqueue.remove_copy(copy, windows=False) is False and len(calls) == 1   # macOS, Linux: no waiting
    assert taskqueue.remove_copy(copy, tries=4, windows=True) is False and len(calls) == 5
    assert copy.root.exists()                               # left for the trash, as a quick look, as before

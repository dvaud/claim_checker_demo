"""2026-11-12: a round of the shared folder that finds nothing new writes (almost) nothing to disk.

The poller starts a round every couple of minutes for each project with a shared folder, all day; a round that wrote
even a few MB each time (a copy of the database, files rewritten with the same content) would wear the SSD for
nothing. These tests run rounds the way the poller does (`poller._round`, which calls `folder.sync_now`), after a
warm-up round, and count the bytes this process asks to write (tools/writemeter.py) and the files whose time of last
change moved: for one copy alone in the folder, and for two copies with nothing new on either side.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import threading
from pathlib import Path

from writemeter import written

from enlens_claims import sharing, store
from enlens_claims.gui import poller
from test_shared_projects import anna_and_ben  # noqa: F401  (fixture)
from test_shared_folder import _check, pair, shared_dir  # noqa: F401  (fixtures)

ROUNDS = 10
BUDGET = 1024 * 1024   # bytes, for all ten rounds
EVERY = dt.timedelta(minutes=2)   # the poller's interval (Settings: sync_every_minutes)


class _Job:
    """What `poller._round` uses of a job."""

    def __init__(self):
        self.progress, self.cancel = None, threading.Event()


def _poller_round(p) -> dict:
    with p:
        out = poller._round(p.ws, _Job())
    assert out is not None and not [x for x in out["problems"] if x["kind"] != "documents"], out
    return out


def _mtimes(*folders: Path) -> dict[str, int]:
    out = {}
    for d in folders:
        for root, _dirs, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                try:
                    out[p] = os.stat(p).st_mtime_ns
                except FileNotFoundError:
                    pass
    return out


def _idle(people, folders, monkeypatch) -> tuple[int, list[str]]:
    """Ten idle rounds (each person's, in turn), two minutes apart on ENLENS's clock (`store.now`, wherever a module
    took it in), so a time written each round is caught; returns the bytes written and the files changed or added."""
    start, at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0), [0]

    def now() -> str:
        return (start + at[0] * EVERY).isoformat()

    real = store.now
    for name, mod in list(sys.modules.items()):
        if name.startswith("enlens_claims") and getattr(mod, "now", None) is real:
            monkeypatch.setattr(mod, "now", now)
    before = _mtimes(*folders)
    w0 = written()
    for i in range(ROUNDS):
        at[0] = i + 1
        for p in people:
            out = _poller_round(p)
            assert out["wrote"]["seq"] is None, out["wrote"]
            assert not [e for e in out["read"] if e.get("report")], out["read"]
    used = written() - w0
    after = _mtimes(*folders)
    return used, sorted(f for f, t in after.items() if before.get(f) != t)


def test_idle_rounds_of_a_copy_alone_in_the_folder_write_almost_nothing(pair, shared_dir, monkeypatch):
    anna, _ben = pair
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    assert _poller_round(anna)["wrote"]["seq"] == 1
    _poller_round(anna)   # warm-up: what the first round left to settle
    used, changed = _idle([anna], [anna.ws.root, shared_dir], monkeypatch)
    print(f"\n{ROUNDS} idle rounds, one copy: {used} bytes, files changed: {changed}")
    assert used < BUDGET, used
    assert not changed, changed


def test_idle_rounds_with_a_colleague_present_write_almost_nothing(pair, shared_dir, monkeypatch):
    anna, ben = pair
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    _poller_round(anna)
    _poller_round(ben)    # Ben brings in Anna's work, and writes his first bundle
    _poller_round(anna)   # Anna reads Ben's
    _poller_round(ben)    # warm-up
    _poller_round(anna)
    used, changed = _idle([anna, ben], [anna.ws.root, ben.ws.root, shared_dir], monkeypatch)
    print(f"\n{ROUNDS} idle rounds, two copies: {used} bytes, files changed: {changed}")
    assert used < 2 * BUDGET, used
    assert not changed, changed

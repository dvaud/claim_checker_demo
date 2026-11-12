"""0.17.0: setting up a project flushed each of its ~110 schema statements to disk on its own (the default
synchronous=FULL; each statement of a script is a transaction). Cheap on macOS and Linux, about a second on Windows,
where a flush is FlushFileBuffers; every round of the shared folder sets up one to three scratch projects, so the 0.18
tests ran some 20 times slower there and the suite outran CI's time. The schema is written as every other connection
writes (`Workspace._conn`): synchronous=NORMAL, safe with WAL."""
from __future__ import annotations

import sqlite3

from enlens_claims.store import Workspace


def test_setting_up_a_project_does_not_flush_each_schema_statement_to_disk(tmp_path, monkeypatch):
    levels = []

    class Probe(sqlite3.Connection):
        def executescript(self, script):
            levels.append(self.execute("PRAGMA synchronous").fetchone()[0])
            return super().executescript(script)

    real = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: real(*a, **{"factory": Probe, **kw}))
    Workspace.create(tmp_path / "new")   # a new project, as each scratch copy of a round of the shared folder is
    Workspace.open(tmp_path / "new")     # and one opened again
    assert levels and all(v <= 1 for v in levels), levels   # 0 OFF, 1 NORMAL; 2 FULL flushes every statement

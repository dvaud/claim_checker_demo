"""2026-11-12: the project's write-ahead log (enlens.sqlite-wal) does not keep the size of the largest write it held.

Without `journal_size_limit` the log stays as large as its largest transaction (adding many documents, a new
glossary) for as long as the app has the project open, and `store.trim_log` empties it right after a big write when
nothing reads an older state. A reader that holds an older state blocks that; once it lets go, ordinary use brings
the log back under the limit."""
from __future__ import annotations

import threading
from pathlib import Path

from enlens_claims.store import JOURNAL_SIZE_LIMIT, Workspace

BIG = "x" * 4000


def _big_write(ws: Workspace) -> None:
    with ws.connect() as cx:   # ~24 MB in one transaction: three times the limit
        cx.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", [(f"big{i}", BIG) for i in range(6000)])


def _wal(ws: Workspace) -> int:
    p = Path(f"{ws.db_path}-wal")
    return p.stat().st_size if p.exists() else 0


def _in_thread(fn) -> None:
    t = threading.Thread(target=fn)
    t.start()
    t.join()


def test_the_log_is_emptied_right_after_a_big_write(ws):
    ws.set_meta("before", "1")
    _big_write(ws)
    assert _wal(ws) <= JOURNAL_SIZE_LIMIT
    _in_thread(lambda: ws.query("SELECT COUNT(*) FROM meta"))   # another thread's connection, as a request's
    ws.set_meta("after", "1")
    assert _wal(ws) <= JOURNAL_SIZE_LIMIT
    assert ws.scalar("SELECT COUNT(*) FROM meta WHERE key LIKE 'big%'") == 6000


def test_a_reader_holds_the_log_only_while_it_reads(ws):
    holding, done = threading.Event(), threading.Event()

    def reader():   # a connection of its own that reads an older state of the project during the big write
        import sqlite3

        cx = sqlite3.connect(ws.db_path, timeout=60, isolation_level=None)
        try:
            cx.execute("BEGIN")
            cx.execute("SELECT COUNT(*) FROM meta").fetchone()
            holding.set()
            done.wait(30)
            cx.execute("COMMIT")
        finally:
            cx.close()

    t = threading.Thread(target=reader)
    t.start()
    try:
        assert holding.wait(30)
        _big_write(ws)
        assert _wal(ws) > JOURNAL_SIZE_LIMIT   # it could not be emptied: the reader needed what the file held
    finally:
        done.set()
        t.join()
    for i in range(3):   # ordinary use afterwards: reads in other threads, small writes
        _in_thread(lambda: ws.query("SELECT key FROM meta LIMIT 5"))
        ws.set_meta(f"small{i}", str(i))
    assert _wal(ws) <= JOURNAL_SIZE_LIMIT

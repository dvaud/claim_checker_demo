"""2026-11-13: a new project's database (also each scratch project of a shared-folder round) is a copy of an empty one
the process made once with the usual setup (`store._copy_empty_database`), not set up again table by table. The copy
must be the same database the setup makes, follow any change to the layout, and share nothing between projects."""
import sqlite3
import threading

from enlens_claims import addons, store
from enlens_claims.store import Workspace


def _picture(db) -> tuple[list, list]:
    """The layout and every row of a database."""
    cx = sqlite3.connect(db)
    try:
        layout = sorted(cx.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        rows = []
        for (table,) in cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            rows += [(table, r) for r in sorted(cx.execute(f'SELECT * FROM "{table}"'), key=repr)]
        settings = [cx.execute(f"PRAGMA {p}").fetchone()[0]
                    for p in ("journal_mode", "page_size", "auto_vacuum", "user_version", "encoding")]
        return layout, rows, settings
    finally:
        cx.close()


def _set_up_the_old_way(root):
    ws = Workspace(root)
    ws.root.mkdir(parents=True)
    ws._setup()  # a database file that does not exist yet, set up statement by statement
    return ws


def test_a_new_project_is_the_database_the_setup_makes(tmp_path):
    made = Workspace.create(tmp_path / "copied")
    old = _set_up_the_old_way(tmp_path / "set-up")
    assert _picture(made.db_path) == _picture(old.db_path)
    # and it is a project like any other: it opens, takes writes and makes its own id
    again = Workspace.open(made.root)
    with again.connect() as cx:
        again.set_meta("note", "x", cx)
    assert again.meta("note") == "x"


def test_projects_share_nothing(tmp_path):
    a, b = Workspace.create(tmp_path / "a"), Workspace.create(tmp_path / "b")
    with a.connect() as cx:
        a.set_meta("only_a", "1", cx)
    assert a.project_uid() != b.project_uid()
    assert b.meta("only_a") is None


def test_a_changed_layout_makes_a_new_empty_database(tmp_path, monkeypatch):
    Workspace.create(tmp_path / "before")
    monkeypatch.setattr(store, "MIGRATIONS", store.MIGRATIONS + [("documents", "added_later", "TEXT")])
    after = Workspace.create(tmp_path / "after")
    cols = {r[1] for r in sqlite3.connect(after.db_path).execute("PRAGMA table_info(documents)")}
    assert "added_later" in cols
    assert _picture(after.db_path) == _picture(_set_up_the_old_way(tmp_path / "set-up").db_path)


def test_a_table_defined_anew_is_made_anew(tmp_path, monkeypatch):
    """The setup after the copy adds what a copy lacks, but cannot change a table that is there: a table whose own
    definition changed needs a new empty database, which the key of `_copy_empty_database` gives."""
    Workspace.create(tmp_path / "before")
    old = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);"
    assert old in store.SCHEMA
    monkeypatch.setattr(store, "SCHEMA", store.SCHEMA.replace(old, old.replace("value TEXT", "value TEXT DEFAULT ''")))
    after = Workspace.create(tmp_path / "after")
    sql = sqlite3.connect(after.db_path).execute("SELECT sql FROM sqlite_master WHERE name='meta'").fetchone()[0]
    assert "DEFAULT ''" in sql


def test_an_add_ons_tables_are_in_the_copy(tmp_path, monkeypatch):
    Workspace.create(tmp_path / "before")
    extra = [{"addon": "t", "schema": "CREATE TABLE IF NOT EXISTS t_notes(id TEXT PRIMARY KEY, body TEXT);",
              "migrations": [("t_notes", "at", "TEXT")], "indexes": "CREATE INDEX IF NOT EXISTS t_notes_at ON t_notes(at);"}]
    monkeypatch.setattr(addons, "database", lambda: extra)
    ws = Workspace.create(tmp_path / "with-add-on")
    cx = sqlite3.connect(ws.db_path)
    assert {r[1] for r in cx.execute("PRAGMA table_info(t_notes)")} == {"id", "body", "at"}
    assert cx.execute("SELECT 1 FROM sqlite_master WHERE name='t_notes_at'").fetchone()


def test_many_at_once(tmp_path):
    errors, made = [], []

    def make(i):
        try:
            made.append(Workspace.create(tmp_path / f"p{i}"))
        except Exception as e:  # pragma: no cover - shown by the assert
            errors.append(e)

    threads = [threading.Thread(target=make, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(made) == 8
    pictures = {repr(_picture(ws.db_path)) for ws in made}
    assert len(pictures) == 1
    for ws in made:
        ws.close_all()

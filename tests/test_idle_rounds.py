"""Deep dive after 0.17.0, S5 and S14: a round of the shared folder that finds nothing new costs almost nothing.

A round used to fingerprint every check and set of themes and read every one of the project's rows, also when nothing
had changed anywhere. Now triggers count what changes (sync/changes.py) and a round looks only at that: these tests
check that every kind of change between two rounds is still written, that a change made during a round goes into the
next one, that two rounds with no change write nothing and read nothing, and that the record of what was written
(`sync_written`) is pruned when a snapshot is written. Throughout, the plan a round makes with what it remembers is
compared with the plan it would make looking at everything (`_plans_agree`).
"""
from __future__ import annotations

import random
import sqlite3
import zipfile

import pytest

from enlens_claims import access, bundle, claimcheck, codebooks, notes, people, profile, researchlog, sharing, themes
from enlens_claims.sync import changes, fingerprints, folder
from test_0_14_0_shared_projects import anna_and_ben  # noqa: F401  (fixture)
from test_0_18_0_shared_folder import _check, _claim, _excerpts, _round, pair, shared_dir  # noqa: F401  (fixtures)


# ---------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------
def _plan(ws, memory):
    team, _info = folder._open_team(ws, create=False)
    me = people.me()
    w = folder._Writer(ws, team, me, folder.keep_out_state(ws, team, me)["in_force"], None)
    rcx = folder._reader_cx(ws)
    try:
        w.plan(rcx, memory)
    finally:
        rcx.rollback()
        rcx.close()
    return {"items": [(it["kind"], it["key"], it["fp"]) for it in w.items], "waiting": w.waiting,
            "rows": {t: sorted(ids) for t, ids in w.new_rows.items()}, "row_keys": sorted(w.row_keys),
            "stubs": w.stub_fps, "readings": w.readings, "files": [f for f, _src in w.files], "words": w.words}


def _plans_agree(p) -> dict:
    """The plan made with what this process remembers is the plan made looking at everything."""
    with p:
        remembered = _plan(p.ws, changes.memory(p.ws.db_path))
        whole = _plan(p.ws, None)
    assert remembered == whole
    return whole


class _Spy:
    """What a round looked at: the items fingerprinted, the project's tables read, the checks fingerprinted for
    `record_seen`."""

    def __init__(self, monkeypatch):
        self.items, self.tables, self.units = [], [], []
        item, scan, unit = folder._item, sharing.ProjectRows.scan, fingerprints._check_unit

        def spy_item(ws, cx, kind, key, *a, **kw):
            self.items.append((kind, key))
            return item(ws, cx, kind, key, *a, **kw)

        def spy_scan(rows, only=None):
            self.tables.append(None if only is None else set(only))
            return scan(rows, only)

        def spy_unit(cx, hid):
            self.units.append(hid)
            return unit(cx, hid)

        monkeypatch.setattr(folder, "_item", spy_item)
        monkeypatch.setattr(sharing.ProjectRows, "scan", spy_scan)
        monkeypatch.setattr(fingerprints, "_check_unit", spy_unit)

    def clear(self):
        self.items.clear(), self.tables.clear(), self.units.clear()

    def read(self) -> set[str]:
        out: set[str] = set()
        for t in self.tables:
            out |= {"(every table)"} if t is None else t
        return out


def _records(p) -> tuple:
    with p:
        cx = p.ws._conn()
        return (sorted(tuple(r) for r in cx.execute("SELECT kind, key, fp, seq FROM sync_written")),
                sorted(tuple(r) for r in cx.execute("SELECT kind, key, fp FROM sync_seen")))


def _quiet(p, spy=None) -> None:
    """A round that writes nothing (and, with `spy`, reads nothing but who was last seen)."""
    before = _records(p)
    if spy:
        spy.clear()
    out = _round(p)
    assert out["wrote"]["seq"] is None, out["wrote"]
    assert _records(p) == before
    if spy:
        assert spy.items == [] and spy.units == [], (spy.items, spy.units)
        assert spy.read() <= {"people"}, spy.read()  # (this person's own row: when they were last here)


@pytest.fixture
def shared(pair):
    """Anna shares a check (with a judgement), a note and a log entry; both copies have done two rounds."""
    anna, ben = pair
    with anna:
        anna.h2 = _check(anna.ws, "Electrolysers create local jobs.")
        anna.ex = _excerpts(anna.ws, anna.h2)
        claimcheck.set_judgement(anna.ws, _claim(anna.ws, anna.h2), anna.ex[0]["passage_id"], "supports")
        doc, body = anna.ws.query("SELECT doc_id, text FROM documents ORDER BY doc_id LIMIT 1")[0]
        a = body.index(body.split()[5])
        anna.doc = doc
        anna.nid = notes.add(anna.ws, doc, a, a + 20, text="first thought")["note_id"]
        anna.eid = researchlog.add(anna.ws, "Met the water board.")["entry_id"]
        sharing.share(anna.ws, [{"kind": "check", "key": anna.h2}, {"kind": "note", "key": anna.nid},
                                {"kind": "log", "key": anna.eid}])
    for _ in range(2):
        _round(anna)
        _round(ben)
    return anna, ben


# ---------------------------------------------------------------------------------------------------------------------
# idle rounds
# ---------------------------------------------------------------------------------------------------------------------
def test_two_rounds_with_no_change_write_nothing_and_read_nothing(shared, monkeypatch):
    anna, ben = shared
    spy = _Spy(monkeypatch)
    for _ in range(2):
        for p in (anna, ben):
            _plans_agree(p)
            _quiet(p, spy)


def test_the_first_round_of_a_new_process_looks_at_everything(shared, monkeypatch):
    anna, _ben = shared
    changes.forget_all()  # (the app started again)
    spy = _Spy(monkeypatch)
    _quiet(anna)
    assert None in spy.tables and anna.h2 in spy.units
    _quiet(anna, spy)


# ---------------------------------------------------------------------------------------------------------------------
# a change between two rounds is always written
# ---------------------------------------------------------------------------------------------------------------------
def _written_after(p, change, item=None, table=None) -> dict:
    with p:
        change(p)
    _plans_agree(p)
    out = _round(p)["wrote"]
    assert out["seq"] is not None, out
    if item:
        assert item in [(i["kind"], i["key"]) for i in out["items"]], out["items"]
    if table:
        with p:
            assert out["rows"] > 0
    _plans_agree(p)
    _quiet(p)
    return out


def test_a_judgement_is_written(shared):
    anna, _ben = shared
    _written_after(anna, lambda p: claimcheck.set_judgement(p.ws, _claim(p.ws, p.h2), p.ex[1]["passage_id"], "refutes"),
                   ("check", anna.h2))


def test_a_note_and_a_log_entry_are_written(shared):
    anna, _ben = shared
    _written_after(anna, lambda p: notes.update(p.ws, p.nid, text="second thought"), ("note", anna.nid))
    _written_after(anna, lambda p: researchlog.update(p.ws, p.eid, "Met the water board twice."), ("log", anna.eid))


def test_a_check_shared_and_a_check_taken_back_are_written(shared):
    anna, _ben = shared
    with anna:
        h3 = _check(anna.ws, "Desalination costs little.")
    assert _round(anna)["wrote"]["seq"] is None  # private: nothing goes
    _quiet(anna)
    _written_after(anna, lambda p: sharing.share(p.ws, [{"kind": "check", "key": h3}]), ("check", h3))
    _written_after(anna, lambda p: sharing.unshare(p.ws, [{"kind": "check", "key": h3}]), ("check", h3))


def test_a_set_of_themes_is_written_when_a_theme_is_renamed(shared):
    from pathlib import Path

    from enlens_claims import ingest

    anna, _ben = shared
    with anna:
        ingest.ingest(anna.ws, [Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"])
        run = themes.run(anna.ws, k=3, seed=1)
        sharing.share(anna.ws, [{"kind": "themes", "key": run}])
    _round(anna)
    _quiet(anna)
    tid = themes.view(anna.ws, run)["themes"][0]["theme_id"]
    _written_after(anna, lambda p: themes.edit(p.ws, run, "rename", tid, "Water and brine"), ("themes", run))


def test_a_codebook_is_written_when_a_label_or_a_code_changes(shared):
    from test_0_18_0_codebook_merge import _edit, _set

    anna, _ben = shared
    with anna:
        codebooks.create(anna.ws, "water", "Water", "project", "csv",
                         {"csv": "code,description\nA,Water use of electrolysis\nB,Jobs near the plant\n"})
        sharing.share(anna.ws, [{"kind": "codebook", "key": "water"}])
    _round(anna)
    _quiet(anna)
    pid = anna.ex[0]["passage_id"]
    _written_after(anna, lambda p: profile.add_label(p.ws, "water", pid, "A"), ("codebook", "water"))
    _written_after(anna, lambda p: _edit(p.ws, "water", _set("description", "B", "Local jobs and training")),
                   ("codebook", "water"))


def test_the_projects_own_rows_are_written(shared):
    anna, _ben = shared
    pid = anna.ex[0]["passage_id"]
    out = _written_after(anna, lambda p: profile.add_label(p.ws, "sdg", pid, "6.4"), table="labels")
    assert out["items"] == []


def test_a_documents_ai_setting_is_written(shared):
    anna, _ben = shared
    before = _round(anna)
    assert before["wrote"]["seq"] is None
    out = _written_after(anna, lambda p: access.set_documents(p.ws, [p.doc], "local"))
    assert out["documents"] >= 1


def test_a_document_read_again_is_written(pair, tmp_path):
    from enlens_claims import reread
    from owner_helpers import add_doc

    anna, ben = pair
    doc = add_doc(anna, tmp_path, "jobs", reader=1)
    _round(anna)
    _quiet(anna)
    out = _written_after(anna, lambda p: reread.move(p.ws, doc))
    assert out["readings"] == 1


def test_a_block_left_out_is_written(pair):
    from owner_helpers import leave_out

    anna, ben = pair
    with anna:
        doc = anna.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
    _round(anna)
    _quiet(anna)
    _written_after(anna, lambda p: leave_out(p, doc, 1))


def test_a_change_made_by_another_program_is_written(shared):
    """The counters are triggers in the database: a change made outside the app (another version of ENLENS, a script)
    counts too."""
    anna, _ben = shared

    def outside(p):
        cx = sqlite3.connect(p.ws.db_path)
        with cx:
            cx.execute("UPDATE notes SET text='written elsewhere' WHERE note_id=?", (p.nid,))
        cx.close()

    _written_after(anna, outside, ("note", anna.nid))


def test_a_table_made_anew_gets_its_counters_again_and_is_read_whole(shared):
    """A table remade (as a migration remakes one) loses its triggers: they are made again, and the round reads every
    table, so nothing changed meanwhile is missed."""
    anna, _ben = shared

    def remake(p):
        with p.ws.connect() as cx:
            (sql,) = cx.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='doc_refs'").fetchone()
            cx.execute("CREATE TEMP TABLE old_refs AS SELECT * FROM doc_refs")
            cx.execute("DROP TABLE doc_refs")
            cx.execute(sql)
            cx.execute("INSERT INTO doc_refs SELECT * FROM old_refs")
            cx.execute("DROP TABLE old_refs")
            cx.execute("INSERT INTO doc_refs(doc_id, ref_key, method, score) VALUES (?, 'by-hand', 'person', 1)",
                       (p.doc,))
        assert not p.ws.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'enlens_changes_doc_refs_%'")

    out = _written_after(anna, remake)
    assert out["rows"] == 1
    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE "
                              "'enlens_changes_doc_refs_%'") == 3


# ---------------------------------------------------------------------------------------------------------------------
# a change during a round
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("step", ["Looking for what changed", "Writing what you shared"])
def test_a_change_made_during_a_round_goes_into_the_next_round(shared, step):
    anna, _ben = shared
    with anna:
        notes.update(anna.ws, anna.nid, text="something to write this round")
    cid, pid = _claim(anna.ws, anna.h2), anna.ex[1]["passage_id"]
    done = []

    def progress(where, message, info):
        if message == step and not done:  # the round has read the project already
            done.append(claimcheck.set_judgement(anna.ws, cid, pid, "refutes"))

    with anna:
        out = folder.sync_now(anna.ws, progress=progress)
    assert done and [(i["kind"], i["key"]) for i in out["wrote"]["items"]] == [("note", anna.nid)]
    _plans_agree(anna)
    out = _round(anna)
    assert [(i["kind"], i["key"]) for i in out["wrote"]["items"]] == [("check", anna.h2)]
    _quiet(anna)


def test_a_change_made_during_a_round_with_nothing_to_write_goes_into_the_next_round(shared):
    anna, _ben = shared
    done = []

    def progress(where, message, info):
        if message == "Looking for what changed" and not done:
            done.append(notes.update(anna.ws, anna.nid, text="changed while the round looked"))

    with anna:
        out = folder.sync_now(anna.ws, progress=progress)
    assert done and out["wrote"]["seq"] is None
    out = _round(anna)
    assert [(i["kind"], i["key"]) for i in out["wrote"]["items"]] == [("note", anna.nid)]


def test_a_round_that_fails_after_reading_forgets_nothing(shared, monkeypatch):
    anna, _ben = shared
    with anna:
        notes.update(anna.ws, anna.nid, text="a round fails before this is written")

    def broken(*a, **kw):
        raise OSError("the cloud folder went away")

    with monkeypatch.context() as m:
        m.setattr(folder._Writer, "write_bundle", broken)
        with anna, pytest.raises(OSError):
            folder.write(anna.ws)
    _plans_agree(anna)
    out = _round(anna)
    assert [(i["kind"], i["key"]) for i in out["wrote"]["items"]] == [("note", anna.nid)]


# ---------------------------------------------------------------------------------------------------------------------
# many changes in turn
# ---------------------------------------------------------------------------------------------------------------------
def test_rounds_after_random_changes_plan_as_if_they_looked_at_everything(shared):
    anna, ben = shared
    rng = random.Random(5)
    with anna:
        h3 = _check(anna.ws, "Desalination costs little.")
        pids = [r[0] for r in anna.ws.query("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 30")]
        docs = [r[0] for r in anna.ws.query("SELECT doc_id FROM documents")]
    cid = _claim(anna.ws, anna.h2)

    steps = [
        lambda: claimcheck.set_judgement(anna.ws, cid, rng.choice(anna.ex)["passage_id"],
                                         rng.choice(["supports", "refutes", "not_relevant"])),
        lambda: notes.update(anna.ws, anna.nid, text=f"thought {rng.random():.4f}"),
        lambda: researchlog.update(anna.ws, anna.eid, f"Met the board {rng.randint(1, 99)} times."),
        lambda: sharing.share(anna.ws, [{"kind": "check", "key": h3}]),
        lambda: sharing.unshare(anna.ws, [{"kind": "check", "key": h3}]) if sharing.state(
            anna.ws._conn(), "check", h3)["state"] == "shared" else None,
        lambda: profile.add_label(anna.ws, "sdg", rng.choice(pids), rng.choice(["6.4", "7.2", "8.5"])),
        lambda: access.set_documents(anna.ws, [rng.choice(docs)], rng.choice(["cloud", "local", "none"])),
        lambda: researchlog.add(anna.ws, f"A private note {rng.random():.3f}."),
        lambda: None,
    ]
    for i in range(24):
        with anna:
            rng.choice(steps)()
        _plans_agree(anna)
        _round(anna)
        _plans_agree(anna)
        if i % 4 == 3:
            _round(ben)
            _plans_agree(ben)
    _quiet(anna)


# ---------------------------------------------------------------------------------------------------------------------
# S14: the record of what was written
# ---------------------------------------------------------------------------------------------------------------------
def test_the_record_keeps_no_row_that_is_no_more_once_a_snapshot_is_written(shared, monkeypatch):
    anna, _ben = shared
    with anna:
        cx = anna.ws._conn()
        live = cx.execute("SELECT COUNT(*) FROM sync_written WHERE kind='row'").fetchone()[0]
        with anna.ws.connect() as w:  # a colleague's row that came in, and one of this copy's own, both gone since
            w.execute("INSERT INTO sync_written(kind, key, fp, seq, at) VALUES ('row', 'gone-theirs', 'x', NULL, '')")
            w.execute("INSERT INTO sync_written(kind, key, fp, seq, at) VALUES ('row', 'gone-mine', 'x', 1, '')")
    _quiet(anna)  # (an ordinary round leaves the record as it is)
    with anna:
        folder._begin_again(folder._open_team(anna.ws, create=False)[0] / people.me())
    out = _round(anna)
    assert out["wrote"]["snapshot"]
    with anna:
        keys = {r[0] for r in cx.execute("SELECT key FROM sync_written WHERE kind='row'")}
        assert "gone-theirs" not in keys and "gone-mine" not in keys
        assert len(keys) == live
    spy = _Spy(monkeypatch)
    _plans_agree(anna)
    _quiet(anna, spy)  # the round's own pruning is no change for the next one


def test_a_row_written_again_is_no_change_for_the_next_round(shared, monkeypatch):
    """A row of the project changed in place is written again, and its entry in the record replaced. Some SQLite builds
    have recursive triggers on by default, where INSERT OR REPLACE deletes the old entry first: the round's own
    bookkeeping must not count as a change, or every round after it would read every table again."""
    anna, _ben = shared
    pid = anna.ex[0]["passage_id"]
    with anna:
        lid = profile.add_label(anna.ws, "sdg", pid, "6.4")
    _round(anna)
    _quiet(anna)
    with anna:
        anna.ws._conn().execute("PRAGMA recursive_triggers=ON")
        with anna.ws.connect() as cx:
            cx.execute("UPDATE labels SET relevance='low' WHERE label_id=?", (lid,))
    out = _round(anna)
    assert out["wrote"]["rows"] == 1
    spy = _Spy(monkeypatch)
    _quiet(anna, spy)


def test_a_round_never_loads_the_whole_record_of_rows(shared):
    anna, _ben = shared
    seen = []
    with anna:
        cx = anna.ws._conn()
        assert cx.execute("SELECT COUNT(*) FROM sync_written WHERE kind='row'").fetchone()[0] > 0
        assert all(k != "row" for k, _key in folder._written(cx))
        team, _ = folder._open_team(anna.ws, create=False)
        w = folder._Writer(anna.ws, team, people.me(), False, None)
        rcx = folder._reader_cx(anna.ws)
        rcx.set_trace_callback(seen.append)
        try:
            w.plan(rcx, None)
        finally:
            rcx.rollback()
            rcx.close()
    reads = [q for q in seen if "sync_written" in q]
    assert reads and all("WHERE" in q for q in reads), reads
    assert all("'row'" not in q or "kind != 'row'" in q or "kind='row' AND key IN" in q for q in reads), reads


# ---------------------------------------------------------------------------------------------------------------------
# privacy: the counters never leave this computer
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("scope", ["shared", "all"])
def test_a_project_zip_carries_no_change_counters(shared, tmp_path, scope):
    anna, _ben = shared
    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM sync_changes") > 1
        out = tmp_path / f"anna-{scope}.zip"
        bundle.export_project(anna.ws, out, scope=scope)
    with zipfile.ZipFile(out) as zf:
        zf.extract("enlens.sqlite", tmp_path / scope)
    cx = sqlite3.connect(tmp_path / scope / "enlens.sqlite")
    try:
        assert not cx.execute("SELECT 1 FROM sqlite_master WHERE name='sync_changes'").fetchone()
        assert not cx.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name LIKE 'enlens_changes_%'"
                              ).fetchone()
    finally:
        cx.close()
    _quiet(anna)  # the project's own counters are as they were


def test_a_whole_project_zip_keeps_nothing_of_the_counters_in_free_pages(shared, tmp_path):
    anna, _ben = shared
    with anna, anna.ws.connect() as cx:
        cx.execute("INSERT INTO sync_changes(tbl, hint, n) VALUES ('notes', 'PRIVATEHINT42', 1)")
    out = tmp_path / "anna-all.zip"
    with anna:
        bundle.export_project(anna.ws, out, scope="all")
    with zipfile.ZipFile(out) as zf:
        assert b"PRIVATEHINT42" not in zf.read("enlens.sqlite")


# ---------------------------------------------------------------------------------------------------------------------
# what the counters cannot see
# ---------------------------------------------------------------------------------------------------------------------
def test_a_codebook_rewritten_at_the_same_size_and_time_is_written(shared):
    import os
    from pathlib import Path

    anna, _ben = shared
    with anna:
        codebooks.create(anna.ws, "water", "Water", "project", "csv",
                         {"csv": "code,description\nA,Water use of the plant\nB,Jobs near the plant\n"})
        sharing.share(anna.ws, [{"kind": "codebook", "key": "water"}])
    _round(anna)
    _quiet(anna)
    f = Path(anna.ws.root) / "frameworks" / "water.csv"

    def same_size(p):
        st = f.stat()
        data = f.read_bytes()
        assert b"plant" in data
        f.write_bytes(data.replace(b"plant", b"plank", 1))
        assert f.stat().st_size == st.st_size
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))  # (as a sync service or `cp -p` carries it over)

    _written_after(anna, same_size, ("codebook", "water"))


def test_triggers_made_by_another_version_are_made_again(shared):
    anna, _ben = shared
    with anna, anna.ws.connect() as cx:  # a trigger of notes as another version made it: it counts nothing
        cx.execute('DROP TRIGGER "enlens_changes_notes_u"')
        cx.execute('CREATE TRIGGER "enlens_changes_notes_u" AFTER UPDATE ON "notes" BEGIN SELECT 1; END')
    _written_after(anna, lambda p: notes.update(p.ws, p.nid, text="seen by this version's trigger"), ("note", anna.nid))
    with anna:
        assert "SELECT 1" not in anna.ws.scalar("SELECT sql FROM sqlite_master WHERE name='enlens_changes_notes_u'")


def test_another_copy_of_the_database_put_in_its_place_is_looked_at_whole(shared, tmp_path):
    """The project folder synced from another computer of the same person: its database has its own counters, whose
    clock may be ahead of what this process remembers."""
    import shutil

    anna, _ben = shared
    with anna:
        other = tmp_path / "other.sqlite"
        src, dst = sqlite3.connect(anna.ws.db_path), sqlite3.connect(other)
        src.backup(dst)
        src.close()
        dst.execute("UPDATE notes SET text='written on the desktop' WHERE note_id=?", (anna.nid,))
        dst.execute("UPDATE sync_changes SET n = n + 100000 WHERE tbl='' AND hint=''")  # its clock: far ahead
        dst.execute("UPDATE sync_changes SET n = 7 WHERE tbl='' AND hint='id'")         # another database
        dst.execute("UPDATE sync_changes SET n = 1 WHERE tbl='notes'")                   # (a change it stamped early)
        dst.commit()
        dst.close()
        anna.ws.close_all()
        for suffix in ("-wal", "-shm"):
            w = anna.ws.db_path.with_name(anna.ws.db_path.name + suffix)
            if w.exists():
                w.unlink()
        shutil.copyfile(other, anna.ws.db_path)
    _plans_agree(anna)
    out = _round(anna)
    assert ("note", anna.nid) in [(i["kind"], i["key"]) for i in out["wrote"]["items"]]


def test_what_a_colleagues_round_brought_in_is_counted_without_the_counters_own_writes(shared):
    """The report of work brought in counts rows. SQLite's `total_changes` also counts what triggers write, so with
    the change counters every judgement and row brought in counted three times (it said 6 judgements came for 2)."""
    anna, ben = shared
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE "
                             "'enlens_changes_judgements_%'") == 3
    pid = anna.ex[1]["passage_id"]
    with anna:
        claimcheck.set_judgement(anna.ws, _claim(anna.ws, anna.h2), pid, "refutes")
        profile.add_label(anna.ws, "sdg", pid, "6.4")
    _round(anna)
    rep = _round(ben)["read"][0]["report"]
    assert rep["judgements"] == 1
    assert rep["labels"] == 1

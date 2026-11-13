"""Roles, groundwork (DESIGN-roles §3, S0): the tables and columns, format 4, and which tables travel.

- a new project has every table and column of §3;
- a project made before (the schema of a0088bb: 0.17.0 and the deep-dive fixes) gains them and keeps its rows;
- each new table travels or stays in this copy exactly as §3.1 and §3.2 say;
- format 4 (§3.3): what this ENLENS writes; a file of format 3 or older still comes in; the shared folder's bundles
  and a zip of a project with an owner need format 4, a zip of a project with no owner still needs only format 1.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from enlens_claims import sharing
from enlens_claims.store import Workspace
from enlens_claims.sync import common, folder, formats
from test_0_14_0_shared_projects import CLAIM, Person, anna_and_ben  # noqa: F401  (fixture)

# DESIGN-roles §3.1 and §3.2: table -> its columns as the design names them
TRAVEL = {
    "ownership": {"seq", "owner", "by", "at", "kind", "after", "why", "sig"},
    "roles": {"person", "by", "owner_seq", "n", "role", "grant", "same_as", "at", "sig"},
    "decisions": {"proposal", "by", "owner_seq", "verdict", "reason", "at", "auto", "n", "grant", "knew_json", "sig"},
    "canon": {"doc", "by", "owner_seq", "n", "grant", "state", "state_n", "state_by", "sha1", "title", "text_fp",
              "reader", "read_n", "read_by", "ai_access", "ai_n", "ai_by", "ai_hist_json", "blocks_json", "blocks_n",
              "blocks_by", "hist_json", "at", "sig"},
}
LOCAL = {
    "owner_pins": {"seq", "by", "owner", "state", "at"},
    "removed_docs": {"doc_id", "title", "at", "by", "why", "cause", "archive", "bytes"},
    "sync_via": {"kind", "key", "author", "via", "at"},
    "sync_from": {"kind", "key", "fp", "person", "at"},
    "sync_refused": {"kind", "key", "what_json", "via", "n", "at", "state"},
}
SEEN_NEW = {"state_by", "read_by", "ai_by", "blocks_by", "blocks_base", "ai_offer"}  # canon_seen's new columns
NEW_TABLES = {"roles"} | set(LOCAL)

# the four tables as a0088bb made them (store.SCHEMA of then), to make a project of that version
OLD_SCHEMA = """
CREATE TABLE ownership(seq INT, owner TEXT, by TEXT, at TEXT, kind TEXT, after TEXT, why TEXT, PRIMARY KEY(seq, by));
CREATE TABLE decisions(proposal TEXT, by TEXT, owner_seq INT, verdict TEXT, reason TEXT, at TEXT,
  auto INT, PRIMARY KEY(proposal, by));
CREATE TABLE canon(doc TEXT, by TEXT, owner_seq INT, n INT, state TEXT, state_n INT, sha1 TEXT, title TEXT,
  text_fp TEXT, reader INT, read_n INT, ai_access TEXT, ai_n INT, ai_hist_json TEXT, blocks_json TEXT, blocks_n INT,
  at TEXT, PRIMARY KEY(doc, by));
CREATE TABLE canon_seen(doc TEXT PRIMARY KEY, state_n INT, read_n INT, ai_n INT, ai_level TEXT,
  blocks_n INT, blocks_json TEXT, gone INT, came_from TEXT, read_tried INT, read_note TEXT, read_from TEXT);
"""


def _cols(db: Path, table: str) -> set[str]:
    cx = sqlite3.connect(db)
    try:
        return {r[1] for r in cx.execute(f"PRAGMA table_info({table})")}
    finally:
        cx.close()


def _tables(db: Path) -> set[str]:
    cx = sqlite3.connect(db)
    try:
        return {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        cx.close()


def _has_everything(db: Path) -> None:
    for table, cols in {**TRAVEL, **LOCAL}.items():
        assert cols <= _cols(db, table), (table, cols - _cols(db, table))
    assert SEEN_NEW <= _cols(db, "canon_seen")


def test_a_new_project_has_every_table_and_column_of_the_design(tmp_path):
    ws = Workspace.create(tmp_path / "p")
    ws.close()
    _has_everything(ws.db_path)


def test_a_project_of_a0088bb_gains_them_and_keeps_its_rows(tmp_path):
    ws = Workspace.create(tmp_path / "p")
    ws.close()
    cx = sqlite3.connect(ws.db_path)
    for t in ("ownership", "decisions", "canon", "canon_seen", *NEW_TABLES):
        cx.execute(f"DROP TABLE {t}")
    cx.executescript(OLD_SCHEMA)
    cx.execute("INSERT INTO ownership VALUES (1, 'pA', 'pA', '2026-11-01', 'claim', NULL, NULL)")
    cx.execute("INSERT INTO decisions VALUES ('x1', 'pA', 1, 'accept', NULL, '2026-11-02', 0)")
    cx.execute("INSERT INTO canon(doc, by, owner_seq, n, state, state_n) VALUES ('d1', 'pA', 1, 3, 'in', 3)")
    cx.execute("INSERT INTO canon_seen(doc, state_n) VALUES ('d1', 3)")
    cx.commit()
    cx.close()
    assert not NEW_TABLES & _tables(ws.db_path) and "grant" not in _cols(ws.db_path, "canon")

    ws = Workspace.open(ws.root)
    try:
        _has_everything(ws.db_path)
        # the rows of then are kept; what they did not say reads as the design says (NULL: an owner's row, its `by`)
        assert ws.scalar("SELECT owner FROM ownership WHERE seq=1") == "pA"
        assert ws.scalar("SELECT verdict FROM decisions WHERE proposal='x1'") == "accept"
        assert ws.scalar("SELECT COALESCE(n, grant, knew_json, sig) FROM decisions") is None
        assert ws.scalar("SELECT state FROM canon WHERE doc='d1'") == "in"
        assert ws.scalar("SELECT COALESCE(grant, state_by, read_by, ai_by, blocks_by, hist_json, sig) FROM canon") is None
        assert ws.scalar("SELECT state_n FROM canon_seen WHERE doc='d1'") == 3
        for t in NEW_TABLES:
            assert ws.scalar(f"SELECT COUNT(*) FROM {t}") == 0
    finally:
        ws.close()
    Workspace.open(ws.root).close()  # opening it again changes nothing (each column is added once)


def test_each_new_table_travels_or_stays_here_as_the_design_says(tmp_path):
    # §3.1: the tables that travel, by their own merge rules, as the project's rows, without words of a document
    for t in TRAVEL:
        assert t in common.OWN_RULES and t not in common.LOCAL_ONLY and t in sharing._NO_TEXT
    ws = Workspace.create(tmp_path / "p")
    try:
        with ws.connect() as cx:
            listed = [x[0] for x in sharing.ProjectRows(cx, ws.root).tables()]
            present = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        ws.close()
    for t in TRAVEL:
        assert listed.count(t) == 1, t
    # §3.2: this copy's own, never merged, never among the project's rows
    for t in LOCAL:
        assert t in common.LOCAL_ONLY and t not in common.OWN_RULES and t not in listed
    assert "sync_changes" in common.LOCAL_ONLY  # the idle rounds' counters stay this copy's own
    # in a zip for a colleague: the pins (and canon_seen) are kept, the rest emptied
    assert {"removed_docs", "sync_via", "sync_from", "sync_refused"} <= set(sharing._LOCAL_TABLES)
    assert not {"owner_pins", "canon_seen"} & set(sharing._LOCAL_TABLES)
    assert "roles_upgraded" in sharing._META_KEPT
    # every table of a new project is either this copy's own or travels (its own rules, or row by row)
    for t in present - {"sqlite_sequence", "meta"}:  # (meta: this copy's own, but for the bibliography key)
        assert (t in common.LOCAL_ONLY) != (t in listed or t in common.OWN_RULES), t


def _rewrite(f: Path, out: Path, change) -> Path:
    with zipfile.ZipFile(f) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "bundle.json":
                meta = json.loads(data)
                change(meta)
                data = json.dumps(meta).encode()
            zout.writestr(item, data)
    return out


def test_format_4_is_written_and_needed_by_bundles_and_by_zips_of_a_project_with_an_owner(tmp_path, monkeypatch):
    assert formats.FORMAT == 4 and folder.NEEDS == 4
    assert formats.stamp(needs=folder.NEEDS) == {"sync_format": 4, "sync_needs": 4}
    ws = Workspace.create(tmp_path / "p")
    try:
        with ws.connect() as cx:
            assert formats.zip_needs(cx) == formats.ZIP_NEEDS == 1  # no owner: nothing new travels
            cx.execute("INSERT INTO ownership(seq, owner, by, kind) VALUES (1, 'pA', 'pA', 'claim')")
            assert formats.zip_needs(cx) == 4
    finally:
        ws.close()
    assert formats.zip_needs(sqlite3.connect(":memory:")) == 1  # a database without the table has no owner
    # a file of format 3 (or older) comes in here; a copy of format 3 stops at a bundle or an owned project's zip
    assert formats.problem({"sync_format": 3, "sync_needs": 3}) is None
    assert formats.problem({}) is None
    monkeypatch.setattr(formats, "FORMAT", 3)
    for needs in (folder.NEEDS, 4):
        msg = formats.problem({"version": "0.17.2", **{"sync_format": 4, "sync_needs": needs}})
        assert msg and "Update ENLENS" in msg and "Nothing was changed" in msg
    assert formats.problem({"sync_format": 4, "sync_needs": 1}) is None  # no owner: an older copy still reads it


def test_a_project_zip_of_format_3_comes_in(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    with anna:
        from enlens_claims import claimcheck

        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    f = _rewrite(anna.send(), tmp_path / "f3.zip", lambda m: m.update(sync_format=3, sync_needs=3, version="0.17.1"))
    rep = ben.bring_in(f)
    assert rep["checks"]["updated"] == 1

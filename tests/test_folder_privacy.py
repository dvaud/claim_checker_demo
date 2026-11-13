"""0.18.0: nothing private ever reaches the shared folder (sync/folder.py, design note §2.6).

Only shared items and the marks of those taken back are written, never a private item (also not a colleague's private
item that came in a whole-project zip), never work under way, never this copy's own tables, and no path of this
computer. This test writes several rounds from two copies and reads every byte of every file in the folder.
"""
from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from pathlib import Path

from enlens_claims import bundle, claimcheck, notes, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder
from test_0_14_0_shared_projects import Person
from test_0_18_0_rows_of import rich  # noqa: F401  (fixture)


def _everything(shared_dir: Path) -> list[tuple[str, bytes]]:
    """Every file in the folder, and every file inside each zip, as bytes (a database as it is stored)."""
    out = []
    for f in sorted(shared_dir.rglob("*")):
        if not f.is_file():
            continue
        data = f.read_bytes()
        out.append((str(f.relative_to(shared_dir)), data))
        if zipfile.is_zipfile(f):
            with zipfile.ZipFile(f) as zf:
                out += [(f"{f.relative_to(shared_dir)}!{n}", zf.read(n)) for n in zf.namelist()]
    return out


def _bundle_dbs(shared_dir: Path, tmp: Path) -> list[sqlite3.Connection]:
    out = []
    for i, b in enumerate(sorted(shared_dir.rglob("bundles/*.zip"))):
        db = tmp / f"bundle-{i}.sqlite"
        with zipfile.ZipFile(b) as zf:
            db.write_bytes(zf.read("rows.sqlite"))
        out.append(sqlite3.connect(db))
    return out


def test_nothing_private_is_ever_written_to_the_folder(rich, tmp_path, monkeypatch):
    anna = rich
    ws = anna.ws
    shared_dir = tmp_path / "Közös" / "team"
    shared_dir.mkdir(parents=True)
    with anna:
        cid = ws.scalar("SELECT claim_id FROM user_claims WHERE hyp_id=?", (anna.h_private,))
        tid = ws.scalar("SELECT task_id FROM tasks WHERE task_id LIKE ? LIMIT 1", (f"%{cid}%",))
        pid, doc = ws.query("SELECT passage_id, doc_id FROM passages LIMIT 1")[0]
        with ws.connect() as cx:  # Claude read a passage for the private check: the ledger keeps it, without its task
            cx.execute("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) VALUES (?,?,?,?,?,?)",
                       (pid, doc, "claude_code", tid, "2026-11-11T01:00:00+00:00", "check"))
        # shared once and taken back before any round: only its mark goes, without its words
        body = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,))
        words = " ".join(body.split()[30:34])
        a = body.index(words)
        n_gone = notes.add(ws, doc, a, a + len(words), text="a withdrawn thought")["note_id"]
        sharing.share(ws, [{"kind": "note", "key": n_gone}])
        sharing.unshare(ws, [{"kind": "note", "key": n_gone}])
        # a shared check with work under way is not written until it is done
        h_running = claimcheck.check_hypothesis(ws, "A shared check still being read.", BaselineBackend(), "baseline",
                                                k=2)
        with ws.connect() as cx:
            cx.execute("UPDATE hypotheses SET queue='waiting' WHERE hyp_id=?", (h_running,))
        sharing.share(ws, [{"kind": "check", "key": h_running}])
        folder.set_folder(ws, str(shared_dir))
    ben = Person(tmp_path, "Ben", monkeypatch)
    with ben:  # Ben's copy is Anna's whole project: her private items are in it, as hers and private
        ben.ws = bundle.import_project(anna.send(), tmp_path / "ben-project")
        folder.set_folder(ben.ws, str(shared_dir))
    for p in (anna, ben, anna, ben):
        with p:
            out = folder.sync_now(p.ws)
            assert not out["problems"], out["problems"]
    with anna:  # a later round, after more private work
        h_later = claimcheck.check_hypothesis(ws, "Another private idea about ammonia.", BaselineBackend(), "baseline",
                                              k=2)
        claimcheck.set_note(ws, anna.h_shared, "a shared note on the shared check")
        folder.sync_now(ws)
    with ben:
        folder.sync_now(ben.ws)
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (anna.h_shared,)) == \
            "a shared note on the shared check"

    # (the withdrawn note's key goes, as its mark: a colleague who has it marks it withdrawn; its words do not)
    private_ids = [anna.h_private, h_later, cid, tid, h_running, anna.r_private, anna.n_private, anna.e_private]
    private_words = ["A private hunch about desalination", "Another private idea about ammonia", "private thought",
                     "A private field note", "Private code", "Secret theme name", f"judged {anna.h_private}",
                     "a review on mine", "a withdrawn thought", "A shared check still being read"]
    paths = [str(ws.root), str(ben.ws.root), str(Path.home()), str(tmp_path)]
    files = _everything(shared_dir)
    assert len(files) > 10
    for name, data in files:
        for needle in private_ids + private_words + paths:
            assert needle.encode("utf-8") not in data, (needle, name)
    # what is shared is there, so the scan above looked in the right places
    blob = b"".join(d for _n, d in files)
    assert b"Electrolysers create local jobs" in blob and b"shared thought" in blob and b"A field note to share" in blob
    for cx in _bundle_dbs(shared_dir, Path(tempfile.mkdtemp(dir=tmp_path))):
        # no queued or unanswered task, no table of this copy's own, no private mark
        assert not cx.execute("SELECT 1 FROM tasks WHERE status IN ('pending', 'retry') OR queued=1").fetchone()
        for t in ("versions", "sync_log", "task_claims", "embeddings", "terms", "concepts", "sync_written",
                  "sync_folder_read", "sync_folder_docs"):
            assert not cx.execute(f"SELECT 1 FROM {t}").fetchone(), t
        assert not cx.execute("SELECT 1 FROM shares WHERE state='private' OR (state='withdrawn' AND title IS NOT NULL)"
                              ).fetchone()
        assert set(r[0] for r in cx.execute("SELECT key FROM meta")) <= {"project_uid", "corpus_version",
                                                                          "bibliography", "codebook_followed:ours",
                                                                          "roles_upgraded"}  # (roles §3.5: a marker)
        cx.close()
    assert not list(shared_dir.rglob("frameworks/mine.*")) and not [n for n, _d in files if "frameworks/mine." in n]

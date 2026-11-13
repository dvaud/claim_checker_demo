"""0.18.0: one definition of what sharing an item covers (sharing.rows_of).

A zip for a colleague takes every item not shared out of a copy of the database (`sharing.drop`, `strip`); the shared
folder writes the rows of the items shared (sync/folder.py). Both read which rows an item covers from `rows_of`, and
the project's rows that are no one's item from `ProjectRows`, so the two ways of sending can never disagree about what
is private.
"""
from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, claimcheck, codebooks, notes, profile, researchlog, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder
from enlens_claims.sync.common import LOCAL_ONLY
from test_shared_projects import Person


def _check(ws, text: str) -> str:
    return claimcheck.check_hypothesis(ws, text, BaselineBackend(), "baseline", k=2)


def _note(ws, words_from: int, text: str) -> str:
    doc, body = ws.query("SELECT doc_id, text FROM documents ORDER BY doc_id LIMIT 1")[0]
    words = " ".join(body.split()[words_from:words_from + 4])
    a = body.index(words)
    return notes.add(ws, doc, a, a + len(words), text=text)["note_id"]


@pytest.fixture
def rich(loaded, tmp_path, monkeypatch):
    """Anna's project with an item of every kind, shared and private, people's decisions on them, and the project's own
    AI work (labels of the bundled SDG codebook, a review of one)."""
    from enlens_claims import ingest, terms, themes

    anna = Person(tmp_path, "Anna", monkeypatch)
    anna.ws = ws = loaded
    with anna:
        ingest.ingest(ws, [Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"])
        anna.h_shared = _check(ws, "Electrolysers create local jobs.")
        anna.h_private = _check(ws, "A private hunch about desalination.")
        for h in (anna.h_shared, anna.h_private):
            cid = ws.scalar("SELECT claim_id FROM user_claims WHERE hyp_id=? LIMIT 1", (h,))
            pid = ws.scalar("SELECT passage_id FROM verifications WHERE subject_id=? LIMIT 1", (cid,))
            claimcheck.set_judgement(ws, cid, pid, "supports", note=f"judged {h}")
        anna.n_shared, anna.n_private = _note(ws, 10, "shared thought"), _note(ws, 20, "private thought")
        anna.e_shared = researchlog.add(ws, "A field note to share.")["entry_id"]
        anna.e_private = researchlog.add(ws, "A private field note.")["entry_id"]
        codebooks.create(ws, "ours", "Ours", "project", "csv", {"csv": "code,description\nY,Shared code\n"})
        codebooks.create(ws, "mine", "Mine", "project", "csv", {"csv": "code,description\nX,Private code\n"})
        pids = [r[0] for r in ws.query("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 3")]
        for fw, code in (("ours", "Y"), ("mine", "X"), ("sdg", "6.4")):
            lid = profile.add_label(ws, fw, pids[0], code)
            profile.set_label(ws, lid, "reject", note=f"a review on {fw}")
        anna.r_shared, anna.r_private = themes.run(ws, k=3, seed=1), themes.run(ws, k=3, seed=2)
        themes.edit(ws, anna.r_private, "rename", themes.view(ws, anna.r_private)["themes"][0]["theme_id"],
                    "Secret theme name")
        terms.build(ws)
        (a, b), (c, d) = [sorted(r[0] for r in ws.query("SELECT term_id FROM terms ORDER BY df DESC LIMIT 2")),
                          sorted(r[0] for r in ws.query("SELECT term_id FROM terms ORDER BY df DESC LIMIT 2 OFFSET 2"))]
        terms.set_link(ws, a, b, "add", "same")
        terms.set_link(ws, c, d, "add", "broader")
        anna.l_shared, anna.l_private = f"{a}|{b}", f"{c}|{d}"
        sharing.share(ws, [{"kind": "check", "key": anna.h_shared}, {"kind": "note", "key": anna.n_shared},
                           {"kind": "log", "key": anna.e_shared}, {"kind": "codebook", "key": "ours"},
                           {"kind": "themes", "key": anna.r_shared}, {"kind": "link", "key": anna.l_shared}])
    return anna


def _counts(cx: sqlite3.Connection) -> dict[str, int]:
    return {t: cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for (t,) in cx.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _copy(ws, tmp: Path) -> sqlite3.Connection:
    out = tmp / f"copy-{len(list(tmp.glob('copy-*')))}.sqlite"
    src, dst = sqlite3.connect(ws.db_path), sqlite3.connect(out)
    src.backup(dst)
    src.close()
    return dst


def test_drop_takes_out_exactly_the_rows_of_an_item(rich, tmp_path):
    anna = rich
    items = [("check", anna.h_private), ("note", anna.n_private), ("log", anna.e_private), ("codebook", "mine"),
             ("themes", anna.r_private), ("link", anna.l_private)]
    for kind, key in items:
        cx = _copy(anna.ws, tmp_path)
        got = sharing.rows_of(cx, kind, key)
        assert got, (kind, key)
        before = _counts(cx)
        with cx:
            sharing.drop(cx, kind, [key])
        after = _counts(cx)
        want = {t: before[t] - len({r[sharing.ROWID] for r in got.get(t, [])}) for t in before}
        assert after == want, (kind, {t: (before[t], after[t], want[t]) for t in before if after[t] != want[t]})
        cx.close()
    with anna:
        cx = anna.ws._conn()
        check = sharing.rows_of(cx, "check", anna.h_private)
        assert {"hypotheses", "user_claims", "verifications", "judgements", "tasks", "research_log"} <= set(check)
        assert {"labels", "reviews"} <= set(sharing.rows_of(cx, "codebook", "mine"))
        assert {"theme_runs", "themes", "theme_members", "reviews"} <= set(sharing.rows_of(cx, "themes", anna.r_private))


def test_the_projects_rows_are_no_ones_item(rich):
    anna = rich
    with anna:
        cx = anna.ws._conn()
        project = {}
        for table, rowid, _ident, _content in sharing.ProjectRows(cx, anna.ws.root).scan():
            project.setdefault(table, set()).add(rowid)
        assert {"labels", "reviews", "research_log"} <= set(project)  # SDG labels, a review of one, the documents' log
        for kind, keys in sharing.items(cx, anna.ws.root).items():
            for key in keys:
                for table, got in sharing.rows_of(cx, kind, key).items():
                    both = project.get(table, set()) & {r[sharing.ROWID] for r in got}
                    assert not both, (kind, key, table)
        assert not set(project) & (LOCAL_ONLY - {"meta"})


def _rows_of_db(cx: sqlite3.Connection, table: str) -> set[str]:
    import json

    # not a review's number (each copy's own), nor when a person was last seen (the zip's export notes it anew)
    cols = [r[1] for r in cx.execute(f"PRAGMA table_info({table})") if r[1] not in ("review_id", "seen_at")]
    return {json.dumps([r[i] for i in range(len(cols))], default=str) for r in
            cx.execute(f"SELECT {','.join(cols)} FROM {table}")}


def test_the_folder_writes_nothing_a_zip_for_a_colleague_would_not_carry(rich, tmp_path):
    anna = rich
    shared_dir = tmp_path / "team"
    shared_dir.mkdir()
    with anna:
        folder.set_folder(anna.ws, str(shared_dir))
        folder.write(anna.ws)
        claimcheck.set_note(anna.ws, anna.h_shared, "changed later")  # a second bundle, with the check again
        folder.write(anna.ws)
        out = tmp_path / "shared.zip"
        bundle.export_project(anna.ws, out, scope="shared")
    zdb = tmp_path / "zip.sqlite"
    with zipfile.ZipFile(out) as zf:
        zdb.write_bytes(zf.read("enlens.sqlite"))
    zcx = sqlite3.connect(zdb)
    bundles = sorted(shared_dir.rglob("bundles/*.zip"))
    assert len(bundles) == 2
    for i, b in enumerate(bundles):
        bdb = tmp_path / f"b{i}.sqlite"
        with zipfile.ZipFile(b) as zf:
            bdb.write_bytes(zf.read("rows.sqlite"))
        bcx = sqlite3.connect(bdb)
        for (table,) in bcx.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            if table.startswith("sqlite_") or table in ("shares", "sync_seen", "sync_copies"):
                continue  # marks and sync states: compared by their own tests
            extra = _rows_of_db(bcx, table) - _rows_of_db(zcx, table)
            if table == "hypotheses":  # the second bundle has the check as it is now; the zip was made after it
                extra = {e for e in extra if anna.h_shared not in e}
            assert not extra, (b.name, table, sorted(extra)[:2])
        bcx.close()
    zcx.close()

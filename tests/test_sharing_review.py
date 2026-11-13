"""0.18.0: what a review of stage 1 found, each proved fixed by the behaviour it broke.

- a zip for a colleague carried the words of private items you had removed (notes of removal), and the titles of items
  you took back (their marks, and the log entry of taking several back at once);
- a colleague's file from 0.17 made a third person's withdrawn and private items shared again;
- a round trip between two readings of a document replaced your own check with a version that had lost places;
- a project only backed up or moved before 0.18 counted as shared;
- two codes of one name, added in both copies, mixed their labels, and a long name made the codebook unreadable;
- you could not share your check tagged with a colleague's shared codebook;
- what Claude read of a colleague's other reading was added again at every bring-in;
- the zip for a colleague kept this copy's own settings (the glossary's state, a path of this computer) and the runs of
  a private codebook.
"""
from __future__ import annotations

import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, claimcheck, codebooks, frameworks, notes, profile, reread, researchlog, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.store import Workspace
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_0_15_0_read_with_new_reader import HEAD, Q_WATER, _add, _check as _graded, _paper
from test_0_18_0_old_readings import _doc_text, _placed


def _check(ws, text: str) -> str:
    return claimcheck.check_hypothesis(ws, text, BaselineBackend(), "baseline", k=2)


def _shared(p: Person) -> Path:
    with p:
        p.n += 1
        out = p.files / f"{p.name}-s{p.n}.zip"
        bundle.export_project(p.ws, out, scope="shared")
        return out


def _raw(f: Path, tmp: Path) -> tuple[sqlite3.Connection, bytes]:
    out = tmp / f"{f.stem}.sqlite"
    with zipfile.ZipFile(f) as zf:
        out.write_bytes(zf.read("enlens.sqlite"))
    return sqlite3.connect(out), out.read_bytes()


def _as_017(f: Path, tmp: Path, name: str) -> Path:
    """The same file as 0.17 makes it: no table of shares, no format."""
    work, old = tmp / f"w-{name}", tmp / f"{name}.zip"
    with zipfile.ZipFile(f) as zf:
        zf.extractall(work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    cx.execute("DROP TABLE shares")
    cx.commit()
    cx.close()
    meta = json.loads((work / "bundle.json").read_text())
    for k in ("sync_format", "sync_needs", "scope"):
        meta.pop(k, None)
    (work / "bundle.json").write_text(json.dumps(meta))
    with zipfile.ZipFile(old, "w") as zf:
        for p in work.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(work).as_posix())
    return old


def test_removed_and_withdrawn_items_leave_no_words_in_a_zip_for_a_colleague(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    with anna:
        gone = _check(anna.ws, "REMOVEDPRIVATECHECK about hydrogen water.")
        claimcheck.delete_hypothesis(anna.ws, gone)
        eid = researchlog.add(anna.ws, "REMOVEDPRIVATEENTRY of mine.")["entry_id"]
        researchlog.remove(anna.ws, eid)
        body = anna.ws.scalar("SELECT text FROM documents ORDER BY doc_id LIMIT 1")
        words = " ".join(body.split()[20:24])
        doc = anna.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        a = body.index(words)
        nid = notes.add(anna.ws, doc, a, a + len(words), text="REMOVEDPRIVATENOTE")["note_id"]
        notes.remove(anna.ws, nid)
        h1, h2 = _check(anna.ws, "TAKENBACKONE about jobs."), _check(anna.ws, "TAKENBACKTWO about prices.")
        sharing.share(anna.ws, [{"kind": "check", "key": h1}, {"kind": "check", "key": h2}])
        sharing.unshare(anna.ws, [{"kind": "check", "key": h1}, {"kind": "check", "key": h2}])
        kept = _check(anna.ws, "SHAREDCHECK about water.")
        sharing.share(anna.ws, [{"kind": "check", "key": kept}])
    f = _shared(anna)
    db, raw = _raw(f, tmp_path)
    for secret in (b"REMOVEDPRIVATECHECK", b"REMOVEDPRIVATEENTRY", b"REMOVEDPRIVATENOTE", b"TAKENBACKONE",
                   b"TAKENBACKTWO"):
        assert secret not in raw, secret
    assert b"SHAREDCHECK" in raw
    marks = {r[0]: (r[1], r[2]) for r in db.execute("SELECT key, state, title FROM shares WHERE kind='check'")}
    assert marks[h1] == ("withdrawn", None) and marks[h2] == ("withdrawn", None)  # the mark travels, without words
    db.close()
    rep = ben.bring_in(f)
    with ben:
        assert sharing.state(ben.ws._conn(), "check", h1)["state"] == "withdrawn"
        assert not ben.ws.scalar("SELECT 1 FROM sync_removed WHERE title LIKE '%REMOVEDPRIVATE%'")
    assert rep["checks"]["new"] == 1


def test_a_017_file_does_not_make_a_third_persons_withdrawn_or_private_items_shared(anna_and_ben, tmp_path,
                                                                                   monkeypatch):
    anna, ben = anna_and_ben
    clara = Person(tmp_path, "Clara", monkeypatch)
    with clara:
        clara.ws = bundle.import_project(anna.files / "Anna-1.zip", tmp_path / "clara-project")
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    f = _shared(anna)
    ben.bring_in(f)
    clara.bring_in(f)
    with anna:
        sharing.unshare(anna.ws, [{"kind": "check", "key": h2}])
    clara.bring_in(_shared(anna))
    clara.bring_in(_as_017(ben.send(), tmp_path, "ben017"))  # Ben, as if on 0.17: his whole project
    with clara:
        assert sharing.state(clara.ws._conn(), "check", h2)["state"] == "withdrawn"
        st = sharing.state(clara.ws._conn(), "check", anna.hid)
        assert st["state"] == "private" and st["owner"] == anna.id
    db, _ = _raw(_shared(clara), tmp_path)
    assert not db.execute("SELECT 1 FROM hypotheses WHERE hyp_id IN (?, ?)", (h2, anna.hid)).fetchone()


@pytest.fixture
def paper_shared(tmp_path, monkeypatch):
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    with anna:
        anna.ws = Workspace.create(tmp_path / "anna-project")
        anna.doc = _add(anna.ws, monkeypatch, _paper(tmp_path))
        anna.cid, _at = _graded(anna.ws, [(Q_WATER, "supports")])
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
    return anna, ben


def test_a_round_trip_between_two_readings_never_replaces_your_check_with_one_that_lost_places(paper_shared):
    anna, ben = paper_shared
    with ben:
        reread.move(ben.ws, anna.doc)
    with anna:
        old_text = _doc_text(anna.ws, anna.doc)
        i = old_text.index(HEAD, 10)
        bad = old_text[i + len(HEAD) - 5:i + len(HEAD) + 22].strip()
        bad = bad[:bad.rfind(" ")]
        assert re.search(r"45-67 2 ", bad), bad
        cid2, _ = _graded(anna.ws, [(bad, "supports"), (Q_WATER, "supports")])
        before = sorted(_placed(anna.ws, anna.doc, cid2))
        assert before == sorted([(bad, True), (Q_WATER, True)])
    ben.bring_in(anna.send())  # on Ben's reading, her quote with the running head has no place
    rep = anna.bring_in(ben.send())  # Ben changed nothing: the same checks come back
    assert rep["checks"]["updated"] == 0 and not rep["checks"]["clash"]
    with anna:
        assert sorted(_placed(anna.ws, anna.doc, cid2)) == before  # her excerpts keep their places
        assert _placed(anna.ws, anna.doc, anna.cid) == [(Q_WATER, True)]


def test_a_newer_version_that_lost_places_comes_in_beside_yours(paper_shared):
    anna, ben = paper_shared
    with anna:
        old_text = _doc_text(anna.ws, anna.doc)
        i = old_text.index(HEAD, 10)
        bad = old_text[i + len(HEAD) - 5:i + len(HEAD) + 22].strip()
        bad = bad[:bad.rfind(" ")]
        cid2, _ = _graded(anna.ws, [(bad, "supports")])
    ben.bring_in(anna.send())
    with ben:
        reread.move(ben.ws, anna.doc)  # Ben moves the paper (her quote finds no place) and changes her check
        claimcheck.set_note(ben.ws, cid2, "Ben's note")
    rep = anna.bring_in(ben.send())
    assert len(rep["checks"]["clash"]) == 1 and rep["checks"]["updated"] == 0
    with anna:
        assert _placed(anna.ws, anna.doc, cid2) == [(bad, True)]  # hers keeps its place; his is beside it


def test_codes_of_one_name_added_in_both_copies_keep_their_labels_apart(loaded, tmp_path, monkeypatch):
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    anna.ws = loaded
    with anna:
        codebooks.create(loaded, "water", "Water", "project", "csv", {"csv": "code,description\nA,Water use\n"})
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
    long = "Water withdrawn by electrolysers in arid"[:40]

    def add(code, d):
        def change(codes):
            codes.append({"uid": "", "code": code, "description": d, "group": "", "keywords": [], "examples": []})
        return change

    pids = [r[0] for r in loaded.query("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 3")]
    with anna:
        st = codebooks.load(anna.ws, "water")
        codebooks.save(anna.ws, "water", {**st, "codes": [dict(c) for c in st["codes"]]
                                           + [{"uid": "", "code": "Energy", "description": "Anna: energy use",
                                               "group": "", "keywords": [], "examples": []},
                                              {"uid": "", "code": long, "description": "Anna: long", "group": "",
                                               "keywords": [], "examples": []}]})
        profile.add_label(anna.ws, "water", pids[2], "Energy")
    with ben:
        st = codebooks.load(ben.ws, "water")
        codebooks.save(ben.ws, "water", {**st, "codes": [dict(c) for c in st["codes"]]
                                         + [{"uid": "", "code": "Energy", "description": "Ben: energy prices",
                                             "group": "", "keywords": [], "examples": []},
                                            {"uid": "", "code": long, "description": "Ben: long", "group": "",
                                             "keywords": [], "examples": []}]})
        profile.add_label(ben.ws, "water", pids[0], "Energy")
    rep = ben.bring_in(anna.send())
    assert len(rep["codebooks"]["merged"][0]["renamed"]) == 2
    with ben:
        codes = {c.code: c.description for c in frameworks.get("water", ben.ws).codes.values()}  # readable
        assert codes["Energy"] == "Ben: energy prices" and codes["Energy (Anna)"] == "Anna: energy use"
        assert codes[long] == "Ben: long" and all(len(c) <= 40 for c in codes)
        assert sum(1 for d in codes.values() if d == "Anna: long") == 1
        labels = {tuple(r) for r in ben.ws.query("SELECT passage_id, code FROM labels WHERE framework='water' AND "
                                                  "source='person'")}
        assert labels == {(pids[0], "Energy"), (pids[2], "Energy (Anna)")}


def test_you_can_share_your_check_tagged_with_a_colleagues_shared_codebook(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        codebooks.create(anna.ws, "water", "Water", "project", "csv", {"csv": "code,description\nA,Water use\n"})
        sharing.share(anna.ws, [{"kind": "codebook", "key": "water"}])
    ben.bring_in(_shared(anna))
    with ben:
        hid = _check(ben.ws, "Ben's hypothesis about water.")
        with ben.ws.connect() as cx:
            cx.execute("UPDATE hypotheses SET framework='water', code='A' WHERE hyp_id=?", (hid,))
        r = sharing.share(ben.ws, [{"kind": "check", "key": hid}])
        assert [i["key"] for i in r["shared"]] == [hid] and [i["key"] for i in r["already"]] == ["water"]
        assert sharing.state(ben.ws._conn(), "codebook", "water")["owner"] == anna.id  # still Anna's


def test_what_claude_read_of_their_other_reading_counts_once(paper_shared):
    anna, ben = paper_shared
    for p in (anna, ben):  # nothing sent to Claude yet, in either copy
        with p:
            with p.ws.connect() as cx:
                cx.execute("DELETE FROM ai_sent")
                cx.execute("UPDATE documents SET sent_share=NULL")
    with ben:
        reread.move(ben.ws, anna.doc)
    with anna:  # Claude read one passage of Anna's reading, one that has no place in Ben's
        pid = anna.ws.scalar("SELECT passage_id FROM passages WHERE text LIKE ? ORDER BY seq LIMIT 1", (f"%{HEAD}%",))
        with anna.ws.connect() as cx:
            cx.execute("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) VALUES "
                       "(?,?,?,?,?,?)", (pid, anna.doc, "claude_code", "x", "2026-11-11T00:00:00+00:00", "check"))
    f = anna.send()
    shares = []
    for _ in range(3):
        ben.bring_in(f)
        with ben:
            shares.append(ben.ws.scalar("SELECT COALESCE(sent_share, 0) FROM documents"))
    assert 0 < shares[0] < 0.5 and shares[0] == shares[1] == shares[2], shares


def test_a_zip_for_a_colleague_keeps_none_of_this_copys_own_settings(anna_and_ben, tmp_path):
    from enlens_claims import terms

    anna, _ben = anna_and_ben
    with anna:
        terms.build(anna.ws)
        anna.ws.set_meta("evaluation", {"folder": "/Users/anna/private/eval"})
        codebooks.create(anna.ws, "mine", "Mine", "project", "csv", {"csv": "code,description\nX,Private code\n"})
        with anna.ws.connect() as cx:
            cx.execute("INSERT INTO runs(run_id, kind, scope, model) VALUES ('u1', 'label', 'mine', 'm')")
    db, raw = _raw(_shared(anna), tmp_path)
    keys = {r[0] for r in db.execute("SELECT key FROM meta")}
    assert "project_uid" in keys and not any(k.startswith("terms_") for k in keys) and "evaluation" not in keys
    assert b"/Users/anna/private" not in raw
    assert not db.execute("SELECT 1 FROM runs WHERE scope='mine'").fetchone()
    db.close()
    # a colleague who opens it as a project of its own builds the glossary afresh, not "already built"
    imported = bundle.import_project(_shared(anna), tmp_path / "imported")
    assert terms.status(imported)["missing"]

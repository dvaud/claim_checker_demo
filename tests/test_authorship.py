"""Rows of a third person (DESIGN-roles §4.8, BRIEF §2.7, SYNC-3): judgements, reviews, notes, log entries,
proposals and names that arrive in someone else's file.

A row is first-hand when its author is the sender, else relayed. A relayed row is taken when this copy has none, and
labelled "via" (`sync_via`); it never replaces or removes a first-hand one; the author's own file takes its place. A
removal of a third person's note, log entry or review is applied only first-hand: relayed, it is held back and
counted. One human on two computers (the Owner's `same_as`) counts once.
"""
from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, claimcheck, notes, people, researchlog, sharing
from owner_helpers import add_doc, sync
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_0_18_0_owner import shared_dir, team  # noqa: F401  (fixtures)


def _forge(src: Path, out: Path, *sql: tuple) -> Path:
    """A colleague's zip with rows added to its database by any SQLite tool."""
    work = out.with_suffix("")
    work.mkdir()
    with zipfile.ZipFile(src) as zf:
        zf.extractall(work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    for q, args in sql:
        cx.execute(q, args)
    cx.commit()
    cx.close()
    with zipfile.ZipFile(out, "w") as zf:
        for p in sorted(work.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(work).as_posix())
    return out


def _judgement(person: str, claim: str, passage: str, verdict: str, at: str) -> tuple:
    return ("INSERT OR REPLACE INTO judgements(claim_id, passage_id, person_id, verdict, note, at) VALUES "
            "(?,?,?,?,?,?)", (claim, passage, person, verdict, None, at))


def _excerpt(p: Person, hid: str) -> tuple[str, str]:
    with p:
        cid = p.ws.scalar("SELECT claim_id FROM user_claims WHERE hyp_id=?", (hid,))
        pid = p.ws.scalar("SELECT passage_id FROM verifications WHERE subject_kind='user_claim' AND subject_id=? "
                          "ORDER BY passage_id LIMIT 1", (cid,))
    return cid, pid


def _verdict(p: Person, cid: str, pid: str, person: str):
    with p:
        return p.ws.scalar("SELECT verdict FROM judgements WHERE claim_id=? AND passage_id=? AND person_id=?",
                           (cid, pid, person))


def _via(p: Person) -> dict:
    with p:
        return people.via(p.ws._conn())


@pytest.fixture
def abc(anna_and_ben, tmp_path, monkeypatch):  # noqa: F811
    """Anna, Ben (from Anna's first zip) and Carol (from the same zip)."""
    anna, ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    with carol:
        carol.ws = bundle.import_project(anna.files / "Anna-1.zip", tmp_path / "carol-project")
    return anna, ben, carol


# ---- SYNC-3, turned round ------------------------------------------------------------------------------------
def test_a_zip_in_a_third_persons_name_is_labelled_via_and_removes_nothing(team, tmp_path):  # noqa: F811
    """Ben's copy takes, from Carol's zip, a judgement written under Anna's id, labelled "via Carol"; the removal of
    Anna's note the zip says Anna made is held back."""
    anna, ben, carol = team
    with anna:
        doc = anna.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        text = anna.ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,))
        words = text.split()[:4]
        a = text.index(words[0])
        z = text.index(words[3]) + len(words[3])
        note = notes.add(anna.ws, doc, a, z, text="Anna's own note")
        sharing.share(anna.ws, [{"kind": "note", "key": note["note_id"]}])
    sync(anna, ben, carol)
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM notes WHERE note_id=?", (note["note_id"],))
        row = ben.ws.query("SELECT subject_id, passage_id FROM verifications WHERE subject_kind='user_claim' LIMIT 1")[0]
    forged = _forge(carol.send(), tmp_path / "forged.zip",
                    ("INSERT OR REPLACE INTO sync_removed(kind, key, title, at, person_id) VALUES ('note', ?, 'x', "
                     "'2030-01-01T00:00:00+00:00', ?)", (note["note_id"], anna.id)),
                    _judgement(anna.id, row[0], row[1], "refutes", "2030-01-01T00:00:00+00:00"))
    rep = ben.bring_in(forged)
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM notes WHERE note_id=?", (note["note_id"],))
        assert not ben.ws.scalar("SELECT 1 FROM sync_removed WHERE kind='note' AND key=?", (note["note_id"],))
    assert _verdict(ben, row[0], row[1], anna.id) == "refutes"
    assert _via(ben)[("judgement", f"{row[0]}|{row[1]}|{anna.id}")] == carol.id
    with ben:
        assert ben.ws.scalar("SELECT author FROM sync_via WHERE kind='judgement'") == anna.id
    assert rep["held_back"] == 1 and rep["via"] >= 1
    assert any("held back" in line for line in rep["lines"]), rep["lines"]


# ---- judgements ----------------------------------------------------------------------------------------------
def test_a_relayed_judgement_never_replaces_a_first_hand_one(abc, tmp_path):
    anna, ben, carol = abc
    cid, pid = _excerpt(anna, anna.hid)
    with anna:
        claimcheck.set_judgement(anna.ws, cid, pid, "supports")
    ben.bring_in(anna.send())
    assert _verdict(ben, cid, pid, anna.id) == "supports"
    forged = _forge(carol.send(), tmp_path / "carol.zip", _judgement(anna.id, cid, pid, "refutes",
                                                                    "2999-01-01T00:00:00+00:00"))
    ben.bring_in(forged)
    assert _verdict(ben, cid, pid, anna.id) == "supports"
    assert not _via(ben)


def test_the_authors_own_file_takes_the_place_of_a_relayed_judgement(abc, tmp_path):
    anna, ben, carol = abc
    cid, pid = _excerpt(anna, anna.hid)
    late = "2999-01-01T00:00:00+00:00"
    ben.bring_in(_forge(carol.send(), tmp_path / "c1.zip", _judgement(anna.id, cid, pid, "refutes", late)))
    assert _verdict(ben, cid, pid, anna.id) == "refutes"
    assert _via(ben) == {("judgement", f"{cid}|{pid}|{anna.id}"): carol.id}
    # a later relayed version brings a relayed row up to date
    ben.bring_in(_forge(carol.send(), tmp_path / "c2.zip",
                        _judgement(anna.id, cid, pid, "not_relevant", "2999-02-01T00:00:00+00:00")))
    assert _verdict(ben, cid, pid, anna.id) == "not_relevant"
    # Anna's own file: her row counts, though it is dated earlier than the relayed one
    with anna:
        claimcheck.set_judgement(anna.ws, cid, pid, "supports")
    ben.bring_in(anna.send())
    assert _verdict(ben, cid, pid, anna.id) == "supports"
    assert not _via(ben)


def test_nothing_comes_in_under_this_copys_own_id(abc, tmp_path):
    anna, ben, carol = abc
    cid, pid = _excerpt(anna, anna.hid)
    ben.bring_in(_forge(carol.send(), tmp_path / "c.zip", _judgement(ben.id, cid, pid, "refutes",
                                                                    "2999-01-01T00:00:00+00:00")))
    assert _verdict(ben, cid, pid, ben.id) is None


# ---- notes, log entries, reviews --------------------------------------------------------------------------------
def _note(p: Person) -> str:
    with p:
        doc = p.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        text = p.ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,))
        w = text.split()[:3]
        return notes.add(p.ws, doc, text.index(w[0]), text.index(w[2]) + len(w[2]), text=f"{p.name}'s note")["note_id"]


def test_a_relayed_removal_is_held_back_and_the_authors_own_applies(abc, tmp_path):
    anna, ben, carol = abc
    nid = _note(anna)
    with anna:
        eid = researchlog.add(anna.ws, "Anna's field note")["entry_id"]
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM notes WHERE note_id=?", (nid,))
        assert ben.ws.scalar("SELECT 1 FROM research_log WHERE entry_id=?", (eid,))
    removal = "INSERT OR REPLACE INTO sync_removed(kind, key, title, at, person_id) VALUES (?, ?, 'x', ?, ?)"
    rep = ben.bring_in(_forge(carol.send(), tmp_path / "c.zip",
                              (removal, ("note", nid, "2999-01-01T00:00:00+00:00", anna.id)),
                              (removal, ("log", eid, "2999-01-01T00:00:00+00:00", anna.id))))
    assert rep["held_back"] == 2
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM notes WHERE note_id=?", (nid,))
        assert ben.ws.scalar("SELECT 1 FROM research_log WHERE entry_id=?", (eid,))
    with anna:
        notes.remove(anna.ws, nid)
        researchlog.remove(anna.ws, eid)
    rep = ben.bring_in(anna.send())
    assert not rep.get("held_back")
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM notes WHERE note_id=?", (nid,))
        assert not ben.ws.scalar("SELECT 1 FROM research_log WHERE entry_id=?", (eid,))


def test_a_relayed_note_entry_and_review_are_taken_and_labelled_via(abc, tmp_path):
    anna, ben, carol = abc
    nid = _note(anna)
    with anna:
        eid = researchlog.add(anna.ws, "Anna's field note")["entry_id"]
    carol.bring_in(anna.send())  # Carol has Anna's note and entry; Ben does not yet
    review = ("INSERT INTO reviews(item_kind, item_id, field, decision, person_id, decided_at) VALUES "
              "('label', 'lx', 'code', 'accept', ?, '2026-11-12T10:00:00+00:00')", (anna.id,))
    rep = ben.bring_in(_forge(carol.send(), tmp_path / "c.zip", review))
    via = _via(ben)
    assert via[("note", nid)] == carol.id and via[("log", eid)] == carol.id
    assert [k for k in via if k[0] == "review"] and rep["via"] >= 3
    # a relayed note is brought up to date by a later relayed version; the author's own file ends the label
    with anna:
        notes.update(anna.ws, nid, text="Anna's later words")
    carol.bring_in(anna.send())
    ben.bring_in(carol.send())
    with ben:
        assert ben.ws.scalar("SELECT text FROM notes WHERE note_id=?", (nid,)) == "Anna's later words"
    ben.bring_in(anna.send())
    assert ("note", nid) not in _via(ben) and ("log", eid) not in _via(ben)


# ---- names ----------------------------------------------------------------------------------------------------
def test_a_name_comes_from_the_persons_own_file(abc, tmp_path):
    anna, ben, carol = abc
    ben.bring_in(anna.send())
    dora = "p0123456789ab"
    ben.bring_in(_forge(carol.send(), tmp_path / "c.zip",
                        ("INSERT OR REPLACE INTO people(person_id, name, seen_at) VALUES (?, 'Mallory', '2999')",
                         (anna.id,)),
                        ("INSERT OR REPLACE INTO people(person_id, name, seen_at) VALUES (?, 'Dora', '2999')",
                         (dora,))))
    with ben:
        who = people.names(ben.ws)
    assert who[anna.id] == "Anna" and who[dora] == "Dora" and who[carol.id] == "Carol"


# ---- proposals and the shared folder ----------------------------------------------------------------------------
def test_a_relayed_proposal_is_labelled_via_until_its_makers_own_subfolder_is_read(team, tmp_path):  # noqa: F811
    anna, ben, carol = team
    add_doc(ben, tmp_path, "jobs")
    sync(ben, carol, rounds=1)  # Carol has Ben's proposal; Anna has not read the folder since
    with ben:
        pid = ben.ws.scalar("SELECT id FROM proposals WHERE by=?", (ben.id,))
    anna.bring_in(carol.send())
    assert _via(anna).get(("proposal", pid)) == carol.id
    sync(anna, rounds=1)
    assert ("proposal", pid) not in _via(anna)


def test_in_the_shared_folder_no_row_stays_relayed(team):  # noqa: F811
    anna, ben, carol = team
    for p in team:
        _note(p)
    cid, pid = _excerpt(anna, anna.hid)
    with anna:
        claimcheck.set_judgement(anna.ws, cid, pid, "supports")
    reps = sync(carol, ben, anna, rounds=3)
    assert not any(r.get("held_back") for r in reps)
    for p in team:
        assert not _via(p), p.name


# ---- one human on two computers -----------------------------------------------------------------------------------
def _same_as_row(ws, person: str, other: str) -> None:
    """The Owner's word that `person` is the same human as `other`, as a role row that counts (roles-p1: the real
    `ownership.roles` in place of the stand-in used while P1 was being built): written by the project's owner, or by
    one made for the test when the project has none."""
    from enlens_claims import ownership

    with ws.connect() as cx:
        ch = ownership.chain(cx)
        if not ch:
            own = "p999999999999"
            cx.execute("INSERT INTO ownership(seq, owner, by, at, kind, after) VALUES (1, ?, ?, '2026', 'made', NULL)",
                       (own, own))
            cx.execute("INSERT INTO owner_pins(seq, by, owner, state, at) VALUES (1, ?, ?, 'followed', '2026')",
                       (own, own))
            ch = ownership.chain(cx)
        own, seq = ch[-1]["owner"], ch[-1]["seq"]
        n = cx.execute("SELECT COALESCE(MAX(n), 0) + 1 FROM roles WHERE by=?", (own,)).fetchone()[0]
        cx.execute("INSERT INTO roles(person, by, owner_seq, n, role, grant, same_as) VALUES (?, ?, ?, ?, 'co', ?, ?)",
                   (person, own, seq, n, "g" + person, other))


def test_group_is_the_connected_set_and_via_lists_relayed_rows(loaded):
    a, b, c, d = "p00000000000a", "p00000000000b", "p00000000000c", "p00000000000d"
    _same_as_row(loaded, b, a)
    _same_as_row(loaded, c, b)
    cx = loaded._conn()
    assert people.group(cx, a) == people.group(cx, c) == {a, b, c}
    assert people.group(cx, d) == {d}
    with loaded.connect() as w:
        w.execute("INSERT INTO sync_via(kind, key, author, via, at) VALUES ('note', 'n1', ?, ?, 'x')", (a, d))
    assert people.via(loaded._conn()) == {("note", "n1"): d}


def test_one_human_on_two_computers_counts_once(anna_and_ben, monkeypatch):  # noqa: F811
    """Anna's laptop (a second id, `same_as` Anna) judged an excerpt after Anna's desktop: the later counts, once."""
    anna, ben = anna_and_ben
    laptop = "p0aaaaaaaaaaa"
    cid, pid = _excerpt(ben, anna.hid)
    with ben:
        ws = ben.ws
        _same_as_row(ws, laptop, anna.id)
        with ws.connect() as cx:
            people.remember(cx, anna.id, "Anna")
            people.remember(cx, laptop, "Anna (laptop)")
            people.record(cx, cid, pid, anna.id, "refutes", None, "2026-11-01T00:00:00+00:00")
            people.record(cx, cid, pid, laptop, "supports", None, "2026-11-02T00:00:00+00:00")
            people.record(cx, cid, pid, ben.id, "supports", None, "2026-11-03T00:00:00+00:00")
            people.refresh(cx, [cid], ben.id)
        others = people.others(ws, [cid])[(cid, pid)]
        assert [(o["name"], o["verdict"]) for o in others] == [("Anna (laptop)", "supports")]
        agree = people.agreement(ws)
        assert len(agree) == 1 and agree[0]["both"] == 1 and agree[0]["agreed"] == 1
        # this person's own two computers: the later of their judgements is theirs
        with ws.connect() as cx:
            people.record(cx, cid, pid, anna.id, "refutes", None, "2026-11-04T00:00:00+00:00")
            people.refresh(cx, [cid], anna.id)
            assert tuple(cx.execute("SELECT user_verdict, user_by FROM verifications WHERE subject_id=? AND passage_id=?",
                              (cid, pid)).fetchone()) == ("refutes", anna.id)
            people.record(cx, cid, pid, laptop, "not_relevant", None, "2026-11-05T00:00:00+00:00")
            people.refresh(cx, [cid], anna.id)
            assert tuple(cx.execute("SELECT user_verdict, user_by FROM verifications WHERE subject_id=? AND passage_id=?",
                              (cid, pid)).fetchone()) == ("not_relevant", laptop)

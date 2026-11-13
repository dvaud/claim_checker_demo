"""0.18.0 (roadmap L1): private until shared.

Everything a person makes in a project is theirs alone until they share it: checks, sets of themes, codebooks, notes,
their own research log entries, links between terms (sharing.py). Sharing and taking back are deliberate acts, each in
the research log. A zip for a colleague (`scope="shared"`) carries only what is shared; the whole-project zip still
carries everything, and says whose each item is. What a colleague took back stays with you, marked withdrawn, and does
not reach a copy that does not have it. Only an item's owner decides about it. Projects exchanged before 0.18 count as
shared; one never sent starts private.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, claimcheck, codebooks, notes, people, researchlog, sharing, sync
from enlens_claims.llm import BaselineBackend
from enlens_claims.store import Workspace
from test_shared_projects import CLAIM, Person, anna_and_ben  # noqa: F401  (fixture)
from test_app import api, home  # noqa: F401  (fixtures)


def _check(ws, text: str) -> str:
    return claimcheck.check_hypothesis(ws, text, BaselineBackend(), "baseline", k=2)


def _note(ws, words: str, text: str = "") -> str:
    doc, body = ws.query("SELECT doc_id, text FROM documents WHERE text LIKE ? LIMIT 1", (f"%{words}%",))[0]
    a = body.index(words)
    return notes.add(ws, doc, a, a + len(words), text=text)["note_id"]


def _words(ws, n: int = 4) -> str:
    """A few words of a document, to note: taken from one line of its text, so they stand in it as written. Words
    across a paragraph break would not (on Windows the test files have CRLF endings, so another document comes first
    by its id, and its words 10 to 16 crossed a break)."""
    body = ws.scalar("SELECT text FROM documents ORDER BY doc_id LIMIT 1")
    for line in sorted(body.splitlines(), key=lambda t: -len(t.split())):
        w = line.split()
        if len(w) >= n:
            words = " ".join(w[min(2, len(w) - n):][:n])
            if words in body:
                return words
    return " ".join(body.split()[10:10 + n])


def _send_shared(p: Person) -> Path:
    with p:
        p.n += 1
        out = p.files / f"{p.name}-shared-{p.n}.zip"
        bundle.export_project(p.ws, out, scope="shared")
        return out


def _db_of(f: Path, tmp: Path) -> sqlite3.Connection:
    """The database inside a project zip, to look at what it carries."""
    out = tmp / f"{f.stem}.sqlite"
    with zipfile.ZipFile(f) as zf:
        out.write_bytes(zf.read("enlens.sqlite"))
    return sqlite3.connect(out)


def _state(ws, kind: str, key: str) -> str:
    return sharing.state(ws._conn(), kind, key)["state"]


# --- a new project ------------------------------------------------------------------------------------------------
def test_what_you_make_is_private_until_you_share_it_and_both_acts_are_logged(loaded):
    hid = _check(loaded, CLAIM)
    nid = _note(loaded, _words(loaded), "a thought")
    eid = researchlog.add(loaded, "A field note of my own.")["entry_id"]
    got = {(i["kind"], i["key"]): i for i in sharing.listing(loaded)["items"]}
    for k in (("check", hid), ("note", nid), ("log", eid)):
        assert got[k]["state"] == "private" and got[k]["mine"] and got[k]["can_change"] and got[k]["here"]
    r = sharing.share(loaded, [{"kind": "check", "key": hid}, {"kind": "note", "key": nid}], why="worth discussing")
    assert [i["key"] for i in r["shared"]] == [hid, nid] and not r["also"]
    assert _state(loaded, "check", hid) == "shared" and _state(loaded, "log", eid) == "private"
    e = researchlog.entries(loaded, group="together")["entries"][0]
    assert e["kind"] == "shared" and e["why"] == "worth discussing" and "1 check" in e["text"] and "1 note" in e["text"]
    assert sharing.share(loaded, [{"kind": "check", "key": hid}])["already"]  # sharing twice changes nothing
    r = sharing.unshare(loaded, [{"kind": "check", "key": hid}])
    assert [i["key"] for i in r["withdrawn"]] == [hid] and _state(loaded, "check", hid) == "withdrawn"
    e = researchlog.entries(loaded, group="together")["entries"][0]
    assert e["kind"] == "unshared" and e["subject_id"] == hid and CLAIM[:30] in e["text"]
    assert sharing.unshare(loaded, [{"kind": "log", "key": eid}])["not_shared"]
    with pytest.raises(KeyError):
        sharing.share(loaded, [{"kind": "check", "key": "h-nothere"}])
    with pytest.raises(ValueError):
        sharing.share(loaded, [{"kind": "document", "key": "d1"}])
    with pytest.raises(ValueError):
        sharing.share(loaded, [])


def test_sharing_a_check_tagged_with_your_codebook_shares_the_codebook(loaded):
    codebooks.create(loaded, "water", "Water", "project", "csv", {"csv": "code,description\nA,Water use\n"})
    hid = _check(loaded, CLAIM)
    with loaded.connect() as cx:  # tagged with a code of that codebook
        cx.execute("UPDATE hypotheses SET framework='water', code='A' WHERE hyp_id=?", (hid,))
    r = sharing.share(loaded, [{"kind": "check", "key": hid}])
    assert [(i["kind"], i["key"]) for i in r["also"]] == [("codebook", "water")]
    assert _state(loaded, "codebook", "water") == "shared"


# --- a zip for a colleague ----------------------------------------------------------------------------------------
def test_a_zip_for_a_colleague_carries_only_what_is_shared(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    with anna:
        h2, h3 = _check(anna.ws, "Electrolysers create local jobs."), _check(anna.ws, "Secret hypothesis about water.")
        n1 = _note(anna.ws, _words(anna.ws), "shared thought")
        n2 = _note(anna.ws, _words(anna.ws, 6), "private thought")
        e1 = researchlog.add(anna.ws, "Private field note.")["entry_id"]
        codebooks.create(anna.ws, "mine", "Mine", "project", "csv", {"csv": "code,description\nX,Private code\n"})
        codebooks.create(anna.ws, "ours", "Ours", "project", "csv", {"csv": "code,description\nY,Shared code\n"})
        sharing.share(anna.ws, [{"kind": "check", "key": h2}, {"kind": "note", "key": n1},
                                {"kind": "codebook", "key": "ours"}])
        sent = {}
        with anna.ws.connect() as cx:  # Claude read a passage for each check (the ledger of what was sent)
            for h in (h2, h3):
                cid = cx.execute("SELECT claim_id FROM user_claims WHERE hyp_id=?", (h,)).fetchone()[0]
                tid = cx.execute("SELECT task_id FROM tasks WHERE task_id LIKE ? LIMIT 1", (f"%{cid}%",)).fetchone()[0]
                pid, doc = cx.execute("SELECT passage_id, doc_id FROM passages LIMIT 1").fetchone()
                cx.execute("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) VALUES "
                           "(?,?,?,?,?,?)", (pid, doc, "claude_code", tid, f"2026-11-11T0{len(sent)}:00:00+00:00", "check"))
                sent[h] = tid
    f = _send_shared(anna)
    assert sync.peek(f)["scope"] == "shared"
    db = _db_of(f, tmp_path)
    hyps = {r[0] for r in db.execute("SELECT hyp_id FROM hypotheses")}
    assert hyps == {h2}  # her first check is hers and private too: it went in the whole-project zip, not this one
    assert {r[0] for r in db.execute("SELECT note_id FROM notes")} == {n1}
    assert not db.execute("SELECT 1 FROM research_log WHERE entry_id=?", (e1,)).fetchone()
    assert not db.execute("SELECT 1 FROM research_log WHERE subject_id=?", (h3,)).fetchone()
    assert db.execute("SELECT 1 FROM research_log WHERE kind='check-added' AND subject_id=?", (h2,)).fetchone()
    assert db.execute("SELECT 1 FROM research_log WHERE kind='documents-added'").fetchone()  # the corpus is shared
    assert not db.execute("SELECT 1 FROM shares WHERE state='private'").fetchone()
    assert not db.execute("SELECT 1 FROM versions").fetchone() and not db.execute("SELECT 1 FROM sync_log").fetchone()
    # what Claude read still counts in every copy, but the ledger names no task of work not shared
    ledger = {r[0] for r in db.execute("SELECT task_id FROM ai_sent")}
    assert sent[h2] in ledger and sent[h3] not in ledger and "private" in ledger
    assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] > 0
    db.close()
    raw = (tmp_path / f"{f.stem}.sqlite").read_bytes()
    assert b"Secret hypothesis" not in raw and b"private thought" not in raw and b"Private field note" not in raw
    with zipfile.ZipFile(f) as zf:
        names = set(zf.namelist())
    assert "frameworks/ours.csv" in names and "frameworks/mine.csv" not in names
    assert not any(n.startswith("frameworks/history/") for n in names)
    rep = ben.bring_in(f)
    assert rep["checks"]["new"] == 1 and rep["notes"] == 1
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h2,))
        assert not ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h3,))
        assert not ben.ws.scalar("SELECT 1 FROM notes WHERE note_id=?", (n2,))
        st = sharing.state(ben.ws._conn(), "check", h2)
        assert st["state"] == "shared" and st["owner"] == anna.id and not st["mine"]
        assert (ben.ws.root / "frameworks" / "ours.csv").is_file() and not (ben.ws.root / "frameworks" / "mine.csv").is_file()
        assert _state(ben.ws, "codebook", "ours") == "shared"


def test_the_whole_project_zip_says_whose_each_item_is_and_a_colleagues_private_item_is_not_passed_on(anna_and_ben,
                                                                                                    tmp_path):
    anna, ben = anna_and_ben
    with ben:  # Ben has Anna's first check from her whole-project zip: hers, and private
        st = sharing.state(ben.ws._conn(), "check", anna.hid)
        assert st["state"] == "private" and st["owner"] == anna.id and not st["mine"]
        with pytest.raises(PermissionError):  # only Anna can share it
            sharing.share(ben.ws, [{"kind": "check", "key": anna.hid}])
        mine = _check(ben.ws, "Ben's own hypothesis about pipelines.")
        sharing.share(ben.ws, [{"kind": "check", "key": mine}])
    db = _db_of(_send_shared(ben), tmp_path)
    assert {r[0] for r in db.execute("SELECT hyp_id FROM hypotheses")} == {mine}  # Anna's private check stays with Ben
    db.close()


def test_unsharing_stops_sending_and_a_colleague_keeps_it_marked_withdrawn(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    ben.bring_in(_send_shared(anna))
    with anna:
        claimcheck.set_note(anna.ws, h2, "changed after taking it back")
        sharing.unshare(anna.ws, [{"kind": "check", "key": h2}], why="not ready")
    f = _send_shared(anna)
    rep = ben.bring_in(f)
    assert any("No longer shared by its owner" in line for line in rep["lines"])
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h2,))  # it stays with Ben
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (h2,)) != "changed after taking it back"
        st = sharing.state(ben.ws._conn(), "check", h2)
        assert st["state"] == "withdrawn" and st["owner"] == anna.id
        with pytest.raises(PermissionError):  # only Anna can take it back or share it again
            sharing.share(ben.ws, [{"kind": "check", "key": h2}])
    with anna:  # sharing it again: it travels again, with its change
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    rep = ben.bring_in(_send_shared(anna))
    with ben:
        assert _state(ben.ws, "check", h2) == "shared"
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (h2,)) == "changed after taking it back"


def test_a_withdrawn_item_does_not_reach_a_copy_through_someone_who_still_has_it(anna_and_ben, tmp_path, monkeypatch):
    anna, ben = anna_and_ben
    clara = Person(tmp_path, "Clara", monkeypatch)
    with clara:  # Clara's copy, from Anna's first whole-project zip
        clara.ws = bundle.import_project(anna.files / "Anna-1.zip", tmp_path / "clara-project")
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    ben.bring_in(_send_shared(anna))      # Ben has it, shared
    with anna:
        sharing.unshare(anna.ws, [{"kind": "check", "key": h2}])
    clara.bring_in(_send_shared(anna))   # Clara learns that Anna took it back (she never had it)
    with clara:
        assert not clara.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h2,))
        assert _state(clara.ws, "check", h2) == "withdrawn"
    rep = clara.bring_in(_send_shared(ben))  # Ben has not heard yet and still sends it
    assert rep["shares"]["withheld"] and any("taken back by the person who shared it" in x for x in rep["lines"])
    with clara:
        assert not clara.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h2,))


def test_only_an_items_owner_decides_about_it(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    ben.bring_in(_send_shared(anna))
    with ben:
        cx = ben.ws._conn()
        later = "2999-01-01T00:00:00+00:00"
        # a mark about Anna's check by someone else than Anna changes nothing
        assert sharing.receive(cx, "check", h2, {"state": "withdrawn", "owner": anna.id, "by": ben.id, "at": later},
                               ben.id, True, had=True) is None
        assert _state(ben.ws, "check", h2) == "shared"
        # nor does any mark about an item of your own
        mine = _check(ben.ws, "Ben's hypothesis.")
        assert sharing.receive(cx, "check", mine, {"state": "shared", "owner": anna.id, "by": anna.id, "at": later},
                               ben.id, True, had=True) is None
        assert _state(ben.ws, "check", mine) == "private"


# --- projects from before 0.18 ------------------------------------------------------------------------------------
def _as_before_018(ws: Workspace) -> None:
    """The project as 0.17 left it: no table of shares."""
    with ws.connect() as cx:
        cx.execute("DROP TABLE shares")


def test_a_project_exchanged_before_018_counts_as_shared_and_one_never_sent_starts_private(loaded, tmp_path):
    hid = _check(loaded, CLAIM)
    nid = _note(loaded, _words(loaded))
    _as_before_018(loaded)
    loaded.close_all()
    ws = Workspace.open(loaded.root)  # never sent: private, no rows
    assert not ws.scalar("SELECT COUNT(*) FROM shares")
    assert sharing.state(ws._conn(), "check", hid)["mine"]
    _as_before_018(ws)
    with ws.connect() as cx:  # a zip of it was made (a backup, a move): that is no exchange with a colleague
        cx.execute("INSERT INTO sync_seen(kind, key, fp) VALUES ('check', ?, 'x')", (hid,))
    ws.close_all()
    ws = Workspace.open(loaded.root)
    assert not ws.scalar("SELECT COUNT(*) FROM shares")
    _as_before_018(ws)
    with ws.connect() as cx:  # a colleague's work was brought in once: it was exchanged
        cx.execute("INSERT INTO sync_log(at, person_id, report_json) VALUES ('2026-11-01', 'p0123456789ab', '{}')")
    ws.close_all()
    ws = Workspace.open(loaded.root)
    st = sharing.state(ws._conn(), "check", hid)
    assert st["state"] == "shared" and st["owner"] == people.me()  # its maker, from the research log
    assert st["by"] is None and st["at"] is None  # a guess, not anyone's word: any real mark counts over it
    assert sharing.state(ws._conn(), "note", nid)["state"] == "shared"


def test_a_file_from_a_colleague_on_017_counts_as_shared(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
    f = anna.send()
    old = tmp_path / "from-017.zip"  # the same file as 0.17 makes it: no table of shares, no format
    work = tmp_path / "unpacked"
    with zipfile.ZipFile(f) as zf:
        zf.extractall(work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    cx.execute("DROP TABLE shares")
    cx.commit()
    cx.close()
    meta = json.loads((work / "bundle.json").read_text())
    for k in ("sync_format", "sync_needs", "scope"):
        meta.pop(k)
    (work / "bundle.json").write_text(json.dumps(meta))
    with zipfile.ZipFile(old, "w") as zf:
        for p in work.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(work).as_posix())
    rep = ben.bring_in(old)
    assert rep["checks"]["new"] == 1
    with ben:
        st = sharing.state(ben.ws._conn(), "check", h2)
        assert st["state"] == "shared" and not st["mine"]


# --- through the app ----------------------------------------------------------------------------------------------
def test_sharing_through_the_app(api, tmp_path):  # noqa: F811
    from enlens_claims import home as home_mod, ingest

    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    ws = home_mod.open_project("Demo")
    ingest.ingest(ws, [Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"])
    hid = _check(ws, "Remote work reduces commuting emissions.")
    st, r = api("GET", "/api/projects/Demo/sharing?kind=check")
    assert st == 200 and [(i["key"], i["state"], i["mine"]) for i in r["items"]] == [(hid, "private", True)]
    assert r["counts"]["check"] == {"private": 1, "shared": 0, "withdrawn": 0} and r["me"]["id"] and r["kinds"]["note"]
    st, r = api("POST", "/api/projects/Demo/sharing/share", {"items": [{"kind": "check", "key": hid}], "why": "ready"})
    assert st == 200 and [i["key"] for i in r["shared"]] == [hid]
    st, r = api("GET", f"/api/projects/Demo/sharing/check/{hid}")
    assert st == 200 and r["item"]["state"] == "shared"
    assert api("GET", "/api/projects/Demo/sharing/check/nothere")[0] == 404
    assert api("GET", "/api/projects/Demo/sharing?state=odd")[0] == 400
    assert api("POST", "/api/projects/Demo/sharing/share", {"items": "x"})[0] == 400
    assert api("POST", "/api/projects/Demo/sharing/share", {"kind": "check", "key": "nothere"})[0] == 404
    st, r = api("GET", "/api/projects/Demo/export.zip?scope=shared")
    f = tmp_path / "shared.zip"
    f.write_bytes(r)
    assert st == 200 and sync.peek(f)["scope"] == "shared"
    assert api("GET", "/api/projects/Demo/export.zip?scope=everything")[0] == 400
    st, r = api("POST", "/api/projects/Demo/sharing/unshare", {"kind": "check", "key": hid})
    assert st == 200 and [i["key"] for i in r["withdrawn"]] == [hid]
    with ws.connect() as cx:  # a colleague's item: only they decide (403)
        cx.execute("INSERT INTO people(person_id, name) VALUES ('p0123456789ab', 'Anna')")
        cx.execute("UPDATE shares SET owner='p0123456789ab' WHERE kind='check' AND key=?", (hid,))
    st, r = api("POST", "/api/projects/Demo/sharing/share", {"kind": "check", "key": hid})
    assert st == 403 and "Anna" in r["error"]


def test_sets_of_themes_and_links_between_terms_travel_only_when_shared(anna_and_ben, tmp_path):
    from enlens_claims import ingest, terms, themes

    anna, ben = anna_and_ben
    with anna:
        ingest.ingest(anna.ws, [Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"])
        r1, r2 = themes.run(anna.ws, k=3, seed=1), themes.run(anna.ws, k=3, seed=2)
        themes.edit(anna.ws, r2, "rename", themes.view(anna.ws, r2)["themes"][0]["theme_id"], "Secret theme name")
        terms.build(anna.ws)
        (a, b), (c, d) = [sorted(r[0] for r in anna.ws.query("SELECT term_id FROM terms ORDER BY df DESC LIMIT 2")),
                          sorted(r[0] for r in anna.ws.query("SELECT term_id FROM terms ORDER BY df DESC LIMIT 2 "
                                                              "OFFSET 2"))]
        terms.set_link(anna.ws, a, b, "add", "same")   # a link she shares
        terms.set_link(anna.ws, c, d, "add", "broader")  # and one she keeps
        listed = {(i["kind"], i["key"]) for i in sharing.listing(anna.ws)["items"]}
        assert {("themes", r1), ("themes", r2), ("link", f"{a}|{b}"), ("link", f"{c}|{d}")} <= listed
        sharing.share(anna.ws, [{"kind": "themes", "key": r1}, {"kind": "link", "key": f"{a}|{b}"}])
    f = _send_shared(anna)
    db = _db_of(f, tmp_path)
    assert {r[0] for r in db.execute("SELECT run_id FROM theme_runs")} == {r1}
    assert not db.execute("SELECT 1 FROM tasks WHERE task_id LIKE ?", (f"theme:{r2}:%",)).fetchone()
    assert {(r[0], r[1]) for r in db.execute("SELECT a, b FROM concept_links WHERE source='person'")} == {(a, b)}
    assert not db.execute("SELECT 1 FROM terms").fetchone()  # the glossary is made again in each copy
    db.close()
    assert b"Secret theme name" not in (tmp_path / f"{f.stem}.sqlite").read_bytes()
    rep = ben.bring_in(f)
    assert rep["themes"]["new"] == 1
    with ben:
        assert _state(ben.ws, "themes", r1) == "shared" and _state(ben.ws, "link", f"{a}|{b}") == "shared"

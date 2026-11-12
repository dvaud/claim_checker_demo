"""0.18.0 (roadmap L5): working together through a shared folder.

Each copy of a project writes what its person shared into its own subfolder of a folder the team already shares
(OneDrive, Dropbox, a network drive), as small numbered bundles never rewritten, and brings in what the others wrote
with the merge rules of a zip (sync/folder.py). These tests run two and three copies of one project, each with its own
person and its own ENLENS folder, through one temporary folder over several rounds.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from enlens_claims import claimcheck, codebooks, people, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder
from test_0_14_0_shared_projects import CLAIM, Person, anna_and_ben  # noqa: F401  (fixture)


def _check(ws, text: str) -> str:
    return claimcheck.check_hypothesis(ws, text, BaselineBackend(), "baseline", k=2)


def _share(p: Person, kind: str, key: str) -> dict:
    with p:
        return sharing.share(p.ws, [{"kind": kind, "key": key}])


def _round(p: Person) -> dict:
    with p:
        out = folder.sync_now(p.ws)
    assert not [x for x in out["problems"] if x["kind"] not in ("documents",)], out["problems"]
    return out


def _state(ws, kind: str, key: str) -> str:
    return sharing.state(ws._conn(), kind, key)["state"]


@pytest.fixture
def shared_dir(tmp_path) -> Path:
    """The team's folder, with spaces and accents in its path (the owner's Windows user folder is C:\\Users\\Dávid)."""
    d = tmp_path / "Dávid" / "OneDrive - Közös egyetem" / "Csapat mappa"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def pair(anna_and_ben, shared_dir):
    anna, ben = anna_and_ben
    for p in (anna, ben):
        with p:
            folder.set_folder(p.ws, str(shared_dir))
    return anna, ben


def test_a_shared_check_reaches_a_colleague_through_the_folder(pair, shared_dir):
    anna, ben = pair
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        h3 = _check(anna.ws, "A private hunch about desalination.")
    _share(anna, "check", h2)
    w = _round(anna)
    assert w["wrote"]["seq"] == 1 and w["wrote"]["snapshot"]
    r = _round(ben)
    rep = r["read"][0]["report"]
    assert rep and rep["checks"]["new"] >= 1
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h2,))
        assert not ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h3,))
        assert _state(ben.ws, "check", h2) == "shared"


def _join(p: Person, shared_dir: Path) -> None:
    with p:
        folder.set_folder(p.ws, str(shared_dir))


@pytest.fixture
def trio(pair, shared_dir, tmp_path, monkeypatch):
    """Anna and Ben, and Carol, who joins later with a copy from Anna's whole-project zip."""
    from enlens_claims import bundle

    anna, ben = pair
    carol = Person(tmp_path, "Carol", monkeypatch)
    f = anna.send()
    with carol:
        carol.ws = bundle.import_project(f, tmp_path / "carol-project")
    return anna, ben, carol


def _claim(ws, hid: str) -> str:
    return ws.scalar("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY claim_id LIMIT 1", (hid,))


def _excerpts(ws, hid: str) -> list[dict]:
    return [p for part in claimcheck.hypothesis_result(ws, hid)["parts"] for p in part["passages"]]


def _has(ws, hid: str) -> bool:
    return bool(ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,)))


def _lines(out: dict) -> list[str]:
    return [line for e in out["read"] if e.get("report") for line in e["report"]["lines"]]


# --- sharing, changing and taking back -----------------------------------------------------------------------------
def test_share_change_and_withdraw_over_several_rounds(trio, shared_dir):
    anna, ben, carol = trio
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        h3 = _check(anna.ws, "A private hunch about desalination.")
    _share(anna, "check", h2)
    _round(anna)
    out = _round(ben)
    assert any("1 new result" in line for line in _lines(out))
    with ben:
        assert _has(ben.ws, h2) and not _has(ben.ws, h3) and _state(ben.ws, "check", h2) == "shared"
    # a second round with nothing new writes nothing and brings nothing
    assert _round(anna)["wrote"]["seq"] is None
    assert not [e for e in _round(ben)["read"] if e["report"]]
    # Anna changes her shared check: Ben's copy is brought up to date
    with anna:
        claimcheck.set_note(anna.ws, h2, "Anna's note")
    assert [i["key"] for i in _round(anna)["wrote"]["items"]] == [h2]
    out = _round(ben)
    assert out["read"][0]["report"]["checks"]["updated"] == 1
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (h2,)) == "Anna's note"
    # she takes it back: Ben keeps it, marked withdrawn; Carol, who never had it, does not get it from anyone
    with anna:
        sharing.unshare(anna.ws, [{"kind": "check", "key": h2}])
    _round(anna)
    out = _round(ben)
    gone = out["read"][0]["report"]["shares"]["withdrawn"]
    with ben:
        assert _has(ben.ws, h2) and _state(ben.ws, "check", h2) == "withdrawn"
        # named as Ben's copy knows it, not by its key (final check: 'No longer shared by its owner: "hf864a9b2c80c"')
        assert gone == [ben.ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (h2,))] and h2 not in gone
    _join(carol, shared_dir)
    _round(carol)
    with carol:
        # Carol's copy is Anna's whole zip: she has h2 from it already, as Anna's private item; it stays so
        assert _state(carol.ws, "check", h2) in ("private", "withdrawn")
        assert not _has(carol.ws, h3) or _state(carol.ws, "check", h3) == "private"


def test_a_newcomer_starts_from_each_colleagues_snapshot(pair, shared_dir, tmp_path, monkeypatch):
    """Dan has a copy made before any of this work (an empty project of the same id): everything shared reaches him,
    from both colleagues' folders, and nothing private does."""
    from enlens_claims.store import Workspace

    anna, ben = pair
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        h3 = _check(anna.ws, "A private hunch about desalination.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    with ben:
        hb = _check(ben.ws, "Water stress limits hydrogen exports.")
        sharing.share(ben.ws, [{"kind": "check", "key": hb}])
    for _ in range(2):
        _round(anna)
        _round(ben)
    dan = Person(tmp_path, "Dan", monkeypatch)
    with dan:
        dan.ws = Workspace.create(tmp_path / "dan-project")
        dan.ws.set_meta("project_uid", anna.ws.meta("project_uid"))
    _join(dan, shared_dir)
    out = _round(dan)
    assert {e["name"] for e in out["read"] if e["report"]} == {"Anna", "Ben"}
    with dan:
        assert _has(dan.ws, h2) and _has(dan.ws, hb) and not _has(dan.ws, h3)
        assert not _has(dan.ws, anna.hid)  # Anna's first check was never shared
        # the documents came with their readings and their files, checked against their sha1
        from enlens_claims import sources

        docs = [r[0] for r in dan.ws.query("SELECT doc_id FROM documents")]
        assert docs and all(sources.original_file(dan.ws, d)["available"] for d in docs)
        assert dan.ws.scalar("SELECT COUNT(*) FROM passages") == anna.ws.scalar("SELECT COUNT(*) FROM passages")
        # the result pages work on the check that came in
        assert _excerpts(dan.ws, h2)


# --- a sync clash ----------------------------------------------------------------------------------------------------
def test_a_check_both_changed_between_rounds_is_a_sync_clash_in_both_copies(pair):
    anna, ben = pair
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
    _share(anna, "check", h2)
    _round(anna)
    _round(ben)
    with anna:
        claimcheck.set_note(anna.ws, h2, "Anna's note")
    with ben:
        claimcheck.set_note(ben.ws, h2, "Ben's note")
    _round(anna)
    out = _round(ben)
    rep = out["read"][0]["report"]
    assert len(rep["checks"]["clash"]) == 1
    copy_id = rep["checks"]["clash"][0]["hyp_id"]
    _round(anna)
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (copy_id,)) == "Anna's note"
    for p in (anna, ben):  # each keeps their own version under its id, and the other's as a copy (named by its mark)
        with p:
            got = sorted(r[0] for r in p.ws.query("SELECT note FROM hypotheses WHERE hyp_id LIKE ?", (h2 + "%",)))
            assert got == ["Anna's note", "Ben's note"]
            assert p.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (h2,)) == f"{p.name}'s note"
    # another round changes nothing: no copy of a copy, no echo
    for p in (anna, ben, anna):
        out = _round(p)
        assert not [e for e in out["read"] if e["report"] and (e["report"]["checks"]["clash"] or
                                                                e["report"]["checks"]["new"])]
    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM hypotheses WHERE hyp_id LIKE ?", (h2 + "%",)) == 2


# --- judgements by two people -------------------------------------------------------------------------------------
def test_judgements_by_two_people_on_one_check_reach_both_and_a_third(trio, shared_dir):
    anna, ben, carol = trio
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        ex = _excerpts(anna.ws, h2)
        assert len(ex) >= 2
        claimcheck.set_judgement(anna.ws, _claim(anna.ws, h2), ex[0]["passage_id"], "supports", note="clear")
    _share(anna, "check", h2)
    _round(anna)
    _round(ben)
    with ben:
        claimcheck.set_judgement(ben.ws, _claim(ben.ws, h2), ex[0]["passage_id"], "refutes")
        claimcheck.set_judgement(ben.ws, _claim(ben.ws, h2), ex[1]["passage_id"], "not_relevant")
    assert [i["key"] for i in _round(ben)["wrote"]["items"]] == [h2]  # his judgements travel with her check
    out = _round(anna)
    assert out["read"][0]["report"]["judgements"] == 2
    with anna:
        got = {p["passage_id"]: p for p in _excerpts(anna.ws, h2)}
        assert got[ex[0]["passage_id"]]["judged_by"] == "you" and got[ex[0]["passage_id"]]["user_verdict"] == "supports"
        assert [(o["name"], o["verdict"]) for o in got[ex[0]["passage_id"]]["others"]] == [("Ben", "refutes")]
        assert got[ex[1]["passage_id"]]["judged_by"] == "Ben"
        assert people.agreement(anna.ws)[0]["name"] == "Ben"
    # Carol joins: every judgement comes, each under its maker's name
    _join(carol, shared_dir)
    _round(carol)
    with carol:
        got = {p["passage_id"]: p for p in _excerpts(carol.ws, h2)}
        names = {o["name"] for o in got[ex[0]["passage_id"]]["others"]} | {got[ex[0]["passage_id"]]["judged_by"]}
        assert names == {"Anna", "Ben"}
    # nobody writes again what came in: the next rounds are quiet
    for p in (anna, ben, carol):
        assert _round(p)["wrote"]["items"] == []


# --- a codebook edited on both sides -------------------------------------------------------------------------------
def test_a_codebook_edited_on_both_sides_is_merged_code_by_code(pair):
    from enlens_claims import frameworks
    from test_0_18_0_codebook_merge import _edit, _set

    anna, ben = pair
    with anna:
        codebooks.create(anna.ws, "water", "Water", "project", "csv",
                         {"csv": "code,description\nA,Water use of electrolysis\nB,Jobs near the plant\n"})
    _share(anna, "codebook", "water")
    _round(anna)
    _round(ben)
    with ben:
        assert {c.code for c in frameworks.get("water", ben.ws).codes.values()} == {"A", "B"}
        assert _state(ben.ws, "codebook", "water") == "shared"
        _edit(ben.ws, "water", _set("description", "B", "Local jobs and training"))
    with anna:
        _edit(anna.ws, "water", _set("description", "A", "Water drawn by electrolysers"))
    _round(anna)
    out = _round(ben)
    assert [m["name"] for m in out["read"][0]["report"]["codebooks"]["merged"]] == ["water"]
    _round(anna)
    want = {"A": "Water drawn by electrolysers", "B": "Local jobs and training"}
    for p in (anna, ben):
        with p:
            assert {c.code: c.description for c in frameworks.get("water", p.ws).codes.values()} == want
            assert [n for n in frameworks.available(p.ws) if n.startswith("water")] == ["water"]


# --- documents -------------------------------------------------------------------------------------------------------
def test_a_document_added_by_one_copy_comes_with_its_file_once(pair, shared_dir, tmp_path):
    from enlens_claims import ingest, sources

    anna, ben = pair
    _round(anna)
    _round(ben)
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "colleague report.txt").write_text("Desalination for electrolysis adds cost but removes water stress. " * 20)
    with anna:
        ingest.ingest(anna.ws, [extra])
        doc = anna.ws.scalar("SELECT doc_id FROM documents WHERE path LIKE '%colleague report.txt'")
    w = _round(anna)["wrote"]
    assert w["readings"] == 1 and w["files"] == 1  # only the new document goes, not the corpus again
    with ben:
        v = ben.ws.corpus_version()
    out = _round(ben)
    assert out["read"][0]["report"]["documents"]["new"] == [anna.ws.scalar("SELECT title FROM documents WHERE "
                                                                           "doc_id=?", (doc,))]
    with ben:
        assert ben.ws.corpus_version() > v
        info = sources.original_file(ben.ws, doc)
        assert info["available"] and Path(info["path"]).is_relative_to(ben.ws.root.resolve())
        assert ben.ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,)) == \
            anna.ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,))
    # the file is in the folder once, though both copies hold it now
    assert len([f for f in shared_dir.rglob("files/*") if f.name.startswith(
        anna.ws.scalar("SELECT sha1 FROM documents WHERE doc_id=?", (doc,)))]) == 1
    assert _round(ben)["wrote"]["files"] == 0


def test_a_document_moved_to_the_new_reader_by_one_copy_stays_one_document(tmp_path, monkeypatch, shared_dir):
    from enlens_claims import reread
    from test_0_18_0_old_readings import _doc_text, _placed
    from test_0_15_0_read_with_new_reader import Q_DESAL, _check as _paper_check

    anna, ben = _paper_pair(tmp_path, monkeypatch)
    for p in (anna, ben):
        _join(p, shared_dir)
    with anna:
        hid = anna.ws.scalar("SELECT hyp_id FROM hypotheses")
        sharing.share(anna.ws, [{"kind": "check", "key": hid}])
    _round(anna)
    _round(ben)
    with ben:
        reread.move(ben.ws, anna.doc)  # Ben reads it with the new reader
        new_text = _doc_text(ben.ws, anna.doc)
    with anna:  # Anna, still on reader 1, checks another hypothesis on it
        cid2, _ = _paper_check(anna.ws, [(Q_DESAL, "partially_supports")])
        h2 = anna.ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (cid2,))
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    _round(anna)
    out = _round(ben)
    rep = out["read"][0]["report"]
    assert rep["documents"]["other_reading"] and not rep["documents"]["clash"] and not rep["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM documents") == 1
        assert _doc_text(ben.ws, anna.doc) == new_text  # his reading stays
        assert all(ok for _q, ok in _placed(ben.ws, anna.doc, h2))  # her results land on his reading
    # and back: Anna's copy keeps her reading and gets Ben's moved check without a clash
    _round(ben)
    out = _round(anna)
    assert not [e for e in out["read"] if e["report"] and e["report"]["checks"]["clash"]]
    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM documents") == 1


def _paper_pair(tmp_path, monkeypatch):
    """Anna's project with a two-column paper read by reader 1 and a check on it; Ben's copy from her zip (the old
    readings tests' fixture, as a function)."""
    from enlens_claims import bundle
    from enlens_claims.store import Workspace
    from test_0_15_0_read_with_new_reader import Q_WATER, _add, _check as _paper_check, _paper

    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    with anna:
        anna.ws = Workspace.create(tmp_path / "anna-project")
        anna.doc = _add(anna.ws, monkeypatch, _paper(tmp_path))
        _paper_check(anna.ws, [(Q_WATER, "supports")])
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
    return anna, ben


# --- who may read a document with AI -------------------------------------------------------------------------------
def test_a_document_marked_no_ai_on_one_side_is_no_ai_in_every_copy(trio, shared_dir):
    from enlens_claims import access

    anna, ben, carol = trio
    with ben:
        doc = ben.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        access.set_documents(ben.ws, [doc], "none")
    _round(ben)
    out = _round(anna)
    assert any(a["doc_id"] == doc and a["now"] == "none" for a in out["read"][0]["report"]["ai_access"])
    with anna:
        assert access.levels(anna.ws, [doc], budget=False)[doc] == "none"
    _join(carol, shared_dir)
    _round(carol)
    with carol:
        assert access.levels(carol.ws, [doc], budget=False)[doc] == "none"
    # a colleague's looser setting never loosens it again
    with anna:
        assert access.levels(anna.ws, [doc], budget=False)[doc] == "none"


# --- the switch: documents marked Only a local AI or No AI kept out of the folder ------------------------------------
def _bundle_rows(shared_dir: Path, sql: str, args=()) -> list[tuple]:
    import sqlite3
    import tempfile
    import zipfile

    out = []
    for b in sorted(shared_dir.rglob("bundles/*.zip")):
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(b) as zf:
            db = Path(tmp) / "rows.sqlite"
            db.write_bytes(zf.read("rows.sqlite"))
            cx = sqlite3.connect(db)
            out += cx.execute(sql, args).fetchall()
            cx.close()
    return out


def test_documents_kept_out_of_the_folder_still_merge_by_what_names_them(pair, shared_dir, tmp_path):
    from enlens_claims import access, ingest, profile

    anna, ben = pair
    _round(anna)
    _round(ben)
    with anna:
        folder.set_keep_out(anna.ws, True)
    src = tmp_path / "interviews"
    src.mkdir()
    (src / "interview notes.txt").write_text(
        "Electrolysers in the valley create local jobs for welders and technicians. " * 8 + "\n\n" +
        "A confidential remark about the mayor and the zebrafish permit. " * 12)
    with anna:
        ingest.ingest(anna.ws, [src])
        doc, sha, fp = anna.ws.query("SELECT doc_id, sha1, text_fp FROM documents WHERE path LIKE "
                                     "'%interview notes.txt'")[0]
        access.set_documents(anna.ws, [doc], "none")
        hid = claimcheck.check_hypothesis(anna.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline",
                                          k=1, per_doc=1, doc_ids=[doc])
        sharing.share(anna.ws, [{"kind": "check", "key": hid}])
        last = anna.ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq DESC LIMIT 1", (doc,))
        profile.add_label(anna.ws, "sdg", last, "16.5")
    w = _round(anna)["wrote"]
    assert w["kept_out"] == 1 and w["readings"] == 0 and w["files"] == 0
    # neither its reading, nor its file, nor the AI work on it is in the folder
    assert not list(shared_dir.rglob(folder.reading_name(doc, fp))) and not list(shared_dir.rglob(f"{sha}.*"))
    assert not _bundle_rows(shared_dir, "SELECT 1 FROM labels WHERE doc_id=?", (doc,))
    out = _round(ben)
    rep = out["read"][0]["report"]
    assert rep["checks"]["new"] == 1 and [x["doc_id"] for x in rep["documents"]["not_here"]] == [doc]
    assert any("not in the shared folder" in line for line in rep["lines"])
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))
        assert _excerpts(ben.ws, hid)  # its excerpts are kept, as records
        st = folder.status(ben.ws)
        assert [x["doc_id"] for x in st["not_here"]] == [doc] and st["not_here"][0]["from"] == "Anna"
        assert st["keep_out"] == {"mine": False, "colleagues": ["Anna"], "in_force": True}
    # Anna changes her check: Ben's copy is brought up to date, without a sync clash (it names the document alike)
    with anna:
        claimcheck.set_note(anna.ws, hid, "seen once")
    _round(anna)
    rep = _round(ben)["read"][0]["report"]
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"] and not rep["documents"]["not_here"]
    # Ben adds the file himself: it is the same document, kept from AI as in Anna's copy, and nothing clashes
    with ben:
        ingest.ingest(ben.ws, [src])
        assert ben.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))
    with anna:
        claimcheck.set_note(anna.ws, hid, "seen twice")
    _round(anna)
    rep = _round(ben)["read"][0]["report"]
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"] and not rep["documents"]["clash"]
    with ben:
        assert access.levels(ben.ws, [doc], budget=False)[doc] == "none"
        assert folder.status(ben.ws)["not_here"] == []
    # the switch holds in Ben's copy too while Anna has it on: his own document for a local AI stays out
    more = tmp_path / "bens"
    more.mkdir()
    (more / "ben local.txt").write_text("Notes Ben keeps for the local model only, about the regional grid. " * 10)
    with ben:
        ingest.ingest(ben.ws, [more])
        bdoc, bsha = ben.ws.query("SELECT doc_id, sha1 FROM documents WHERE path LIKE '%ben local.txt'")[0]
        access.set_documents(ben.ws, [bdoc], "local")
    assert _round(ben)["wrote"]["readings"] == 0 and not list(shared_dir.rglob(f"{bsha}.*"))


# --- removals, notes ------------------------------------------------------------------------------------------------
def test_a_shared_check_removed_by_its_owner_stays_with_colleagues_and_does_not_reach_a_newcomer(trio, shared_dir):
    anna, ben, carol = trio
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    _round(anna)
    _round(ben)
    with anna:
        claimcheck.delete_hypothesis(anna.ws, h2)
    _round(anna)
    rep = _round(ben)["read"][0]["report"]
    assert rep["checks"]["removed_there"] == ["Electrolysers create local jobs."]
    with ben:
        assert _has(ben.ws, h2)  # nothing is taken from anyone
    _join(carol, shared_dir)
    _round(carol)
    with carol:
        assert not _has(carol.ws, h2)
        assert carol.ws.scalar("SELECT 1 FROM sync_removed WHERE kind='check' AND key=?", (h2,))


def test_a_shared_note_and_a_log_entry_are_brought_up_to_date(pair):
    from enlens_claims import notes, researchlog

    anna, ben = pair
    with anna:
        doc, body = anna.ws.query("SELECT doc_id, text FROM documents ORDER BY doc_id LIMIT 1")[0]
        a = body.index(body.split()[5])
        nid = notes.add(anna.ws, doc, a, a + 20, text="first thought")["note_id"]
        eid = researchlog.add(anna.ws, "Met the water board.")["entry_id"]
        sharing.share(anna.ws, [{"kind": "note", "key": nid}, {"kind": "log", "key": eid}])
    _round(anna)
    _round(ben)
    with ben:
        assert ben.ws.scalar("SELECT text FROM notes WHERE note_id=?", (nid,)) == "first thought"
        assert ben.ws.scalar("SELECT text FROM research_log WHERE entry_id=?", (eid,)) == "Met the water board."
    with anna:
        notes.update(anna.ws, nid, text="second thought")
        researchlog.update(anna.ws, eid, "Met the water board twice.")
    _round(anna)
    _round(ben)
    with ben:
        assert ben.ws.scalar("SELECT text FROM notes WHERE note_id=?", (nid,)) == "second thought"
        assert ben.ws.scalar("SELECT text FROM research_log WHERE entry_id=?", (eid,)) == "Met the water board twice."


def test_a_check_naming_a_document_one_copy_removed_is_not_churned(pair):
    anna, ben = pair
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
        doc = anna.ws.scalar("SELECT doc_id FROM verifications WHERE subject_id=? LIMIT 1", (_claim(anna.ws, h2),))
    _round(anna)
    _round(ben)
    with anna:
        anna.ws.remove_document(doc)  # her check keeps what it read of it
        claimcheck.set_note(anna.ws, h2, "after the removal")
    _round(anna)
    rep = _round(ben)["read"][0]["report"]
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]
    assert rep["documents"]["removed_there"]
    with ben:
        # 0.18 L2: Anna made the project, so she is its owner, and a document the owner removes leaves every copy
        # (a collaborator's removal would stay theirs, as a proposal: tests/test_0_18_0_owner.py)
        assert not ben.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))
        claimcheck.set_note(ben.ws, h2, "Ben's reply")
    _round(ben)
    rep = _round(anna)["read"][0]["report"]
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]


def test_one_log_entry_that_came_in_is_said_in_the_singular():
    # final check: "1 research log entry of Anna's came in or were brought up to date"
    from enlens_claims.sync.report import summary

    def rep(log, notes):
        return {"from": {"name": "Anna"}, "documents": {"new": [], "clash": [], "removed_here": [], "removed_there": [],
                                                         "not_wanted": [], "other_reading": [], "not_here": []},
                "checks": {"new": 0, "updated": 0, "same": 0, "yours_newer": 0, "clash": [], "running": [],
                           "running_here": [], "removed_here": [], "removed_there": []},
                "themes": {"new": 0, "updated": 0, "clash": [], "removed_here": 0, "running_here": []},
                "codebooks": {"new": [], "updated": [], "clash": [], "merged": []}, "judgements": 0, "reviews": 0,
                "labels": 0, "labels_kept_yours": 0, "links": 0, "other_rows": 0, "log": log, "notes": notes,
                "shares": {"shared": [], "withdrawn": [], "withheld": []}, "bibliography": None, "ai_access": []}

    assert "1 research log entry of Anna's came in or was brought up to date, under their name." in summary(rep(1, 0))
    assert "2 research log entries and 1 note of Anna's came in or were brought up to date, under their name." in \
        summary(rep(2, 1))



def test_a_title_that_starts_with_a_quotation_reads_well_in_what_came_in():
    # the Team tab showed: about ""You never really meet anyone": young employees on remote wo"
    from enlens_claims.sync.report import _title

    t = '"You never really meet anyone": young employees on remote work and their first year in the firm'
    assert _title(t, 60) == "“‘You never really meet anyone’: young employees on remote w…”"
    assert _title("Bird migration notes.") == "“Bird migration notes”" and _title(None) == "“a document”"

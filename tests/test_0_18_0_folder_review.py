"""0.18.0: fixes from an independent review of the shared folder (sync/folder.py); each test failed before its fix.

1. With the switch on, the words of documents kept out of the folder still reached it in the passages handed to the AI
   (a shared check's tasks, the SDG pack's tasks whose id names no document).
2. One damaged bundle (no database in it, or not a database) stopped the whole round, every round.
3. A shared folder that holds the project itself (or ENLENS's own folder) was accepted: the cloud service would copy
   the project's database to the team.
4. project.json missing for a moment (not brought by the cloud yet) was made anew, and every copy started over.
5. The project's rows were written once by their key: a later change (a reason added to an entry) never travelled.
6. The bibliography's attachments carried their paths on this computer into the folder and into a zip for a colleague.
7. A reading recorded as already in the folder was never written again after its writer's subfolder went away.
8. An original file changed since it was added was copied into the folder under the old checksum.
10. A writer whose record and subfolder were both lost started again at bundle 1, and a colleague who had read up to a
    higher number never read that new start.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import access, bundle, claimcheck, researchlog, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_0_18_0_folder_privacy import _everything
from test_0_18_0_folder_robustness import _bundles, _note_here, _upto, started  # noqa: F401  (fixture)
from test_0_18_0_shared_folder import _check, _join, _round, pair, shared_dir, trio  # noqa: F401  (fixtures)


# 1 ------------------------------------------------------------------------------------------------------------------
def test_the_switch_keeps_the_words_of_kept_out_documents_out_of_shared_work(pair, shared_dir, tmp_path):
    from enlens_claims import ingest

    anna, ben = pair
    src = tmp_path / "interviews"
    src.mkdir()
    (src / "short interview.txt").write_text("Interview with the mayor, spring 2026\n\n"
                                             "Electrolysers in the valley create local jobs for welders. "
                                             "The mayor mentioned the zebrafish permit in confidence.")
    with anna:
        folder.set_keep_out(anna.ws, True)
        ingest.ingest(anna.ws, [src])
        doc = anna.ws.scalar("SELECT doc_id FROM documents WHERE path LIKE '%short interview.txt'")
        access.set_documents(anna.ws, [doc], "none")
        hid = claimcheck.check_hypothesis(anna.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline",
                                          k=1, per_doc=1, doc_ids=[doc])
        assert anna.ws.scalar("SELECT COUNT(*) FROM tasks WHERE payload_json LIKE '%zebrafish%'")  # handed to the AI
        quote = anna.ws.scalar("SELECT quote FROM verifications v JOIN user_claims u ON u.claim_id=v.subject_id WHERE "
                               "u.hyp_id=? AND v.quote IS NOT NULL LIMIT 1", (hid,))
        sharing.share(anna.ws, [{"kind": "check", "key": hid}])
    _round(anna)
    blob = b"".join(d for _n, d in _everything(shared_dir))
    assert b"zebrafish" not in blob
    assert b"Interview with the mayor" in blob  # its title names it, so colleagues know which file to add
    assert not quote or "zebrafish" in quote or quote.encode() in blob  # what was quoted goes with the shared check
    _round(ben)
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,))
    # no echo: Ben does not write the check back, and Anna's copy keeps its tasks whole
    assert _round(ben)["wrote"]["items"] == []
    _round(anna)
    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM tasks WHERE payload_json LIKE '%zebrafish%'")


def test_the_sdg_packs_tasks_on_a_kept_out_document_stay(loaded):
    ws = loaded
    doc, pid, text = ws.query("SELECT doc_id, passage_id, text FROM passages LIMIT 1")[0]
    payload = {"subject_kind": "vca_claim", "subject_id": "vc9", "passages": [{"passage_id": pid, "doc_id": doc,
                                                                                "text": text}]}
    with ws.connect() as cx:
        cx.execute("INSERT INTO tasks(task_id, kind, model, payload_json, status) VALUES (?,?,?,?,?)",
                   ("verify_set:vc9:local", "verify_set", "m", json.dumps(payload), "done"))
        cx.execute("INSERT INTO results(task_id, attempt, kind, raw_json, valid) VALUES (?,?,?,?,?)",
                   ("verify_set:vc9:local", 1, "verify_set", json.dumps({"quote": text[:50]}), 1))
    rows = sharing.ProjectRows(ws._conn(), ws.root, {doc})
    got = {(t, rows.fetch(t, [rid])[0]["task_id"]) for t, rid, *_ in rows.scan() if t in ("tasks", "results")}
    assert ("tasks", "verify_set:vc9:local") not in got and ("results", "verify_set:vc9:local") not in got
    rows = sharing.ProjectRows(ws._conn(), ws.root)
    got = {(t, rows.fetch(t, [rid])[0]["task_id"]) for t, rid, *_ in rows.scan() if t in ("tasks", "results")}
    assert ("tasks", "verify_set:vc9:local") in got  # without the switch it goes, as in a zip


# 2 ------------------------------------------------------------------------------------------------------------------
def _rewrite(f: Path, drop: str | None = None, put: dict[str, bytes] | None = None) -> None:
    with zipfile.ZipFile(f) as zf:
        members = {n: zf.read(n) for n in zf.namelist() if n != drop}
    members.update(put or {})
    with zipfile.ZipFile(f, "w") as zf:
        for n, data in members.items():
            zf.writestr(n, data)


@pytest.mark.parametrize("damage", ["no database", "not a database"])
def test_a_damaged_bundle_stops_only_its_writer(trio, shared_dir, damage):
    anna, ben, carol = trio
    _join(carol, shared_dir)
    _round(carol)
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    with carol:
        hc = _check(carol.ws, "Carol's check on grid capacity.")
        sharing.share(carol.ws, [{"kind": "check", "key": hc}])
    seq = _round(anna)["wrote"]["seq"]
    _round(carol)
    f = _bundles(shared_dir, anna) / f"{seq:06d}.zip"
    if damage == "no database":
        _rewrite(f, drop="rows.sqlite")
    else:
        _rewrite(f, put={"rows.sqlite": b"not a database at all" * 50})
    with ben:
        out = folder.sync_now(ben.ws)
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hc,))  # Carol's work came in
        assert not ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h2,))
    assert [(x["kind"], x["person"]["name"], x["seq"]) for x in out["problems"]] == [("damaged", "Anna", seq)]
    assert out["wrote"] is not None and out["files"] == 0


def test_a_merge_that_fails_stops_only_that_colleague_and_changes_nothing(trio, shared_dir, monkeypatch):
    from enlens_claims.sync import merge

    anna, ben, carol = trio
    _join(carol, shared_dir)
    for p in (carol, ben):
        _round(p)
    with anna:
        h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h2}])
    _round(anna)
    real = merge._Merge.run

    def boom(self):
        if self.sender["name"] == "Anna":
            raise RuntimeError("something unexpected")
        return real(self)

    monkeypatch.setattr(merge._Merge, "run", boom)
    with ben:
        out = folder.sync_now(ben.ws)
        assert not ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h2,))
    assert [(x["kind"], x["person"]["name"]) for x in out["problems"]] == [("failed", "Anna")]
    assert "something unexpected" in out["problems"][0]["message"]
    monkeypatch.setattr(merge._Merge, "run", real)
    _round(ben)
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h2,))


# 3 ------------------------------------------------------------------------------------------------------------------
def test_a_shared_folder_that_holds_the_project_or_enlens_itself_is_refused(anna_and_ben, tmp_path):
    from enlens_claims.home import home
    from enlens_claims.store import Workspace

    anna, _ben = anna_and_ben
    team = tmp_path / "OneDrive - Uni" / "Team"
    with anna:
        ws = Workspace.create(team / "projects" / "X")
        with pytest.raises(folder.FolderProblem, match="holds this project"):
            folder.check_folder(ws, str(team))
        with pytest.raises(folder.FolderProblem, match="holds"):
            folder.check_folder(anna.ws, str(home().parent))  # ENLENS's own folder, with every project, is in it
        if Path(str(team).upper()).exists():  # a file system that does not tell capital letters apart
            with pytest.raises(folder.FolderProblem, match="holds this project"):
                folder.check_folder(ws, str(team).upper())


# 4 ------------------------------------------------------------------------------------------------------------------
def test_project_json_not_there_for_a_moment_starts_nobody_over(started, shared_dir, tmp_path, monkeypatch):
    from enlens_claims.store import Workspace

    anna, ben = started
    team = next(shared_dir.glob("ENLENS-*"))
    before = json.loads((team / "project.json").read_text())["folder_id"]
    (team / "project.json").unlink()  # the cloud service has not brought it (yet), or it cannot be read now
    out = _round(ben)
    assert json.loads((team / "project.json").read_text())["folder_id"] == before  # made again as it was
    w = _round(anna)["wrote"]
    assert w["seq"] is None and not w["snapshot"]  # nobody starts over
    # a copy new to the folder, with no record of it, waits for project.json instead of making a new one
    (team / "project.json").unlink()
    dan = Person(tmp_path, "Dan", monkeypatch)
    with dan:
        dan.ws = Workspace.create(tmp_path / "dan")
        dan.ws.set_meta("project_uid", anna.ws.meta("project_uid"))
        folder.set_folder(dan.ws, str(shared_dir))
        out = folder.sync_now(dan.ws)
    assert [x["kind"] for x in out["problems"]] == ["arriving"] and not (team / "project.json").exists()
    assert not (team / dan.id).exists()


# 5 ------------------------------------------------------------------------------------------------------------------
def test_a_later_change_of_the_projects_rows_travels(pair):
    anna, ben = pair
    with anna:
        with anna.ws.connect() as cx:
            researchlog.record(cx, "documents-added", "Added 3 documents.", "documents", None)
        eid = anna.ws.scalar("SELECT entry_id FROM research_log WHERE kind='documents-added' AND person_id=? AND "
                             "text='Added 3 documents.'", (anna.id,))
    _round(anna)
    _round(ben)
    with anna:
        researchlog.update(anna.ws, eid, why="because the reviewers asked")
    assert _round(anna)["wrote"]["rows"] >= 1
    _round(ben)
    with ben:
        assert ben.ws.scalar("SELECT why FROM research_log WHERE entry_id=?", (eid,)) == "because the reviewers asked"


# 6 ------------------------------------------------------------------------------------------------------------------
def test_the_bibliographys_attachments_carry_no_path_of_this_computer(pair, shared_dir, tmp_path):
    anna, _ben = pair
    where = "/Users/anna/Zotero/storage/ABCD1234/smith 2021.pdf"
    with anna:
        with anna.ws.connect() as cx:
            cx.execute("INSERT INTO bib_items(item_key, item_type, title, files_json, seq) VALUES (?,?,?,?,?)",
                       ("ABCD1234", "report", "Smith 2021", json.dumps([{"path": where, "name": "smith 2021.pdf",
                                                                         "type": "application/pdf"}]), 1))
        out = tmp_path / "shared.zip"
        bundle.export_project(anna.ws, out, scope="shared")
    _round(anna)
    blob = b"".join(d for _n, d in _everything(shared_dir))
    assert b"Smith 2021" in blob and b"smith 2021.pdf" in blob and b"/Users/anna/Zotero" not in blob
    with zipfile.ZipFile(out) as zf:
        db = tmp_path / "z.sqlite"
        db.write_bytes(zf.read("enlens.sqlite"))
    files = json.loads(sqlite3.connect(db).execute("SELECT files_json FROM bib_items").fetchone()[0])
    assert files == [{"name": "smith 2021.pdf", "type": "application/pdf"}]


# 7 ------------------------------------------------------------------------------------------------------------------
def test_readings_and_files_whose_writer_left_are_written_again(started, shared_dir):
    anna, ben = started
    team = next(shared_dir.glob("ENLENS-*"))
    readings = {f.name for f in (team / anna.id / "docs").iterdir()}
    assert readings and not any((team / ben.id / "docs").iterdir())  # Anna wrote them; Ben found them there
    shutil.rmtree(team / anna.id / "docs")
    shutil.rmtree(team / anna.id / "files")
    w = _round(ben)["wrote"]
    assert w["readings"] == len(readings) and {f.name for f in (team / ben.id / "docs").iterdir()} == readings


# 8 ------------------------------------------------------------------------------------------------------------------
def test_an_original_that_changed_since_it_was_added_is_not_written(pair, shared_dir, tmp_path):
    from enlens_claims import ingest

    anna, _ben = pair
    extra = tmp_path / "extra"
    extra.mkdir()
    f = extra / "changing.txt"
    f.write_text("Hydrogen storage in salt caverns near the coast. " * 30)
    with anna:
        ingest.ingest(anna.ws, [extra])
        sha = anna.ws.scalar("SELECT sha1 FROM documents WHERE path LIKE '%changing.txt'")
    f.write_text("Someone edited this file afterwards. " * 30)
    _round(anna)
    assert not list(shared_dir.rglob(f"files/{sha}.*"))


# 10 -----------------------------------------------------------------------------------------------------------------
def test_a_writer_that_lost_its_record_and_its_subfolder_is_read_from_its_new_start(started, shared_dir):
    anna, ben = started
    for note in ("one", "two", "three"):
        with anna:
            claimcheck.set_note(anna.ws, anna.h2, note)
        _round(anna)
    _round(ben)
    assert _upto(ben, anna) >= 4
    with anna:  # both gone: her record of the folder (as if a colleague's zip had been imported) and her subfolder
        with anna.ws.connect() as cx:
            for t in ("sync_written", "sync_folder_read", "sync_folder_docs"):
                cx.execute(f"DELETE FROM {t}")
        claimcheck.set_note(anna.ws, anna.h2, "after the loss")
    shutil.rmtree(_bundles(shared_dir, anna).parent)
    w = _round(anna)["wrote"]
    assert w["snapshot"]
    _round(ben)
    assert _note_here(ben, anna.h2) == "after the loss"


# --- a second look at the fixes ------------------------------------------------------------------------------------
def test_a_colleagues_edit_never_takes_the_text_out_of_the_writers_own_tasks(pair, shared_dir, tmp_path):
    from enlens_claims import ingest

    anna, ben = pair
    src = tmp_path / "local docs"
    src.mkdir()
    (src / "plant notes.txt").write_text("Notes on the plant, 2026\n\nElectrolysers in the valley create local jobs for "
                                         "welders. The zebrafish permit was discussed.")
    with anna:
        folder.set_keep_out(anna.ws, True)
        ingest.ingest(anna.ws, [src])
        doc = anna.ws.scalar("SELECT doc_id FROM documents WHERE path LIKE '%plant notes.txt'")
        access.set_documents(anna.ws, [doc], "local")
        hid = claimcheck.check_hypothesis(anna.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline",
                                          k=1, per_doc=1, doc_ids=[doc])
        sharing.share(anna.ws, [{"kind": "check", "key": hid}])
        with_text = anna.ws.scalar("SELECT COUNT(*) FROM tasks WHERE payload_json LIKE '%zebrafish%'")
    _round(anna)
    _round(ben)
    with ben:
        claimcheck.set_note(ben.ws, hid, "Ben's note")
    _round(ben)
    rep = _round(anna)["read"][0]["report"]
    # roles (H5, DESIGN-roles §4.9): Anna's own check is not replaced; Ben's version comes in beside it. Her own
    # tasks keep their text either way
    assert rep["checks"]["updated"] == 0 and len(rep["checks"]["clash"]) == 1
    with anna:
        assert anna.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (hid,)) is None
        assert anna.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (rep["checks"]["clash"][0]["hyp_id"],)) == \
            "Ben's note"
        assert anna.ws.scalar("SELECT COUNT(*) FROM tasks WHERE payload_json LIKE '%zebrafish%'") == with_text > 0


def test_the_bibliography_page_shows_works_whose_attachments_came_without_paths(pair, tmp_path):
    from enlens_claims import bibliography

    anna, _ben = pair
    with anna:
        with anna.ws.connect() as cx:
            cx.execute("INSERT INTO bib_items(item_key, item_type, title, files_json, seq) VALUES (?,?,?,?,?)",
                       ("K1", "report", "Smith 2021", sharing.without_paths(json.dumps(
                           [{"path": "/Users/x/a.pdf", "name": "a.pdf", "type": "application/pdf", "exists": True,
                             "size": 10}])), 1))
        anna.ws.set_meta("bibliography", {"kind": "file", "library": "x", "collection": None, "format": "ris"})
        assert json.loads(anna.ws.scalar("SELECT files_json FROM bib_items")) == [{"name": "a.pdf",
                                                                                    "type": "application/pdf"}]
        bibliography.view(anna.ws)  # no KeyError


def test_another_shared_folder_starts_the_record_afresh_and_passes_on_what_came_from_colleagues(pair, shared_dir,
                                                                                               tmp_path, monkeypatch):
    from enlens_claims.store import Workspace

    anna, ben = pair
    with ben:
        hb = _check(ben.ws, "Water stress limits hydrogen exports.")
        sharing.share(ben.ws, [{"kind": "check", "key": hb}])
    for p in (anna, ben, anna):
        _round(p)
    other = tmp_path / "new team folder"
    other.mkdir()
    _join(anna, other)  # Anna moves to another folder; Ben does not (yet)
    w = _round(anna)["wrote"]
    assert w["snapshot"] and hb in [i["key"] for i in w["items"]]  # what came from Ben goes too: he is not there
    dan = Person(tmp_path, "Dan", monkeypatch)
    with dan:
        dan.ws = Workspace.create(tmp_path / "dan")
        dan.ws.set_meta("project_uid", anna.ws.meta("project_uid"))
    _join(dan, other)
    _round(dan)
    with dan:
        assert dan.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hb,))


def test_a_local_change_is_never_taken_for_what_came_in(anna_and_ben, shared_dir):
    """Ben confirmed a work's document in his copy (from Anna's zip) before his first round, which reads first: his
    decision is his to write, though the row of that work and document came from Anna as well."""
    anna, ben = anna_and_ben
    with anna:
        doc = anna.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        anna.ws.set_meta("bibliography", {"kind": "file", "library": "x", "collection": None, "format": "ris"})
        with anna.ws.connect() as cx:
            cx.execute("INSERT INTO bib_items(item_key, item_type, title, seq) VALUES ('K1', 'report', 'Smith', 1)")
            cx.execute("INSERT INTO bib_links(item_key, doc_id, status, method) VALUES ('K1', ?, 'probable', 'title')",
                       (doc,))
    from enlens_claims import bundle as bundle_mod

    with ben:
        ben.ws = bundle_mod.import_project(anna.send(), shared_dir.parent / "ben-again")
        with ben.ws.connect() as cx:
            cx.execute("UPDATE bib_links SET status='confirmed' WHERE item_key='K1'")
    _join(anna, shared_dir)
    _join(ben, shared_dir)
    _round(anna)
    _round(ben)  # reads Anna's first, then writes
    _round(anna)
    with anna:
        assert anna.ws.scalar("SELECT status FROM bib_links WHERE item_key='K1'") == "confirmed"


def test_a_reader_never_takes_a_bundle_from_before_its_writer_started_afresh(started, shared_dir):
    anna, ben = started
    head = _bundles(shared_dir, anna).parent / "head.json"
    h = json.loads(head.read_text())
    _round(ben)
    with ben:  # Ben has read Anna's work of the epoch she had; the cloud brings her new head.json before her new bundles
        with ben.ws.connect() as cx:
            cx.execute("UPDATE sync_folder_read SET seq=? WHERE person_id=?", (h["last"] + 5, anna.id))
    head.write_text(json.dumps({**h, "epoch": "a-new-start"}))
    with ben:
        out = folder.sync_now(ben.ws)
    assert [(x["kind"], x["seq"]) for x in out["problems"]] == [("arriving", h["snapshot"])]
    assert _upto(ben, anna) == h["last"] + 5  # nothing taken from the old start


def test_project_json_without_an_id_keeps_this_copys_record(started, shared_dir):
    anna, ben = started
    team = next(shared_dir.glob("ENLENS-*"))
    pj = json.loads((team / "project.json").read_text())
    (team / "project.json").write_text(json.dumps({k: v for k, v in pj.items() if k != "folder_id"}))
    with anna:
        claimcheck.set_note(anna.ws, anna.h2, "a change")
    _round(anna)
    with anna:
        assert anna.ws.scalar("SELECT fp FROM sync_written WHERE kind='head'") == pj["folder_id"]

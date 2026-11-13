"""Shared projects after 0.17.0: what comes into a copy from a colleague's zip or from the shared folder, what the
shared folder keeps, and the cost of a round. 0.17.0 was the first version in which other people's data comes into a
copy by itself, so each defect found in the reviews is closed here with a test that failed before its fix."""
from __future__ import annotations

import json
import sqlite3
import threading
import zipfile
from pathlib import Path

import pytest

from enlens_claims import access, bundle, claimcheck, home, notes, ownership, people, researchlog, sharing, sync
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder
from owner_helpers import add_doc, level, sync as rounds
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_0_18_0_owner import shared_dir, team  # noqa: F401  (fixtures)
from test_0_18_0_shared_folder import pair, trio  # noqa: F401  (fixtures)


def _person(tmp: Path, name: str, mp, pid: str) -> Person:
    """A person whose id is chosen, so a test can put them before or after a colleague in the order of ids."""
    p = Person(tmp, name, mp)
    with p:
        home.update_settings({"person_id": pid})
        p.id = people.me()
    assert p.id == pid
    return p


def _round(p: Person) -> dict:
    with p:
        return folder.sync_now(p.ws)


def _forged(p: Person, tmp: Path, *statements: tuple[str, tuple]) -> Path:
    """`p`'s zip for a colleague, with its database changed by hand (any SQLite tool does this)."""
    f = p.send()
    work = tmp / f"forged-{f.stem}"
    work.mkdir()
    with zipfile.ZipFile(f) as zf:
        zf.extractall(work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    for sql, args in statements:
        cx.execute(sql, args)
    cx.commit()
    cx.close()
    out = tmp / f"forged-{f.stem}.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for x in sorted(work.rglob("*")):
            if x.is_file():
                zf.write(x, x.relative_to(work).as_posix())
    return out


# ---- A. privacy ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ben_id", ["p000000000001", "pfffffffffff1"])
def test_an_item_its_owner_took_back_never_reaches_a_newcomer_through_a_colleague_whatever_the_order_of_ids(
        loaded, tmp_path, monkeypatch, ben_id):
    anna = _person(tmp_path, "Anna", monkeypatch, "p888888888888")
    ben = _person(tmp_path, "Ben", monkeypatch, ben_id)
    carol = _person(tmp_path, "Carol", monkeypatch, "p777777777777")
    anna.ws = loaded
    shared = tmp_path / "team"
    shared.mkdir()
    with anna:
        z = tmp_path / "anna-shared.zip"
        bundle.export_project(anna.ws, z, scope="shared")
    with ben:
        ben.ws = bundle.import_project(z, tmp_path / "ben-project")
    with carol:
        carol.ws = bundle.import_project(z, tmp_path / "carol-project")  # from before the check
    with anna:
        h = claimcheck.check_hypothesis(anna.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline", k=2)
        sharing.share(anna.ws, [{"kind": "check", "key": h}])
        folder.set_folder(anna.ws, str(shared))
    _round(anna)
    with ben:
        folder.set_folder(ben.ws, str(shared))
    _round(ben)
    with ben:
        cid = ben.ws.scalar("SELECT claim_id FROM user_claims WHERE hyp_id=?", (h,))
        pid = ben.ws.scalar("SELECT passage_id FROM verifications WHERE subject_id=?", (cid,))
        claimcheck.set_judgement(ben.ws, cid, pid, "supports", "Ben agrees")
    _round(ben)  # Ben's subfolder holds the whole check, with his judgement
    with anna:
        sharing.unshare(anna.ws, [{"kind": "check", "key": h}])
    _round(anna)  # Anna's subfolder: only the mark that she took it back; Ben's app stays closed
    with carol:
        folder.set_folder(carol.ws, str(shared))
    _round(carol)
    with carol:
        assert carol.ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (h,)) is None
        assert sharing.state(carol.ws._conn(), "check", h)["state"] == "withdrawn"


def test_the_switch_takes_out_of_the_folder_a_restricted_document_this_copy_removed(loaded, tmp_path, monkeypatch):
    anna = Person(tmp_path, "Anna", monkeypatch)
    anna.ws = ws = loaded
    shared = tmp_path / "team"
    shared.mkdir()
    with anna:
        d = ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        with ws.connect() as cx:
            cx.execute("UPDATE documents SET ai_access='none' WHERE doc_id=?", (d,))
        folder.set_folder(ws, str(shared))
        folder.sync_now(ws)  # the switch is off: the reading of the No AI document goes into the folder
        mine = shared / folder.team_name(ws) / anna.id
        name = folder.reading_name(d, ws.scalar("SELECT text_fp FROM documents WHERE doc_id=?", (d,)))
        assert (mine / "docs" / name).is_file()
        ws.remove_document(d)
        folder.set_keep_out(ws, True)
        out = folder.sync_now(ws)
        assert out["wrote"]["taken_out"] == 1
        assert not (mine / "docs" / name).is_file()


def test_a_removed_document_that_an_ai_could_read_stays_in_the_folder_when_the_switch_comes_on(
        loaded, tmp_path, monkeypatch):
    anna = Person(tmp_path, "Anna", monkeypatch)
    anna.ws = ws = loaded
    shared = tmp_path / "team"
    shared.mkdir()
    with anna:
        d = ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        with ws.connect() as cx:
            cx.execute("UPDATE documents SET ai_access='cloud' WHERE doc_id=?", (d,))
        folder.set_folder(ws, str(shared))
        folder.sync_now(ws)
        ws.remove_document(d)
        folder.set_keep_out(ws, True)
        out = folder.sync_now(ws)
        assert out["wrote"]["taken_out"] == 0  # nothing to take out: no new start for every colleague


def _payload_docs(payload_json: str | None) -> set[str]:
    pids, dids = access.ids_in(json.loads(payload_json or "{}"))
    return set(dids) | {p.split(":", 1)[0] for p in pids}


def test_a_task_that_comes_in_says_what_this_copy_lets_an_ai_read_not_what_the_sender_let(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        h = claimcheck.check_hypothesis(anna.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline", k=3)
        cids = [r[0] for r in anna.ws.query("SELECT claim_id FROM user_claims WHERE hyp_id=?", (h,))]
        from enlens_claims.sync.fingerprints import check_tasks

        where, args = check_tasks(h, cids)
        sent = anna.ws.query(f"SELECT task_id, status, access, payload_json FROM tasks WHERE {where}", args)
    read = {t["task_id"]: _payload_docs(t["payload_json"]) for t in sent if t["status"] == "done"}
    docs = set().union(*read.values())
    assert docs and all((t["access"] or "cloud") == "cloud" for t in sent)
    with ben:
        access.set_documents(ben.ws, sorted(docs), setting="none")
    ben.bring_in(anna.send())
    with ben:
        got = {r["task_id"]: r["access"]
               for r in ben.ws.query(f"SELECT task_id, access FROM tasks WHERE {where}", args)}
    assert set(got) >= set(read)
    assert all(got[t] == "none" for t, d in read.items() if d)


def test_a_colleagues_bibliography_never_names_a_file_of_this_computer(anna_and_ben, tmp_path):
    from enlens_claims import bibliography

    anna, ben = anna_and_ben
    private = tmp_path / "ben-own" / "diary.txt"
    private.parent.mkdir()
    private.write_text("Ben's own private diary.", encoding="utf-8")
    files = json.dumps([{"name": "diary.txt", "path": str(private), "exists": True, "size": 24, "mtime": 1,
                         "content_type": "text/plain"}])
    forged = _forged(anna, tmp_path,
                     ("INSERT OR REPLACE INTO meta(key, value) VALUES ('bibliography', ?)",
                      (json.dumps({"kind": "file", "library": "x", "collection": None, "format": "ris"}),)),
                     ("INSERT INTO bib_items(item_key, item_type, title, files_json, seq) VALUES ('K1', 'report', "
                      "'A report', ?, 1)", (files,)))
    ben.bring_in(forged)
    with ben:
        stored = json.loads(ben.ws.scalar("SELECT files_json FROM bib_items WHERE item_key='K1'"))
        assert stored and all("path" not in f for f in stored)
        assert private not in bibliography.files_to_add(ben.ws)


def test_a_project_from_a_colleagues_zip_never_names_a_file_of_this_computer(anna_and_ben, tmp_path):
    from enlens_claims import bibliography

    anna, ben = anna_and_ben
    private = tmp_path / "ben-own" / "diary.txt"
    private.parent.mkdir()
    private.write_text("Ben's own private diary.", encoding="utf-8")
    files = json.dumps([{"name": "diary.txt", "path": str(private), "exists": True}])
    forged = _forged(anna, tmp_path, ("INSERT INTO bib_items(item_key, item_type, title, files_json, seq) VALUES "
                                      "('K2', 'report', 'A report', ?, 1)", (files,)))
    with ben:
        ws = bundle.import_project(forged, tmp_path / "ben-second-project")
        stored = json.loads(ws.scalar("SELECT files_json FROM bib_items WHERE item_key='K2'"))
        assert stored and all("path" not in f for f in stored)
        assert private not in bibliography.files_to_add(ws)


def test_the_last_look_before_writing_finds_every_row_of_an_item_that_is_not_shared(tmp_path):
    from enlens_claims.store import Workspace

    shared = [{"kind": "check", "key": "h1", "state": "shared"}, {"kind": "themes", "key": "r1", "state": "shared"}]

    def bundle_with(*statements: str) -> str | None:
        ws = Workspace.create(tmp_path / f"b{len(list(tmp_path.iterdir()))}")
        cx = sqlite3.connect(ws.db_path)
        cx.execute("INSERT INTO hypotheses(hyp_id, text) VALUES ('h1', 'shared')")
        cx.execute("INSERT INTO user_claims(claim_id, hyp_id, text) VALUES ('c1', 'h1', 'a part')")
        cx.execute("INSERT INTO theme_runs(run_id) VALUES ('r1')")
        for s in statements:
            cx.execute(s)
        cx.commit()
        try:
            return folder._leaks(cx, shared)
        finally:
            cx.close()

    assert bundle_with() is None
    assert bundle_with("INSERT INTO tasks(task_id, kind, status) VALUES ('check:c1:0', 'check', 'done')",
                       "INSERT INTO verifications(ver_id, subject_kind, subject_id, passage_id) VALUES "
                       "('v1', 'user_claim', 'c1', 'd1:0001')",
                       "INSERT INTO theme_members(run_id, theme_id, passage_id) VALUES ('r1', 0, 'd1:0001')") is None
    assert bundle_with("INSERT INTO user_claims(claim_id, hyp_id, text) VALUES ('c2', 'h2', 'private')")
    assert bundle_with("INSERT INTO verifications(ver_id, subject_kind, subject_id, passage_id) VALUES "
                       "('v2', 'user_claim', 'c9', 'd1:0001')")
    assert bundle_with("INSERT INTO tasks(task_id, kind, status) VALUES ('check:c9:0', 'check', 'done')")
    assert bundle_with("INSERT INTO tasks(task_id, kind, status) VALUES ('decompose:h2', 'decompose', 'done')")
    assert bundle_with("INSERT INTO tasks(task_id, kind, status) VALUES ('theme:r2:0', 'theme', 'done')")
    assert bundle_with("INSERT INTO theme_members(run_id, theme_id, passage_id) VALUES ('r2', 0, 'd1:0001')")


# ---- B. nothing in a colleague's file acts in this person's name ---------------------------------------------
def _a_passage(p: Person) -> tuple[str, int, int]:
    with p:
        doc = p.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        text = p.ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,))
    w = text.split()
    a = text.index(w[2])
    return doc, a, a + len(w[2])


def test_a_note_in_this_persons_name_does_not_come_in_from_a_colleagues_file(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    doc, a, z = _a_passage(anna)
    forged = _forged(anna, tmp_path, ("INSERT INTO notes(note_id, doc_id, start, end, quote, text, person_id, "
                                      "created_at, edited_at) VALUES ('n00000000000f0001', ?, ?, ?, 'x', "
                                      "'not Ben''s', ?, '2030-01-01', '2030-01-01')", (doc, a, z, ben.id)))
    got = ben.bring_in(forged)
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM notes WHERE note_id='n00000000000f0001'")
    assert got["notes"] == 0


def test_an_entry_of_the_research_log_in_this_persons_name_does_not_come_in(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    forged = _forged(anna, tmp_path, ("INSERT INTO research_log(entry_id, at, person_id, kind, text) VALUES "
                                      "('e00000000000f0001', '2030-01-01', ?, 'entry', 'Ben never wrote this')",
                                      (ben.id,)))
    ben.bring_in(forged)
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM research_log WHERE entry_id='e00000000000f0001'")


def test_a_colleagues_note_and_entry_still_come_in(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    doc, a, z = _a_passage(anna)
    with anna:
        n = notes.add(anna.ws, doc, a, z, text="Anna's note")
        e = researchlog.add(anna.ws, "Anna's entry")
        sharing.share(anna.ws, [{"kind": "note", "key": n["note_id"]}, {"kind": "log", "key": e["entry_id"]}])
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT person_id FROM notes WHERE note_id=?", (n["note_id"],)) == anna.id
        assert ben.ws.scalar("SELECT person_id FROM research_log WHERE entry_id=?", (e["entry_id"],)) == anna.id


def _canon_row(p: Person, doc: str) -> dict:
    with p:
        cx = p.ws._conn()
        cur = cx.execute("SELECT * FROM canon WHERE doc=? ORDER BY owner_seq DESC, n DESC LIMIT 1", (doc,))
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, cur.fetchone()))


def test_the_owners_copy_takes_no_record_of_the_documents_in_the_owners_name_from_a_colleague(team, tmp_path):
    anna, ben, carol = team
    doc = add_doc(anna, tmp_path, "interview", ai="local")
    rounds(anna, ben, carol)
    assert level(anna, doc) == level(carol, doc) == "local"
    r = _canon_row(carol, doc)
    assert r["by"] == anna.id
    n = 10 ** 6
    r.update(n=n, ai_n=n, ai_access="cloud", at="2030-01-01T00:00:00+00:00",
             ai_hist_json=json.dumps(json.loads(r["ai_hist_json"] or "[]") + [[n, "cloud"]]))
    cols = list(r)
    forged = _forged(carol, tmp_path, (f"INSERT OR REPLACE INTO canon({','.join(cols)}) VALUES "
                                       f"({','.join('?' * len(cols))})", tuple(r[c] for c in cols)))
    anna.bring_in(forged)
    with anna:
        assert not anna.ws.scalar("SELECT 1 FROM canon WHERE n=?", (n,))
        ownership.settle(anna.ws)
        # roles (DESIGN-roles §4.10): the refused row is recorded, and answered with her own row above it
        assert anna.ws.scalar("SELECT via FROM sync_refused WHERE kind='canon' AND key=?", (doc,)) == carol.id
        assert anna.ws.scalar("SELECT n FROM canon WHERE doc=? AND by=?", (doc, anna.id)) > n
    assert level(anna, doc) == "local"


def test_the_owners_copy_takes_no_hand_over_decision_or_proposal_in_the_owners_name(team, tmp_path):
    anna, ben, carol = team
    forged = _forged(carol, tmp_path,
                     ("INSERT INTO ownership(seq, owner, by, at, kind, after, why) VALUES (2, ?, ?, "
                      "'2030-01-01T00:00:00+00:00', 'handover', ?, NULL)", (carol.id, anna.id, anna.id)),
                     ("INSERT INTO proposals(id, kind, doc, title, by, at, detail_json) VALUES ('xforged1', 'remove', "
                      "'dnothing', 'x', ?, '2030-01-01', '{}')", (anna.id,)),
                     ("INSERT INTO decisions(proposal, by, owner_seq, verdict, reason, at, auto) VALUES "
                      "('xforged1', ?, 1, 'accept', NULL, '2030-01-01', 0)", (anna.id,)))
    anna.bring_in(forged)
    with anna:
        cx = anna.ws._conn()
        assert not cx.execute("SELECT 1 FROM ownership WHERE seq=2").fetchone()
        assert not cx.execute("SELECT 1 FROM proposals WHERE id='xforged1'").fetchone()
        # roles (DESIGN-roles §4.10): each refused row is recorded; the answer is replaced by one of hers that counts
        # for nothing (so third copies drop the forged one)
        assert not cx.execute("SELECT 1 FROM decisions WHERE proposal='xforged1' AND verdict IN ('accept', 'decline')"
                              ).fetchone()
        assert {r[0] for r in cx.execute("SELECT kind FROM sync_refused WHERE state='new'")} == \
            {"ownership", "proposals", "decisions"}
        assert ownership.owner(cx) == anna.id


def test_an_owner_who_has_not_come_to_the_shared_folder_yet_has_not_left_it(loaded, tmp_path, monkeypatch):
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    anna.ws = loaded
    with anna:
        z = tmp_path / "a.zip"
        bundle.export_project(anna.ws, z, scope="shared")
    shared = tmp_path / "team"
    shared.mkdir()
    with ben:
        ben.ws = bundle.import_project(z, tmp_path / "ben-project")
        folder.set_folder(ben.ws, str(shared))
        folder.sync_now(ben.ws)  # Ben is first in the folder; Anna has not chosen it yet
        with pytest.raises(ownership.NotAllowed):
            ownership.take_over(ben.ws)
        assert ownership.owner(ben.ws._conn()) == anna.id


def test_an_owner_whose_subfolder_this_copy_saw_and_that_is_gone_has_left(team, shared_dir):
    import shutil

    anna, ben, carol = team
    with ben:
        team_dir = shared_dir / folder.team_name(ben.ws)
    shutil.rmtree(team_dir / anna.id)
    with ben:
        assert ownership.owner_left(ben.ws, ben.ws._conn(), ownership.chain(ben.ws._conn()))


# ---- C. a broken or hostile sender ---------------------------------------------------------------------------
@pytest.fixture
def waiting(pair):
    """Anna and Ben in the folder after a round each; then Anna shares a new check: one bundle of hers waits for Ben."""
    anna, ben = pair
    _round(anna)
    _round(ben)
    with anna:
        anna.h = claimcheck.check_hypothesis(anna.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline",
                                             k=2)
        sharing.share(anna.ws, [{"kind": "check", "key": anna.h}])
    _round(anna)
    return anna, ben


def _count_opens(monkeypatch) -> dict[str, int]:
    """How often each member of a zip is unpacked (`ZipFile.open`, which `ZipFile.read` uses too)."""
    seen: dict[str, int] = {}
    real = zipfile.ZipFile.open

    def counted(self, name, *a, **k):
        n = name.filename if isinstance(name, zipfile.ZipInfo) else name
        seen[n] = seen.get(n, 0) + 1
        return real(self, name, *a, **k)

    monkeypatch.setattr(zipfile.ZipFile, "open", counted)
    return seen


def test_a_bundles_database_is_unpacked_once_per_round(waiting, monkeypatch):
    anna, ben = waiting
    opens = _count_opens(monkeypatch)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: pytest.fail("the whole zip was read once more"))
    out = _round(ben)
    assert [p["bundles"] for p in out["read"] if p["bundles"]]
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (anna.h,))
    assert opens.get("rows.sqlite") == 1


def test_a_bundle_larger_than_enlens_reads_waits_with_a_message_and_changes_nothing(waiting, monkeypatch):
    anna, ben = waiting
    monkeypatch.setattr(folder, "_MAX_ROWS", 1024, raising=False)
    with ben:
        out = folder.sync_now(ben.ws)
        assert not ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (anna.h,))
    got = [x for x in out["problems"] if x["kind"] == "too_large"]
    assert got and "larger than ENLENS reads" in got[0]["message"] and got[0]["person"]["id"] == anna.id
    monkeypatch.setattr(folder, "_MAX_ROWS", 4 * 1024 ** 3, raising=False)
    _round(ben)
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (anna.h,))


def test_a_bundle_whose_description_is_too_large_is_not_read_into_memory(waiting, monkeypatch):
    anna, ben = waiting
    monkeypatch.setattr(folder, "_MAX_META", 16, raising=False)
    getattr(folder, "_META_SEEN", {}).clear()  # (what an earlier test read stays out of it)
    opens = _count_opens(monkeypatch)
    with ben:
        out = folder.sync_now(ben.ws)
    assert "too_large" in [x["kind"] for x in out["problems"]]
    assert not opens.get("bundle.json")


def test_a_reading_larger_than_enlens_reads_waits_with_a_message(pair, tmp_path, monkeypatch):
    anna, ben = pair
    _round(anna)
    _round(ben)
    add_doc(anna, tmp_path, "interview")
    _round(anna)
    monkeypatch.setattr(folder, "_MAX_READING", 16, raising=False)
    with ben:
        out = folder.sync_now(ben.ws)
    assert "too_large" in [x["kind"] for x in out["problems"]]


def test_the_team_tab_looks_at_a_waiting_bundle_without_unpacking_it(waiting, monkeypatch):
    anna, ben = waiting
    getattr(folder, "_META_SEEN", {}).clear()  # (what an earlier test read stays out of it)
    opens = _count_opens(monkeypatch)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: pytest.fail("the whole bundle was unpacked"))
    with ben:
        for _ in range(3):
            st = folder.status(ben.ws)
    assert [p["waiting"] for p in st["people"] if p["id"] == anna.id] == [1]
    assert not opens.get("rows.sqlite") and opens.get("bundle.json") == 1


def test_a_bundle_that_goes_while_it_is_brought_in_is_a_gap_not_an_unreachable_folder(waiting, monkeypatch):
    from enlens_claims.gui import poller

    anna, ben = waiting

    def gone(*a, **k):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(folder, "_apply_bundle", gone)
    with ben:
        out = folder.sync_now(ben.ws)
    assert [x["kind"] for x in out["problems"]] == ["gap"]
    assert not poller.offline(out)


def test_a_round_whose_only_problem_is_one_colleagues_file_is_not_offline():
    from enlens_claims.gui import poller

    one = {"problems": [{"kind": "unreachable", "person": {"id": "p1"}, "message": "", "seq": None}]}
    folder_gone = {"problems": [{"kind": "unreachable", "person": None, "message": "", "seq": None}]}
    assert not poller.offline(one)
    assert poller.offline(folder_gone) and poller.offline({"problems": folder_gone["problems"] + one["problems"]})


def _zip_of(ws, tmp: Path, name: str, extra: dict[str, bytes]) -> Path:
    f = tmp / f"{name}.zip"
    bundle.export_project(ws, f)
    out = tmp / f"{name}-changed.zip"
    with zipfile.ZipFile(f) as src, zipfile.ZipFile(out, "w") as dst:
        for i in src.infolist():
            if i.filename not in extra:
                dst.writestr(i, src.read(i))
        for n, data in extra.items():
            dst.writestr(n, data)
    return out


def test_a_project_from_a_zip_keeps_only_the_settings_enlens_knows(loaded, tmp_path):
    from enlens_claims.store import DEFAULT_CONFIG

    cfg = {"thresholds": "high", "models": {"verify": 5, "split": "claude-fable-5-1", "extract": "x" * 500},
           "passages": {"max_chars": -3, "min_chars": 200}, "ai_access_default": "local", "evil": {"a": 1},
           "shared_folder_keep_out": True}
    z = _zip_of(loaded, tmp_path, "cfg", {"config.json": json.dumps(cfg).encode()})
    ws = bundle.import_project(z, tmp_path / "imported")
    kept = json.loads(ws.config_path.read_text(encoding="utf-8"))
    assert "evil" not in kept
    assert ws.config["thresholds"] == DEFAULT_CONFIG["thresholds"]
    assert ws.config["models"]["verify"] == DEFAULT_CONFIG["models"]["verify"]
    assert ws.config["models"]["extract"] == DEFAULT_CONFIG["models"]["extract"]
    assert ws.config["models"]["split"] == "claude-fable-5-1"
    assert ws.config["passages"] == DEFAULT_CONFIG["passages"]
    assert ws.config["ai_access_default"] == "local" and ws.config["shared_folder_keep_out"] is True


def test_a_project_from_a_zip_keeps_a_colleagues_sensible_thresholds(loaded, tmp_path):
    cfg = {"thresholds": {"support_confidence": 0.7, "verify_top_k": 8, "screen_min_score": "a lot"},
           "passages": {"max_chars": 1500, "min_chars": 300}}
    z = _zip_of(loaded, tmp_path, "cfg2", {"config.json": json.dumps(cfg).encode()})
    ws = bundle.import_project(z, tmp_path / "imported2")
    assert ws.config["thresholds"]["support_confidence"] == 0.7 and ws.config["thresholds"]["verify_top_k"] == 8
    assert ws.config["thresholds"]["screen_min_score"] == 2.0
    assert ws.config["passages"] == {"max_chars": 1500, "min_chars": 300}


def test_a_project_from_a_zip_leaves_its_cache_and_backups_behind(loaded, tmp_path):
    z = _zip_of(loaded, tmp_path, "cache", {"cache/terms.bin": b"x" * 1000, "backups/before-bringing-in.sqlite": b"y"})
    ws = bundle.import_project(z, tmp_path / "imported3")
    assert not (Path(ws.root) / "cache" / "terms.bin").exists()
    assert not (Path(ws.root) / "backups" / "before-bringing-in.sqlite").exists()


def test_codebook_events_at_the_same_moment_are_ordered_alike_in_every_copy():
    from enlens_claims.sync.codebook_merge import _event_order

    mine = [{"id": "b2", "at": "2026-11-12T10:00:00", "seq": 1, "op": "rename"}]
    theirs = [{"id": "a1", "at": "2026-11-12T10:00:00", "seq": 1, "op": "merge"},
              {"id": "c3", "at": "2026-11-12T10:00:00", "seq": "not a number", "op": "unmerge"}]
    assert [e["id"] for e in sorted(mine + theirs, key=_event_order)] == \
        [e["id"] for e in sorted(theirs + mine, key=_event_order)]


def test_choosing_the_same_shared_folder_again_keeps_what_this_copy_wrote_and_read(pair, shared_dir):
    anna, ben = pair
    for p in (anna, ben, anna, ben):
        _round(p)
    with ben:
        read_before = ben.ws.query("SELECT person_id, seq FROM sync_folder_read")
        folder.clear_folder(ben.ws)
        folder.set_folder(ben.ws, str(shared_dir))
        out = folder.sync_now(ben.ws)
        assert not out["problems"]
        assert [tuple(r) for r in ben.ws.query("SELECT person_id, seq FROM sync_folder_read")] == \
            [tuple(r) for r in read_before]
        assert not (out["wrote"] or {}).get("snapshot")


def test_two_backups_at_once_each_have_their_own_temporary_file(loaded):
    errors: list[BaseException] = []
    go = threading.Barrier(6)

    def one():
        try:
            go.wait()
            for _ in range(5):
                sync._backup(loaded)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=one) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, errors
    assert (Path(loaded.root) / "backups" / "before-bringing-in.sqlite").is_file()
    assert not list((Path(loaded.root) / "backups").glob("*.part"))


def test_a_round_makes_one_backup_however_many_colleagues_it_brings_in(trio, shared_dir, monkeypatch):
    anna, ben, carol = trio
    with carol:
        folder.set_folder(carol.ws, str(shared_dir))
    for p in (anna, ben, carol):
        _round(p)
    for p, text in ((anna, "Electrolysers create local jobs."), (ben, "Desalination is cheap.")):
        with p:
            h = claimcheck.check_hypothesis(p.ws, text, BaselineBackend(), "baseline", k=2)
            sharing.share(p.ws, [{"kind": "check", "key": h}])
        _round(p)
    made = []
    real = sync._backup
    monkeypatch.setattr(sync, "_backup", lambda ws: made.append(1) or real(ws))
    out = _round(carol)
    assert len([p for p in out["read"] if p["report"]]) == 2
    assert len(made) == 1


# ---- D. the cost of a round ------------------------------------------------------------------------------------
def test_a_round_finds_each_reading_in_one_listing_of_the_folder(pair, tmp_path, monkeypatch):
    anna, ben = pair
    _round(anna)
    _round(ben)
    for key in ("interview", "jobs", "grid"):
        add_doc(anna, tmp_path, key)
    _round(anna)
    looked = []
    real = folder._find
    monkeypatch.setattr(folder, "_find", lambda *a: looked.append(a) or real(*a))
    _round(ben)
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM documents") >= 3
    assert not looked


def test_an_original_that_changed_is_not_read_whole_again_every_round(pair, monkeypatch):
    from enlens_claims import ingest, sources

    anna, ben = pair
    with ben:  # (Ben's originals came in Anna's zip: they are in his project's folder)
        doc = ben.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        info = sources.original_file(ben.ws, doc, verify=False)
    assert info["inside"]
    f = Path(info["path"]).resolve()
    f.write_bytes(f.read_bytes() + b"\nchanged since")
    hashed = []
    real = ingest._sha1
    monkeypatch.setattr(ingest, "_sha1", lambda p: hashed.append(Path(p).resolve()) or real(p))
    _round(ben)
    _round(ben)
    assert hashed.count(f) == 1


def test_a_round_does_not_hold_the_projects_write_lock_while_it_works_in_the_folder(pair, monkeypatch):
    anna, ben = pair
    _round(anna)
    locked = []

    def probe(ws):
        cx = sqlite3.connect(ws.db_path, timeout=0)
        try:
            cx.execute("BEGIN IMMEDIATE")
            cx.execute("ROLLBACK")
        except sqlite3.OperationalError:
            locked.append(True)
        finally:
            cx.close()

    real_mend = folder._mend_readings

    def mend(*a, **k):
        probe(anna.ws)
        return real_mend(*a, **k)

    monkeypatch.setattr(folder, "_mend_readings", mend)
    real_begin = folder._begin_again

    def begin(*a, **k):
        probe(anna.ws)
        return real_begin(*a, **k)

    monkeypatch.setattr(folder, "_begin_again", begin)
    with anna:
        h = claimcheck.check_hypothesis(anna.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline", k=2)
        sharing.share(anna.ws, [{"kind": "check", "key": h}])
    _round(anna)
    with anna:
        sharing.unshare(anna.ws, [{"kind": "check", "key": h}])  # a new start: its bundles go from the folder
    _round(anna)
    assert not locked

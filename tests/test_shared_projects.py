"""0.14.0: shared projects. Each person keeps their own copy of a project and brings in a colleague's work as a file.

Two people are simulated with two ENLENS folders (each its own settings, so its own person id and name): Anna makes
the project and sends it, Ben imports it, both work, and each brings in the other's file.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from enlens_claims import bundle, claimcheck, people, profile, sync
from enlens_claims.llm import BaselineBackend
from enlens_claims.store import Workspace

CLAIM = "Green hydrogen production can increase water stress in arid regions."


class Person:
    """One person: their own ENLENS folder (settings, name, id) and their own copy of the project."""

    def __init__(self, tmp: Path, name: str, monkeypatch):
        self.name, self.home, self.mp = name, tmp / f"home-{name}", monkeypatch
        self.ws: Workspace | None = None
        self.files = tmp / f"sent-{name}"
        self.files.mkdir()
        self.n = 0
        with self:
            from enlens_claims import home

            home.update_settings({"your_name": name})
            self.id = people.me()

    def __enter__(self):
        self.mp.setenv("ENLENS_HOME", str(self.home))
        return self

    def __exit__(self, *exc):
        return False

    def send(self) -> Path:
        with self:
            self.n += 1
            out = self.files / f"{self.name}-{self.n}.zip"
            bundle.export_project(self.ws, out)
            return out

    def bring_in(self, f: Path, **kw) -> dict:
        with self:
            return sync.bring_in(self.ws, f, **kw)


@pytest.fixture
def anna_and_ben(loaded, tmp_path, monkeypatch):
    """Anna's project (the loaded corpus, one check); Ben's copy, imported from Anna's first file."""
    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    anna.ws = loaded
    with anna:
        anna.hid = claimcheck.check_hypothesis(loaded, CLAIM, BaselineBackend(), "baseline", k=3)
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
    return anna, ben


def _excerpts(ws: Workspace, hid: str) -> list[dict]:
    res = claimcheck.hypothesis_result(ws, hid)
    return [p for part in res["parts"] for p in part["passages"]]


def _claim(ws: Workspace, hid: str) -> str:
    return ws.scalar("SELECT claim_id FROM user_claims WHERE hyp_id=?", (hid,))


def test_the_file_says_which_project_and_who_sent_it(anna_and_ben):
    anna, ben = anna_and_ben
    f = anna.send()
    info = sync.peek(f)
    assert info["from"] == {"id": anna.id, "name": "Anna"}
    assert info["project_uid"] == anna.ws.meta("project_uid") == ben.ws.meta("project_uid")
    assert anna.id != ben.id


def test_a_colleagues_check_and_judgements_come_in_under_their_name(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        hid2 = claimcheck.check_hypothesis(anna.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline", k=2)
        ex = _excerpts(anna.ws, anna.hid)[0]
        claimcheck.set_judgement(anna.ws, _claim(anna.ws, anna.hid), ex["passage_id"], "refutes", note="not arid")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["new"] == 1 and rep["judgements"] >= 1
    assert any("1 new result" in line for line in rep["lines"])
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid2,))
        got = {p["passage_id"]: p for p in _excerpts(ben.ws, anna.hid)}[ex["passage_id"]]
        assert got["user_verdict"] == "refutes" and got["judged_by"] == "Anna"
        # Ben judges the same excerpt himself: his counts in his copy, Anna's is kept beside it
        claimcheck.set_judgement(ben.ws, _claim(ben.ws, anna.hid), ex["passage_id"], "supports")
        got = {p["passage_id"]: p for p in _excerpts(ben.ws, anna.hid)}[ex["passage_id"]]
        assert got["user_verdict"] == "supports" and got["judged_by"] == "you"
        assert [(o["name"], o["verdict"]) for o in got["others"]] == [("Anna", "refutes")]
        agree = people.agreement(ben.ws)
        assert agree[0]["name"] == "Anna" and agree[0]["both"] == 1 and agree[0]["agreed"] == 0
        # how often *you* agreed with the AI counts only your own judgements
        cal = claimcheck.calibration(ben.ws)
        assert cal["total"] <= 1
        # removing his own judgement: Anna's counts again
        claimcheck.set_judgement(ben.ws, _claim(ben.ws, anna.hid), ex["passage_id"], None)
        got = {p["passage_id"]: p for p in _excerpts(ben.ws, anna.hid)}[ex["passage_id"]]
        assert got["user_verdict"] == "refutes" and got["judged_by"] == "Anna"


def test_bringing_in_the_same_file_twice_changes_nothing(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "seen by Anna")
    f = anna.send()
    ben.bring_in(f)
    with ben:
        counts = ben.ws.counts()
    rep = ben.bring_in(f)
    with ben:
        assert ben.ws.counts() == counts
    assert rep["lines"] == ["Nothing new: this copy already has everything in Anna's file."]


def test_a_check_changed_on_one_side_is_brought_up_to_date(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (anna.hid,)) == "Anna's note"
        # and the other way round: Ben's later note is newer than Anna's unchanged check. Roles (H5, DESIGN-roles
        # §4.9): it is Anna's own check, so Ben's version comes in beside hers (a sync clash), never in its place
        claimcheck.set_note(ben.ws, anna.hid, "Ben's note")
    rep = anna.bring_in(ben.send())
    assert rep["checks"]["updated"] == 0 and len(rep["checks"]["clash"]) == 1
    with anna:
        assert anna.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (anna.hid,)) == "Anna's note"
        assert anna.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (rep["checks"]["clash"][0]["hyp_id"],)) == \
            "Ben's note"


def test_a_check_both_changed_comes_in_as_a_sync_clash_copy(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    with ben:
        claimcheck.set_note(ben.ws, anna.hid, "Ben's note")
    f = anna.send()
    rep = ben.bring_in(f)
    assert len(rep["checks"]["clash"]) == 1
    copy_id = rep["checks"]["clash"][0]["hyp_id"]
    assert any("Sync clash" in line for line in rep["lines"])
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (anna.hid,)) == "Ben's note"
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (copy_id,)) == "Anna's note"
        assert sync.copies_of(ben.ws, "check")[copy_id] == {"of": anna.hid, "name": "Anna", "at": rep["at"]}
        res = claimcheck.hypothesis_result(ben.ws, copy_id)  # the copy is a whole check of its own
        assert res["parts"] and res["parts"][0]["passages"]
    # bringing the same file in again makes no second copy
    rep = ben.bring_in(f)
    assert not rep["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM hypotheses") == 2
    # Anna brings in Ben's work: both copies end up with the same two versions
    anna.bring_in(ben.send())
    with anna:
        notes = sorted(r[0] for r in anna.ws.query("SELECT note FROM hypotheses"))
    with ben:
        assert notes == sorted(r[0] for r in ben.ws.query("SELECT note FROM hypotheses")) == ["Anna's note", "Ben's note"]


def test_the_same_file_read_into_other_text_comes_in_as_a_copy_of_its_own(anna_and_ben):
    anna, ben = anna_and_ben
    with ben:  # Ben's ENLENS read the paper differently (another version, text recognition on or off)
        doc = ben.ws.scalar("SELECT doc_id FROM documents WHERE title LIKE 'Water footprint%'")
        with ben.ws.connect() as cx:
            cx.execute("UPDATE documents SET text = text || ' (read again)', text_fp=NULL WHERE doc_id=?", (doc,))
    with anna:
        hid = claimcheck.check_hypothesis(anna.ws, "Electrolysis needs a lot of water.", BaselineBackend(), "baseline", k=4)
        read = {p["doc_id"] for p in _excerpts(anna.ws, hid)}
    rep = ben.bring_in(anna.send())
    assert [c["title"] for c in rep["documents"]["clash"]] == [anna.ws.scalar("SELECT title FROM documents WHERE doc_id=?", (doc,))]
    copy = rep["documents"]["clash"][0]["doc_id"]
    assert copy.startswith(doc + "-")
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=?", (copy,)) > 0
        assert sync.copies_of(ben.ws, "document")[copy]["of"] == doc
        assert doc in read  # Anna's check points at her reading of the paper: in Ben's copy, at the copy
        got = {p["doc_id"] for p in _excerpts(ben.ws, hid)}
        assert copy in got and doc not in got
        # the copy's passages and the original's do not mix
        assert ben.ws.scalar("SELECT COUNT(*) FROM passages WHERE passage_id LIKE ?", (copy + ":%",)) == \
            ben.ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=?", (copy,))
    # again: nothing new
    rep = ben.bring_in(anna.send())
    assert not rep["documents"]["clash"] and not rep["documents"]["new"]


def test_the_stricter_ai_setting_wins_with_a_warning(anna_and_ben):
    from enlens_claims import access

    anna, ben = anna_and_ben
    with ben:
        docs = [r[0] for r in ben.ws.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    d1, d2 = docs[0], docs[1]
    with anna:
        access.set_documents(anna.ws, [d1], "cloud")
        access.set_documents(anna.ws, [d2], "local")
        with anna.ws.connect() as cx:  # Claude read part of d1 in Anna's copy
            cx.execute("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) VALUES (?,?,?,?,?,?)",
                       (f"{d1}:0001", d1, "claude_code", "t1", "2026-11-06T10:00:00+00:00", "check"))
    with ben:
        access.set_documents(ben.ws, [d1], "none")
        access.set_documents(ben.ws, [d2], "cloud")
    rep = ben.bring_in(anna.send())
    with ben:
        lv = access.levels(ben.ws, [d1, d2], budget=False)
    assert lv == {d1: "none", d2: "local"}
    why = {a["doc_id"]: a["why"] for a in rep["ai_access"]}
    assert why == {d1: "yours", d2: "theirs"}
    assert any("is now kept from Claude" in line for line in rep["lines"])
    assert any("let Claude read" in line for line in rep["lines"])


def test_a_document_removed_here_does_not_come_back(anna_and_ben):
    anna, ben = anna_and_ben
    with ben:
        doc = ben.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        title = ben.ws.scalar("SELECT title FROM documents WHERE doc_id=?", (doc,))
        ben.ws.remove_document(doc)
        v = ben.ws.corpus_version()
    rep = ben.bring_in(anna.send())
    assert rep["documents"]["removed_here"] == [title] and not rep["documents"]["new"]
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))
        assert ben.ws.corpus_version() == v  # nothing came in, nothing to rebuild
    # Anna learns that Ben removed it; it stays in her copy
    rep = anna.bring_in(ben.send())
    assert rep["documents"]["removed_there"] == [title]
    with anna:
        assert anna.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))


def test_new_documents_come_with_their_files_and_step_the_corpus_on(anna_and_ben, tmp_path):
    from enlens_claims import ingest, sources

    anna, ben = anna_and_ben
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "colleague_report.txt").write_text("Desalination for electrolysis adds cost but removes water stress. " * 20)
    with anna:
        ingest.ingest(anna.ws, [extra])
    with ben:
        v = ben.ws.corpus_version()
    rep = ben.bring_in(anna.send())
    assert len(rep["documents"]["new"]) == 1
    with ben:
        assert ben.ws.corpus_version() > v
        row = ben.ws.query("SELECT doc_id, path FROM documents WHERE path LIKE '%colleague_report.txt'")[0]
        assert Path(row["path"]).is_file() and Path(row["path"]).is_relative_to(ben.ws.root.resolve())
        info = sources.original_file(ben.ws, row["doc_id"])
        assert info["available"]


def test_a_file_from_another_project_is_brought_in_only_on_purpose(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    other = Person(tmp_path, "Cleo", ben.mp)
    other.ws = Workspace.create(tmp_path / "cleo-project")  # a project of her own
    f = other.send()
    with pytest.raises(sync.NotThisProject) as e:
        ben.bring_in(f)
    assert "Cleo" in str(e.value)
    rep = ben.bring_in(f, anyway=True)
    assert rep["from"]["name"] == "Cleo"
    with ben:  # the next file from Cleo is known
        assert other.ws.meta("project_uid") in ben.ws.meta("project_uids_known")
    ben.bring_in(other.send())


def test_judgements_from_before_014_are_yours_when_sent(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        ex = _excerpts(anna.ws, anna.hid)[0]
        cid = _claim(anna.ws, anna.hid)
        with anna.ws.connect() as cx:  # a judgement written by 0.13 (no person, no row in judgements)
            cx.execute("UPDATE verifications SET user_verdict='supports', user_at='2026-11-01T10:00:00+00:00' WHERE "
                       "subject_id=? AND passage_id=?", (cid, ex["passage_id"]))
    ben.bring_in(anna.send())
    with anna:
        assert anna.ws.scalar("SELECT person_id FROM judgements WHERE claim_id=? AND passage_id=?",
                              (cid, ex["passage_id"])) == anna.id
    with ben:
        got = {p["passage_id"]: p for p in _excerpts(ben.ws, anna.hid)}[ex["passage_id"]]
        assert got["judged_by"] == "Anna"


def test_label_reviews_are_per_person_and_yours_count(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        lid = profile.add_label(anna.ws, "sdg", pid, "6.4")
        profile.set_label(anna.ws, lid, "reject")
    rep = ben.bring_in(anna.send())
    assert rep["labels"] >= 1 and rep["reviews"] >= 1
    with ben:
        assert profile._decisions(ben.ws)[lid]["decision"] == "reject"
        profile.set_label(ben.ws, lid, "accept")
        assert profile._decisions(ben.ws)[lid]["decision"] == "accept"
    rep = ben.bring_in(anna.send())  # Anna's reject again: Ben's accept still counts in his copy
    with ben:
        assert profile._decisions(ben.ws)[lid]["decision"] == "accept"
        # "clear" removes his own verdict only: Anna's counts again
        profile.set_label(ben.ws, lid, "clear")
        assert profile._decisions(ben.ws)[lid]["decision"] == "reject"


def test_a_copy_before_the_merge_is_kept(anna_and_ben):
    anna, ben = anna_and_ben
    ben.bring_in(anna.send())
    assert (ben.ws.root / "backups" / "before-bringing-in.sqlite").is_file()


def test_a_removed_check_does_not_come_back(anna_and_ben):
    anna, ben = anna_and_ben
    with ben:
        claimcheck.delete_hypothesis(ben.ws, anna.hid)
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["removed_here"] == [CLAIM] and not rep["checks"]["new"]
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (anna.hid,))


def test_the_app_brings_a_colleagues_work_in(anna_and_ben):
    import threading

    from test_app import Api

    from enlens_claims.gui.server import make_server

    anna, ben = anna_and_ben
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    f = anna.send()
    with ben:
        from enlens_claims import home

        shutil.copytree(ben.ws.root, home.home() / "projects" / "Shared")
        srv, app = make_server("127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            api = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
            st, r = api("POST", "/api/projects/Shared/bring-in", raw=f.read_bytes())
            assert st == 200, r
            assert r["report"]["from"]["name"] == "Anna" and r["report"]["lines"]
            st, t = api("GET", "/api/projects/Shared/together")
            assert st == 200 and t["history"][0]["from"]["name"] == "Anna" and t["people"][0]["name"] == "Anna"
            assert t["me"]["name"] == "Ben"
            # a file of another project: the app asks first (409), then brings it in on purpose
            other = Person(f.parent.parent, "Cleo", ben.mp)
            other.ws = Workspace.create(f.parent.parent / "cleo-project")
            g = other.send()
            ben.__enter__()
            st, r = api("POST", "/api/projects/Shared/bring-in", raw=g.read_bytes())
            assert st == 409 and r["not_this_project"]["from"]["name"] == "Cleo"
            st, r = api("POST", "/api/projects/Shared/bring-in?anyway=1", raw=g.read_bytes())
            assert st == 200
        finally:
            srv.shutdown()
            srv.server_close()


def test_a_withdrawn_number_is_not_this_release():
    from enlens_claims import __version__, update

    # 0.14.1: this release is not a withdrawn number either (the test no longer pins 0.14.0 as the version);
    # 0.15: a withdrawn number may be released for real (gui/launcher.is_older), so only 0.14.0 is checked
    assert "0.14.0" not in update.WITHDRAWN


def test_agreement_between_two_people_and_cohens_kappa(ws):
    """You and a colleague judged the same excerpts: how often alike, and Cohen's kappa from 10 excerpts on."""
    me = people.me()
    with ws.connect() as cx:
        people.remember(cx, "p0123456789ab", "Anna")
        mine = ["supports"] * 6 + ["refutes"] * 4
        theirs = ["supports"] * 5 + ["refutes"] * 5
        for i, (a, b) in enumerate(zip(mine, theirs)):
            people.record(cx, "u1", f"d1:{i:04d}", me, a, None, "2026-11-06T10:00:00+00:00")
            people.record(cx, "u1", f"d1:{i:04d}", "p0123456789ab", b, None, "2026-11-06T11:00:00+00:00")
    a = people.agreement(ws)[0]
    assert (a["name"], a["both"], a["agreed"], a["rate"]) == ("Anna", 10, 9, 0.9)
    # po 0.9; pe = 0.6*0.5 + 0.4*0.5 = 0.5; kappa = 0.4/0.5
    assert a["kappa"] == 0.8
    with ws.connect() as cx:
        cx.execute("DELETE FROM judgements WHERE passage_id='d1:0009'")
    assert people.agreement(ws)[0]["kappa"] is None  # 9 in common: too few to say


def test_the_command_line_brings_a_colleagues_work_in(anna_and_ben, capsys):
    from enlens_claims import cli

    anna, ben = anna_and_ben
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    f = anna.send()
    with ben:
        assert cli.main(["--ws", str(ben.ws.root), "bring-in", str(f)]) == 0
    assert "From Anna" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------
# found in review (0.14.0): each case that went wrong in the first version
# ---------------------------------------------------------------------------------------------
def _crafted(f: Path, tmp: Path, sql: list[tuple]) -> Path:
    """A copy of the project zip `f` with its database changed by `sql` (what a crafted file could hold)."""
    import sqlite3
    import zipfile

    work = tmp / "crafted"
    work.mkdir()
    with zipfile.ZipFile(f) as zf:
        zf.extractall(work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    with cx:
        for q, args in sql:
            cx.execute(q, args)
    cx.close()
    out = tmp / "crafted.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for p in sorted(work.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(work).as_posix())
    return out


def test_a_crafted_file_cannot_read_or_write_files_elsewhere(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    secret = tmp_path / "secret.txt"
    secret.write_text("not for colleagues")
    cols = "(doc_id, path, sha1, title, kind, n_chars, text, text_fp)"
    f = _crafted(anna.send(), tmp_path, [
        (f"INSERT INTO documents{cols} VALUES (?,?,?,?,?,?,?,?)",
         (str(tmp_path / "planted"), str(secret), "s1", "evil one", "text", 5, "hello", "f1")),
        (f"INSERT INTO documents{cols} VALUES (?,?,?,?,?,?,?,?)",
         ("d0000000001", str(secret), "s2", "evil two", "text", 5, "hello", "f2"))])
    ben.bring_in(f)
    assert not (tmp_path / "planted").exists()
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM documents WHERE title='evil one'")
        assert ben.ws.scalar("SELECT path FROM documents WHERE doc_id='d0000000001'") is None  # its text, not the file
    assert not list((ben.ws.root / "originals").rglob("secret.txt")) if (ben.ws.root / "originals").exists() else True


def test_another_reading_of_a_file_you_keep_from_ai_is_kept_from_ai_too(anna_and_ben):
    from enlens_claims import access

    anna, ben = anna_and_ben
    with ben:
        doc = ben.ws.scalar("SELECT doc_id FROM documents WHERE title LIKE 'Water footprint%'")
        access.set_documents(ben.ws, [doc], "none")
        with ben.ws.connect() as cx:
            cx.execute("UPDATE documents SET text = text || ' (read again)', text_fp=NULL WHERE doc_id=?", (doc,))
    rep = ben.bring_in(anna.send())
    copy = rep["documents"]["clash"][0]["doc_id"]
    with ben:
        assert access.levels(ben.ws, [copy], budget=False)[copy] == "none"
    assert [a["why"] for a in rep["ai_access"] if a["doc_id"] == copy] == ["yours"]


def test_a_judgement_taken_back_does_not_come_back(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        ex = _excerpts(anna.ws, anna.hid)[0]
        claimcheck.set_judgement(anna.ws, _claim(anna.ws, anna.hid), ex["passage_id"], "refutes")
    ben.bring_in(anna.send())
    with anna:  # Anna takes hers back, then brings in Ben's file, which still holds it
        claimcheck.set_judgement(anna.ws, _claim(anna.ws, anna.hid), ex["passage_id"], None)
    anna.bring_in(ben.send())
    with anna:
        got = {p["passage_id"]: p for p in _excerpts(anna.ws, anna.hid)}[ex["passage_id"]]
        assert got["user_verdict"] is None and not got["others"]
    ben.bring_in(anna.send())  # and it goes from Ben's copy too
    with ben:
        got = {p["passage_id"]: p for p in _excerpts(ben.ws, anna.hid)}[ex["passage_id"]]
        assert got["user_verdict"] is None


def test_a_review_taken_back_does_not_come_back(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        lid = profile.add_label(anna.ws, "sdg", pid, "6.4")
        profile.set_label(anna.ws, lid, "reject")
    ben.bring_in(anna.send())
    with anna:
        profile.set_label(anna.ws, lid, "clear")
    anna.bring_in(ben.send())
    with anna:
        assert lid not in profile._decisions(anna.ws)
    ben.bring_in(anna.send())
    with ben:
        assert lid not in profile._decisions(ben.ws)


def test_after_a_clash_each_keeps_their_own_version_and_a_copy_is_brought_up_to_date(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna 1")
    with ben:
        claimcheck.set_note(ben.ws, anna.hid, "Ben 1")
    ben.bring_in(anna.send())
    rep = anna.bring_in(ben.send())
    assert len(rep["checks"]["clash"]) == 1 and not rep["checks"]["updated"]
    note = lambda p, h: p.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (h,))  # noqa: E731
    with anna:
        assert note(anna, anna.hid) == "Anna 1"  # hers stays hers
        marks = sync.copies_of(anna.ws, "check")
        assert [(m["of"], m["name"]) for m in marks.values()] == [(anna.hid, "Ben")]
    with ben:
        assert note(ben, anna.hid) == "Ben 1"
        assert [m["name"] for m in sync.copies_of(ben.ws, "check").values()] == ["Anna"]
    # files going back and forth: nothing new
    assert not ben.bring_in(anna.send())["checks"]["clash"]
    assert not anna.bring_in(ben.send())["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM hypotheses") == 2
    # Anna goes on with hers: Ben's copy of her version is brought up to date, not copied again
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna 2")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM hypotheses") == 2
        copy = next(iter(sync.copies_of(ben.ws, "check")))
        assert note(ben, copy) == "Anna 2" and note(ben, anna.hid) == "Ben 1"
    # a judgement Anna makes on her version reaches Ben's copy of it
    with anna:
        ex = _excerpts(anna.ws, anna.hid)[0]
        claimcheck.set_judgement(anna.ws, _claim(anna.ws, anna.hid), ex["passage_id"], "refutes")
    ben.bring_in(anna.send())
    with ben:
        got = {p["passage_id"]: p for p in _excerpts(ben.ws, copy)}[ex["passage_id"]]
        assert got["judged_by"] == "Anna" and got["user_verdict"] == "refutes"
        assert not {p["passage_id"]: p for p in _excerpts(ben.ws, anna.hid)}[ex["passage_id"]]["user_verdict"]


def test_a_codebook_both_changed_is_kept_twice_and_labels_are_not_doubled(anna_and_ben):
    from enlens_claims import frameworks

    anna, ben = anna_and_ben
    with anna:
        frameworks.save(anna.ws, "mycb", "code,description\nA,Water use of electrolysis\nB,Jobs\n")
        pid = anna.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        profile.add_label(anna.ws, "mycb", pid, "A")
    with ben:
        frameworks.save(ben.ws, "mycb", "code,description\nA,Water\nB,Jobs and training\n")
    f = anna.send()
    rep = ben.bring_in(f)
    assert [c["of"] for c in rep["codebooks"]["clash"]] == ["mycb"]
    copy = rep["codebooks"]["clash"][0]["name"]
    ben.bring_in(f)
    with ben:
        labels = [tuple(r) for r in ben.ws.query("SELECT framework, code FROM labels WHERE source='person'")]
        assert labels == [(copy, "A")]
        assert "Anna's version" in frameworks.get(copy, ben.ws).title
        assert len(frameworks.get("mycb", ben.ws).codes["A"].description) == len("Water")


def test_an_excerpt_id_is_made_again_the_way_the_app_makes_it(anna_and_ben):
    from enlens_claims.tasks import _h

    anna, ben = anna_and_ben
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    with ben:
        claimcheck.set_note(ben.ws, anna.hid, "Ben's note")
    copy = ben.bring_in(anna.send())["checks"]["clash"][0]["hyp_id"]
    with ben:
        unit = sync._check_unit(ben.ws._conn(), copy)
        tids = [t["task_id"] for t in unit["tasks"]]
        assert unit["verifications"] and all(any(v["ver_id"] == f"v{_h(t, v['passage_id'])}" for t in tids)
                                             for v in unit["verifications"])


def test_another_reading_of_a_file_still_opens_its_original(anna_and_ben):
    from enlens_claims import sources

    anna, ben = anna_and_ben
    with ben:
        doc = ben.ws.scalar("SELECT doc_id FROM documents WHERE title LIKE 'Water footprint%'")
        with ben.ws.connect() as cx:
            cx.execute("UPDATE documents SET text = text || ' (read again)', text_fp=NULL WHERE doc_id=?", (doc,))
    copy = ben.bring_in(anna.send())["documents"]["clash"][0]["doc_id"]
    with ben:
        assert sources.original_file(ben.ws, copy)["available"]


def test_starting_over_notes_theme_runs_as_removed(ws):
    with ws.connect() as cx:
        cx.execute("INSERT INTO theme_runs(run_id, mode, k, created_at) VALUES ('r1', 'words', 5, '2026-11-06')")
    ws.reset_corpus()
    assert ws.scalar("SELECT 1 FROM sync_removed WHERE kind='themes' AND key='r1'")


# ---------------------------------------------------------------------------------------------
# found in the second review (0.14.0)
# ---------------------------------------------------------------------------------------------
def test_a_crafted_text_fingerprint_cannot_place_a_file(anna_and_ben, tmp_path):
    """The id of another reading of a file is made of the fingerprint of its text: worked out here, never taken
    from the file (a crafted one could otherwise name a path and replace the project's config.json)."""
    anna, ben = anna_and_ben
    with ben:
        doc = ben.ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
        config = (ben.ws.root / "config.json").read_text()
    f = _crafted(anna.send(), tmp_path, [
        ("UPDATE documents SET text = text || ' changed', text_fp='/../..abcdef' WHERE doc_id=?", (doc,))])
    rep = ben.bring_in(f)
    assert (ben.ws.root / "config.json").read_text() == config
    copies = [c["doc_id"] for c in rep["documents"]["clash"]]
    assert copies and all(sync.DOC_ID.fullmatch(c) for c in copies)


def test_keeping_a_colleagues_version_settles_a_clash(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna 1")
    with ben:
        claimcheck.set_note(ben.ws, anna.hid, "Ben 1")
    copy = ben.bring_in(anna.send())["checks"]["clash"][0]["hyp_id"]
    anna.bring_in(ben.send())
    with ben:  # Ben keeps Anna's version: he deletes his own
        claimcheck.delete_hypothesis(ben.ws, anna.hid)
        assert sync.copies_of(ben.ws, "check") == {}  # settled: no sync clash shown any more
    with anna:
        claimcheck.set_note(anna.ws, anna.hid, "Anna 2")
    rep = ben.bring_in(anna.send())
    assert rep["checks"]["updated"] == 1 and not rep["checks"]["clash"]
    with ben:
        notes = {r[0]: r[1] for r in ben.ws.query("SELECT hyp_id, note FROM hypotheses")}
    assert notes == {copy: "Anna 2"}  # his removed version did not come back, and hers followed hers


def test_a_review_taken_back_goes_also_where_its_label_has_another_id(anna_and_ben):
    from enlens_claims import frameworks

    anna, ben = anna_and_ben
    with anna:
        frameworks.save(anna.ws, "mycb", "code,description\nA,Water use of electrolysis\n")
        pid = anna.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        lid = profile.add_label(anna.ws, "mycb", pid, "A")
        profile.set_label(anna.ws, lid, "reject")
    with ben:
        frameworks.save(ben.ws, "mycb", "code,description\nA,Water\n")
    rep = ben.bring_in(anna.send())
    copy = rep["codebooks"]["clash"][0]["name"]
    with ben:
        theirs = ben.ws.scalar("SELECT label_id FROM labels WHERE framework=?", (copy,))
        assert profile._decisions(ben.ws)[theirs]["decision"] == "reject"
    with anna:
        profile.set_label(anna.ws, lid, "clear")
    ben.bring_in(anna.send())
    with ben:
        assert theirs not in profile._decisions(ben.ws)


def test_a_check_that_read_a_document_removed_on_one_side_is_not_churned(anna_and_ben):
    anna, ben = anna_and_ben
    with ben:
        doc = ben.ws.scalar("SELECT doc_id FROM verifications WHERE subject_kind='user_claim' LIMIT 1")
        ben.ws.remove_document(doc)
    rep = anna.bring_in(ben.send())
    assert rep["checks"]["updated"] == 0 and rep["checks"]["same"] >= 1
    rep = anna.bring_in(ben.send())
    assert rep["checks"]["updated"] == 0

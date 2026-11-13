"""0.18.0: the shared folder is a cloud folder (sync/folder.py).

A cloud service delivers files late, in any order, half-written for a while, twice under another name (a conflict
copy), or not at all; a network drive is not always connected. A copy reads only names that are exactly its own, stops
one colleague's stream where a bundle is missing or still arriving and goes on next round, and changes nothing in the
project until a merge, which reads only a scratch copy, runs in one transaction.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, claimcheck, sharing
from enlens_claims.sync import folder, formats
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_0_18_0_shared_folder import _check, _join, _round, pair, shared_dir, trio  # noqa: F401  (fixtures)


def _bundles(shared_dir: Path, p: Person) -> Path:
    return next(shared_dir.glob("ENLENS-*")) / p.id / "bundles"


def _note_round(p: Person, hid: str, note: str) -> int:
    with p:
        claimcheck.set_note(p.ws, hid, note)
    return _round(p)["wrote"]["seq"]


def _problems(out: dict) -> list[tuple[str, int | None]]:
    return [(x["kind"], x["seq"]) for x in out["problems"]]


@pytest.fixture
def started(pair):
    """Anna shared a check; both have had a round."""
    anna, ben = pair
    with anna:
        anna.h2 = _check(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": anna.h2}])
    _round(anna)
    _round(ben)
    return anna, ben


def _note_here(p: Person, hid: str) -> str | None:
    with p:
        return p.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (hid,))


def _upto(p: Person, other: Person) -> int:
    with p:
        return p.ws.scalar("SELECT seq FROM sync_folder_read WHERE person_id=?", (other.id,)) or 0


def test_a_bundle_still_arriving_is_tried_again_next_round(started, shared_dir):
    anna, ben = started
    seq = _note_round(anna, anna.h2, "second")
    f = _bundles(shared_dir, anna) / f"{seq:06d}.zip"
    whole = f.read_bytes()
    f.write_bytes(whole[:len(whole) // 2])  # the cloud service has brought half of it so far
    with ben:
        out = folder.sync_now(ben.ws)
    assert _problems(out) == [("arriving", seq)] and "may still be arriving" in out["problems"][0]["message"]
    assert _note_here(ben, anna.h2) is None and _upto(ben, anna) == seq - 1
    f.write_bytes(whole)
    _round(ben)
    assert _note_here(ben, anna.h2) == "second" and _upto(ben, anna) == seq


def test_a_head_before_its_bundle_and_a_bundle_before_its_head(started, shared_dir):
    anna, ben = started
    seq = _note_round(anna, anna.h2, "second")
    f = _bundles(shared_dir, anna) / f"{seq:06d}.zip"
    away = f.with_name("elsewhere")
    f.rename(away)  # head.json says it is there; the cloud has not brought it yet
    with ben:
        out = folder.sync_now(ben.ws)
        st = folder.status(ben.ws)
    assert _problems(out) == [("gap", seq)] and _note_here(ben, anna.h2) is None
    assert [(x["kind"], x["person"]["name"]) for x in st["problems"]] == [("gap", "Anna")]
    assert st["people"][0]["waiting"] == 1
    away.rename(f)
    _round(ben)
    assert _note_here(ben, anna.h2) == "second"
    # the other way round: the bundle is there, its head.json not yet: it waits for the next round, unread
    head = f.parent.parent / "head.json"
    before = head.read_text(encoding="utf-8")
    seq = _note_round(anna, anna.h2, "third")
    head.write_text(before, encoding="utf-8")
    assert not _problems(_round(ben)) and _note_here(ben, anna.h2) == "second"
    head.write_text(json.dumps({"last": seq, "snapshot": 1, **formats.stamp(needs=2)}), encoding="utf-8")
    _round(ben)
    assert _note_here(ben, anna.h2) == "third"


def test_a_missing_middle_bundle_stops_the_stream_there(started, shared_dir):
    anna, ben = started
    s1 = _note_round(anna, anna.h2, "one")
    with anna:
        h3 = _check(anna.ws, "Water stress limits hydrogen exports.")
        sharing.share(anna.ws, [{"kind": "check", "key": h3}])
    s2 = _round(anna)["wrote"]["seq"]
    s3 = _note_round(anna, anna.h2, "three")
    assert (s1 + 1, s2 + 1) == (s2, s3)
    gone = _bundles(shared_dir, anna) / f"{s2:06d}.zip"
    data = gone.read_bytes()
    gone.unlink()
    with ben:
        out = folder.sync_now(ben.ws)
    assert _problems(out) == [("gap", s2)]
    assert _note_here(ben, anna.h2) == "one" and _upto(ben, anna) == s1  # what came before the gap came in
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h3,))
    gone.write_bytes(data)
    _round(ben)
    assert _note_here(ben, anna.h2) == "three" and _upto(ben, anna) == s3
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h3,))


def test_conflict_copies_and_half_written_files_are_never_read(started, shared_dir):
    anna, ben = started
    seq = _note_round(anna, anna.h2, "second")
    team = next(shared_dir.glob("ENLENS-*"))
    b = _bundles(shared_dir, anna)
    (b / f"{seq:06d} (1).zip").write_bytes(b"not a zip")             # OneDrive and Dropbox name conflicts so
    (b / f"{seq + 1:06d}.zip.part").write_bytes(b"half")             # a writer's file not finished
    (b / f"{seq:06d}-DESKTOP-4F2K.zip").write_bytes(b"not a zip")
    (team / anna.id / "head (1).json").write_text('{"last": 99}')
    (team / f"{anna.id} (Ben's conflicted copy)").mkdir()
    (team / "p0000000000ab (1)").mkdir()
    out = _round(ben)
    assert not out["problems"] and _note_here(ben, anna.h2) == "second" and _upto(ben, anna) == seq
    with ben:
        assert {p["id"] for p in folder.status(ben.ws)["people"]} == {anna.id}


def test_names_in_the_folder_are_short_and_never_differ_only_in_letter_case(trio, shared_dir):
    anna, ben, carol = trio
    _join(carol, shared_dir)
    for p in (anna, ben, carol, anna):
        _round(p)
    names = [f.relative_to(shared_dir).as_posix() for f in shared_dir.rglob("*")]
    assert names and max(len(n) for n in names) <= 90
    assert len({n.lower() for n in names}) == len(names)
    team = next(shared_dir.glob("ENLENS-*")).name
    assert all(n == team or n.split("/", 1)[1] == n.split("/", 1)[1].lower() for n in names)  # all lower case inside
    assert not [n for n in names if n.endswith(".part")]


def test_a_folder_path_with_spaces_and_accents(pair, shared_dir):
    anna, ben = pair
    with anna:
        assert json.loads(anna.ws.config_path.read_text(encoding="utf-8"))["shared_folder"] == str(shared_dir.resolve())
        assert folder.status(anna.ws)["folder"] == str(shared_dir.resolve())
        # the project's own folder in it, chosen by mistake, stands for the folder that holds it
        _round(anna)
        team = next(shared_dir.glob("ENLENS-*"))
        assert folder.check_folder(anna.ws, str(team)) == shared_dir.resolve()
        assert folder.check_folder(anna.ws, str(shared_dir) + "/") == shared_dir.resolve()
        for bad, words in ((str(anna.ws.root / "exports"), "inside this project"), ("relative/path", "whole path"),
                           (str(shared_dir / "nowhere"), "no folder"), ("", "Choose")):
            with pytest.raises(folder.FolderProblem, match=words):
                folder.check_folder(anna.ws, bad)
    _round(ben)
    assert _round(anna)["wrote"]["seq"] is None


def _dump(ws) -> dict[str, list]:
    cx = sqlite3.connect(ws.db_path)
    try:
        return {t: sorted(map(repr, cx.execute(f"SELECT * FROM {t}").fetchall()))
                for (t,) in cx.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        cx.close()


def test_a_folder_that_disappears_in_the_middle_of_a_round_changes_nothing(started, shared_dir, tmp_path):
    anna, ben = started
    with anna:
        h3 = _check(anna.ws, "Water stress limits hydrogen exports.")
        sharing.share(anna.ws, [{"kind": "check", "key": h3}])
    _round(anna)
    moved = tmp_path / "unplugged"

    def unplug(step, message, info):
        if step == "read" and shared_dir.exists():
            shared_dir.rename(moved)  # the network drive goes away while Ben's round reads Anna's work

    before = _dump(ben.ws)
    with ben:
        out = folder.read(ben.ws, progress=unplug)
    assert [x["kind"] for x in out["problems"]] == ["unreachable"]
    assert _dump(ben.ws) == before  # not a row changed
    moved.rename(shared_dir)
    _round(ben)
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h3,))
    # and while writing: nothing recorded as written, nothing half there; the next round writes it whole
    with anna:
        claimcheck.set_note(anna.ws, h3, "written later")

    def unplug_writing(step, message, info):
        if message == "Writing what you shared" and shared_dir.exists():
            shared_dir.rename(moved)

    with anna:
        written = anna.ws.query("SELECT * FROM sync_written")
        out = folder.sync_now(anna.ws, progress=unplug_writing)
        assert [x["kind"] for x in out["problems"]] == ["unreachable"]
        assert [tuple(r) for r in anna.ws.query("SELECT * FROM sync_written")] == [tuple(r) for r in written]
    moved.rename(shared_dir)
    seq = _round(anna)["wrote"]["seq"]
    assert seq and json.loads((_bundles(shared_dir, anna).parent / "head.json").read_text())["last"] == seq
    _round(ben)
    assert _note_here(ben, h3) == "written later"


def test_a_big_corpus_is_not_copied_every_round(started, shared_dir, tmp_path, monkeypatch):
    from enlens_claims import ingest

    anna, ben = started
    docs_before = {f.name for f in shared_dir.rglob("docs/*")}
    files_before = {f.name for f in shared_dir.rglob("files/*")}
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "one more.txt").write_text("Hydrogen storage in salt caverns near the coast. " * 30)
    with anna:
        ingest.ingest(anna.ws, [extra])
    w = _round(anna)["wrote"]
    assert (w["readings"], w["files"]) == (1, 1)
    assert len({f.name for f in shared_dir.rglob("docs/*")} - docs_before) == 1
    assert len({f.name for f in shared_dir.rglob("files/*")} - files_before) == 1
    fetched = []
    real = folder._put_reading
    monkeypatch.setattr(folder, "_put_reading", lambda *a: fetched.append(a[3]["doc_id"]) or real(*a))
    _round(ben)
    assert len(fetched) == 1  # only the new document's reading is read from the folder
    w = _round(ben)["wrote"]
    assert (w["readings"], w["files"]) == (0, 0)  # and nobody stores it a second time
    # every reading and every file is in the folder once
    names = [f.name for f in shared_dir.rglob("docs/*")] + [f.name for f in shared_dir.rglob("files/*")]
    assert len(names) == len(set(names))


def test_a_newer_format_stops_one_colleague_while_the_others_go_on(trio, shared_dir, monkeypatch):
    anna, ben, carol = trio
    _join(carol, shared_dir)
    _round(carol)
    with carol:
        hc = _check(carol.ws, "Carol's check on grid capacity.")
        sharing.share(carol.ws, [{"kind": "check", "key": hc}])
    monkeypatch.setattr(folder, "NEEDS", 9)  # Carol updated to an ENLENS that shares in a way this one does not know
    _round(carol)
    monkeypatch.setattr(folder, "NEEDS", 2)
    with anna:
        ha = _check(anna.ws, "Anna's check on water.")
        sharing.share(anna.ws, [{"kind": "check", "key": ha}])
        folder.sync_now(anna.ws)
    with ben:
        out = folder.sync_now(ben.ws)
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (ha,))
        assert not ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hc,))
    newer = [x for x in out["problems"] if x["kind"] == "newer_format"]
    assert [x["person"]["name"] for x in newer] == ["Carol"] and "Update ENLENS" in newer[0]["message"]


def test_a_bundle_that_is_not_what_its_name_says_is_left_aside(started, shared_dir):
    anna, ben = started
    seq = _note_round(anna, anna.h2, "second")
    b = _bundles(shared_dir, anna)
    real = (b / f"{seq:06d}.zip").read_bytes()
    shutil.copyfile(b / f"{seq - 1:06d}.zip", b / f"{seq:06d}.zip")  # its number inside says otherwise
    with ben:
        out = folder.sync_now(ben.ws)
    assert _problems(out) == [("damaged", seq)] and _note_here(ben, anna.h2) is None
    (b / f"{seq:06d}.zip").write_bytes(real)
    _round(ben)
    assert _note_here(ben, anna.h2) == "second"


def test_a_writer_whose_subfolder_was_emptied_starts_afresh_without_reusing_a_number(started, shared_dir, tmp_path,
                                                                                    monkeypatch):
    from enlens_claims.store import Workspace

    anna, ben = started
    s = _note_round(anna, anna.h2, "before")
    _round(ben)
    mine = _bundles(shared_dir, anna).parent
    shutil.rmtree(mine)  # someone tidied the shared folder
    w = _round(anna)["wrote"]
    assert w["seq"] == s + 1 and w["snapshot"]  # the next number, holding everything she shares
    head = json.loads((mine / "head.json").read_text())
    assert head == {**head, "last": s + 1, "snapshot": s + 1}
    out = _round(ben)  # Ben, who read up to s, goes on at s + 1
    assert not out["problems"] and _upto(ben, anna) == s + 1
    dan = Person(tmp_path, "Dan", monkeypatch)  # someone new starts at the snapshot
    with dan:
        dan.ws = Workspace.create(tmp_path / "dan")
        dan.ws.set_meta("project_uid", anna.ws.meta("project_uid"))
    _join(dan, shared_dir)
    out = _round(dan)
    assert not [x for x in out["problems"] if x["person"] and x["person"]["id"] == anna.id]
    with dan:
        assert dan.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (anna.h2,)) == "before"


def test_another_folder_starts_the_record_afresh(started, tmp_path):
    anna, ben = started
    other = tmp_path / "another team folder"
    other.mkdir()
    for p in (anna, ben):
        _join(p, other)
    w = _round(anna)["wrote"]
    assert w["snapshot"] and w["items"]  # everything she shares, written again in the new folder
    out = _round(ben)
    assert out["read"][0]["bundles"] == [w["seq"], w["seq"]]


def test_a_zip_never_carries_the_folder_and_a_colleagues_copy_starts_without_its_record(started, tmp_path,
                                                                                       monkeypatch):
    anna, ben = started
    f = anna.send()
    with zipfile.ZipFile(f) as zf:
        assert "shared_folder" not in json.loads(zf.read("config.json"))
    carol = Person(tmp_path, "Carol", monkeypatch)
    with carol:
        ws = bundle.import_project(f, tmp_path / "carol")
        assert ws.config.get("shared_folder") is None
        for t in ("sync_written", "sync_folder_read", "sync_folder_docs"):
            assert not ws.scalar(f"SELECT COUNT(*) FROM {t}"), t
    with anna:  # Anna herself, moving to another computer, keeps her record (she chooses the folder there again)
        moved = bundle.import_project(f, tmp_path / "anna-moved")
        assert moved.config.get("shared_folder") is None
        assert moved.scalar("SELECT seq FROM sync_written WHERE kind='head'") == \
            anna.ws.scalar("SELECT seq FROM sync_written WHERE kind='head'")


def test_many_rows_of_the_projects_ai_work_arrive_whole(started):
    """A bundle's rows are read a slice at a time when it is written (a large corpus's AI work is never held in memory
    at once): every one arrives, once."""
    anna, ben = started
    with anna:
        pids = anna.ws.query("SELECT passage_id, doc_id FROM passages ORDER BY passage_id")
        with anna.ws.connect() as cx:
            cx.executemany("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) VALUES "
                           "(?,?,?,?,?,?)", [(pids[i % len(pids)][0], pids[i % len(pids)][1], "claude_code", None,
                                              f"2026-11-11T02:{i // 60 % 60:02d}:{i % 60:02d}.{i:06d}+00:00", "check")
                                             for i in range(4500)])
    with ben:
        before = ben.ws.scalar("SELECT COUNT(*) FROM ai_sent")
    assert _round(anna)["wrote"]["rows"] >= 4500
    _round(ben)
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM ai_sent") == before + 4500
    assert _round(ben)["wrote"]["rows"] == 0  # what came in is not written back

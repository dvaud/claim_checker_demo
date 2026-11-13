"""0.18.0 stage 5: a round of the shared folder that is stopped part-way (sync/folder.py `should_stop`).

The person stops a round, or quits the app, while it runs: it ends between two steps. What came in from a colleague is
in the project and recorded as read; a colleague not reached yet, or one whose work was being put together, is left as
it was; nothing is recorded as written before its bundle is whole in the folder. The next round carries on, and the
copies end as they would have without the stop.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from enlens_claims import claimcheck, ingest, sharing
from enlens_claims.gui import api_folder, poller
from enlens_claims.gui.api_common import Jobs
from enlens_claims.sync import folder
from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_0_18_0_shared_folder import _check, _join, _round, pair, shared_dir, trio  # noqa: F401  (fixtures)


def _dump(ws) -> dict[str, list]:
    cx = sqlite3.connect(ws.db_path)
    try:
        return {t: sorted(map(repr, cx.execute(f"SELECT * FROM {t}").fetchall()))
                for (t,) in cx.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        cx.close()


def _read_from(p: Person) -> dict[str, int]:
    with p:
        return {r[0]: r[1] for r in p.ws.query("SELECT person_id, seq FROM sync_folder_read")}


def _written(p: Person) -> list[tuple]:
    with p:
        return sorted(tuple(r) for r in p.ws.query("SELECT kind, key, fp, seq FROM sync_written"))


def _has(p: Person, hid: str) -> bool:
    with p:
        return bool(p.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,)))


def _mine(shared_dir: Path, p: Person) -> Path:
    return next(shared_dir.glob("ENLENS-*")) / p.id


def _shared_check(p: Person, text: str) -> str:
    with p:
        hid = _check(p.ws, text)
        sharing.share(p.ws, [{"kind": "check", "key": hid}])
    return hid


@pytest.fixture
def three(trio, shared_dir):
    """Anna and Carol each shared a check and wrote it to the folder; Ben has not had a round yet."""
    anna, ben, carol = trio
    _join(carol, shared_dir)
    anna.h = _shared_check(anna, "Electrolysers create local jobs.")
    carol.h = _shared_check(carol, "Hydrogen valleys need water permits.")
    _round(anna)
    _round(carol)
    return anna, ben, carol


def test_a_round_stopped_between_two_colleagues_keeps_the_first_and_the_next_round_brings_the_second(three, shared_dir):
    anna, ben, carol = three
    ben.h = _shared_check(ben, "Ben's own shared check.")
    with ben:
        out = folder.sync_now(ben.ws, should_stop=lambda: len(_read_from(ben)) >= 1)  # stop once one came in
    assert out["stopped"] and out["problems"] == [] and out["wrote"] is None
    read = _read_from(ben)
    assert len(read) == 1
    first, second = (anna, carol) if anna.id in read else (carol, anna)
    assert _has(ben, first.h) and not _has(ben, second.h)             # what came in is in, and recorded as read
    assert [e["id"] for e in out["read"] if e["report"]] == [first.id]
    assert not [r for r in _written(ben) if r[0] != "head" and r[3] is not None]  # nothing of his written
    assert not (_mine(shared_dir, ben) / "head.json").exists()        # and no bundle in the folder
    # the next round carries on: the second colleague's check comes in, and Ben's shared check goes out
    out = _round(ben)
    assert not out["stopped"] and _has(ben, second.h) and set(_read_from(ben)) == {anna.id, carol.id}
    assert [e["id"] for e in out["read"] if e["report"]] == [second.id]
    assert out["wrote"]["seq"] == 1 and out["wrote"]["snapshot"]
    _round(anna)
    assert _has(anna, ben.h)


def test_a_round_stopped_while_a_colleagues_work_is_put_together_changes_nothing(three, shared_dir):
    anna, ben, carol = three
    _round(ben)
    anna.h2 = _shared_check(anna, "Desalination raises the cost of hydrogen.")
    with anna:
        claimcheck.set_note(anna.ws, anna.h, "changed")
    _round(anna)
    read_before, written_before = _read_from(ben), _written(ben)
    with ben:
        before = _dump(ben.ws)
    seen: list[str] = []

    def progress(step, message, info):
        seen.append(message)

    with ben:  # stop once Anna's bundle is in the scratch copy, before it is merged
        out = folder.sync_now(ben.ws, progress, should_stop=lambda: any("Reading Anna" in m for m in seen))
        after = _dump(ben.ws)
    assert out["stopped"] and out["problems"] == [] and out["wrote"] is None
    assert after == before and _read_from(ben) == read_before and _written(ben) == written_before
    assert not (_mine(shared_dir, ben) / "waiting.json").exists()
    out = _round(ben)
    assert _has(ben, anna.h2) and _read_from(ben)[anna.id] > read_before[anna.id]
    with ben:
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (anna.h,)) == "changed"


def test_a_round_stopped_while_writing_records_nothing_and_the_next_writes_it_whole(three, shared_dir, tmp_path):
    anna, ben, carol = three
    _round(ben)
    head = json.loads((_mine(shared_dir, ben) / "head.json").read_text())
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "ben field notes.txt").write_text("Field notes on water permits for electrolysers in dry regions. " * 20)
    with ben:
        ingest.ingest(ben.ws, [extra])
        doc = ben.ws.scalar("SELECT doc_id FROM documents WHERE path LIKE '%ben field notes.txt'")
    ben.h = _shared_check(ben, "Water permits slow electrolyser projects.")
    written_before = _written(ben)
    seen: list[str] = []

    def progress(step, message, info):
        seen.append(message)

    with ben:  # stop once the document's reading is in the folder, before its file and the bundle
        out = folder.sync_now(ben.ws, progress, should_stop=lambda: any(m.startswith("Writing document") for m in seen))
    assert out["stopped"] and out["problems"] == [] and out["wrote"] is None
    assert _written(ben) == written_before                                   # nothing recorded as written
    assert json.loads((_mine(shared_dir, ben) / "head.json").read_text()) == head  # no new bundle named
    assert len(list((_mine(shared_dir, ben) / "docs").iterdir())) == 1       # the reading written stays there
    assert not list((_mine(shared_dir, ben) / "files").iterdir())
    w = _round(ben)["wrote"]
    assert w["seq"] == head["last"] + 1 and w["readings"] == 0 and w["files"] == 1
    assert any(it["key"] == ben.h for it in w["items"])
    _round(anna)
    assert _has(anna, ben.h)
    with anna:
        assert anna.ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc,))
    again = _round(ben)["wrote"]
    assert again["readings"] == 0 and again["files"] == 0 and not again["items"]  # nothing written twice


def _until(cond, timeout=20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


@pytest.mark.parametrize("which", [api_folder._round, poller._round], ids=["sync-now", "poller"])
def test_a_round_job_cancelled_part_way_ends_as_cancelled_and_the_next_one_completes(three, shared_dir, monkeypatch,
                                                                                     which):
    anna, ben, carol = three
    jobs = Jobs()
    real = folder._say

    def say(progress, step, message, info=None):
        real(progress, step, message, info)
        if step == "read" and job_box:
            jobs.cancel(job_box[0])  # the person presses Stop (or quits) while the first colleague's work is read

    job_box: list = []
    monkeypatch.setattr(folder, "_say", say)
    with ben:
        job = jobs.start(folder.JOB, poller.TITLE, "P", lambda j: (job_box.append(j), which(ben.ws, j))[1],
                         uses_model=False, unique=True)
        assert _until(lambda: job.state in ("done", "error", "cancelled"))
    assert job.state == "cancelled" and job.error is None and job.result is None
    assert _read_from(ben) == {} and not _has(ben, anna.h) and not _has(ben, carol.h)
    monkeypatch.setattr(folder, "_say", real)
    out = _round(ben)
    assert _has(ben, anna.h) and _has(ben, carol.h) and out["wrote"]["seq"] == 1


# --- offline: the Team tab keeps who holds the switch on ----------------------------------------------------------
def test_offline_the_status_keeps_the_colleagues_who_keep_documents_out_as_last_known(three, shared_dir, tmp_path):
    anna, ben, carol = three
    with anna:
        folder.set_keep_out(anna.ws, True)
    _round(anna)
    _round(ben)
    with ben:
        live = folder.status(ben.ws)["keep_out"]
    assert live == {"mine": False, "colleagues": ["Anna"], "in_force": True}  # (no "last_known" while it is read)
    away = tmp_path / "unplugged"
    shared_dir.rename(away)  # the network drive is not connected
    with ben:
        st = folder.status(ben.ws)
        out = folder.sync_now(ben.ws)
    assert st["reachable"] is False and [x["kind"] for x in st["problems"]] == ["unreachable"]
    assert st["keep_out"] == {"mine": False, "colleagues": ["Anna"], "in_force": True, "last_known": True}
    assert [x["kind"] for x in out["problems"]] == ["unreachable"]
    with ben:
        assert folder.status(ben.ws)["keep_out"]["colleagues"] == ["Anna"]  # a round that failed forgets nothing
    away.rename(shared_dir)
    # Anna turns it off: the next round sees it, and offline the status says so too
    with anna:
        folder.set_keep_out(anna.ws, False)
    _round(anna)
    _round(ben)
    shared_dir.rename(away)
    with ben:
        assert folder.status(ben.ws)["keep_out"] == {"mine": False, "colleagues": [], "in_force": False,
                                                     "last_known": True}
    away.rename(shared_dir)


def test_a_colleague_who_left_is_not_kept_as_last_known(three, shared_dir, tmp_path):
    import shutil

    anna, ben, carol = three
    for p in (anna, carol):
        with p:
            folder.set_keep_out(p.ws, True)
        _round(p)
    _round(ben)
    with ben:
        assert sorted(folder.status(ben.ws)["keep_out"]["colleagues"]) == ["Anna", "Carol"]
    shutil.rmtree(_mine(shared_dir, carol))  # Carol left the team, and her subfolder with her
    _round(ben)
    away = tmp_path / "unplugged"
    shared_dir.rename(away)
    with ben:
        assert folder.status(ben.ws)["keep_out"]["colleagues"] == ["Anna"]
    away.rename(shared_dir)


def test_without_a_folder_no_colleague_is_named(three, shared_dir):
    anna, ben, carol = three
    with anna:
        folder.set_keep_out(anna.ws, True)
    _round(anna)
    _round(ben)
    with ben:
        folder.clear_folder(ben.ws)
        assert folder.status(ben.ws)["keep_out"] == {"mine": False, "colleagues": [], "in_force": False}

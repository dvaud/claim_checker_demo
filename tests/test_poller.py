"""0.18 (roadmap L3): near-live, and light. Each copy looks in a project's shared folder every couple of minutes by
itself (gui/poller.py): a round soon after the app starts, then every `sync_every_minutes`, and soon after a change made
through the app; paused per project or for the whole app; nothing for a project without a shared folder; one round per
project at a time and never beside adding documents or the new reader; offline backs off 2 → 4 → 8 → 16 → 30 minutes
and comes back after a round that reaches the folder; rounds that find nothing back off to four intervals (2026-11-12)
and come back at once with a change, a round that found something or a round by hand; what came in is kept until the
person marks it seen; it stops with the app. The clock is the test's: nothing waits real minutes.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from enlens_claims.gui.poller import Poller, things
from enlens_claims.sync import folder

from test_shared_projects import anna_and_ben  # noqa: F401  (fixture)
from test_shared_folder import pair, shared_dir  # noqa: F401  (fixtures)
from test_app import Api, home  # noqa: F401  (fixtures)


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _until(cond, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _report(problems=(), came=None) -> dict:
    """What folder.sync_now returns, with one colleague's merge when `came` is a merge report."""
    return {"at": "2026-11-11T10:00:00+00:00", "folder": "/x", "wrote": {"seq": None}, "files": 0,
            "read": [{"id": "pabc", "name": "Anna", "bundles": [1, 1], "report": came}] if came else [],
            "problems": list(problems)}


UNREACHABLE = {"kind": "unreachable", "person": None, "seq": None, "message": "The shared folder cannot be reached."}


class FakeRounds:
    """Stands in for folder.sync_now: records each round, answers what the test says, can be held back."""

    def __init__(self):
        self.calls, self.answer, self.hold = [], _report(), None
        self.began = threading.Event()

    def __call__(self, ws, progress=None, should_stop=None):
        self.calls.append(ws.root.name)
        self.began.set()
        if self.hold is not None:
            assert self.hold.wait(20)
        return self.answer() if callable(self.answer) else self.answer


@pytest.fixture
def setup(home, tmp_path, monkeypatch):  # noqa: F811
    """An app (no server, no thread) whose poller runs on the test's clock, a project P with a shared folder and a
    project Q without one, and folder.sync_now replaced by FakeRounds."""
    from enlens_claims.gui.server import App

    app = App()
    app.jobs.ended.clear()  # the app's own poller listens on the real clock: this one takes its place
    clock = Clock()
    app.poller = Poller(app, clock=clock, start_delay=15, debounce=20, max_backoff=1800)
    for n in ("P", "Q"):
        home.create_project(n)
    shared = tmp_path / "shared"
    shared.mkdir()
    folder.set_folder(home.open_project("P"), str(shared))
    rounds = FakeRounds()
    monkeypatch.setattr(folder, "sync_now", rounds)
    return app, app.poller, clock, rounds


def _step(poller, clock, at=None):
    """One look at clock time `at` (seconds after the poller was made); waits for the rounds it started to end."""
    if at is not None:
        clock.t = poller.born + at
    started = poller.step()
    for j in started:
        assert _until(lambda: j.state in ("done", "error", "cancelled")), j.state
        assert _until(lambda: poller.projects[j.project].round is None)
    return started


def _rounds(app, project="P"):
    return [j for j in app.jobs.all() if j.kind == folder.JOB and j.project == project]


def test_a_round_soon_after_start_then_every_interval(setup, home):  # noqa: F811
    app, poller, clock, rounds = setup
    assert _step(poller, clock, 0) == [] and _step(poller, clock, 14) == []
    st = poller.state("P")
    assert st["state"] == "waiting" and st["next_round_in"] == 1 and st["every_seconds"] == 120
    first = _step(poller, clock, 15)
    assert len(first) == 1 and first[0].background and first[0].view()["background"] is True
    assert rounds.calls == ["P"]                                        # never Q, which has no shared folder
    assert _step(poller, clock, 15 + 119) == []
    assert len(_step(poller, clock, 15 + 120)) == 1 and rounds.calls == ["P", "P"]
    home.update_settings({"sync_every_minutes": 5})                    # the interval is the setting's, read each look
    assert poller.state("P")["every_seconds"] == 300
    assert _step(poller, clock, 135 + 299) == []
    assert len(_step(poller, clock, 135 + 300)) == 1
    last = poller.state("P")["last_round"]
    assert last["background"] is True and last["state"] == "done" and last["offline"] is False and last["came_in"] == 0


def test_no_round_without_a_shared_folder(setup):
    app, poller, clock, rounds = setup
    for at in (15, 200, 5000):
        assert [j.project for j in _step(poller, clock, at)] == ["P"]
    assert rounds.calls == ["P", "P", "P"] and not _rounds(app, "Q")
    st = poller.state("Q")
    assert st["folder"] is False and st["state"] == "off" and st["next_round_at"] is None
    assert [p["project"] for p in poller.overview()["projects"]] == ["P"]


def test_pause_per_project_and_for_the_whole_app(setup, home):  # noqa: F811
    app, poller, clock, rounds = setup
    poller.set_paused("P", True)
    assert home.load_settings()["sync_paused_projects"] == ["P"]
    assert _step(poller, clock, 500) == [] and rounds.calls == []
    st = poller.state("P")
    assert st["state"] == "paused" and st["paused"] is True and st["next_round_at"] is None
    poller.set_paused("P", False)                                      # resumed: the round it missed, now
    assert poller.state("P")["next_round_in"] == 0 and len(_step(poller, clock, 500)) == 1
    poller.set_paused("P", True)
    poller.set_paused("P", False)                                      # resumed between rounds: one soon
    assert poller.state("P")["next_round_in"] == 20
    assert _step(poller, clock, 519) == [] and len(_step(poller, clock, 520)) == 1
    poller.set_paused(None, True)
    assert home.load_settings()["sync_paused"] is True
    assert _step(poller, clock, 5000) == [] and len(rounds.calls) == 2
    st = poller.state("P")
    assert st["state"] == "paused" and st["paused_all"] is True and st["paused"] is False
    poller.set_paused(None, False)
    assert len(_step(poller, clock, 5020)) == 1


def test_offline_backs_off_and_a_good_round_resets_it(setup):
    app, poller, clock, rounds = setup
    rounds.answer = _report([UNREACHABLE])
    at, waits = 15, []
    assert len(_step(poller, clock, at)) == 1
    for _ in range(6):
        st = poller.state("P")
        assert st["state"] == "offline" and st["offline"]["failures"] == len(waits) + 1
        wait = st["offline"]["retry_seconds"]
        assert st["next_round_in"] == wait
        poller.touched("P")                                            # a change does not bring a try forward
        assert _step(poller, clock, at + wait - 1) == []
        waits.append(wait)
        at += wait
        assert len(_step(poller, clock, at)) == 1
    assert waits == [120, 240, 480, 960, 1800, 1800]
    assert poller.state("P")["offline"]["since"]
    rounds.answer = _report()                                          # the folder is back
    at += 1800
    assert len(_step(poller, clock, at)) == 1
    st = poller.state("P")
    assert st["offline"] is None and st["state"] == "waiting" and st["next_round_in"] == 120
    # problems of other kinds are not offline
    rounds.answer = _report([UNREACHABLE, {"kind": "gap", "person": {"id": "p1"}, "seq": 3, "message": "…"}])
    assert len(_step(poller, clock, at + 120)) == 1 and poller.state("P")["offline"] is None


def test_a_round_by_hand_counts_and_brings_the_folder_back(setup):
    app, poller, clock, rounds = setup
    rounds.answer = _report([UNREACHABLE])
    _step(poller, clock, 15)
    _step(poller, clock, 135)
    assert poller.state("P")["offline"]["failures"] == 2
    rounds.answer = _report()
    ws = app.ws("P")
    by_hand = app.jobs.start(folder.JOB, "Working together: the shared folder", "P",
                             lambda job: folder.sync_now(ws), uses_model=False, unique=True)   # as api_folder does
    assert _until(lambda: poller.state("P")["last_round"]["job"] == by_hand.id)
    st = poller.state("P")
    assert st["offline"] is None and st["last_round"]["background"] is False and st["next_round_in"] == 120


def test_one_round_per_project_at_a_time(setup):
    app, poller, clock, rounds = setup
    rounds.hold = threading.Event()
    clock.t = poller.born + 15
    first = poller.step()
    assert len(first) == 1 and rounds.began.wait(5)
    for at in (200, 400, 4000):                                        # due again by the clock, but one runs
        clock.t = poller.born + at
        assert poller.step() == []
    poller.touched("P")
    clock.t += 60
    assert poller.step() == []
    by_hand = app.jobs.start(folder.JOB, "by hand", "P", lambda job: None, uses_model=False, unique=True)
    assert by_hand is first[0]                                         # Sync now gets the round that runs
    st = poller.state("P")
    assert st["state"] == "running" and st["round"]["id"] == first[0].id and st["next_round_at"] is None
    rounds.hold.set()
    assert _until(lambda: first[0].state == "done")
    assert len(rounds.calls) == 1 and len(_rounds(app)) == 1


def test_a_round_waits_while_documents_are_added_without_queueing_a_job(setup):
    app, poller, clock, rounds = setup
    release = threading.Event()
    adding = app.jobs.start("ingest", "Adding sources", "P", lambda job: release.wait(30), uses_model=False)
    assert _until(lambda: adding.state == "running")
    assert _step(poller, clock, 15) == [] and not _rounds(app)
    st = poller.state("P")
    assert st["state"] == "busy" and st["busy"]["id"] == adding.id and "Adding sources" in st["busy"]["message"]
    assert _step(poller, clock, 16) == []                              # still held: it stays due, nothing queued
    release.set()
    assert _until(lambda: adding.state == "done")
    started = _step(poller, clock, 17)                                 # the first look after it ended
    assert len(started) == 1 and rounds.calls == ["P"]
    # a check runs beside a round
    hold = threading.Event()
    check = app.jobs.start("keywords", "Codes", "P", lambda job: hold.wait(30), uses_model=False)
    assert len(_step(poller, clock, 17 + 120)) == 1
    hold.set()
    assert _until(lambda: check.state == "done")


def test_a_change_brings_a_round_forward_debounced(setup):
    app, poller, clock, rounds = setup
    _step(poller, clock, 15)                                           # next by the interval: 135
    clock.t = poller.born + 30
    poller.touched("P")                                                # due at 50
    clock.t = poller.born + 45
    poller.touched("P")                                                # a later change: due at 65
    assert _step(poller, clock, 60) == []
    assert len(_step(poller, clock, 65)) == 1
    assert _step(poller, clock, 100) == [] and poller.state("P")["next_round_in"] == 85   # back to the interval
    # the end of another job of the project is a change too (but not the end of a round)
    done = app.jobs.start("keywords", "Codes", "P", lambda job: None, uses_model=False)
    assert _until(lambda: done.state == "done") and _until(lambda: poller.projects["P"].touched is not None)
    assert poller.state("P")["next_round_in"] == 20


def test_changes_through_the_app_bring_a_round_forward(home, tmp_path):  # noqa: F811
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    try:
        assert api("POST", "/api/projects", {"name": "P"})[0] == 200
        assert "P" not in app.poller.projects or app.poller.projects["P"].touched is None
        assert api("GET", "/api/projects/P/sharing")[0] == 200
        assert "P" not in app.poller.projects or app.poller.projects["P"].touched is None   # a look is no change
        shared = tmp_path / "shared"
        shared.mkdir()
        assert api("PUT", "/api/projects/P/shared-folder", {"path": str(shared)})[0] == 200
        assert app.poller.projects["P"].touched is not None             # choosing the folder: a round soon
        app.poller.projects["P"].touched = None
        assert api("PUT", "/api/projects/P/sync-poller", {"paused": True})[0] == 200
        assert app.poller.projects["P"].touched is None                 # the poller's own routes are no change
        assert api("PUT", "/api/projects/P/shared-folder/keep-out", {"keep_out": True})[0] == 200
        assert app.poller.projects["P"].touched is not None
    finally:
        srv.shutdown()
        srv.server_close()


def test_what_came_in_is_counted_until_marked_seen(setup):
    app, poller, clock, rounds = setup
    ws = app.ws("P")
    came = {"from": {"id": "pa", "name": "Anna"}, "via": "folder", "bundles": [1, 2], "lines": ["From Anna: 2 new results."],
            "documents": {"new": ["Doc"], "clash": [], "other_reading": []}, "checks": {"new": 2, "updated": 1, "clash": []},
            "themes": {"new": 0, "updated": 0, "clash": []}, "codebooks": {"new": [], "updated": [], "merged": [], "clash": []},
            "judgements": 3, "notes": 1, "log": 0, "labels": 500, "links": 9, "shares": {"withdrawn": ["x"]}}
    assert things(came) == 1 + 2 + 1 + 3 + 1 + 1
    nothing = {**came, "documents": {}, "checks": {}, "judgements": 0, "notes": 0, "shares": {}, "lines": ["Nothing new"]}
    by_zip = {**came, "via": None}
    with ws.connect() as cx:
        for rep in (came, nothing, by_zip, {**came, "from": {"id": "pb", "name": "Ben"}}):
            cx.execute("INSERT INTO sync_log(at, person_id, report_json) VALUES (?,?,?)",
                       ("2026-11-11T10:00:00+00:00", rep["from"]["id"], json.dumps(rep)))
    ids = [r[0] for r in ws.query("SELECT log_id FROM sync_log ORDER BY log_id")]
    c = poller.state("P")["came_in"]
    assert c["count"] == 18 and c["seen_through"] == 0
    assert [r["id"] for r in c["rounds"]] == [ids[3], ids[0]]          # newest first; the zip and "nothing" left out
    assert c["rounds"][0]["from"]["name"] == "Ben" and c["rounds"][1]["lines"] == ["From Anna: 2 new results."]
    Poller.mark_seen(ws, ids[0])                                       # the person saw Anna's, not Ben's yet
    c = poller.state("P")["came_in"]
    assert c["count"] == 9 and [r["id"] for r in c["rounds"]] == [ids[3]]
    Poller.mark_seen(ws, ids[0] - 1)                                   # a mark never goes back
    assert poller.state("P")["came_in"]["seen_through"] == ids[0]
    Poller.mark_seen(ws)
    assert poller.state("P")["came_in"] == {"count": 0, "seen_through": ids[3], "rounds": []}
    # the last round says how much it brought
    rounds.answer = _report(came=came)
    _step(poller, clock, 15)
    assert poller.state("P")["last_round"]["came_in"] == 9


def test_what_came_in_from_a_real_round(pair):
    """Ben's round brings Anna's shared check in: it is counted, under her name, until Ben marks it seen."""
    from test_shared_folder import _check, _round, _share

    anna, ben = pair
    with anna:
        h = _check(anna.ws, "Electrolysers create local jobs.")
    _share(anna, "check", h)
    _round(anna)
    _round(ben)
    with ben:
        c = Poller.came_in(ben.ws)
        assert c["count"] >= 1 and c["rounds"][0]["from"]["name"] == "Anna" and c["rounds"][0]["lines"]
        Poller.mark_seen(ben.ws, c["rounds"][0]["id"])
        assert Poller.came_in(ben.ws)["count"] == 0
        _round(ben)                                                    # nothing new: nothing to count
        assert Poller.came_in(ben.ws)["count"] == 0


def test_it_stops_cleanly(home):  # noqa: F811
    from enlens_claims.gui.server import App

    app = App()
    poller = app.poller
    poller.tick = 0.02
    looks = []
    real = poller.step
    poller.step = lambda: looks.append(1) or real()
    poller.start()
    assert poller.running() and _until(lambda: len(looks) >= 3)
    poller.stop()
    assert not poller.running() and not poller._thread.is_alive()
    n = len(looks)
    time.sleep(0.1)
    assert len(looks) == n and real() == []                            # no look, and no round, after it stopped


def test_quitting_stops_the_poller(home):  # noqa: F811
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    try:
        app.poller.tick = 0.02
        app.poller.start()
        stopped = threading.Event()
        app.stop = stopped.set
        assert api("POST", "/api/quit", {})[0] == 200
        assert _until(lambda: not app.poller._thread.is_alive(), 3) and stopped.wait(10)
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_api(home, tmp_path):  # noqa: F811
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    try:
        assert api("POST", "/api/projects", {"name": "P"})[0] == 200
        st, s = api("GET", "/api/projects/P/sync-poller")
        assert st == 200 and s["state"] == "off" and s["folder"] is False
        assert set(s) == {"project", "folder", "paused", "paused_all", "state", "every_seconds", "next_round_at",
                          "next_round_in", "offline", "busy", "round", "last_round", "came_in"}
        shared = tmp_path / "shared"
        shared.mkdir()
        assert api("PUT", "/api/projects/P/shared-folder", {"path": str(shared)})[0] == 200
        st, s = api("GET", "/api/projects/P/sync-poller")
        assert s["folder"] is True and s["state"] in ("waiting", "due") and s["next_round_at"]
        assert api("GET", "/api/projects/Nope/sync-poller")[0] == 404
        assert api("PUT", "/api/projects/P/sync-poller", {"paused": "yes"})[0] == 400
        st, s = api("PUT", "/api/projects/P/sync-poller", {"paused": True})
        assert st == 200 and s["state"] == "paused"
        assert api("POST", "/api/projects/P/sync-poller/seen", {"through": "x"})[0] == 400
        st, s = api("POST", "/api/projects/P/sync-poller/seen", {})
        assert st == 200 and s["came_in"]["count"] == 0
        st, o = api("GET", "/api/sync-poller")
        assert st == 200 and o["every_minutes"] == 2 and o["paused"] is False and o["running"] is False
        assert [p["project"] for p in o["projects"]] == ["P"]
        for bad in (0, 61, "2", True, 2.5):
            assert api("PUT", "/api/sync-poller", {"every_minutes": bad})[0] == 400, bad
        st, o = api("PUT", "/api/sync-poller", {"every_minutes": 10, "paused": True})
        assert st == 200 and o["every_minutes"] == 10 and o["paused"] is True
        assert api("PUT", "/api/settings", {"sync_every_minutes": 0})[0] == 400
        assert api("PUT", "/api/settings", {"sync_paused_projects": "P"})[0] == 400
        # a round by hand shows as the round of the moment, then as the last round
        st, r = api("POST", "/api/projects/P/shared-folder/sync", {})
        assert st == 200 and r["job"]["background"] is False
        assert api.wait(r["job"]["id"])["state"] == "done"
        assert _until(lambda: (api("GET", "/api/projects/P/sync-poller")[1]["last_round"] or {}).get("job")
                      == r["job"]["id"])
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_round_being_started_when_the_app_quits_is_not_started(setup, monkeypatch):
    """Quit arrives while a look is opening a project to start its round: once stop() has returned, no round starts
    (a round already in the list of jobs is stopped and waited for with the others)."""
    app, poller, clock, rounds = setup
    inside, go = threading.Event(), threading.Event()
    real = folder.chosen

    def slow(ws):
        inside.set()
        assert go.wait(10)
        return real(ws)

    monkeypatch.setattr(folder, "chosen", slow)
    clock.t = poller.born + 15
    got = []
    look = threading.Thread(target=lambda: got.extend(poller.step()))
    look.start()
    assert inside.wait(5)
    poller.stop(wait=0)                                                # what Quit does first
    go.set()
    look.join(10)
    assert got == [] and not _rounds(app) and rounds.calls == []


def test_weeks_offline_do_not_overflow_the_back_off(setup):
    app, poller, clock, rounds = setup
    rounds.answer = _report([UNREACHABLE])
    _step(poller, clock, 15)
    poller.projects["P"].failures = 5000                               # about three months of tries
    st = poller.state("P")
    assert st["state"] == "offline" and st["offline"]["retry_seconds"] == 1800
    assert len(_step(poller, clock, 15 + 1800)) == 1


def test_pauses_asked_for_at_once_are_all_kept(setup, home):  # noqa: F811
    app, poller, clock, rounds = setup
    names = [f"R{i}" for i in range(12)]
    threads = [threading.Thread(target=poller.set_paused, args=(n, True)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert home.load_settings()["sync_paused_projects"] == sorted(names)


# ---------------------------------------------------------------------------------------------------------------------
# 2026-11-12: idle rounds back off (gui/poller.py, "Idle")
# ---------------------------------------------------------------------------------------------------------------------
def _waits(poller, clock, at, n):
    """`n` rounds, each started when it is due (and not a second before); returns the waits and the time of the last."""
    out = []
    for _ in range(n):
        wait = poller.state("P")["next_round_in"]
        assert _step(poller, clock, at + wait - 1) == []
        at += wait
        assert len(_step(poller, clock, at)) == 1
        out.append(wait)
    return out, at


def test_idle_rounds_back_off_to_four_intervals(setup):
    app, poller, clock, rounds = setup
    assert len(_step(poller, clock, 15)) == 1                          # idle 1
    waits, _at = _waits(poller, clock, 15, 6)
    assert waits == [120, 120, 120, 240, 480, 480]                     # three at 2, then 4, then 8 minutes at most
    assert poller.state("P")["state"] == "waiting" and poller.state("P")["offline"] is None


def test_idle_back_off_never_passes_fifteen_minutes_and_a_long_interval_stays_as_it_is(setup, home):  # noqa: F811
    app, poller, clock, rounds = setup
    home.update_settings({"sync_every_minutes": 10})
    assert len(_step(poller, clock, 15)) == 1
    waits, at = _waits(poller, clock, 15, 5)
    assert waits == [600, 600, 600, 900, 900]
    home.update_settings({"sync_every_minutes": 60})
    waits, _at = _waits(poller, clock, at, 2)
    assert waits == [3600, 3600]


def _backed_off(poller, clock):
    assert len(_step(poller, clock, 15)) == 1
    _w, at = _waits(poller, clock, 15, 4)                             # idle 5
    assert poller.state("P")["next_round_in"] == 480
    return at


def test_a_change_brings_the_usual_interval_back_at_once(setup):
    app, poller, clock, rounds = setup
    at = _backed_off(poller, clock)
    clock.t = poller.born + at + 10
    poller.touched("P")                                                # a change made through the app: 20 s
    assert poller.state("P")["next_round_in"] == 20
    assert len(_step(poller, clock, at + 30)) == 1                     # (it found nothing: idle 1 again)
    assert poller.state("P")["next_round_in"] == 120


def test_a_round_that_found_something_or_a_problem_brings_the_usual_interval_back(setup):
    app, poller, clock, rounds = setup
    at = _backed_off(poller, clock)
    rounds.answer = _report(came={"from": {"id": "pabc", "name": "Anna"}, "checks": {"new": 1}})
    assert len(_step(poller, clock, at + 480)) == 1
    assert poller.state("P")["next_round_in"] == 120
    rounds.answer = _report()
    _w, at = _waits(poller, clock, at + 480, 5)
    assert poller.state("P")["next_round_in"] == 480
    for found in ({**_report(), "wrote": {"seq": 7}}, {**_report(), "files": 2},
                  _report([{"kind": "documents", "person": {"id": "p1"}, "seq": 3, "message": "Waiting for …"}])):
        rounds.answer = found
        wait = poller.state("P")["next_round_in"]
        at += wait
        assert len(_step(poller, clock, at)) == 1
        assert poller.state("P")["next_round_in"] == 120, found        # wrote, fetched a file, waits for documents
        rounds.answer = _report()
        _w, at = _waits(poller, clock, at, 5)


def test_a_round_by_hand_brings_the_usual_interval_back(setup):
    app, poller, clock, rounds = setup
    at = _backed_off(poller, clock)
    ws = app.ws("P")
    by_hand = app.jobs.start(folder.JOB, "Working together: the shared folder", "P",
                             lambda job: folder.sync_now(ws), uses_model=False, unique=True)   # as api_folder does
    assert _until(lambda: poller.state("P")["last_round"]["job"] == by_hand.id)
    assert poller.state("P")["next_round_in"] == 120
    assert poller.projects["P"].idle == 0

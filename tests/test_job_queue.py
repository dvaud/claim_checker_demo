"""0.18 (M6): jobs wait their turn.

Jobs of one project that change the same things do not run at the same time: the later one waits in the project's
queue (state "queued", `waiting_for` names the job it waits for, "Queued: starts when … has finished") and can be
cancelled while it waits. Lanes (api_common.LANES): the new reader runs alone in its project; adding documents, search
by meaning and a round of the shared folder each wait for the ones they clash with; checks and the like run beside each
other. First come, first served, except that the new reader goes ahead of search by meaning still waiting.
The refusals "Wait until … has finished" (the new reader, one document or several) and "A new theme is being found …
Wait until it is ready" became waits.
"""
from __future__ import annotations

import threading
import time

import pytest

from enlens_claims.gui.api_common import Jobs, conflicts
from enlens_claims.sync import folder

from test_app import Api, home  # noqa: F401  (fixtures)


def _until(cond, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.01)
    return False


class Gate:
    """A job's work that waits until the test lets it finish, and records when it ran."""

    def __init__(self, ran: list, name: str):
        self.ran, self.name = ran, name
        self.go = threading.Event()
        self.began = threading.Event()

    def __call__(self, job):
        self.ran.append(self.name)
        self.began.set()
        assert self.go.wait(20), f"{self.name} was never let go"
        return {"name": self.name}


def _start(jobs, kind, project, ran, name, **kw):
    g = Gate(ran, name)
    return jobs.start(kind, name, project, g, uses_model=kw.pop("uses_model", False), **kw), g


def _done(job, timeout=10.0):
    assert _until(lambda: job.state in ("done", "error", "cancelled"), timeout), (job.kind, job.state)
    return job


def test_jobs_of_a_project_that_clash_wait_first_come_first_served():
    jobs, ran = Jobs(), []
    a, ga = _start(jobs, "ingest", "P", ran, "A")
    assert ga.began.wait(5) and a.state == "running" and a.view()["waiting_for"] is None
    b, gb = _start(jobs, "ingest", "P", ran, "B")
    c, gc = _start(jobs, "ingest", "P", ran, "C")
    v = b.view()
    assert v["state"] == "queued" and v["waiting_for"] == {"id": a.id, "kind": "ingest", "title": "A",
                                                           "message": "Queued: starts when “A” has finished"}
    assert c.view()["waiting_for"]["id"] == b.id          # the one just ahead of it
    ga.go.set()
    assert gb.began.wait(5) and ran == ["A", "B"] and c.state == "queued"
    assert _until(lambda: (c.view()["waiting_for"] or {}).get("id") == b.id)
    gb.go.set()
    assert gc.began.wait(5)
    gc.go.set()
    for j in (a, b, c):
        assert _done(j).state == "done"
    assert ran == ["A", "B", "C"] and c.view()["waiting_for"] is None


def test_checks_and_other_projects_run_beside_each_other():
    jobs, ran = Jobs(), []
    a, ga = _start(jobs, "ingest", "P", ran, "adding")
    k, gk = _start(jobs, "keywords", "P", ran, "codes")       # no lane: it only writes its own results
    t, gt = _start(jobs, "themes", "P", ran, "themes")
    o, go = _start(jobs, "ingest", "Q", ran, "other project")
    s, gs = _start(jobs, folder.JOB, "Q", ran, "a round in Q")  # clashes with Q's adding
    g, gg = _start(jobs, "model-pull", None, ran, "download")  # not a project's job
    for gate in (ga, gk, gt, go, gg):
        assert gate.began.wait(5)
    assert s.state == "queued" and s.view()["waiting_for"]["id"] == o.id
    for gate in (ga, gk, gt, go, gg, gs):
        gate.go.set()
    for j in (a, k, t, o, s, g):
        assert _done(j).state == "done"


def test_the_new_reader_runs_alone_and_while_it_waits_the_project_goes_on():
    """It waits until nothing else of the project runs; while it waits, a check or themes started later run (a move
    waiting behind a check that waits for Claude Code must not stall the project); while it runs, everything waits."""
    jobs, ran = Jobs(), []
    chk, gc = _start(jobs, "keywords", "P", ran, "codes")
    assert gc.began.wait(5)
    r, gr = _start(jobs, "new_reader", "P", ran, "reader")
    assert r.state == "queued" and r.view()["waiting_for"]["id"] == chk.id
    later, gl = _start(jobs, "themes", "P", ran, "themes")     # not held back by the move that waits
    assert gl.began.wait(5) and later.view()["waiting_for"] is None
    rnd, gs = _start(jobs, folder.JOB, "P", ran, "round")       # nor is a round of the shared folder
    assert gs.began.wait(5)
    gc.go.set()
    gs.go.set()
    assert _until(lambda: (r.view()["waiting_for"] or {}).get("id") == later.id)   # the last one still running
    gl.go.set()
    assert gr.began.wait(5)
    after, ga = _start(jobs, "keywords", "P", ran, "codes again")   # while it runs: waits
    assert after.state == "queued" and after.view()["waiting_for"]["id"] == r.id
    r2, gr2 = _start(jobs, "reread", "P", ran, "one document", lane="reader")   # first come, first served
    assert r2.view()["waiting_for"]["id"] == after.id                  # (the one just ahead of it)
    gr.go.set()
    assert ga.began.wait(5)
    assert r2.state == "queued" and r2.view()["waiting_for"]["id"] == after.id
    ga.go.set()
    assert gr2.began.wait(5)
    gr2.go.set()
    for j in (chk, r, later, rnd, after, r2):
        assert _done(j).state == "done"
    assert ran.index("reader") > ran.index("themes") and ran[-3:] == ["reader", "codes again", "one document"]


def test_what_waits_behind_a_waiting_move_does_not_stall_the_project_either():
    """A check on hold (nothing answers it), a move waiting for it, search by meaning waiting for the move: adding
    documents and a round of the shared folder still start; they do not wait behind search by meaning."""
    jobs, ran = Jobs(), []
    k, gk = _start(jobs, "check", "P", ran, "check on hold")
    assert gk.began.wait(5)
    r, gr = _start(jobs, "new_reader", "P", ran, "reader")
    i, gi = _start(jobs, "index", "P", ran, "index")
    assert i.view()["waiting_for"]["id"] == r.id and r.view()["waiting_for"]["id"] == k.id
    assert jobs.holder("P", folder.JOB) is None
    rnd = jobs.start(folder.JOB, "round", "P", lambda job: ran.append("round"), uses_model=False, if_free=True)
    assert rnd is not None and _done(rnd).state == "done"
    c, gc = _start(jobs, "ingest", "P", ran, "adding")
    assert gc.began.wait(5) and c.view()["waiting_for"] is None
    i2, _ = _start(jobs, "index", "P", ran, "index again")             # search by meaning still queues behind
    assert i2.view()["waiting_for"]["id"] == i.id
    gc.go.set()
    gk.go.set()
    assert gr.began.wait(5)
    gr.go.set()
    assert gi.began.wait(5)
    gi.go.set()
    jobs.cancel(i2)
    for j in (k, r, i, c):
        assert _done(j).state == "done"
    assert ran.index("reader") < ran.index("index") and "index again" not in ran


def test_a_move_started_only_if_free_moves_nothing_when_it_would_wait():
    jobs, ran = Jobs(), []
    a, ga = _start(jobs, "ingest", "P", ran, "adding")
    i, gi = _start(jobs, "index", "P", ran, "index")
    before = i.order
    assert jobs.start("new_reader", "reader", "P", lambda job: None, uses_model=False, if_free=True) is None
    assert i.order == before
    ga.go.set()
    assert gi.began.wait(5)
    gi.go.set()
    _done(a)
    _done(i)


def test_a_queued_job_can_be_cancelled_and_the_next_moves_up():
    jobs, ran = Jobs(), []
    a, ga = _start(jobs, "ingest", "P", ran, "A")
    b, gb = _start(jobs, "ingest", "P", ran, "B")
    c, gc = _start(jobs, "ingest", "P", ran, "C")
    assert ga.began.wait(5) and c.view()["waiting_for"]["id"] == b.id
    t0 = time.time()
    jobs.cancel(b)
    assert _done(b, 2).state == "cancelled" and time.time() - t0 < 1.0
    assert "B" not in ran and b.view()["waiting_for"] is None
    assert _until(lambda: (c.view()["waiting_for"] or {}).get("id") == a.id)   # it waits for the running one now
    ga.go.set()
    assert gc.began.wait(5)
    gc.go.set()
    assert _done(c).state == "done" and ran == ["A", "C"]


def test_cancelled_through_the_api(home, tmp_path):  # noqa: F811
    srv, app, api = _server()
    try:
        assert api("POST", "/api/projects", {"name": "P"})[0] == 200
        ran = []
        a, ga = _start(app.jobs, "ingest", "P", ran, "A")
        b, _gb = _start(app.jobs, "index", "P", ran, "B")
        assert ga.began.wait(5)
        listed = {j["id"]: j for j in api("GET", "/api/jobs")[1]["jobs"]}
        assert listed[b.id]["waiting_for"]["message"] == "Queued: starts when “A” has finished"
        assert listed[a.id]["waiting_for"] is None and listed[a.id]["background"] is False
        st, r = api("POST", f"/api/jobs/{b.id}/cancel")
        assert st == 200
        assert api.wait(b.id, timeout=3)["state"] == "cancelled" and ran == ["A"]
        ga.go.set()
        assert api.wait(a.id)["state"] == "done"
    finally:
        _stop(srv)


def test_the_new_reader_goes_ahead_of_search_by_meaning_still_waiting():
    """When both are asked for, the new reader runs first: its passages get their vectors once. Only search by meaning
    moves behind it; the other jobs keep their places."""
    jobs, ran = Jobs(), []
    a, ga = _start(jobs, "ingest", "P", ran, "adding")
    i, gi = _start(jobs, "index", "P", ran, "index")
    c, gc = _start(jobs, "ingest", "P", ran, "adding more")
    assert ga.began.wait(5) and i.view()["waiting_for"]["id"] == a.id and c.view()["waiting_for"]["id"] == i.id
    r, gr = _start(jobs, "reread", "P", ran, "reader", lane="reader")   # one document: the lane is named
    assert r.view()["waiting_for"]["id"] == c.id                       # behind the jobs already waiting
    assert _until(lambda: (i.view()["waiting_for"] or {}).get("id") == r.id)   # the index now waits for it
    assert _until(lambda: (c.view()["waiting_for"] or {}).get("id") == a.id)   # adding more no longer waits for it
    ga.go.set()
    assert gc.began.wait(5) and i.state == "queued" and r.state == "queued"
    gc.go.set()
    assert gr.began.wait(5) and i.state == "queued" and i.view()["waiting_for"]["id"] == r.id
    gr.go.set()
    assert gi.began.wait(5)
    gi.go.set()
    for j in (a, c, r, i):
        assert _done(j).state == "done"
    assert ran == ["adding", "adding more", "reader", "index"]


def test_search_by_meaning_asked_for_while_the_new_reader_runs_waits():
    jobs, ran = Jobs(), []
    r, gr = _start(jobs, "new_reader", "P", ran, "reader")
    assert gr.began.wait(5)
    i, gi = _start(jobs, "index", "P", ran, "index")
    assert i.state == "queued" and i.view()["waiting_for"]["id"] == r.id
    gr.go.set()
    assert gi.began.wait(5)
    gi.go.set()
    assert _done(i).state == "done" and ran == ["reader", "index"]


def test_a_job_waiting_its_turn_does_not_hold_the_model():
    """A model job that waits for its project's turn leaves the chat model to another project's jobs."""
    jobs, ran = Jobs(), []
    r, gr = _start(jobs, "new_reader", "P", ran, "reader")
    assert gr.began.wait(5)
    m1, g1 = _start(jobs, "check", "P", ran, "check in P", uses_model=True)
    m2, g2 = _start(jobs, "check", "Q", ran, "check in Q", uses_model=True)
    assert g2.began.wait(5) and m1.state == "queued" and m1.view()["waiting_for"]["id"] == r.id
    g2.go.set()
    gr.go.set()
    assert g1.began.wait(5)
    g1.go.set()
    for j in (r, m1, m2):
        assert _done(j).state == "done"


def test_if_free_starts_nothing_when_it_would_wait_and_unique_returns_the_one_there():
    jobs, ran = Jobs(), []
    a, ga = _start(jobs, "ingest", "P", ran, "A")
    assert jobs.start(folder.JOB, "round", "P", lambda j: None, uses_model=False, if_free=True) is None
    assert jobs.holder("P", folder.JOB) is a
    assert jobs.holder("P", "keywords") is None
    assert not [j for j in jobs.all() if j.kind == folder.JOB]
    s1, gs = _start(jobs, folder.JOB, "Q", ran, "round")
    assert jobs.start(folder.JOB, "again", "Q", lambda j: None, uses_model=False, unique=True) is s1
    ga.go.set()
    gs.go.set()
    _done(a)
    _done(s1)


def test_the_lanes():
    from enlens_claims.gui.api_common import Job, LANE_OF_KIND

    def j(kind, project="P", lane=None, serial=None):
        x = Job(kind, kind, project)
        x.lane, x.serial = lane or LANE_OF_KIND.get(kind), serial
        return x

    clash = [("ingest", "ingest"), ("ingest", "index"), ("ingest", folder.JOB), ("index", "index"),
             (folder.JOB, folder.JOB), ("new_reader", "check"), ("new_reader", folder.JOB), ("new_reader", "index")]
    beside = [("index", folder.JOB), ("check", "ingest"), ("check", folder.JOB), ("check", "index"), ("check", "themes")]
    for a, b in clash:
        assert conflicts(j(a), j(b)) and conflicts(j(b), j(a)), (a, b)
    for a, b in beside:
        assert not conflicts(j(a), j(b)) and not conflicts(j(b), j(a)), (a, b)
    assert not conflicts(j("ingest"), j("ingest", project="Q"))
    assert not conflicts(j("ingest", project=None), j("ingest", project=None))
    assert conflicts(j("theme-new", serial="theme-new:r1"), j("theme-new", serial="theme-new:r1"))
    assert not conflicts(j("theme-new", serial="theme-new:r1"), j("theme-new", serial="theme-new:r2"))
    assert conflicts(j("reread", lane="reader"), j("keywords"))       # one document with the new reader
    assert not conflicts(j("reread"), j("keywords"))                   # reading one excerpt again


# ---------------------------------------------------------------------------------------------------------------------
# through the app: the refusals became waits
# ---------------------------------------------------------------------------------------------------------------------
def _server():
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, app, Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)


def _stop(srv):
    srv.shutdown()
    srv.server_close()


def test_the_new_reader_for_several_documents_waits_instead_of_being_refused(home, tmp_path, monkeypatch):  # noqa: F811
    pytest.importorskip("pdfminer")
    from test_0_15_7_documents_reading import _project

    name, one, two = _project(home, tmp_path, monkeypatch, lost=False)
    srv, app, api = _server()
    try:
        release = threading.Event()
        busy = app.jobs.start("keywords", "Codes by keywords", name, lambda job: release.wait(30), uses_model=False)
        st, r = api("POST", f"/api/projects/{name}/new-reader", {})
        assert st == 200 and r["job"]["kind"] == "new_reader" and r["job"]["state"] == "queued"
        assert r["job"]["waiting_for"]["id"] == busy.id
        assert "Queued: starts when “Codes by keywords” has finished" == r["job"]["waiting_for"]["message"]
        # one document asked for meanwhile waits behind it (one at a time: both change passages)
        st, one_job = api("POST", f"/api/projects/{name}/documents/{one}/reread")
        assert st == 200 and one_job["job"]["waiting_for"]["id"] == r["job"]["id"]
        # the same document asked for again: the job already there, not a second one
        assert api("POST", f"/api/projects/{name}/documents/{one}/reread")[1]["job"]["id"] == one_job["job"]["id"]
        release.set()
        done = api.wait(r["job"]["id"])
        assert done["state"] == "done" and len(done["result"]["moved"]) == 2, done
        # the single move found its document moved already: said in words, as a request error, nothing changed
        late = api.wait(one_job["job"]["id"])
        assert late["state"] == "error" and late["error_kind"] == "request" and "already" in late["error"], late
    finally:
        _stop(srv)


def test_a_new_theme_for_another_removed_theme_waits_for_the_first(home, tmp_path, monkeypatch):  # noqa: F811
    from enlens_claims import themes
    from test_0_13_9_remove_themes import topics_corpus

    srv, app, api = _server()
    try:
        assert api("PUT", "/api/settings", {"embed_backend": "off"})[0] == 200
        assert api("POST", "/api/projects", {"name": "P"})[0] == 200
        for f in sorted(topics_corpus(tmp_path / "topics").iterdir()):
            assert api("POST", f"/api/projects/P/uploads?batch=b1&name={f.name}", raw=f.read_bytes())[0] == 200
        assert api.wait(api("POST", "/api/projects/P/ingest", {"batch": "b1"})[1]["job"]["id"])["state"] == "done"
        rid = api.wait(api("POST", "/api/projects/P/themes", {"k": 4})[1]["job"]["id"])["result"]["run_id"]
        base = f"/api/projects/P/themes/{rid}"
        ids = [t["theme_id"] for t in api("GET", base)[1]["themes"]]
        for tid in ids[-2:]:
            assert api("PUT", f"{base}/edit", {"what": "remove", "theme_id": tid, "value": True})[0] == 200
        real, release, began = themes.new_theme, threading.Event(), threading.Event()

        def slow(*a, **kw):
            began.set()
            release.wait(20)
            return real(*a, **kw)

        monkeypatch.setattr(themes, "new_theme", slow)
        st, first = api("POST", f"{base}/new", {"replaces": ids[-1]})
        assert st == 200 and began.wait(5)
        st, second = api("POST", f"{base}/new", {"replaces": ids[-2]})           # refused before 0.18
        assert st == 200 and second["job"]["waiting_for"]["id"] == first["job"]["id"]
        st, again = api("POST", f"{base}/new", {"replaces": ids[-1]})            # the same one: that job
        assert st == 200 and again["job"]["id"] == first["job"]["id"]
        release.set()
        a, b = api.wait(first["job"]["id"]), api.wait(second["job"]["id"])
        assert a["state"] == "done" and b["state"] == "done", (a, b)
        news = {t["replaces"]["theme_id"] for t in api("GET", base)[1]["themes"] if t.get("replaces")}
        assert news == {ids[-1], ids[-2]}
    finally:
        _stop(srv)


def test_a_round_of_the_shared_folder_waits_for_documents_being_added(home, tmp_path):  # noqa: F811
    """api_folder's *Sync now* joins the queue by its kind: it never merges while documents are added."""
    srv, app, api = _server()
    try:
        assert api("POST", "/api/projects", {"name": "P"})[0] == 200
        shared = tmp_path / "shared"
        shared.mkdir()
        assert api("PUT", "/api/projects/P/shared-folder", {"path": str(shared)})[0] == 200
        release = threading.Event()
        busy = app.jobs.start("ingest", "Adding sources", "P", lambda job: release.wait(30), uses_model=False)
        st, r = api("POST", "/api/projects/P/shared-folder/sync", {})
        assert st == 200 and r["job"]["state"] == "queued" and r["job"]["waiting_for"]["id"] == busy.id
        assert api("GET", "/api/projects/P/shared-folder")[1]["job"]["waiting_for"]["title"] == "Adding sources"
        assert not (shared / folder.team_name(app.ws("P"))).exists()           # nothing written while it waits
        release.set()
        done = api.wait(r["job"]["id"])
        assert done["state"] == "done" and done["result"]["wrote"] is not None, done
    finally:
        _stop(srv)


def test_quitting_cancels_the_jobs_waiting_their_turn(home):  # noqa: F811
    srv, app, api = _server()
    try:
        stopped = threading.Event()
        app.stop = stopped.set
        ran = []
        a, ga = _start(app.jobs, "ingest", "P", ran, "A")
        b, _gb = _start(app.jobs, "ingest", "P", ran, "B")
        assert ga.began.wait(5)
        st, r = api("POST", "/api/quit", {})
        assert st == 200 and r["jobs_stopped"] == 2
        assert _done(b, 3).state == "cancelled" and "B" not in ran
        ga.go.set()
        assert stopped.wait(10)
    finally:
        _stop(srv)


def test_a_move_whose_document_was_removed_while_it_waited_says_so(home, tmp_path, monkeypatch):  # noqa: F811
    pytest.importorskip("pdfminer")
    from test_0_15_7_documents_reading import _project

    name, one, two = _project(home, tmp_path, monkeypatch, lost=False)
    srv, app, api = _server()
    try:
        release = threading.Event()
        app.jobs.start("keywords", "Codes by keywords", name, lambda job: release.wait(30), uses_model=False)
        st, r = api("POST", f"/api/projects/{name}/documents/{one}/reread")
        assert st == 200 and r["job"]["state"] == "queued"
        assert api("DELETE", f"/api/projects/{name}/documents/{one}")[0] == 200
        release.set()
        late = api.wait(r["job"]["id"])
        assert late["state"] == "error" and late["error_kind"] == "request" and "removed" in late["error"], late
    finally:
        _stop(srv)

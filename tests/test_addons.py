"""0.13.6: room for add-ons in the server, the database and access (docs/EXTENDING.md).

The stand-in add-on (tests/fake_extension, a package found through its entry point) adds a route, a download, a
state key, an Overview key, its own table with a migration, hypotheses with an origin, a job that waits in the queue
for Claude Code, a floor that keeps its notes' text on this computer and hypotheses hidden from a Claude chat.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time

import pytest

import fake_claude_code as fcc
from test_queue import _project, _settings
from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import access, addons, claimcheck, tasks
from enlens_claims.store import Workspace


def _job(api, job_id):
    return next(j for j in api("GET", "/api/jobs")[1]["jobs"] if j["id"] == job_id)


def _until(fn, seconds=20.0):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return fn()


# ---------------------------------------------------------------------------------------------
# ENLENS on its own
# ---------------------------------------------------------------------------------------------
def test_enlens_alone_adds_nothing(api, tmp_path):  # noqa: F811
    assert addons.routes() == [] and addons.downloads() == set() and addons.database() == []
    st, state = api("GET", "/api/state")
    assert "fake" not in state
    ws = Workspace.create(tmp_path / "w")
    assert not ws.query("SELECT name FROM sqlite_master WHERE name='fake_notes'")
    assert {"origin", "origin_id"} <= {r[1] for r in ws.query("PRAGMA table_info(hypotheses)")}
    assert access.floor(None, {"fake_note_id": "n1"}) == "cloud" and access.hidden_hypotheses(ws) == set()
    assert api("GET", "/api/fake/hello")[0] == 404


def test_the_public_app_interface():
    from enlens_claims.gui.server import App

    for public, old in (("start_job", "_job"), ("start_queued_job", "_model_job"), ("follow_queued", "_follow_queued"),
                        ("wire", "_wire")):
        assert getattr(App, public) is getattr(App, old), public
    for name in ("ws", "backend", "queue_mode"):
        assert callable(getattr(App, name))


# ---------------------------------------------------------------------------------------------
# the server
# ---------------------------------------------------------------------------------------------
def test_routes_a_download_and_extra_keys(api, addon, corpus):  # noqa: F811
    st, r = api("GET", "/api/fake/hello")
    assert st == 200 and r["hello"] == "from the stand-in add-on"
    assert api("GET", "/api/fake/hello", token=False)[0] == 401  # the token, as for every route
    assert api("POST", "/api/fake/hello")[0] == 405

    st, state = api("GET", "/api/state")
    assert state["fake"] == {"ready": True}
    assert state["version"] != "not the add-on's to change"  # an add-on never replaces ENLENS's keys

    _project(api, corpus)
    st, r = api("POST", "/api/projects/P/fake/notes", {"note_id": "n1", "text": "hello"})
    assert st == 200, r
    st, o = api("GET", "/api/projects/P/overview")
    assert o["fake_notes"] == 1 and o["documents"] == 3  # ENLENS's count stays

    # a download: a plain link with ?token= works for the add-on's download, not for its other routes
    tok = api.token
    st, body = api("GET", f"/api/projects/P/fake/notes.csv?token={tok}", token=False)
    assert st == 200 and body.startswith(b"note_id,text\nn1,hello")
    assert api("GET", f"/api/fake/hello?token={tok}", token=False)[0] == 401


def test_a_fork_adds_a_route_by_method_name_or_function(api, local_addon):  # noqa: F811
    def ping(h, q):
        return {"pong": True, "brand": h.app.state()["brand"]["name"]}

    local_addon.set(ROUTES=[("GET", r"/api/ping", ping), ("GET", r"/api/state-again", "get_state")])
    assert api("GET", "/api/ping")[1] == {"pong": True, "brand": "ENLENS"}
    assert api("GET", "/api/state-again")[1]["version"] == api("GET", "/api/state")[1]["version"]


def test_an_addon_cannot_take_over_an_enlens_route(api, local_addon):  # noqa: F811
    local_addon.set(ROUTES=[("GET", r"/api/state", lambda h, q: {"taken": True})])
    assert "taken" not in api("GET", "/api/state")[1]  # ENLENS's own routes come first


def test_a_failing_hook_leaves_the_page_working(api, local_addon):  # noqa: F811
    def state(app):
        raise RuntimeError("broken")

    local_addon.set(state=state)
    st, s = api("GET", "/api/state")
    assert st == 200 and s["brand"]["name"] == "ENLENS"


def test_an_addon_job_waits_for_claude_code_like_any_job(api, addon, corpus):  # noqa: F811
    from enlens_claims import home as core

    _project(api, corpus)
    st, r = api("POST", "/api/projects/P/fake/labels", {})
    assert st == 200, r
    jid = r["job"]["id"]
    try:
        # in /api/jobs and the state, with on_hold: its tasks wait in the queue and nothing answers them
        assert _until(lambda: _job(api, jid)["on_hold"]), _job(api, jid)
        j = _job(api, jid)
        assert j["kind"] == "fake-labels" and j["queue"] is True and j["state"] == "running"
        assert [x["on_hold"] for x in api("GET", "/api/state")[1]["jobs"] if x["id"] == jid] == [True]
        ws = core.open_project("P")
        assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='label' AND queued=1") >= 1
        # a stand-in Claude Code takes the work: the job runs on and finishes
        fcc.FakeClaudeCode(fcc.DirectTools(), wrong_first=False).run("P")
        done = api.wait(jid)
        assert done["state"] == "done", done
        assert done["result"]["read"] == 2 and not done["result"]["failed"]
    finally:
        if _job(api, jid)["state"] in ("queued", "running"):
            api("POST", f"/api/jobs/{jid}/cancel")
            api.wait(jid)


def test_an_addon_job_can_be_stopped(api, addon, corpus):  # noqa: F811
    from enlens_claims import home as core

    _project(api, corpus)
    jid = api("POST", "/api/projects/P/fake/labels", {})[1]["job"]["id"]
    assert _until(lambda: _job(api, jid)["on_hold"])
    assert api("POST", f"/api/jobs/{jid}/cancel")[0] == 200
    assert api.wait(jid)["state"] == "cancelled"
    ws = core.open_project("P")
    # Stop took its waiting tasks back out of the queue
    assert not ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='label' AND queued=1 AND status='pending' "
                         "AND claimed_by IS NULL")


# ---------------------------------------------------------------------------------------------
# the database
# ---------------------------------------------------------------------------------------------
def test_an_addon_table_and_migration_in_a_new_and_an_old_project(addon, tmp_path):
    ws = Workspace.create(tmp_path / "new")
    cols = {r[1] for r in ws.query("PRAGMA table_info(fake_notes)")}
    assert {"note_id", "text", "ai_access", "colour"} <= cols
    assert ws.query("SELECT name FROM sqlite_master WHERE name='ix_fake_notes_colour'")

    # a project made before the add-on had its `colour` column: the column is added once, the rows are kept
    old = tmp_path / "old"
    ws_old = Workspace.create(old)
    ws_old.close()
    cx = sqlite3.connect(old / "enlens.sqlite")
    cx.execute("DROP INDEX ix_fake_notes_colour")
    cx.execute("DROP TABLE fake_notes")
    cx.execute("CREATE TABLE fake_notes(note_id TEXT PRIMARY KEY, text TEXT, ai_access TEXT, created_at TEXT)")
    cx.execute("INSERT INTO fake_notes(note_id, text) VALUES ('n0', 'kept')")
    cx.commit()
    cx.close()
    again = Workspace.open(old)
    assert "colour" in {r[1] for r in again.query("PRAGMA table_info(fake_notes)")}
    assert again.scalar("SELECT text FROM fake_notes WHERE note_id='n0'") == "kept"
    Workspace.open(old)  # opening again changes nothing
    assert [r[1] for r in again.query("PRAGMA table_info(fake_notes)")].count("colour") == 1


def test_an_addon_cannot_add_a_column_with_a_strange_name(local_addon, tmp_path):
    with pytest.raises(ValueError, match="names a column ENLENS cannot add"):
        local_addon.set(MIGRATIONS=[("hypotheses", "x; DROP TABLE documents", "TEXT")])
        Workspace.create(tmp_path / "w")


def test_a_hypothesis_says_where_it_comes_from(loaded):
    hid = claimcheck.create_hypothesis(loaded, "Hydrogen plants need a lot of fresh water.", origin="draft",
                                       origin_id="d1")
    assert claimcheck.hypothesis_result(loaded, hid)["origin"] == "draft"
    assert claimcheck.hypothesis_result(loaded, hid)["origin_id"] == "d1"
    claimcheck.new_claim(loaded, "Hydrogen plants need a lot of fresh water.", hyp_id=hid)  # listed with a part
    row = next(h for h in claimcheck.history(loaded) if h["hyp_id"] == hid)
    assert row["origin"] == "draft" and row["origin_id"] == "d1"
    typed = claimcheck.create_hypothesis(loaded, "Electrolysers use water as their feedstock.")
    assert claimcheck.hypothesis_result(loaded, typed)["origin"] is None
    batch = claimcheck.create_hypothesis(loaded, "Water stress rises near the plants.", batch_id="b1")
    assert claimcheck.hypothesis_result(loaded, batch)["origin"] == "batch"
    assert claimcheck.new_hypothesis is claimcheck.create_hypothesis  # the old name keeps working


def test_a_check_of_several_marks_its_hypotheses_as_a_batch(loaded):
    from enlens_claims.llm import BaselineBackend

    r = claimcheck.check_batch(loaded, [{"text": "Hydrogen plants need a lot of fresh water."}], BaselineBackend(),
                               "baseline", k=2)
    hid = next(h for h in claimcheck.history(loaded) if h["batch_id"] == r["batch_id"])["hyp_id"]
    res = claimcheck.hypothesis_result(loaded, hid)
    assert res["origin"] == "batch" and res["origin_id"] == r["batch_id"]


# ---------------------------------------------------------------------------------------------
# access
# ---------------------------------------------------------------------------------------------
def _note(ws, nid, setting):
    with ws.connect() as cx:
        cx.execute("INSERT OR REPLACE INTO fake_notes(note_id, text, ai_access) VALUES (?,?,?)", (nid, "x", setting))


def test_a_floor_keeps_a_task_on_the_local_model(addon, loaded):
    ws = Workspace.open(loaded.root)  # opened again: with the add-on's table
    _note(ws, "local-note", "local")
    _note(ws, "cloud-note", "cloud")
    doc = ws.query("SELECT doc_id FROM documents LIMIT 1")[0][0]
    with ws.connect() as cx:
        assert access.label_payload(cx, {"fake_note_id": "local-note"}) == "local"
        assert access.label_payload(cx, {"fake_note_id": "cloud-note"}) == "cloud"
        assert access.label_payload(cx, {"fake_note_id": "gone"}) == "none"  # removed since: stays here
        # a floor only restricts: a cloud note does not loosen a document marked local
        access.set_documents(ws, [doc], "local")
        assert access.label_payload(cx, {"fake_note_id": "cloud-note", "doc_id": doc}) == "local"
    # a task holding the note's text is labelled so, and never handed to Claude Code
    with tasks.queueing(True), ws.connect() as cx:
        tasks._insert_task(cx, "t-note", "label", "haiku", {"fake_note_id": "local-note", "passages": []})
    t = ws.query("SELECT access, queued FROM tasks WHERE task_id='t-note'")[0]
    assert t["access"] == "local" and not t["queued"]
    # the guard refuses it to a cloud backend
    from enlens_claims.llm import ClaudeCodeBackend

    task = ws.query("SELECT * FROM tasks WHERE task_id='t-note'")[0]
    with pytest.raises(access.AccessError):
        access.require(ClaudeCodeBackend(), task)


def test_a_failing_floor_keeps_the_text_here(local_addon, loaded):
    def broken(cx, payload, dflt):
        raise RuntimeError("no")

    hooks = list(access._FLOORS)
    try:
        access.register_floor(broken)
        access.register_floor(broken)  # once only
        assert access._FLOORS.count(broken) == 1
        with loaded.connect() as cx:
            assert access.label_payload(cx, {"text": "anything"}) == "none"
    finally:
        access._FLOORS[:] = hooks


def test_local_only_still_decides(addon, loaded, monkeypatch):
    from enlens_claims import home as core

    ws = Workspace.open(loaded.root)
    _note(ws, "cloud-note", "cloud")
    doc = ws.query("SELECT doc_id FROM documents LIMIT 1")[0][0]
    monkeypatch.setattr(core, "local_only", lambda: True)
    with ws.connect() as cx:
        # a document's text: local only, whatever the note says
        assert access.label_payload(cx, {"fake_note_id": "cloud-note", "doc_id": doc}) == "local"
    with pytest.raises(Exception, match="switched off"):
        core.make_backend({**core.load_settings(), "backend": "anthropic", "allow_cloud": True}, "key")


def test_a_hidden_hypothesis_is_missing_from_the_connector(addon, home, corpus):  # noqa: F811
    pytest.importorskip("mcp")
    from mcp import Client

    from enlens_claims import home as core
    from enlens_claims import ingest
    from enlens_claims.mcp_server import build_server

    core.create_project("C")
    ws = core.open_project("C")
    ingest.ingest(ws, [corpus])
    _note(ws, "kept-here", "local")
    _note(ws, "shared", "cloud")
    hidden = claimcheck.create_hypothesis(ws, "Hydrogen plants need a lot of fresh water.", origin="fake-note",
                                          origin_id="kept-here")
    shown = claimcheck.create_hypothesis(ws, "Electrolysers use water as their feedstock.", origin="fake-note",
                                         origin_id="shared")
    for hid in (hidden, shown):
        claimcheck.new_claim(ws, ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (hid,)), hyp_id=hid,
                             claim_id=f"c-{hid}")
    assert access.hidden_hypotheses(ws) == {hidden}

    async def run():
        async with Client(build_server()) as c:
            listed = json.loads((await c.call_tool("list_checks", {"project": "C"})).content[0].text)["checks"]
            ids = {x["check_id"] for x in listed}
            assert f"c-{shown}" in ids and f"c-{hidden}" not in ids
            r = await c.call_tool("get_check", {"check_id": f"c-{hidden}"})
            assert r.is_error and "kept on this computer" in r.content[0].text

    asyncio.run(run())


def test_the_extension_points_are_documented():
    from pathlib import Path

    ext = (Path(__file__).resolve().parent.parent / "docs" / "EXTENDING.md").read_text(encoding="utf-8")
    for name in ("ROUTES", "DOWNLOADS", "def state(app)", "def overview(ws)", "start_job", "start_queued_job",
                 "follow_queued", "SCHEMA", "MIGRATIONS", "INDEXES", "origin_id", "register_floor", "register_hidden"):
        assert name in ext, name

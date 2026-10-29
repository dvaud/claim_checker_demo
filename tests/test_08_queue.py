"""0.8: the task queue answered by Claude Code (a fake one), model routing, stepping up, the plugin, local only, the
acceptance runs, and the items carried over from 0.7.

The fake Claude Code (tests/fake_claude_code.py) plays /enlens-run through the connector's queue tools and answers
with the fake model's canned answers, spoiling the first quote of each kind to prove that it is sent back."""
import json
import random
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

import fake_claude_code as fcc
import fake_servers
from test_app import CLAIM, Api, api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent


def _settings(api, **kw):
    st, r = api("PUT", "/api/settings", {"allow_claude_code": True, "backend": "claude_code", "embed_backend": "off",
                                          **kw})
    assert st == 200, r
    return r


def _project(api, corpus, name="P"):
    _settings(api)
    assert api("POST", "/api/projects", {"name": name})[0] == 200
    for f in sorted(corpus.iterdir()):
        assert api("POST", f"/api/projects/{name}/uploads?batch=b1&name={f.name}", raw=f.read_bytes())[0] == 200
    st, r = api("POST", f"/api/projects/{name}/ingest", {"batch": "b1"})
    assert api.wait(r["job"]["id"])["state"] == "done"
    return {d["file"]: d["doc_id"] for d in api("GET", f"/api/projects/{name}/documents")[1]["documents"]}


class Session(threading.Thread):
    """A fake Claude Code session that keeps running /enlens-run until stopped (as a researcher would type it again)."""

    def __init__(self, project, **kw):
        super().__init__(daemon=True)
        self.project, self.kw = project, kw
        self.stop = threading.Event()
        self.log: list[dict] = []
        self.cc = fcc.FakeClaudeCode(fcc.DirectTools(), **kw)
        self.errors: list[str] = []

    def run(self):
        while not self.stop.is_set():
            try:
                self.cc.run(self.project)
            except Exception as e:  # noqa: BLE001 - reported by the test
                self.errors.append(repr(e))
            time.sleep(0.2)

    def finish(self):
        self.stop.set()
        self.join(10)
        return self.cc.log


# ---------------------------------------------------------------------------------------------
# G1, G2: every AI button by queue, with the right helper and model per kind
# ---------------------------------------------------------------------------------------------
def test_every_ai_button_waits_for_claude_code_and_gets_its_answers(api, corpus):
    docs = _project(api, corpus)
    paper = docs["paper_a.pdf"]
    st, q = api("GET", "/api/projects/P/queue")
    assert st == 200 and q["waiting"] == 0 and q["command"] == "/enlens-run P" and "Anthropic" in q["privacy"]

    # nothing answers yet: the label button prepares tasks and waits, and the page says what waits
    st, r = api("POST", "/api/projects/P/profile/label", {"limit": 3})
    assert st == 200 and r["job"]["queue"] is True
    time.sleep(1.5)
    job = api("GET", f"/api/jobs/{r['job']['id']}")[1]
    assert job["state"] == "running" and job["progress"]["queue"]["text"].startswith("Waiting for Claude Code: 3 passages")
    q = api("GET", "/api/projects/P/queue")[1]
    assert q["waiting"] == 3 and q["groups"][0] == {"kind": "label", "model": "haiku", "helper": "enlens-labeller",
                                                     "waiting": 3}
    assert api("GET", "/api/state")[1]["queue"]["waiting"] == 3

    s = Session("P")
    s.start()
    try:
        job = api.wait(r["job"]["id"])
        assert job["state"] == "done" and job["result"]["read"] == 3, job
        # concept links
        tid = api("GET", "/api/projects/P/concepts?name=hydrogen")[1]["term_id"]
        other = next(e["term_id"] for e in api("GET", "/api/projects/P/terms")[1]["items"] if e["term_id"] != tid)
        r = api("POST", "/api/projects/P/concepts/judge", {"pairs": [[tid, other]]})[1]
        j = api.wait(r["job"]["id"])
        assert j["state"] == "done" and j["result"]["judged"] == 1, j
        # theme names (on more text)
        r = api("POST", "/api/projects/P/ingest", {"path": str(ROOT / "tools" / "demo_corpus")})[1]
        assert api.wait(r["job"]["id"])["state"] == "done"
        r = api("POST", "/api/projects/P/themes", {"k": 4})[1]
        rid = api.wait(r["job"]["id"])["result"]["run_id"]
        r = api("POST", f"/api/projects/P/themes/{rid}/name")[1]
        j = api.wait(r["job"]["id"], timeout=90)
        assert j["state"] == "done" and j["result"]["named"] >= 1, j
        # references in a document
        r = api("POST", f"/api/projects/P/documents/{paper}/references", {})[1]
        j = api.wait(r["job"]["id"], timeout=90)
        assert j["state"] == "done", j
        # a check split into parts, by queue: its search runs here, its model steps wait for Claude Code
        r = api("POST", "/api/projects/P/checks", {"text": "Electrolysis needs large amounts of fresh water, and "
                                                           "hydrogen production can increase water stress in arid regions.",
                                                   "decompose": True, "k": 3})[1]
        j = api.wait(r["job"]["id"], timeout=90)
        assert j["state"] == "done" and j["result"]["status"] != "waiting", j
        hid = j["result"]["hyp_id"]
        h = api("GET", f"/api/projects/P/hypotheses/{hid}")[1]
        assert len(h["parts"]) == 2 and all(p["status"] != "waiting" for p in h["parts"])
        assert h["stronger_model"] == "opus" and h["queue_command"] == "/enlens-run P"
        part = h["parts"][0]
        graded = [x for x in part["passages"] if x["verdict"]]
        assert graded and part["terms"]
        # read one excerpt again; a second opinion; other wordings of a concept
        r = api("POST", f"/api/projects/P/claims/{part['claim_id']}/reread/{graded[0]['passage_id']}", {})[1]
        assert api.wait(r["job"]["id"], timeout=60)["state"] == "done"
        st, r = api("POST", "/api/projects/P/second-opinion", {"hyp_ids": [hid]})
        assert st == 200, r
        j = api.wait(r["job"]["id"], timeout=90)
        assert j["state"] == "done" and j["result"]["graded"] >= 1, j
        r = api("POST", f"/api/projects/P/concepts/{tid}/wordings")[1]
        assert api.wait(r["job"]["id"], timeout=60)["state"] == "done"
    finally:
        log = s.finish()
    assert not s.errors, s.errors
    by_kind = {}
    for e in log:
        by_kind.setdefault(e["kind"], set()).add((e["helper"], e["model"]))
    assert by_kind["label"] == {("enlens-labeller", "haiku")}
    assert by_kind["link"] == {("enlens-linker", "haiku")}
    assert by_kind["theme"] == {("enlens-namer", "sonnet")}
    assert by_kind["expand"] == {("enlens-namer", "sonnet")}
    assert by_kind["decompose"] == {("enlens-reader", "sonnet")}
    assert by_kind["resolve"] == {("enlens-reader", "sonnet")}
    assert by_kind["check"] == {("enlens-checker", "opus")} and by_kind["reread"] == {("enlens-checker", "opus")}
    assert by_kind["second"] == {("enlens-auditor", "opus")}
    assert any(e["resent"] for e in log), "a wrong quote is sent back and answered again"
    assert api("GET", "/api/projects/P/queue")[1]["waiting"] == 0

    from enlens_claims import home as core

    ws = core.open_project("P")
    rows = ws.query("SELECT DISTINCT route, helper FROM results WHERE valid=1 AND kind IN ('label', 'check')")
    assert {tuple(r) for r in rows} == {("Claude Code", "enlens-labeller"), ("Claude Code", "enlens-checker")}
    import io

    import openpyxl
    st, body = api("GET", f"/api/projects/P/hypotheses/{hid}/export.xlsx")
    sheet = list(openpyxl.load_workbook(io.BytesIO(body))["How these results were made"].values)
    head = sheet[0]
    assert "Route" in head and "Helper" in head and "Of them from the stronger model (stepped up)" in head
    assert any(r[head.index("Route")] == "Claude Code" and r[head.index("Helper")] == "enlens-checker" for r in sheet[1:])
    assert any("not repeatable by seed" in str(r[0]) for r in sheet)


def test_stopping_a_waiting_check_withdraws_it(api, corpus):
    _project(api, corpus)
    r = api("POST", "/api/projects/P/checks", {"text": CLAIM, "k": 3})[1]
    time.sleep(1.0)
    q = api("GET", "/api/projects/P/queue")[1]
    assert q["waiting"] == 1 and q["groups"][0]["kind"] == "expand"
    h = api("GET", "/api/projects/P/hypotheses")[1]["hypotheses"]
    assert h and h[0]["status"] == "waiting"
    assert api("POST", f"/api/jobs/{r['job']['id']}/cancel")[0] == 200
    assert api.wait(r["job"]["id"])["state"] == "cancelled"
    assert api("GET", "/api/projects/P/queue")[1]["waiting"] == 0
    assert api("GET", "/api/projects/P/hypotheses")[1]["hypotheses"] == []


def test_a_check_moves_on_without_the_app(home, corpus):
    """The app may be closed: the connector takes the check's next steps when the answers arrive."""
    from enlens_claims import claimcheck, ingest, routing, taskqueue

    ws = home.create_project("Demo")
    ingest.ingest(ws, [corpus])
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    hid = claimcheck.queue_check(ws, CLAIM, routing.from_settings(home.load_settings()), k=3)
    assert claimcheck.hypothesis_result(ws, hid)["status"] == "waiting"
    fcc.run("Demo", tools=fcc.DirectTools())
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] == "supported" and res["queue"] == "done" and res["parts"][0]["terms"]
    assert taskqueue.status(ws)["waiting"] == 0
    assert claimcheck.history(ws)[0]["status"] == "supported"


# ---------------------------------------------------------------------------------------------
# G1, G4: claims, two sessions, lapsed claims, stopping and continuing
# ---------------------------------------------------------------------------------------------
def _queued_labels(home, corpus, name="Q"):
    from enlens_claims import ingest, profile, tasks

    ws = home.create_project(name)
    ingest.ingest(ws, [corpus, ROOT / "tools" / "demo_corpus"])
    profile.keyword_pass(ws, "sdg")
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    plan = profile.label_plan(ws, "sdg", all_passages=True)
    with tasks.queueing():
        profile.make_label_tasks(ws, "sdg", plan["passage_ids"], "haiku", all_passages=True)
    return ws, plan["passage_ids"]


def test_two_sessions_take_different_tasks_and_a_claim_lapses(home, corpus):
    from enlens_claims import taskqueue

    ws, pids = _queued_labels(home, corpus)
    assert len(pids) >= 8
    a = taskqueue.next_tasks(ws, "label", n=3, taken_by="session A")
    b = taskqueue.next_tasks(ws, "label", n=3, taken_by="session B")
    ids_a, ids_b = {t["task_id"] for t in a["tasks"]}, {t["task_id"] for t in b["tasks"]}
    assert len(ids_a) == len(ids_b) == 3 and not ids_a & ids_b
    assert taskqueue.status(ws)["being_answered"] == 6
    # session A stops (a usage limit); 30 minutes later its tasks are handed out again
    old = "2000-01-01T00:00:00+00:00"
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET claimed_at=? WHERE claimed_by=?", (old, a["claim"]))
        cx.execute("UPDATE task_claims SET expires_at=? WHERE claim_id=?", (old, a["claim"]))
    c = taskqueue.next_tasks(ws, "label", n=3, taken_by="session C")
    assert {t["task_id"] for t in c["tasks"]} == ids_a
    late = taskqueue.submit(ws, a["claim"], [{"task_id": t, "answer": {"labels": []}} for t in ids_a])
    assert late["stored"] == 0 and all("another session" in x["problems"][0] for x in late["results"])
    assert taskqueue.release(ws, b["claim"])["returned"] == 3


def test_a_stop_at_a_random_point_then_a_new_session_answers_every_task_once(home, corpus):
    from enlens_claims import taskqueue

    ws, pids = _queued_labels(home, corpus, "R")
    rng = random.Random(3)
    first = fcc.FakeClaudeCode(fcc.DirectTools(), name="before the limit", stop_after=rng.randint(0, 2))
    first.run("R")
    assert first.log and first.log[-1].get("abandoned")   # its last batch was taken and never answered
    with ws.connect() as cx:                                # the claim lapses
        cx.execute("UPDATE tasks SET claimed_at='2000-01-01T00:00:00+00:00' WHERE claimed_by IS NOT NULL")
        cx.execute("UPDATE task_claims SET expires_at='2000-01-01T00:00:00+00:00' WHERE finished_at IS NULL")
    second = fcc.FakeClaudeCode(fcc.DirectTools(), name="next day", wrong_first=False)
    second.run("R")
    ids = [f"label:sdg:{p}" for p in pids]
    assert all(ws.scalar("SELECT status FROM tasks WHERE task_id=?", (t,)) == "done" for t in ids)
    assert all(ws.scalar("SELECT COUNT(*) FROM results WHERE task_id=? AND valid=1", (t,)) == 1 for t in ids)
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE claimed_by IS NOT NULL") == 0
    st = taskqueue.status(ws)
    assert st["waiting"] == 0 and st["kinds"][0]["done"] == len(ids)


def test_order_hold_and_paused(home, corpus):
    from enlens_claims import claimcheck, routing, taskqueue

    ws, pids = _queued_labels(home, corpus, "O")
    claimcheck.queue_check(ws, CLAIM, routing.from_settings(home.load_settings()), k=3)
    st = taskqueue.status(ws)
    assert [g["kind"] for g in st["groups"]] == ["expand", "label"]   # the researcher's own check first
    taskqueue.set_order(ws, "label", "first")
    assert taskqueue.next_tasks(ws)["kind"] == "label"
    taskqueue.set_order(ws, "label", "hold")
    assert [g["kind"] for g in taskqueue.status(ws)["groups"]] == ["expand"]
    assert taskqueue.next_tasks(ws)["kind"] == "expand"
    taskqueue.set_order(ws, "label", "go")
    # nothing has arrived for a while: paused, with where it stopped and what to type
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET claimed_by=NULL, claimed_at=NULL")
        cx.execute("UPDATE task_claims SET finished_at='x'")
        cx.execute("UPDATE tasks SET queued_at='2000-01-01T00:00:00+00:00' WHERE queued=1")
    st = taskqueue.status(ws, "O")
    assert st["paused"] and st["paused_text"].startswith("Paused at 0 of ") and "/enlens-run O" in st["paused_text"]


# ---------------------------------------------------------------------------------------------
# G3: routing and stepping up, on the three routes
# ---------------------------------------------------------------------------------------------
def test_the_router_names_a_model_per_kind():
    from enlens_claims import routing

    r = routing.from_settings({"backend": "claude_code"})
    assert [r.model(k) for k in ("label", "link", "expand", "decompose", "theme", "resolve", "check", "second")] == \
        ["haiku", "haiku", "sonnet", "sonnet", "sonnet", "sonnet", "opus", "opus"]
    assert r.step_up("label") == "sonnet" and r.step_up("theme") == "opus" and r.step_up("second") is None
    assert r.helper("check") == "enlens-checker" and r.helper("check", 1) == "enlens-auditor"
    f = routing.from_settings({"backend": "claude_code", "use_fable": True})
    assert f.model("second") == "fable" and f.step_up("check") == "fable"
    api_r = routing.from_settings({"backend": "anthropic", "anthropic_model": "claude-opus-5-5"})
    assert api_r.call_model("label") == "claude-haiku-5-5" and api_r.call_model("label", 1) == "claude-sonnet-5-5"
    assert api_r.call_model("check") == "claude-opus-5-5" and api_r.helper("check") is None
    o = routing.from_settings({"backend": "claude_code", "task_models": {"claude": {"label": "sonnet"}}})
    assert o.model("label") == "sonnet" and o.step_up("label") == "opus"
    local = routing.from_settings({"backend": "ollama"}, large="big")
    assert {local.model(k) for k in routing.KINDS if k not in ("second", "audit")} == {"big"} and local.step_up("label") is None
    small = routing.from_settings({"backend": "ollama", "local_small_model": "tiny"}, large="big")
    assert small.model("label") == "tiny" and small.step_up("label") == "big" and small.model("check") == "big"
    with pytest.raises(ValueError):
        routing.clean_task_models({"claude": {"label": "gpt"}})


def _low(kind_prefix, conf=0.3):
    """An answer function whose labels are unsure."""
    def answer(kind, system, prompt, model):
        out = fake_servers._answer(system, prompt)
        for lb in out.get("labels", []):
            lb["confidence"] = conf
        return out
    return answer


def test_an_unsure_answer_steps_up_once_by_queue(home, corpus):
    from enlens_claims import runs, taskqueue

    ws, pids = _queued_labels(home, corpus, "S")
    session = fcc.FakeClaudeCode(fcc.DirectTools(), wrong_first=False, answer=_low("label"))
    session.run("S")
    models = [(e["model"], e["helper"]) for e in session.log]
    assert ("haiku", "enlens-labeller") in models and ("sonnet", "enlens-labeller") in models
    rows = ws.query("SELECT task_id, step, again FROM tasks WHERE kind='label'")
    stepped = [r for r in rows if r["step"]]
    assert stepped and all(r["again"] == 0 for r in rows)          # read once more, then never again
    for r in stepped:
        res = ws.query("SELECT model, step FROM results WHERE task_id=? AND valid=1 ORDER BY attempt", (r["task_id"],))
        assert [(x["model"], x["step"]) for x in res] == [("haiku", 0), ("sonnet", 1)]   # both answers are kept
    assert taskqueue.status(ws)["waiting"] == 0
    table = runs.provenance_table(ws, kinds=("label",))
    sonnet = next(t for t in table if "sonnet" in str(t.get("AI model")))
    assert sonnet["Of them from the stronger model (stepped up)"] == len(stepped)

    # two rejected answers: the last attempt goes to the stronger model
    from enlens_claims import profile, tasks

    with tasks.queueing():
        profile.make_label_tasks(ws, "sdg", pids[:1], "haiku")
        ws.query("SELECT 1")
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET status='pending', attempts=0, step=0, again=0, queued=1 WHERE task_id=?",
                   (f"label:sdg:{pids[0]}",))
    got = taskqueue.next_tasks(ws, "label")
    bad = [{"task_id": t["task_id"], "answer": {"labels": [{"code": "6.4", "relevance": "main", "direction": "not_stated",
                                                              "confidence": 0.9, "quote": "not in the passage at all",
                                                              "reason": "x"}]}} for t in got["tasks"]]
    taskqueue.submit(ws, got["claim"], bad)
    r = taskqueue.submit(ws, got["claim"], bad)
    assert r["results"][0].get("moved_to") == "sonnet" and r["open"] == []
    assert taskqueue.next_tasks(ws, "label")["model"] == "sonnet"


def test_routing_on_the_claude_api_and_on_a_local_server(home, corpus, monkeypatch):
    pytest.importorskip("anthropic")
    from enlens_claims import ingest, profile
    from enlens_claims import home as core

    ws = home.create_project("A")
    ingest.ingest(ws, [corpus])
    profile.keyword_pass(ws, "sdg")
    srv, url = fake_servers.start("anthropic")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "good-key")
    real = fake_servers._answer

    def low(system, user, varied=False, model=""):
        out = real(system, user)
        for lb in out.get("labels", []):
            lb["confidence"] = 0.3
        return out

    monkeypatch.setattr(fake_servers, "_answer", low)
    try:
        home.update_settings({"allow_cloud": True, "backend": "anthropic"})
        be, model = core.make_backend(home.load_settings(), "good-key")
        assert model == "claude-opus-5-5" and be.router.route == "anthropic"
        r = profile.run_labels(ws, "sdg", be, model, limit=2)
        assert r["read"] == 2
        sent = [b["model"] for path, b in srv.requests if path.startswith("/v1/messages")]
        assert sent.count("claude-haiku-5-5") == 2 and sent.count("claude-sonnet-5-5") >= 1
        assert set(sent) <= {"claude-haiku-5-5", "claude-sonnet-5-5"}
    finally:
        srv.shutdown()

    # a local server with a small model: labels on it, their second readings on the main model after the run
    osrv, ourl = fake_servers.start("ollama")
    try:
        home.update_settings({"backend": "ollama", "ollama_url": ourl, "ollama_model": fake_servers.FAKE_MODEL,
                              "local_small_model": fake_servers.SECOND})
        be, model = core.make_backend(home.load_settings())
        r = profile.run_labels(ws, "sdg", be, model, limit=4)
        chats = [b["model"] for path, b in osrv.requests if path == "/api/chat"]
        assert set(chats) == {fake_servers.SECOND, fake_servers.FAKE_MODEL}
        first_large = chats.index(fake_servers.FAKE_MODEL)
        assert all(m == fake_servers.FAKE_MODEL for m in chats[first_large:])   # each model loaded once per run
    finally:
        osrv.shutdown()


def test_ask_a_stronger_model_on_a_check(api, corpus):
    _project(api, corpus)
    s = Session("P", wrong_first=False)
    s.start()
    try:
        r = api("POST", "/api/projects/P/checks", {"text": CLAIM, "k": 3, "expand": False})[1]
        hid = api.wait(r["job"]["id"], timeout=60)["result"]["hyp_id"]
        h = api("GET", f"/api/projects/P/hypotheses/{hid}")[1]
        rd = h["parts"][0]["rounds_info"][0]
        assert rd["task_id"].startswith("check:") and not rd["stepped_up"]
        st, r = api("POST", f"/api/projects/P/tasks/{rd['task_id']}/stronger", {})
        assert st == 200, r
        assert api.wait(r["job"]["id"], timeout=60)["state"] == "done"
        rd = api("GET", f"/api/projects/P/hypotheses/{hid}")[1]["parts"][0]["rounds_info"][0]
        assert rd["stepped_up"] and not rd["stronger_waiting"]
        assert api("POST", f"/api/projects/P/tasks/{rd['task_id']}/stronger", {})[0] == 400   # once at most
    finally:
        log = s.finish()
    assert ("check", "enlens-auditor") in {(e["kind"], e["helper"]) for e in log}


# ---------------------------------------------------------------------------------------------
# G5: local only; the plugin's files; the connector's tools over MCP
# ---------------------------------------------------------------------------------------------
def test_local_only_refuses_the_queue(home, corpus, monkeypatch):
    from enlens_claims import claude_setup, ingest, taskqueue

    ws = home.create_project("L")
    ingest.ingest(ws, [corpus])
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    with pytest.raises(ValueError, match="local only"):
        taskqueue.next_tasks(ws)
    with pytest.raises(ValueError, match="switched off"):
        home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    with pytest.raises(ValueError, match="local only"):
        claude_setup.write_plugin()


def test_the_plugin_files_are_as_claude_code_expects(home):
    from enlens_claims import claude_setup, routing

    root = claude_setup.write_plugin()
    assert claude_setup.check_files(root) == []
    plug = root / "plugins" / "enlens-run"
    assert json.loads((root / ".claude-plugin" / "marketplace.json").read_text())["plugins"][0]["source"] == \
        "./plugins/enlens-run"
    mcp = json.loads((plug / ".mcp.json").read_text())["mcpServers"]["enlens"]
    assert mcp["command"] == sys.executable and mcp["env"]["ENLENS_HOME"] == str(home.home())
    queue_tools = {claude_setup.TOOL_PREFIX + t for t in claude_setup.QUEUE_TOOLS}
    for f in sorted((plug / "agents").glob("*.md")):
        fm = claude_setup.frontmatter(f)
        assert fm["name"] == f.stem and fm["description"] and fm["model"] == routing.HELPER_MODEL[f.stem]
        assert {t.strip() for t in fm["tools"].split(",")} <= queue_tools
    skill = claude_setup.frontmatter(plug / "SKILL.md")
    assert skill["name"] == "enlens-run" and "$ARGUMENTS" in (plug / "SKILL.md").read_text()
    if shutil.which("claude"):
        import subprocess

        out = subprocess.run(["claude", "plugin", "validate", str(root)], capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stdout + out.stderr
    info = claude_setup.setup_info()
    assert info["ready"] and info["commands"][1] == "claude plugin install enlens-run@enlens"


def test_the_queue_through_the_connector(home, corpus):
    pytest.importorskip("mcp")
    from enlens_claims import ingest, profile, tasks, taskqueue

    ws = home.create_project("M")
    ingest.ingest(ws, [corpus])
    profile.keyword_pass(ws, "sdg")
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    plan = profile.label_plan(ws, "sdg")
    with tasks.queueing():
        profile.make_label_tasks(ws, "sdg", plan["passage_ids"], "haiku")
    out = fcc.run("M")    # through an in-process MCP client on the connector
    assert out["batches"] >= 1 and out["log"][0]["helper"] == "enlens-labeller"
    assert taskqueue.status(ws)["waiting"] == 0


# ---------------------------------------------------------------------------------------------
# the SDG pack and the existing backends are untouched
# ---------------------------------------------------------------------------------------------
def test_the_sdg_pack_makes_no_new_tasks_on_the_pilot(tmp_path):
    src = ROOT / "pilot" / "enlens.sqlite"
    if not src.exists():
        pytest.skip("the pilot workspace is not in this copy")
    from enlens_claims import tasks
    from enlens_claims.store import Workspace

    d = tmp_path / "pilot"
    d.mkdir()
    a, b = sqlite3.connect(src), sqlite3.connect(d / "enlens.sqlite")
    a.backup(b)
    a.close()
    b.close()
    shutil.copy2(ROOT / "pilot" / "config.json", d / "config.json")
    ws = Workspace.open(d)
    before = ws.scalar("SELECT COUNT(*) FROM tasks")
    made = tasks.make_split(ws) + tasks.make_extract(ws, per_target=6) + \
        tasks.make_verify_vca(ws, k=6)["tasks"]
    assert made == 0 and ws.scalar("SELECT COUNT(*) FROM tasks") == before
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE queued=1") == 0   # nothing of the pack is in the queue


def test_routing_leaves_a_local_main_model_alone(home, corpus):
    """With no small model chosen, a local server answers every kind with the main model, as in 0.7."""
    from enlens_claims import claimcheck, ingest, profile
    from enlens_claims import home as core

    ws = home.create_project("U")
    ingest.ingest(ws, [corpus])
    profile.keyword_pass(ws, "sdg")
    srv, url = fake_servers.start("ollama")
    try:
        home.update_settings({"backend": "ollama", "ollama_url": url, "ollama_model": fake_servers.FAKE_MODEL})
        be, model = core.make_backend(home.load_settings())
        profile.run_labels(ws, "sdg", be, model, limit=2)
        claimcheck.check_hypothesis(ws, CLAIM, be, model, k=3, decompose=True)
        assert {b["model"] for p, b in srv.requests if p == "/api/chat"} == {fake_servers.FAKE_MODEL}
        assert len({b["options"]["num_ctx"] for p, b in srv.requests if p == "/api/chat"}) == 1
    finally:
        srv.shutdown()


# ---------------------------------------------------------------------------------------------
# G6: an acceptance run per kind and model, through the queue
# ---------------------------------------------------------------------------------------------
def test_an_acceptance_run_is_scored(home, corpus, tmp_path):
    from enlens_claims import acceptance, evaluation, ingest, profile

    ref = home.create_project("Ref")
    ingest.ingest(ref, [corpus])
    profile.keyword_pass(ref, "sdg")
    folder = tmp_path / "acceptance"
    acceptance.make_samples(ref, folder)
    rows = acceptance._read(folder / "f2_labels.csv")
    for r in rows:
        cands = [c["code"] for c in profile.candidates_of(ref, "sdg", r["passage_id"])]
        r["codes"] = ";".join(cands[:1]) or "6.4"
    acceptance._write(folder / "f2_labels.csv", rows)
    (folder / "pass_marks.json").write_text(json.dumps({"label": -1}))
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    p = evaluation.prepare(ref, folder, "label", "haiku")
    assert p["tasks"] == len(rows) and p["next"] == f'In Claude Code: /enlens-run "{p["project"]}"'
    fcc.run(p["project"], tools=fcc.DirectTools(), wrong_first=False)
    again = evaluation.prepare(ref, folder, "label", "haiku", again=True)
    fcc.run(again["project"], tools=fcc.DirectTools(), wrong_first=False)
    out = evaluation.score(ref, folder, apply=True)
    row = next(r for r in out["runs"] if r["kind"] == "label" and r["model"] == "haiku")
    assert row["answered"] == row["tasks"] and row["score"] is not None and row["repeatability"] == 1.0
    assert out["chosen"]["label"]["claude"] == "haiku" and (folder / "MODEL_CHOICE.md").exists()
    assert home.load_settings()["task_models"]["claude"]["label"] == "haiku"
    assert "not measured yet" in (folder / "MODEL_CHOICE.md").read_text()   # the kinds not run


# ---------------------------------------------------------------------------------------------
# G7: carried over from 0.7
# ---------------------------------------------------------------------------------------------
def _docx(path: Path, paragraphs: list[tuple[str, str]], title: str | None = None) -> Path:
    import zipfile
    from xml.sax.saxutils import escape

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = ""
    for style, text in paragraphs:
        if style == "pagebreak":
            body += '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
            continue
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style != "p" else ""
        body += f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {w}><w:body>{body}</w:body></w:document>')
        if title:
            z.writestr("docProps/core.xml", '<cp:coreProperties xmlns:cp="c" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                                            f"<dc:title>{escape(title)}</dc:title></cp:coreProperties>")
    return path


def test_a_word_file_reads_like_its_pdf(tmp_path):
    from helpers import PAPER_A_PAGES, make_pdf

    from enlens_claims import ingest
    from enlens_claims.store import Workspace

    title = "Water footprint of electrolytic hydrogen in arid export regions"
    paras = []
    for i, page in enumerate(PAPER_A_PAGES):
        if i:
            paras.append(("pagebreak", ""))
        paras += [("Heading1", "Results")] if i == 1 else []
        paras += [("p", line) for line in page.split("\n")]
    d1, d2 = tmp_path / "w", tmp_path / "p"
    d1.mkdir(), d2.mkdir()
    _docx(d1 / "paper_a.docx", paras, title)
    make_pdf(d2 / "paper_a.pdf", PAPER_A_PAGES, title=title)
    out = {}
    for d in (d1, d2):
        ws = Workspace.create(d / "ws")
        assert ingest.ingest(ws, [d])["added"] == 1
        doc = ws.query("SELECT * FROM documents")[0]
        out[d.name] = {"title": doc["title"], "pages": doc["n_pages"], "kind": doc["kind"],
                       "words": " ".join(doc["text"].replace("Results", "").split()),
                       "passages": ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'"),
                       "paragraph_pages": {r[0] for r in ws.query("SELECT page FROM paragraphs")},
                       "headings": [r[0] for r in ws.query("SELECT text FROM headings")]}
    w, p = out["w"], out["p"]
    assert w["kind"] == "docx" and w["title"] == p["title"] and w["pages"] == p["pages"] == 3
    assert w["words"] == p["words"] and w["passages"] == p["passages"] and w["paragraph_pages"] == {1, 2, 3}
    assert "Results" in w["headings"]


def test_letter_spaced_words_are_joined_for_the_glossary_only(tmp_path):
    from enlens_claims import ingest, terms
    from enlens_claims.store import Workspace

    d = tmp_path / "docs"
    d.mkdir()
    good = ("The electrolyser runs on renewable power. Each electrolyser needs fresh water. A large electrolyser "
            "plant is planned, and the electrolyser stack degrades slowly. Net zero targets drive net zero plans.")
    (d / "a.txt").write_text("Electrolysers\n\n" + good + "\n")
    (d / "b.txt").write_text("Spaced report\n\nThe Elec tr oly ser runs on renewable power. The Elec tr oly ser needs "
                             "water. The Elec tr oly ser plant is planned. Net zero targets drive net zero plans.\n")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [d])
    terms.build(ws)
    labels = {r[0] for r in ws.query("SELECT label FROM terms")}
    assert not {"tr", "oly", "Elec", "Elec tr oly ser"} & labels
    tid = terms.find_term(ws, "electrolyser")
    docs = {r[0] for r in ws.query("SELECT DISTINCT doc_id FROM term_mentions WHERE term_id=?", (tid,))}
    assert len(docs) == 2                                  # the letter-spaced document mentions it too
    assert "net zero" in {x.lower() for x in labels}       # two words written apart stay two words
    assert "Elec tr oly ser" in ws.scalar("SELECT text FROM documents WHERE text LIKE '%Elec tr%'")  # text as read


def test_undo_a_removed_concept_link_and_theme_numbers(home, corpus):
    from enlens_claims import ingest, terms, themes

    ws = home.create_project("G")
    ingest.ingest(ws, [corpus, ROOT / "tools" / "demo_corpus"])
    terms.build(ws)
    ids = [r[0] for r in ws.query("SELECT term_id FROM terms ORDER BY df DESC LIMIT 2")]
    a, b = sorted(ids)
    with ws.connect() as cx:  # a link the AI proposed
        cx.execute("INSERT INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)", (a, b, "same", "model", 0.8, "x", "y", "m", "t"))
    terms.rebuild_concepts(ws)
    together = terms.concept_of(ws, a)
    assert b in together
    terms.set_link(ws, a, b, "reject")                     # "Not right"
    assert b not in terms.concept_of(ws, a)
    terms.set_link(ws, a, b, "undo")
    assert b in terms.concept_of(ws, a) and any(lk["a"] == a and lk["b"] == b for lk in terms.links(ws))
    with pytest.raises(ValueError):
        terms.set_link(ws, a, b, "undo")                   # nothing left to undo

    rid = themes.run(ws, k=5, seed=0)
    v = themes.view(ws, rid)
    assert [t["number"] for t in v["themes"]] == list(range(1, len(v["themes"]) + 1))
    first, second = v["themes"][0]["theme_id"], v["themes"][1]["theme_id"]
    themes.edit(ws, rid, "merge", second, first)
    v2 = themes.view(ws, rid)
    assert [t["number"] for t in v2["themes"]] == list(range(1, len(v2["themes"]) + 1))   # no gap after a merge
    merged = next(t for t in v2["themes"] if t["theme_id"] == first)
    assert merged["merged_from_names"][0]["theme_id"] == second   # the stable id stays for links


# ---------------------------------------------------------------------------------------------
# the command line: prepare, the queue, the plugin's set-up
# ---------------------------------------------------------------------------------------------
def test_command_line_prepare_queue_and_claude_setup(home, corpus, tmp_path, capsys):
    from enlens_claims import cli, ingest
    from enlens_claims.store import Workspace

    ws_dir = tmp_path / "cliws"
    assert cli.main(["--ws", str(ws_dir), "init"]) == 0
    ingest.ingest(Workspace.open(ws_dir), [corpus])
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    capsys.readouterr()
    assert cli.main(["--ws", str(ws_dir), "prepare", "label", "--limit", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["prepared"]["tasks"] == 2 and out["waiting"] == 2 and out["next"] == "In Claude Code: /enlens-run cliws"
    assert "cliws" in home.list_projects()                  # linked, so Claude Code can reach it
    assert cli.main(["--ws", str(ws_dir), "prepare", "check", CLAIM, "--no-expand"]) == 0
    assert json.loads(capsys.readouterr().out)["waiting"] == 3
    assert cli.main(["--ws", str(ws_dir), "queue", "status"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert [g["kind"] for g in st["groups"]] == ["check", "label"]
    assert cli.main(["--ws", str(ws_dir), "queue", "hold", "label"]) == 0
    assert json.loads(capsys.readouterr().out)["held"] == ["label"]
    # the shared installation: the queue answered here (the offline demo stands in for the Claude API)
    assert cli.main(["--ws", str(ws_dir), "queue", "go", "label"]) == 0
    capsys.readouterr()
    assert cli.main(["--ws", str(ws_dir), "queue", "run", "--backend", "baseline"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["answered"] == 3 and r["kinds"] == {"check": 1, "label": 2}
    assert cli.main(["--ws", str(ws_dir), "claude-setup", "--no-check"]) == 0
    text = capsys.readouterr().out
    assert "claude plugin install enlens-run@enlens" in text and "claude plugin marketplace add" in text


def test_claude_setup_starts_the_connector(home):
    pytest.importorskip("mcp")
    from enlens_claims import claude_setup

    claude_setup.write_plugin()
    r = claude_setup.check_connector()
    assert r["ok"], r
    assert set(claude_setup.QUEUE_TOOLS) <= set(r["tools"])

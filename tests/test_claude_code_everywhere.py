"""0.8.1: every task that needs an AI can be answered by Claude Code through the queue.

- the SDG pack (split, extract, verify-vca, verify-claims, audit-vca): `enlens prepare <kind>` puts its tasks in the
  queue, each kind on its routed model and helper; the audits keep their second model and go to the auditor;
- the model tests (label compare, the model test against a reference, repeatable answers) work with Claude Code:
  their tasks wait in the queue of a scratch copy that is removed afterwards, and nothing is stored.
"""
import json
import threading
import time

import pytest

import fake_claude_code as fcc
from test_app import home  # noqa: F401  (fixture)


def _baseline_answer(ws_of):
    """A fake Claude Code answer function that answers like the offline demo (it handles the SDG pack's kinds): the
    task is found by its prompt, so the demo gets the payload it reads."""
    from enlens_claims import prompts
    from enlens_claims.llm import BaselineBackend

    be = BaselineBackend()

    def answer(kind, system, prompt, model):
        prompt = prompt.split("\n\nYOUR PREVIOUS ANSWER HAD THESE PROBLEMS", 1)[0]
        for ws in ws_of():
            for t in ws.query("SELECT payload_json FROM tasks WHERE kind=? AND COALESCE(queued, 0)=1", (kind,)):
                payload = json.loads(t["payload_json"])
                if prompts.user_prompt(kind, payload) == prompt:
                    return json.loads(be.complete(kind, system, prompt, model, payload))
        raise AssertionError(f"no task with this {kind} prompt")
    return answer


@pytest.fixture
def sdg(home, corpus, vca_xlsx):  # noqa: F811
    from enlens_claims import ingest, sources, vca

    ws = home.create_project("S")
    vca.load_into(ws, vca_xlsx)
    ingest.ingest(ws, [corpus])
    sources.match(ws)
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    return ws


def test_the_router_covers_the_sdg_pack():
    from enlens_claims import routing

    r = routing.from_settings({"backend": "claude_code"})
    assert [r.first(k) for k in ("extract", "split", "verify", "verify_set", "audit")] == \
        ["sonnet", "opus", "opus", "opus", "opus"]
    assert r.step_up("extract") == "opus" and r.step_up("split") == "opus" and r.step_up("audit") is None
    assert [r.helper(k) for k in ("extract", "split", "verify", "verify_set", "audit")] == \
        ["enlens-extractor", "enlens-extractor", "enlens-checker", "enlens-checker", "enlens-auditor"]
    assert r.helper("verify_set", 1) == "enlens-auditor" and r.helper("extract", 1) == "enlens-extractor"
    f = routing.from_settings({"backend": "claude_code", "use_fable": True})
    assert f.first("audit") == "fable" and f.step_up("verify_set") == "fable"
    api_r = routing.from_settings({"backend": "anthropic"})
    assert api_r.call_model("extract") == "claude-sonnet-5-5"
    assert routing.certainty("extract", {"claims": [{"confidence": 0.4}, {"confidence": 0.9}]}) == 0.4
    assert routing.certainty("verify", {"verdict": "supports", "confidence": 0.7}) == 0.7
    # every kind a task can have, and every kind the queue hands out, has a model and a helper on Claude Code
    from enlens_claims import prompts, taskqueue, tasks

    for k in set(tasks.KINDS) | set(taskqueue.KINDS) | set(prompts.VERSIONS):
        assert r.first(k) and r.helper(k) in routing.HELPER_MODEL, k
        assert k in taskqueue.BATCH and k in taskqueue.NOUN, k


def test_the_sdg_pack_through_the_queue(sdg, home):  # noqa: F811
    from enlens_claims import routing, taskqueue, tasks
    from enlens_claims.retrieve import screen

    r = routing.from_settings(home.load_settings(), route="claude_code")
    made = tasks.prepare_sdg(sdg, "split", r)
    assert made["tasks"] >= 1 and made["queued"] == made["tasks"] and made["model"] == "opus"
    # the task records the API id of its model, so `enlens run --backend anthropic` can still answer it
    assert {x[0] for x in sdg.query("SELECT model FROM tasks WHERE kind='split'")} == {"claude-opus-5-5"}
    g = taskqueue.status(sdg, "S")["groups"]
    assert [(x["kind"], x["model"], x["helper"]) for x in g] == [("split", "opus", "enlens-extractor")]

    cc = fcc.FakeClaudeCode(fcc.DirectTools(), answer=_baseline_answer(lambda: [sdg]))
    cc.run("S")
    assert sdg.scalar("SELECT COUNT(*) FROM tasks WHERE kind='split' AND status='done'") == made["tasks"]
    assert sdg.scalar("SELECT COUNT(*) FROM vca_claims") >= 1
    assert {tuple(x) for x in sdg.query("SELECT DISTINCT route, helper, model FROM results WHERE kind='split' AND "
                                        "valid=1")} == {("Claude Code", "enlens-extractor", "opus")}

    v = tasks.prepare_sdg(sdg, "verify-vca", r, k=3)
    screen(sdg)
    e = tasks.prepare_sdg(sdg, "extract", r)
    assert v["tasks"] >= 1 and e["tasks"] >= 1 and e["model"] == "sonnet"
    kinds = {(x["kind"], x["helper"]) for x in taskqueue.status(sdg, "S")["groups"]}
    assert kinds == {("verify_set", "enlens-checker"), ("extract", "enlens-extractor")}
    # extract's batch stays within the connector's cap with its long system prompt (the 169 targets)
    got = taskqueue.next_tasks(sdg, "extract", taken_by="t")
    from enlens_claims.llm import estimate_tokens

    assert estimate_tokens(got["system"]) + sum(estimate_tokens(t["prompt"]) for t in got["tasks"]) < \
        taskqueue.CONNECTOR_CAP
    taskqueue.release(sdg, got["claim"])
    cc.run("S")
    assert taskqueue.status(sdg, "S")["waiting"] == 0
    assert sdg.scalar("SELECT COUNT(*) FROM tasks WHERE kind IN ('verify_set', 'extract') AND status != 'done'") == 0
    assert sdg.scalar("SELECT COUNT(*) FROM verifications WHERE subject_kind='vca_claim'") >= 1

    # the audit: a second model on the answered VCA checks, routed as "audit" to the auditor and kept on its model
    home.update_settings({"use_fable": True})
    r = routing.from_settings(home.load_settings(), route="claude_code")
    a = tasks.prepare_sdg(sdg, "audit-vca", r, sample=1.0)
    assert a["tasks"] >= 1 and a["model"] == "fable"
    g = taskqueue.status(sdg, "S")["groups"]
    assert [(x["kind"], x["model"], x["helper"]) for x in g] == [("verify_set", "fable", "enlens-auditor")]
    cc.run("S")
    assert sdg.scalar("SELECT COUNT(*) FROM verifications WHERE subject_kind='vca_claim_audit'") >= 0
    assert {tuple(x) for x in sdg.query("SELECT DISTINCT helper, model FROM results WHERE task_id LIKE '%:audit:%' "
                                        "AND valid=1")} == {("enlens-auditor", "fable")}
    assert sdg.scalar("SELECT COUNT(*) FROM tasks WHERE role='audit' AND step=1") == 0   # an audit never steps up


def test_prepare_on_the_command_line_and_answering_it_here(sdg, home, capsys):  # noqa: F811
    from enlens_claims import cli

    assert cli.main(["--ws", str(sdg.root), "prepare", "split"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["prepared"]["tasks"] >= 1 and out["waiting"] == out["prepared"]["tasks"]
    assert out["next"].startswith("In Claude Code: /enlens-run")
    assert cli.main(["--ws", str(sdg.root), "prepare", "audit-vca", "--model", "gpt-4"]) == 1
    assert "haiku, sonnet, opus or fable" in capsys.readouterr().err
    # a shared installation answers the same queue here, with the routed models
    assert cli.main(["--ws", str(sdg.root), "queue", "run", "--backend", "baseline"]) == 0
    assert sdg.scalar("SELECT COUNT(*) FROM tasks WHERE kind='split' AND status != 'done'") == 0


def test_the_sdg_pack_stays_out_of_the_queue_unless_prepared(sdg):
    """make-tasks and `enlens run` work as before: nothing of the pack enters the queue on its own."""
    from enlens_claims import tasks
    from enlens_claims.llm import BaselineBackend

    tasks.make_split(sdg)
    assert sdg.scalar("SELECT COUNT(*) FROM tasks WHERE queued=1") == 0
    tasks.run(sdg, "split", BaselineBackend())
    assert sdg.scalar("SELECT COUNT(*) FROM tasks WHERE kind='split' AND status='done'") >= 1


# ---------------------------------------------------------------------------------------------
# the model tests with Claude Code
# ---------------------------------------------------------------------------------------------
class _Answering(threading.Thread):
    """A fake Claude Code session that answers every project's queue until stopped."""

    def __init__(self, answer=None):
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.answer = answer
        self.errors: list[str] = []

    def run(self):
        from enlens_claims import home as core

        while not self.stop.is_set():
            for name in core.list_projects():
                try:
                    fcc.FakeClaudeCode(fcc.DirectTools(), wrong_first=False, answer=self.answer).run(name)
                except Exception as e:  # noqa: BLE001 - a copy removed meanwhile
                    self.errors.append(repr(e))
            time.sleep(0.1)


def test_repeatable_says_claude_code_takes_no_seed():
    from enlens_claims.llm import ClaudeCodeBackend, repeatable

    r = repeatable(ClaudeCodeBackend(), "opus")
    assert r["repeatable"] is False and "seed" in r["note"]


def test_label_compare_with_claude_code(home, corpus):  # noqa: F811
    from enlens_claims import home as core
    from enlens_claims import ingest, profile
    from enlens_claims.llm import BaselineBackend

    ws = home.create_project("L")
    ingest.ingest(ws, [corpus])
    profile.keyword_pass(ws, "sdg")
    profile.run_labels(ws, "sdg", BaselineBackend(), "baseline", limit=4)
    before = ws.counts()
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    be, model = core.make_backend(core.load_settings())
    s = _Answering()
    s.start()
    try:
        res = profile.compare_sample(ws, "sdg", be, "haiku", n=3)
    finally:
        s.stop.set()
        s.join(5)
    assert res["compared"] == 3 and res["model"] == "haiku" and res["errors"] == 0
    assert ws.counts() == before                                             # nothing stored in the project
    assert [n for n in core.list_projects() if n != "L"] == []              # the scratch copy is gone


def test_benchmark_with_claude_code(home, corpus, vca_xlsx):  # noqa: F811
    from enlens_claims import benchmark, ingest, sources, tasks, vca
    from enlens_claims import home as core
    from enlens_claims.llm import BaselineBackend
    from enlens_claims.retrieve import screen

    ref = home.create_project("R")
    vca.load_into(ref, vca_xlsx)
    ingest.ingest(ref, [corpus])
    sources.match(ref)
    tasks.make_split(ref, model="m")
    tasks.run(ref, "split", BaselineBackend())
    tasks.make_verify_vca(ref, model="ref", k=3)
    tasks.run(ref, "verify_set", BaselineBackend())
    screen(ref)
    tasks.make_extract(ref, model="ref")
    tasks.run(ref, "extract", BaselineBackend())
    before = ref.counts()
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    be, _m = core.make_backend(core.load_settings())
    s = _Answering(answer=_baseline_answer(lambda: [core.open_project(n) for n in core.list_projects()]))
    s.start()
    try:
        res = benchmark.run(ref, be, None, sample=3)
    finally:
        s.stop.set()
        s.join(5)
    assert ref.counts() == before
    vs, ex = res["kinds"]["verify_set"], res["kinds"]["extract"]
    assert vs["tasks"] >= 1 and vs["errors"] == 0 and vs["same_status"] == 1.0
    assert ex["tasks"] >= 1 and ex["same_has_claims"] == 1.0
    assert res["models"] == {"verify_set": "opus", "extract": "sonnet"}     # each kind on its routed model
    assert [n for n in core.list_projects() if n != "R"] == []


def test_the_app_runs_the_model_tests_with_claude_code(home, corpus):  # noqa: F811
    """The buttons that were refused with Claude Code in 0.8 (compare labels, repeatable answers) now work."""
    from enlens_claims import home as core
    from enlens_claims import ingest, profile
    from enlens_claims.gui.server import make_server
    from enlens_claims.llm import BaselineBackend
    from test_app import Api

    ws = home.create_project("G")
    ingest.ingest(ws, [corpus])
    profile.keyword_pass(ws, "sdg")
    profile.run_labels(ws, "sdg", BaselineBackend(), "baseline", limit=4)
    home.update_settings({"allow_claude_code": True, "backend": "claude_code", "embed_backend": "off"})
    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    s = _Answering()
    s.start()
    try:
        st, r = api("POST", "/api/servers/repeatable", {})
        assert st == 200 and r["repeatable"] is False and "no seed" in r["note"]
        st, r = api("POST", "/api/projects/G/profile/compare", {"framework": "sdg", "n": 5})
        assert st == 200, r
        j = api.wait(r["job"]["id"], timeout=60)
        assert j["state"] == "done", j
        assert j["result"]["model"] == "haiku" and j["result"]["compared"] >= 1
    finally:
        s.stop.set()
        s.join(5)
        srv.shutdown()
    assert core.list_projects() == ["G"]

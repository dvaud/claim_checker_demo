"""Agreement between routes (roadmap I5, 0.18.1): the local model and Claude answer the same sample, kappa per kind.
Stand-in backends only: the local model server points at a dead port, Claude is a stub; nothing is loaded or sent."""
from __future__ import annotations

import json

import pytest

from enlens_claims import access, benchmark, ingest, tasks
from test_app import api, home  # noqa: F401  (fixtures)

LOCAL, CLAUDE = "local model server", "Claude API"


class Local:
    """A local model server (never reached). `grades`: the verdicts it gives the two excerpts, by claim name."""
    name = "ollama"
    base_url = "http://127.0.0.1:9"

    def __init__(self, grades=None):
        self.grades, self.calls = grades or {}, []

    def complete(self, kind, system, user, model, payload):
        self.calls.append(payload.get("claim"))
        return _answer(self.grades.get(payload.get("claim"), ("supports", "refutes")))


class Claude:
    """The Claude API backend: always supports then refutes."""
    name = "anthropic"

    def __init__(self):
        self.calls = []

    def complete(self, kind, system, user, model, payload):
        self.calls.append(payload.get("claim"))
        return _answer(("supports", "refutes"))


def _answer(verdicts):
    return json.dumps({"evidence": [{"passage": i, "verdict": v, "confidence": 0.9, "quote": "some words here"}
                                    for i, v in enumerate(verdicts, 1)]})


def _task(ws, name, pids, kind="check", local=None, claude=None, **extra):
    payload = {"claim": name, "passages": [{"passage_id": p, "text": "text", "title": "T"} for p in pids], **extra}
    with ws.connect() as cx:
        tasks._insert_task(cx, f"{kind}:{name}", kind, "sonnet", payload)
        cx.execute("UPDATE tasks SET status='done' WHERE task_id=?", (f"{kind}:{name}",))
        for i, (route, raw) in enumerate([(LOCAL, local), (CLAUDE, claude)]):
            if raw:
                cx.execute("INSERT INTO results(task_id, attempt, kind, model, raw_json, valid, route) "
                           "VALUES (?,?,?,?,?,1,?)", (f"{kind}:{name}", i + 1, kind, "m", raw, route))
    return f"{kind}:{name}"


def _counts(ws):
    return {t: ws.scalar(f"SELECT COUNT(*) FROM {t}") for t in ("tasks", "results", "verifications", "claims")}


@pytest.fixture
def two_pids(loaded):
    doc = loaded.scalar("SELECT doc_id FROM passages GROUP BY doc_id HAVING COUNT(*) >= 2 ORDER BY doc_id LIMIT 1")
    return [r[0] for r in loaded.query("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY passage_id LIMIT 2", (doc,))]


def test_kappa_on_known_answers():
    assert benchmark.kappa([("a", "a"), ("b", "b"), ("c", "c"), ("a", "a")]) == 1.0
    assert benchmark.kappa([("a", "b"), ("b", "a"), ("a", "b"), ("b", "a")]) == -1.0
    # 6 of 8 the same; marginals 0.5/0.5 against 0.25/0.75: pe 0.5, kappa 0.5
    pairs = [("s", "s")] * 2 + [("r", "r")] * 4 + [("s", "r")] * 2
    assert benchmark.kappa(pairs) == 0.5
    # three categories: po 0.5; marginals a .5/.5, b .25/.5, c .25/0 -> pe 0.375, kappa 0.2
    assert benchmark.kappa([("a", "a"), ("b", "b"), ("a", "b"), ("c", "a")]) == pytest.approx(0.2, abs=0.001)
    assert benchmark.kappa([("a", "a")] * 3) is None and benchmark.kappa([]) is None


def test_the_verdict_has_stated_thresholds():
    assert benchmark.verdict_sentence("label", 0.84, 0.92, 50).startswith(
        "Good enough for labels: the local model agrees with Claude on 92% of decisions (kappa 0.84)")
    assert benchmark.verdict_sentence("check", 0.7, 0.8, 50).startswith("Fair for checking claims")
    assert benchmark.verdict_sentence("link", 0.59, 0.7, 50).startswith("Not good enough for links")
    assert benchmark.verdict_sentence("link", 0.8, 0.9, 5).startswith("Good enough")      # 0.8 is the line
    assert "Too little variety" in benchmark.verdict_sentence("label", None, 1.0, 20)


def test_decisions_per_kind():
    chk = {"passages": [{}, {}, {}]}
    out = {"evidence": [{"passage": 1, "verdict": "supports"}, {"passage": "P3", "verdict": "partial"}]}
    assert benchmark._decisions("check", chk, out) == {"P1": "supports", "P2": "none", "P3": "partially_supports"}
    lab = {"candidates": [{"code": "6.4"}, {"code": "7.2"}], "framework": "sdg"}
    got = benchmark._decisions("label", lab, {"labels": [{"code": "6.4"}]})
    assert got == {"6.4": "yes", "7.2": "no"}
    lnk = {"terms": [{}, {}, {}]}
    got = benchmark._decisions("link", lnk, {"relations": [{"a": 1, "b": 2, "relation": "same"},
                                                           {"a": 2, "b": 3, "relation": "related"}]})
    assert got == {"1-2": "same", "1-3": "none", "2-3": "related"}
    with pytest.raises(ValueError, match="no decision"):
        benchmark._decisions("theme", {}, {})


def test_kappa_per_kind_from_the_answers(loaded, two_pids):
    ws = loaded
    agree, differ = _answer(("supports", "refutes")), _answer(("refutes", "refutes"))
    for n in ("C1", "C2"):
        _task(ws, n, two_pids, claude=agree)
    for n in ("C3", "C4"):
        _task(ws, n, two_pids, claude=agree)
    local = Local({"C3": ("refutes", "refutes"), "C4": ("refutes", "refutes")})
    before = _counts(ws)
    out = benchmark.agreement(ws, "check", 30, (local, "small"), Claude(), claude_model="stub")
    assert out["n"] == 4 and out["decisions"] == 8 and out["failed"] == 0
    assert out["agree"] == 0.75 and out["kappa"] == 0.5          # 6 of 8; marginals .5/.5 against .25/.75
    assert out["verdict"].startswith("Not good enough for checking claims")
    assert out["asked"] == {"local": 4, "claude": 0} and sorted(local.calls) == ["C1", "C2", "C3", "C4"]
    assert _counts(ws) == before                                  # a measurement: nothing stored in the project
    del differ

    # none in agreement: the local model always says the opposite of Claude
    for n in ("C1", "C2", "C3", "C4"):
        local.grades[n] = ("refutes", "supports")
    out = benchmark.agreement(ws, "check", 30, (local, "small"), Claude(), claude_model="stub")
    assert out["agree"] == 0.0 and out["kappa"] == -1.0
    # perfect: the same answers
    for n in ("C1", "C2", "C3", "C4"):
        local.grades[n] = ("supports", "refutes")
    out = benchmark.agreement(ws, "check", 30, (local, "small"), Claude(), claude_model="stub")
    assert out["agree"] == 1.0 and out["kappa"] == 1.0 and out["verdict"].startswith("Good enough for checking claims")


def test_stored_answers_are_reused_and_only_cloud_tasks_go_to_claude(loaded, two_pids):
    ws = loaded
    both = _task(ws, "Both", two_pids, local=_answer(("supports", "refutes")), claude=_answer(("supports", "refutes")))
    _task(ws, "OnlyClaude", two_pids, claude=_answer(("supports", "refutes")))
    _task(ws, "OnlyLocal", two_pids, local=_answer(("supports", "refutes")))
    _task(ws, "Neither", two_pids)
    # a task on a document Claude may not read: left out, never sent
    other = ws.scalar("SELECT doc_id FROM passages WHERE doc_id != (SELECT doc_id FROM passages WHERE passage_id=?) "
                      "LIMIT 1", (two_pids[0],))
    other_p = ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? LIMIT 1", (other,))
    _task(ws, "Private", [other_p], local=_answer(("supports",)))
    access.set_documents(ws, [other], "local")
    plan = benchmark.agreement_plan(ws, "check", 30)
    assert plan == {"kind": "check", "n": 4, "ask_local": 2, "ask_claude": 2, "left_out": 1}
    local, claude = Local(), Claude()
    out = benchmark.agreement(ws, "check", 30, (local, "small"), claude, claude_model="stub")
    assert sorted(local.calls) == ["Neither", "OnlyClaude"] and sorted(claude.calls) == ["Neither", "OnlyLocal"]
    assert "Private" not in local.calls + claude.calls
    assert out["asked"] == {"local": 2, "claude": 2} and out["left_out"] == 1 and out["n"] == 4
    by = {i["task_id"]: i for i in out["items"]}
    assert by[both]["local"] == by[both]["claude"] == "stored"
    # every task asked of Claude went into the ledger of what left this computer, with the feature named
    assert {r[0] for r in ws.query("SELECT feature FROM ai_sent")} == {"check (agreement)"}


def test_claude_code_answers_on_a_scratch_copy(loaded, two_pids, monkeypatch):
    ws = loaded
    _task(ws, "A", two_pids, local=_answer(("supports", "refutes")))
    _task(ws, "B", two_pids, local=_answer(("supports", "refutes")), claude=_answer(("supports", "refutes")))
    seen = []

    def fake(ws_, items, backend, purpose, should_stop=None):
        seen.append([(i[0], i[1], i[3]) for i in items])
        return {i[0]: _answer(("supports", "supports")) for i in items}, {}

    from enlens_claims import taskqueue
    monkeypatch.setattr(taskqueue, "answer_on_copy", fake)

    class Code:
        name = "claude_code"
        router = None

    out = benchmark.agreement(ws, "check", 30, (Local(), "small"), Code())
    assert len(seen) == 1 and [s[0] for s in seen[0]] == ["check:A"]      # B already has Claude's answer
    assert seen[0][0][2] in ("haiku", "sonnet", "opus", "fable")
    assert out["asked"] == {"local": 0, "claude": 1} and out["decisions"] == 4
    assert out["agree"] == 0.75                                         # one of A's two excerpts differs


def test_a_task_that_cannot_be_compared_is_counted_not_fatal(loaded, two_pids):
    _task(loaded, "Good", two_pids, claude=_answer(("supports", "refutes")))
    _task(loaded, "Bad", two_pids, claude="not json at all")
    out = benchmark.agreement(loaded, "check", 30, (Local(), "small"), Claude(), claude_model="stub")
    assert out["failed"] == 1 and out["compared"] == 1


def test_theme_and_the_like_have_no_decision(loaded, two_pids):
    with pytest.raises(ValueError, match="no decision"):
        benchmark.agreement_plan(loaded, "theme")
    assert benchmark.agreement_kinds(loaded) == []
    _task(loaded, "X", two_pids, kind="reread", claude=_answer(("supports", "supports")))
    assert [k["kind"] for k in benchmark.agreement_kinds(loaded)] == ["reread"]


def test_the_routes(api, home, corpus, monkeypatch):  # noqa: F811
    ws = home.create_project("A")
    ingest.ingest(ws, [corpus])
    pids = [r[0] for r in ws.query("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 2")]
    for n in ("C1", "C2", "C3"):
        _task(ws, n, pids, claude=_answer(("supports", "refutes")))
    st, r = api("GET", "/api/projects/A/agreement/plan")
    assert st == 200 and [k["kind"] for k in r["kinds"]] == ["check"] and r["plan"] is None
    assert "Claude Code or the Claude API" in r["problem"] or "local model" in r["problem"]
    home.update_settings({"allow_cloud": True, "backend": "anthropic", "restricted_server": "ollama",
                          "restricted_model": "small"})
    st, r = api("GET", "/api/projects/A/agreement/plan?kind=check&n=10")
    assert st == 200 and r["problem"] is None
    assert r["plan"] == {"kind": "check", "n": 3, "ask_local": 3, "ask_claude": 0, "left_out": 0}
    assert api("GET", "/api/projects/A/agreement/plan?kind=theme")[0] == 400
    assert api("POST", "/api/projects/A/agreement", {"kind": "theme"})[0] == 400
    local, claude = Local(), Claude()
    monkeypatch.setattr(access.Readers, "local", lambda self: (local, "small"))
    monkeypatch.setattr(home, "make_backend", lambda s, key=None, kinds=(): (claude, "stub"))
    before = _counts(ws)
    st, r = api("POST", "/api/projects/A/agreement", {"kind": "check", "n": 10})
    assert st == 200 and r["job"]["kind"] == "agreement", r
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job
    assert job["result"]["kappa"] is None or job["result"]["kappa"] == 1.0
    assert job["result"]["agree"] == 1.0 and job["result"]["asked"] == {"local": 3, "claude": 0}
    assert _counts(ws) == before
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    assert api("POST", "/api/projects/A/agreement", {"kind": "check"})[0] == 400

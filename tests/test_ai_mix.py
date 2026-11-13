"""The AI mix (roadmap I1, I2, I4) and how much thought Claude gives each kind of task (N2), 0.18.1."""
import json

import pytest

from enlens_claims import claimcheck, home, routing, taskqueue, tasks

CLAIM = "Green hydrogen production can increase water stress in arid regions."
MIX = {"backend": "claude_code", "ai_mix": "mostly_local", "restricted_server": "ollama", "restricted_model": "small"}


# ---------------------------------------------------------------------------------------------
# N2: how much thought
# ---------------------------------------------------------------------------------------------
def test_balanced_is_the_table_of_before():
    plain, bal = routing.Router(route="claude_code"), routing.Router(route="claude_code", thought="balanced")
    for k in routing.KINDS:
        assert (plain.first(k), plain.step_up(k)) == (bal.first(k), bal.step_up(k))
        assert bal.effort(k) is None


def test_efficient_and_intelligence_move_each_kind_one_step():
    eff, smart = (routing.Router(route="claude_code", thought=t) for t in ("efficient", "intelligence"))
    assert eff.first("expand") == "haiku" and eff.step_up("expand") == "opus"
    assert eff.first("check") == "sonnet"  # judging excerpts never goes below Sonnet
    assert smart.first("label") == "sonnet" and smart.step_up("label") == "opus"
    assert smart.first("check") == "opus" and smart.step_up("check") is None  # no stronger model, Fable being off
    assert routing.Router(route="claude_code", thought="intelligence", fable=True).step_up("check") == "fable"
    assert eff.effort("label") == "low" and smart.effort("check") == "high"
    free = routing.Router(route="claude_code", thought="intelligence", tier="free")
    assert free.first("expand") == "sonnet" and free.first("check") == "sonnet"  # no Opus on Free
    # a model chosen per task in Settings comes first
    assert routing.Router(route="claude_code", thought="efficient", overrides={"expand": "opus"}).first("expand") == "opus"
    # a local model keeps its own choice
    loc = routing.Router(route="local", thought="intelligence", large="big", small="small")
    assert loc.first("label") == "small" and loc.first("check") == "big"


def test_thought_is_a_kept_setting():
    for bad in ({"claude_thought": "fast"}, {"ai_mix": "all_local"}, {"at_limit": "stop"}):
        with pytest.raises(ValueError, match=next(iter(bad))):
            home.clean_settings(bad)
    s = home.load_settings()
    assert s["claude_thought"] == "balanced" and s["ai_mix"] == "best" and s["at_limit"] == "wait"
    r = routing.from_settings({**s, "backend": "claude_code", "claude_thought": "intelligence"})
    assert r.thought == "intelligence" and r.first("expand") == "opus"


# ---------------------------------------------------------------------------------------------
# I1: a route per kind of task
# ---------------------------------------------------------------------------------------------
def test_mix_needs_claude_and_a_local_model():
    assert routing.mix_kinds({**MIX, "ai_mix": "best"}) == frozenset()
    assert routing.mix_kinds({**MIX, "restricted_model": ""}) == frozenset()
    assert routing.mix_kinds({**MIX, "backend": "ollama"}) == frozenset()
    assert routing.mix_kinds({**MIX, "backend": "anthropic"}) == frozenset()  # Claude Code only, for now
    bal = routing.mix_kinds({**MIX, "ai_mix": "balanced"})
    assert {"label", "link", "expand", "decompose", "theme", "resolve"} <= bal and "check" not in bal
    most = routing.mix_kinds(MIX)
    assert "check" in most and "second" not in most and "audit" not in most


# ---------------------------------------------------------------------------------------------
# I2: the local model first, Claude when it is unsure
# ---------------------------------------------------------------------------------------------
class _Local:
    """A local model server on this computer (never reached): answers each excerpt as told."""
    name = "ollama"
    base_url = "http://127.0.0.1:9"

    def __init__(self, verdict="supports", confidence=0.9, quote_ok=True):
        self.verdict, self.confidence, self.quote_ok, self.calls = verdict, confidence, quote_ok, 0

    def complete(self, kind, system, user, model, payload):
        self.calls += 1
        if kind == "expand":
            return '{"terms": ["water", "aquifer"]}'
        ev = [{"passage": i, "verdict": self.verdict, "confidence": self.confidence,
               "quote": " ".join(p["text"].split()[:6]) if self.quote_ok else "words that are nowhere"}
              for i, p in enumerate(payload["passages"], 1)]
        return json.dumps({"evidence": ev})


@pytest.fixture
def mixed(loaded, monkeypatch):
    s = {**home.load_settings(), **MIX}
    monkeypatch.setattr(home, "load_settings", lambda strict=False: dict(s))
    return loaded, s


def _check_task(ws):
    cid = claimcheck.new_claim(ws, CLAIM)
    picked = [dict(r) for r in ws.query("SELECT p.passage_id, p.doc_id, d.title, p.page, p.text FROM passages p "
                                        "JOIN documents d ON d.doc_id=p.doc_id ORDER BY p.passage_id LIMIT 2")]
    with ws.connect() as cx, tasks.queueing(True):
        tasks._insert_task(cx, f"check:{cid}", "check", "sonnet", claimcheck._payload(ws, cid, CLAIM, None, None, picked))
    return f"check:{cid}"


def _row(ws, tid):
    return ws.query("SELECT status, step, again, queued FROM tasks WHERE task_id=?", (tid,))[0]


def test_a_sure_local_answer_stands(mixed):
    ws, _s = mixed
    tid = _check_task(ws)
    assert tasks.answer_locally_first(ws, tid, _Local(), "small") is None
    r = _row(ws, tid)
    assert (r["status"], r["step"], r["again"]) == ("done", 0, 0)
    assert ws.scalar("SELECT route FROM results WHERE task_id=? ORDER BY attempt DESC LIMIT 1", (tid,)) != "Claude Code"


@pytest.mark.parametrize("local, why", [(_Local(confidence=0.4), "unsure"), (_Local(verdict="refutes"), "decides")])
def test_unsure_or_deciding_goes_up_to_claude(mixed, local, why):
    ws, _s = mixed
    tid = _check_task(ws)
    assert tasks.answer_locally_first(ws, tid, local, "small") == "again"
    r = _row(ws, tid)
    assert (r["status"], r["step"], r["again"], r["queued"]) == ("done", 1, 1, 1)  # the local answer counts meanwhile


def test_rejected_three_times_goes_to_claude(mixed):
    ws, _s = mixed
    tid = _check_task(ws)
    local = _Local(quote_ok=False)
    assert tasks.answer_locally_first(ws, tid, local, "small") == "retry" and local.calls == tasks.MAX_ATTEMPTS
    r = _row(ws, tid)
    assert (r["status"], r["step"], r["queued"]) == ("pending", 1, 1)


def test_claude_code_leaves_the_local_share_alone(mixed):
    ws, _s = mixed
    tid = _check_task(ws)
    st = taskqueue.status(ws, "p")
    assert st["for_local"] == 1 and st["waiting"] == 0 and not st["groups"]
    assert taskqueue.next_tasks(ws, "check")["claim"] is None
    tasks.answer_locally_first(ws, tid, _Local(confidence=0.3), "small")  # unsure: now Claude's
    st = taskqueue.status(ws, "p")
    assert st["for_local"] == 0 and st["waiting"] == 1
    got = taskqueue.next_tasks(ws, "check")
    assert [t["task_id"] for t in got["tasks"]] == [tid] and got["model"] == "opus"  # the stronger model of checks


def test_an_app_run_on_claude_code_asks_the_local_model_first(mixed, monkeypatch):
    ws, _s = mixed
    tid = _check_task(ws)
    local = _Local()
    monkeypatch.setattr(tasks, "mix_local", lambda settings=None: (local, "small"))
    from enlens_claims.llm import ClaudeCodeBackend

    ok, _e = tasks.run_one(ws, tid, ClaudeCodeBackend())  # answered here: nothing waits for Claude Code
    assert ok and local.calls == 1 and _row(ws, tid)["status"] == "done"


def test_the_follower_answers_the_mix_share_of_a_check(mixed, monkeypatch):
    ws, s = mixed
    tid = _check_task(ws)
    hyp = ws.scalar("SELECT hyp_id FROM user_claims")
    assert [w["task_id"] for w in claimcheck.local_waiting(ws, [hyp])] == [tid]

    class R:  # access.Readers with the local model chosen
        read, memory_short, local_problem = 0, None, None

        def local(self):
            return local, "small"

        def stopped(self):
            return False
    local = _Local()
    assert claimcheck.run_local_parts(ws, [hyp], R()) == 1 and _row(ws, tid)["status"] == "done"
    assert claimcheck.local_waiting(ws, [hyp]) == []


def test_answer_mix_waiting_takes_only_the_mix_kinds(mixed):
    ws, _s = mixed
    tid = _check_task(ws)
    with ws.connect() as cx, tasks.queueing(True):
        tasks._insert_task(cx, "second:x", "second", "opus", json.loads(ws.scalar(
            "SELECT payload_json FROM tasks WHERE task_id=?", (tid,))))
    out = tasks.answer_mix_waiting(ws, _Local(), "small")
    assert out == {"answered": 1, "to_claude": 0}
    assert _row(ws, "second:x")["status"] == "pending"


# ---------------------------------------------------------------------------------------------
# I4: at the plan's limit
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("tail, said", [
    ("…\nClaude AI usage limit reached|1731500000", "Claude Code reached your plan's usage limit."),
    ("You've hit your limit · resets 3pm", "Claude Code reached your plan's usage limit (it resets 3pm)."),
    ("Done: 40 answers stored.", None)])
def test_the_plan_limit_is_recognised(tail, said):
    assert taskqueue.limit_reached({"running": False, "report": tail}) == said
    assert taskqueue.limit_reached({"running": True, "report": tail}) is None


def test_without_a_local_model_the_lent_task_goes_to_claude(mixed, monkeypatch):
    """Review, 0.18.1: the chosen local model is missing (deleted from Ollama): Claude Code must not wait for it."""
    ws, _s = mixed
    tid = _check_task(ws)
    monkeypatch.setattr(tasks, "mix_local", lambda settings=None: None)
    from enlens_claims.llm import BackendError, ClaudeCodeBackend

    be = ClaudeCodeBackend()
    be.should_stop = lambda: True  # stop waiting at once: what matters is where the task now is
    with pytest.raises(BackendError):
        tasks.run_one(ws, tid, be)
    assert _row(ws, tid)["step"] == 1 and taskqueue.next_tasks(ws, "check")["claim"]
    tid2 = _check_task(ws)
    assert tasks.answer_mix_waiting(ws) == {"answered": 0, "to_claude": 1} and _row(ws, tid2)["step"] == 1


def test_the_local_model_leaves_a_task_claude_code_holds(mixed):
    ws, _s = mixed
    tid = _check_task(ws)
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET claimed_by='q123', claimed_at=? WHERE task_id=?",
                   (__import__("enlens_claims.store", fromlist=["now"]).now(), tid))
    local = _Local()
    assert tasks.answer_locally_first(ws, tid, local, "small") is None and local.calls == 0
    assert _row(ws, tid)["status"] == "pending"
    # and a task it answers is held while it does, then let go
    tid2 = _check_task(ws)
    tasks.answer_locally_first(ws, tid2, _Local(), "small")
    assert ws.scalar("SELECT claimed_by FROM tasks WHERE task_id=?", (tid2,)) is None

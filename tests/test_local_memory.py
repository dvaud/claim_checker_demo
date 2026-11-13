"""0.13.11: the local model for documents marked "Only a local AI" shows what it does, and is not started on a
computer without room for it.

Found in a user test: with Claude Code as the AI, a check whose key document was marked Only a local AI loaded a
7.6 GB model on a 16 GB Mac that had 2.7 GB free. The computer all but froze for minutes, while the page said only
"Waiting for Claude Code". Now the app says the local model is reading, with its progress and Stop; it does not start
a model that clearly cannot fit (the excerpts wait, and "Read them now" can start it anyway); and it lets go of a
large model's memory once it has read.
"""
from __future__ import annotations

import io
import json
import time

import pytest
from helpers_0110 import Cloud, Local, mixed_project, use_local_model

from enlens_claims import access, claimcheck, home, llm, tasks, taskqueue
from enlens_claims.gui import server
from enlens_claims.gui.progress import Tracker, model_line
from enlens_claims.llm import MemoryShort, OllamaBackend

HYP = "Green hydrogen production can increase water stress in arid regions."
GB = 1 << 30


class Watched(Local):
    """A local model server with the parts of OllamaBackend the app uses: progress, Stop, the memory check, unload."""

    def __init__(self, need: int = 8 * GB, free: int = 3 * GB):
        super().__init__()
        self.progress = None
        self.should_stop = None
        self.memory_guard = True
        self.need, self.free = need, free
        self.unloaded: list[str] = []
        self.seen: list[dict] = []     # what the app showed while this model read
        self.tracker: Tracker | None = None

    def memory_need(self, model):
        return self.need

    def check_memory(self, model):
        if self.memory_guard and self.free < self.need:
            raise MemoryShort(model, self.need, self.free)

    def unload(self, model):
        self.unloaded.append(model)
        return True

    def complete(self, kind, system, user, model, payload=None):
        self.check_memory(model)
        if self.progress:
            self.progress({"task": kind, "model": model, "phase": "waiting", "prompt_tokens": 900, "seconds": 2.0})
        if self.tracker is not None:
            self.seen.append(self.tracker.state())
        return super().complete(kind, system, user, model, payload)


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    return ws, mixed_project(ws, tmp_path / "corpus")


def _queued_check_answered(ws) -> str:
    """A check by queue whose Claude Code part is answered; its local part waits for the app."""
    import fake_claude_code

    with tasks.queueing():
        hid = claimcheck.queue_check(ws, HYP, None, k=12, per_doc=4)
    for _ in range(6):
        fake_claude_code.run("Mixed", tools=fake_claude_code.DirectTools(), wrong_first=False)
        taskqueue.advance(ws)
    assert claimcheck.local_waiting(ws, [hid]), "the check has no local part: the test proves nothing"
    return hid


def _follow(ws, hid: str, tracker: Tracker):
    app = server.App.__new__(server.App)  # follow_queued needs nothing else of the app
    job = server.Job("check", HYP, "Mixed")
    job.tracker = tracker
    app.follow_queued(job, ws, [hid], tracker, poll=0.01)
    return job


# -- the app says what the local model does ----------------------------------------------------
def test_the_page_shows_the_local_model_while_it_reads(mixed, monkeypatch):
    ws, _ids = mixed
    local = Watched(free=64 * GB)
    use_local_model(monkeypatch, local)
    monkeypatch.setattr(llm, "total_memory", lambda: 16 * GB)
    hid = _queued_check_answered(ws)
    tracker = Tracker()
    local.tracker = tracker
    _follow(ws, hid, tracker)
    assert local.sent and local.seen
    during = local.seen[0]
    # the heading and the model line say the local model reads, not "Waiting for Claude Code"
    assert during["message"].startswith("Your local model (local-model) is reading")
    assert "Only a local AI" in during["message"]
    assert during["model"]["who"] == "local" and during["model"]["plain"].startswith("Your local model")
    assert during["model"]["line"].startswith("Local model local-model is loading the model")
    end = tracker.state()
    assert any(n.startswith("Your local model read") for n in end["notes"])
    assert claimcheck.hypothesis_result(ws, hid)["waiting_local"] == 0
    # a model that takes half of this computer's memory is let go once it has read
    assert local.unloaded == ["local-model"]


def test_a_small_local_model_is_kept_in_memory(mixed, monkeypatch):
    ws, _ids = mixed
    local = Watched(need=2 * GB, free=64 * GB)
    use_local_model(monkeypatch, local)
    monkeypatch.setattr(llm, "total_memory", lambda: 16 * GB)
    hid = _queued_check_answered(ws)
    _follow(ws, hid, Tracker())
    assert local.sent and local.unloaded == []


# -- not started on a computer without room for it -----------------------------------------------
def test_no_room_the_excerpts_wait_and_the_check_ends(mixed, monkeypatch):
    ws, ids = mixed
    local = Watched(need=8 * GB, free=int(2.7 * GB))
    use_local_model(monkeypatch, local)
    hid = _queued_check_answered(ws)
    tracker = Tracker()
    t0 = time.time()
    _follow(ws, hid, tracker)  # ends: Claude Code is done, only the local model's part waits
    assert time.time() - t0 < 10
    assert local.sent == [] and local.unloaded == []
    note = " ".join(tracker.state()["notes"])
    assert "local-model was not started: it needs about 8.0 GB of memory" in note
    assert "about 2.7 GB free now" in note and "Read them now" in note
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] == "waiting" and res["waiting_local"] > 0
    # it says what it waits for: Claude Code is done (the answer, its part, the Results list and the map)
    assert res["status_text"] == "Waiting for your local model"
    assert res["parts"][0]["status_text"] == "Waiting for your local model"
    row = next(x for x in claimcheck.history(ws) if x["hyp_id"] == hid)
    assert row["status"] == "waiting" and row["status_text"] == "Waiting for your local model"
    assert next(x for x in claimcheck.evidence_map(ws)["hypotheses"] if x["hyp_id"] == hid)["status_text"] \
        == "Waiting for your local model"
    # nothing was handed to a person: the excerpts still wait for the local model
    assert not [x for x in res["parts"][0]["passages"] if x["doc_id"] == ids["local"] and x["read_by"] == "you"]
    # "Read them now" checks again; "Start it anyway" reads them
    readers = access.Readers(None, "")
    assert claimcheck.run_local_parts(ws, [hid], readers, retry_failed=True) == 0
    assert isinstance(readers.memory_short, MemoryShort)
    anyway = access.Readers(None, "", check_memory=False)
    assert claimcheck.run_local_parts(ws, [hid], anyway, retry_failed=True) == 1
    assert local.sent and claimcheck.hypothesis_result(ws, hid)["waiting_local"] == 0


def test_no_room_on_the_claude_api_route(mixed, monkeypatch):
    """A check on the Claude API: Claude reads its excerpts, the local ones wait instead of loading the model."""
    ws, ids = mixed
    local = Watched(need=8 * GB, free=2 * GB)
    use_local_model(monkeypatch, local)
    steps = []
    hid = claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=12, per_doc=4,
                                      progress=lambda s, m, i=None: steps.append((s, m)))
    res = claimcheck.hypothesis_result(ws, hid)
    assert local.sent == [] and res["waiting_local"] > 0
    assert any("was not started" in m and "Read them now" in m for s, m in steps if s == "note")
    who = {x["read_by"] for x in res["parts"][0]["passages"] if x["doc_id"] == ids["local"]}
    assert who == {"waiting"}


def test_the_claude_api_route_shows_the_local_model_too(mixed, monkeypatch):
    """The Claude API's backend reports no progress of its own; the local model beside it still shows itself."""
    ws, _ids = mixed
    local = Watched(free=64 * GB)
    use_local_model(monkeypatch, local)
    cloud = Cloud()
    assert not hasattr(cloud, "progress")
    tracker = Tracker()
    local.tracker = tracker
    job = server.Job("check", HYP, "Mixed")
    server.App.wire(server.App.__new__(server.App), job, cloud, tracker)
    claimcheck.check_hypothesis(ws, HYP, cloud, "claude-opus", k=12, per_doc=4, progress=tracker.step)
    assert local.seen and local.seen[0]["model"]["who"] == "local"
    assert local.should_stop is not None and local.should_stop() is False


def test_stop_while_the_local_model_reads_keeps_its_excerpts_waiting(mixed, monkeypatch):
    ws, _ids = mixed
    stopped = {"now": False}

    class Stopped(Watched):
        def complete(self, *a, **k):
            stopped["now"] = True
            raise llm.BackendError("Stopped.")

    local = Stopped(free=64 * GB)
    use_local_model(monkeypatch, local)
    hid = _queued_check_answered(ws)
    readers = access.Readers(None, "", should_stop=lambda: stopped["now"])
    with pytest.raises(llm.BackendError, match="Stopped"):
        claimcheck.run_local_parts(ws, [hid], readers, retry_failed=True)
    assert claimcheck.hypothesis_result(ws, hid)["waiting_local"] > 0  # not handed to a person


def test_only_local_waits(mixed, monkeypatch):
    ws, _ids = mixed
    use_local_model(monkeypatch, Watched(free=64 * GB))
    with tasks.queueing():
        hid = claimcheck.queue_check(ws, HYP, None, k=12, per_doc=4)
    assert not claimcheck.only_local_waits(ws, hid)  # Claude Code has not proposed its words yet
    assert claimcheck.hypothesis_result(ws, hid)["status_text"] == "Waiting for Claude Code"
    import fake_claude_code

    for _ in range(6):
        fake_claude_code.run("Mixed", tools=fake_claude_code.DirectTools(), wrong_first=False)
        taskqueue.advance(ws)
    assert claimcheck.only_local_waits(ws, hid)


# -- the Ollama backend -------------------------------------------------------------------------
class _Opener:
    """Answers OllamaBackend's requests: /api/tags with sizes, /api/ps with what is loaded; records the rest."""

    def __init__(self, sizes: dict[str, int], loaded: list[str] = ()):
        self.sizes, self.loaded, self.paths = sizes, list(loaded), []
        self.held: dict[str, int] = {}   # the memory /api/ps says each loaded model holds

    def __call__(self, req, timeout=None):
        path = req.full_url.split("11434", 1)[1]
        self.paths.append(path)
        if path == "/api/tags":
            body = {"models": [{"name": n, "model": n, "size": s} for n, s in self.sizes.items()]}
        elif path == "/api/ps":
            body = {"models": [{"name": n, "model": n, "size": self.held.get(n, 0)} for n in self.loaded]}
        elif path == "/api/show":
            body = {"capabilities": ["completion"]}
        else:
            raise AssertionError(f"the model was asked to load: {path}")
        return _Resp(json.dumps(body).encode())


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_refuses_a_model_that_cannot_fit(monkeypatch):
    opener = _Opener({"qwen3.5:9b": int(7.6e9)})
    be = OllamaBackend("http://localhost:11434", num_ctx=16384, opener=opener, think=False)
    monkeypatch.setattr(llm, "free_memory", lambda: int(2.7 * GB))
    be.check_memory("qwen3.5:9b")  # the guard is off unless the app turns it on
    be.memory_guard = True
    assert be.memory_need("qwen3.5:9b") == int(7.6e9) + 16384 * llm.KV_BYTES_PER_TOKEN
    reports = []
    be.progress = reports.append
    with pytest.raises(MemoryShort) as e:
        be.complete("check", "system", "user", "qwen3.5:9b", {})
    assert "/api/chat" not in opener.paths  # refused before anything was loaded
    assert "needs about 8.1 GB" in str(e.value) and "about 2.7 GB free" in str(e.value)
    assert "smaller local model in Settings → AI" in str(e.value)
    assert reports and reports[0]["phase"] == "waiting"  # said at once, before loading
    # a model already in memory, enough room, a size or free memory not known: no refusal
    be.check_memory("qwen3.5")  # not installed: no size known
    monkeypatch.setattr(llm, "free_memory", lambda: 16 * GB)
    be.check_memory("qwen3.5:9b")
    monkeypatch.setattr(llm, "free_memory", lambda: None)
    be.check_memory("qwen3.5:9b")
    monkeypatch.setattr(llm, "free_memory", lambda: GB)
    opener.loaded = ["qwen3.5:9b"]
    be.check_memory("qwen3.5:9b")
    opener.sizes, opener.loaded = {"qwen3:latest": int(5e9)}, ["qwen3:latest"]
    be.check_memory("qwen3")  # ":latest" is the same model
    # the memory of another model Ollama holds counts as free: Ollama lets go of it to make room
    opener.sizes, opener.loaded = {"qwen3.5:9b": int(7.6e9), "gemma4:12b": int(7.7e9)}, ["gemma4:12b"]
    opener.held = {"gemma4:12b": 9 * GB}
    monkeypatch.setattr(llm, "free_memory", lambda: 2 * GB)
    be.check_memory("qwen3.5:9b")
    opener.held = {"gemma4:12b": 3 * GB}
    with pytest.raises(MemoryShort):
        be.check_memory("qwen3.5:9b")


def test_the_guard_is_on_for_the_restricted_documents_model_only(monkeypatch):
    """The model that starts beside Claude unasked is checked; a local main model the person starts is not."""
    s = {**home.DEFAULTS, "num_ctx": 8192, "think": "off", "backend": "claude_code",
         "restricted_server": "ollama", "restricted_model": "qwen3.5:9b"}
    assert home._ollama(s, "http://localhost:11434", "m", False).memory_guard is False
    monkeypatch.setattr(home, "_make_backend", lambda st, key, kinds: (
        home._ollama(st, st["ollama_url"], st["ollama_model"], False), st["ollama_model"]))
    be, model = home.make_restricted_backend(s)
    assert model == "qwen3.5:9b" and be.memory_guard is True


def test_free_memory_on_this_computer():
    free, total = llm.free_memory(), llm.total_memory()
    assert free is None or free > 0
    assert total is None or total > GB
    if free and total:
        assert free <= total


def test_a_job_refused_for_memory_says_so_in_plain_words():
    jobs = server.Jobs()

    def run(job):
        raise MemoryShort("qwen3.5:9b", 8 * GB, 2 * GB)

    job = jobs.start("read-local", "Reading", None, run, uses_model=False)
    for _ in range(100):
        if job.state not in ("queued", "running"):
            break
        time.sleep(0.02)
    assert job.state == "error" and job.error_kind == "memory" and "was not started" in job.error


# -- the progress line --------------------------------------------------------------------------
def test_the_progress_names_the_local_model():
    t = Tracker()
    t.model_report({"who": "local", "model": "qwen3.5:9b", "phase": "waiting", "prompt_tokens": 1061, "seconds": 3})
    m = t.state()["model"]
    assert m["who"] == "local" and m["name"] == "qwen3.5:9b"
    assert m["plain"].startswith("Your local model is starting")
    assert model_line({"who": "local", "model": "qwen3.5:9b", "phase": "thinking", "seconds": 5,
                       "thinking_tokens": 40}).startswith("Local model qwen3.5:9b is reasoning")
    t.model_report({"phase": "waiting", "seconds": 1})
    assert t.state()["model"]["plain"].startswith("The AI is getting ready")
    t.say("Your local model is reading")
    assert t.state()["message"] == "Your local model is reading" and t.state()["notes"] == []


def test_the_page_offers_start_it_anyway():
    from pathlib import Path

    static = Path(server.__file__).parent / "static" / "views"
    result = (static / "result.js").read_text(encoding="utf-8")
    assert "Start it anyway" in result and "force: true" in result and 'error_kind !== "memory"' in result
    progress = (static / "progress.js").read_text(encoding="utf-8")
    assert 'm.who === "local"' in progress


# -- after the review ---------------------------------------------------------------------------
def test_taking_waiting_checks_out_of_the_queue_keeps_a_finished_one(mixed, monkeypatch):
    """A check Claude Code has finished, whose local excerpts wait, is not removed with the waiting checks."""
    from enlens_claims import cli

    ws, _ids = mixed
    use_local_model(monkeypatch, Watched(free=GB))
    done = _queued_check_answered(ws)
    with tasks.queueing():
        fresh = claimcheck.queue_check(ws, "Electrolysis needs fresh water.", None, k=4)
    assert claimcheck.only_local_waits(ws, done) and not claimcheck.only_local_waits(ws, fresh)
    assert cli.main(["--ws", str(ws.root), "queue", "withdraw", "check"]) == 0
    left = {r[0] for r in ws.query("SELECT hyp_id FROM hypotheses")}
    assert done in left and fresh not in left
    assert claimcheck.hypothesis_result(ws, done)["waiting_local"] > 0


def test_a_set_of_checks_loads_the_local_model_once(mixed, monkeypatch):
    ws, _ids = mixed
    local = Watched(free=64 * GB)
    use_local_model(monkeypatch, local)
    monkeypatch.setattr(llm, "total_memory", lambda: 16 * GB)
    made = []
    real = home.make_restricted_backend
    monkeypatch.setattr(home, "make_restricted_backend", lambda st: made.append(1) or real(st))
    res = claimcheck.check_batch(ws, [{"text": HYP}, {"text": "Electrolysis needs large amounts of fresh water."}],
                                 Cloud(), "claude-opus", k=12, per_doc=4)
    assert len(res["checked"]) == 2 and len(local.kinds) >= 2
    assert made == [1] and local.unloaded == ["local-model"]  # one local model for the set, let go at its end


def test_a_kept_note_stays_through_a_set():
    t = Tracker()
    t.step("note", "local-model was not started", {"keep": True})
    t.step("note", "a note about this hypothesis", {})
    t.step("item", "Hypothesis 2 of 2", {"index": 2, "total": 2, "text": "x"})
    assert t.state()["notes"] == ["local-model was not started"]


def test_the_note_says_what_this_round_did(mixed, monkeypatch):
    """A local part handed to a person after the model failed is not reported as read by the local model."""
    ws, _ids = mixed

    class Fails(Watched):
        def complete(self, *a, **k):
            raise llm.BackendError("Ollama stopped with an error: out of memory")

    local = Fails(free=64 * GB)
    use_local_model(monkeypatch, local)
    hid = _queued_check_answered(ws)
    tracker = Tracker()
    readers = access.Readers(None, "", progress=tracker.model_report)
    readers.read = 3  # the local model read other checks' excerpts before
    app = server.App.__new__(server.App)
    app._read_local_now(ws, [hid], tracker, readers)
    notes = " ".join(tracker.state()["notes"])
    assert "wait for your judgement" in notes and "Your local model read" not in notes
    assert "could not be used (Ollama stopped with an error: out of memory)" in notes

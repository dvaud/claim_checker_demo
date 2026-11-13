"""0.18.4 (roadmap K2 part 2, the optional AI part): the AI drafts a theory document's concepts.

One `theory_codes` task per draft, given the document's Level-0 candidates and the passages where they are defined or
used most. Each concept comes back with a definition quoted exactly from the theory (the quote check sends a quote
that is not there back to be fixed), and joins the dialog's list unticked and marked as the AI's, without the Level-0
candidates already there. The document's own AI setting picks the reader (Claude, the local model, or none: no task);
a draft asked again with the same input reuses its answer (H4); examples still come only from the evidence."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

import fake_claude_code as fcc
from enlens_claims import access, codebooks, docrole, ingest, taskqueue, tasks, theorycodes
from enlens_claims import home as ehome
from enlens_claims.llm import ClaudeCodeBackend
from test_codebook_from_theory import EVIDENCE, _theory_pdf

ROOT = Path(__file__).resolve().parent.parent
# a concept the theory defines that Level 0 does not offer under this name, and one it does ("Stock")
NEW_CONCEPT = ("Changing flows", "the memory of the history of changing flows")
SAME_CONCEPT = ("Stocks", "A stock is the memory of the history")


def _blocks(prompt: str) -> list[tuple[int, str]]:
    return [(int(n), " ".join(t.split())) for n, t in
            re.findall(r"^P(\d+)(?: \(page [^)]*\))?\n(.+?)(?=\n\nP\d+[ \n(]|\Z)", prompt, re.S | re.M)]


def _answer(prompt: str, concepts=(NEW_CONCEPT, SAME_CONCEPT)) -> dict:
    """What a helper answers: each concept with the passage its quote is in."""
    out = []
    for name, quote in concepts:
        n = next((n for n, t in _blocks(prompt) if quote.lower() in t.lower()), 1)
        out.append({"name": name, "definition": {"passage": n, "quote": quote}, "reason": "The theory defines it."})
    return {"concepts": out, "note": None}


class FakeModel:
    """A model server that drafts as `_answer` does and counts its calls. `local`: one on this computer."""

    def __init__(self, local: bool = False):
        self.name = "ollama" if local else "anthropic"
        if local:
            self.base_url = "http://127.0.0.1:11434"
        self.calls = 0

    def complete(self, kind, system, user, model, payload):
        assert kind == "theory_codes" and system.startswith("You draft the concepts of a theory document")
        self.calls += 1
        return json.dumps(_answer(user))


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    ehome.save_settings({**ehome.load_settings(), "backend": "anthropic", "allow_cloud": True, "embed_backend": "off"})
    ws = ehome.create_project("T")
    d = tmp_path / "docs"
    d.mkdir()
    _theory_pdf(d / "meadows.pdf")
    (d / "carehome.txt").write_text(EVIDENCE, encoding="utf-8")
    ingest.ingest(ws, [d])
    theory = ws.scalar("SELECT doc_id FROM documents WHERE text LIKE '%memory of the history%'")
    evidence = ws.scalar("SELECT doc_id FROM documents WHERE doc_id != ?", (theory,))
    docrole.set_role(ws, theory, "theory")
    yield ws, theory, evidence
    ws.close_all()


def _ai_tasks(ws) -> list:
    return ws.query("SELECT * FROM tasks WHERE kind='theory_codes'")


def test_the_kind_is_registered_with_its_prompt_helper_and_row():
    from enlens_claims import prompts, routing, schema

    assert prompts.VERSIONS["theory_codes"] == "theory-codes-v1"
    assert routing.HELPERS["theory_codes"] == "enlens-namer" and routing.CLAUDE_DEFAULTS["theory_codes"] == ("sonnet", "opus")
    assert routing.LOCAL_DEFAULTS["theory_codes"] == "large" and routing.ROW_OF["theory_codes"] == "theory_codes"
    assert "theory_codes" in taskqueue.ORDER and taskqueue.BATCH["theory_codes"] == 1
    assert set(schema.output_schema("theory_codes")["properties"]) == {"concepts", "note"}
    namer = (ROOT / "src/enlens_claims/claude_plugin/agents/enlens-namer.md").read_text(encoding="utf-8")
    assert "theory_codes" in namer and "three whole words" in namer
    assert "theory_codes" in (ROOT / "src/enlens_claims/claude_plugin/SKILL.md").read_text(encoding="utf-8")


def test_a_task_for_a_cloud_theory_document_goes_to_claude_code_and_a_wrong_quote_comes_back(project):
    ws, theory, _ev = project
    ehome.save_settings({**ehome.load_settings(), "backend": "claude_code", "allow_claude_code": True})
    assert theorycodes.ai_offer(ws, theory) == {"offered": True, "why": None, "reader": "claude", "level": "cloud"}
    got: dict = {}

    def draft():
        with tasks.queueing(True):
            got["r"] = theorycodes.draft_with_ai(ws, theory, ClaudeCodeBackend(), "sonnet")

    th = threading.Thread(target=draft, daemon=True)
    th.start()
    for _ in range(200):  # until the task waits in the queue
        if ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='theory_codes' AND queued=1"):
            break
        th.join(0.05)
    t = _ai_tasks(ws)
    assert len(t) == 1 and t[0]["access"] == "cloud" and t[0]["queued"] == 1
    payload = json.loads(t[0]["payload_json"])
    assert payload["doc_id"] == theory and "Stock" in payload["candidates"]
    assert 1 <= len(payload["passages"]) <= theorycodes.AI_MAX_PASSAGES
    assert {ws.scalar("SELECT doc_id FROM passages WHERE passage_id=?", (p["passage_id"],)) for p in payload["passages"]} \
        == {theory}
    cc = fcc.FakeClaudeCode(fcc.DirectTools(), answer=lambda kind, system, prompt, model: _answer(prompt))
    cc.run("T")
    th.join(20)
    assert not th.is_alive()
    entry = next(e for e in cc.log if e["kind"] == "theory_codes")
    assert entry["helper"] == "enlens-namer" and entry["model"] == "sonnet"
    assert entry["problems"] == 1 and entry["stored"] == 1  # the spoiled quote came back and was fixed
    r = got["r"]
    assert r["ok"] and [c["term"] for c in r["concepts"]] == ["Changing flows"]
    rows = ws.query("SELECT valid, errors_json, route, helper FROM results WHERE kind='theory_codes' ORDER BY attempt")
    assert [x["valid"] for x in rows] == [0, 1] and "quote not found" in rows[0]["errors_json"]
    assert rows[1]["route"] == "Claude Code" and rows[1]["helper"] == "enlens-namer"


def test_a_quote_not_in_the_theory_or_too_short_is_rejected(project):
    ws, theory, _ev = project
    tid = theorycodes.make_ai_task(ws, theory, "claude-sonnet-5-5")
    bad = {"concepts": [{"name": "Stock", "definition": {"passage": 1, "quote": "a stock is a pile of money"},
                         "reason": "x"},
                        {"name": "Flow", "definition": {"passage": 1, "quote": "stock"}, "reason": "x"},
                        {"name": "Delay", "definition": {"passage": 99, "quote": "a delay in a balancing loop"},
                         "reason": "x"}]}
    ok, errors = tasks.ingest_result(ws, tid, json.dumps(bad), model="claude-sonnet-5-5")
    assert not ok and len(errors) == 3
    assert "quote not found in passage P1" in errors[0]
    assert "too short to define the concept" in errors[1]
    assert "there is no passage P99" in errors[2]
    assert ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) == "retry"
    assert theorycodes.ai_drafts(ws, tid) == []


def test_a_model_that_never_quotes_the_theory_drafts_nothing(project):
    ws, theory, _ev = project

    class Wrong(FakeModel):
        def complete(self, kind, system, user, model, payload):
            self.calls += 1
            return json.dumps(_answer(user, (("Stock", "a stock is a pile of money"),)))

    model = Wrong()
    r = theorycodes.draft_with_ai(ws, theory, model, "claude-sonnet-5-5")
    assert r["ok"] is False and r["stopped"] is False and r["concepts"] == [] and model.calls == 3
    assert "quote not found" in r["problems"][0]
    log = ws.query("SELECT text FROM research_log WHERE kind='codebook-drafted'")
    assert len(log) == 1 and "could not draft" in log[0]["text"]


def test_no_task_for_a_document_marked_no_ai(project):
    ws, theory, _ev = project
    access.set_documents(ws, [theory], "none")
    offer = theorycodes.ai_offer(ws, theory)
    assert offer["offered"] is False and offer["why"] == theorycodes.NO_AI
    model = FakeModel()
    with pytest.raises(ValueError, match="marked No AI"):
        theorycodes.draft_with_ai(ws, theory, model, "claude-sonnet-5-5")
    assert model.calls == 0 and _ai_tasks(ws) == []


def test_only_a_local_ai_uses_the_local_model_and_never_claude(project, monkeypatch):
    ws, theory, _ev = project
    access.set_documents(ws, [theory], "local")
    cloud, local = FakeModel(), FakeModel(local=True)
    # without a local model chosen, the AI part is not offered, and says why
    assert theorycodes.ai_offer(ws, theory)["why"] == theorycodes.NO_LOCAL
    with pytest.raises(ValueError, match="no local AI is chosen"):
        theorycodes.draft_with_ai(ws, theory, cloud, "claude-sonnet-5-5")
    s = {**ehome.load_settings(), "restricted_server": "ollama", "restricted_model": "big",
         "ollama_url": "http://127.0.0.1:11434"}
    ehome.save_settings(s)
    monkeypatch.setattr(ehome, "make_restricted_backend", lambda settings: (local, "big"))
    assert theorycodes.ai_offer(ws, theory)["reader"] == "local"
    r = theorycodes.draft_with_ai(ws, theory, cloud, "claude-sonnet-5-5")
    assert r["ok"] and r["model"] == "big" and cloud.calls == 0 and local.calls == 1
    assert _ai_tasks(ws)[0]["access"] == "local"
    assert ws.scalar("SELECT route FROM results WHERE kind='theory_codes' AND valid=1") == "local model server"
    assert not access.ledger(ws, theory)  # nothing of it was sent off this computer


def test_a_repeat_with_the_same_input_reuses_the_kept_answer(project):
    ws, theory, _ev = project
    model = FakeModel()
    first = theorycodes.draft_with_ai(ws, theory, model, "claude-sonnet-5-5")
    assert first["ok"] and not first["reused"] and model.calls == 1
    again = theorycodes.draft_with_ai(ws, theory, model, "claude-sonnet-5-5")
    assert again["reused"] and model.calls == 1 and again["concepts"] == first["concepts"]
    assert len(_ai_tasks(ws)) == 1
    # the task gone (as when its id changes), the same question is answered from the kept answer (H4)
    with ws.connect() as cx:
        cx.execute("DELETE FROM results WHERE kind='theory_codes'")
        cx.execute("DELETE FROM tasks WHERE kind='theory_codes'")
    third = theorycodes.draft_with_ai(ws, theory, model, "claude-sonnet-5-5")
    assert third["reused"] and model.calls == 1 and [c["term"] for c in third["concepts"]] == ["Changing flows"]
    assert tasks.avoided(ws).get("theory_codes") == 1
    # each draft is in the research log, the kept ones said so
    log = ws.query("SELECT text, subject_id FROM research_log WHERE kind='codebook-drafted' ORDER BY at, rowid")
    assert len(log) == 3 and all(x["subject_id"] == theory for x in log)
    assert "kept from the same request before" in log[1]["text"] and "Changing flows" not in log[0]["text"]


def test_drafts_come_back_unticked_marked_and_without_the_level_0_candidates(project):
    ws, theory, evidence = project
    r = theorycodes.draft_with_ai(ws, theory, FakeModel(), "claude-sonnet-5-5")
    level0 = {c["term"] for c in theorycodes.candidates(ws, theory)["concepts"]}
    assert "Stock" in level0 and [c["term"] for c in r["concepts"]] == ["Changing flows"]  # "Stocks" is "Stock"
    c = r["concepts"][0]
    assert c["ai"] is True and c["how"] == "ai" and c["reason"] == "The theory defines it."
    text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (theory,))
    d = c["definition"]
    assert " ".join(text[d["start"]:d["end"]].split()).lower() == NEW_CONCEPT[1] and d["page"] == 1
    assert c["code"]["description"].startswith(f"“{d['quote']}” (Thinking in systems, p. 1)")
    # the dialog: AI drafts are never ticked (only Level 0's defined terms are), and are marked "AI draft"
    js = (ROOT / "src/enlens_claims/gui/static/views/codebooks.js").read_text(encoding="utf-8")
    assert 'checked: c.how === "defined" && !c.ai' in js and '"AI draft"' in js and '"Draft with AI"' in js


def test_examples_still_come_only_from_the_evidence(project):
    ws, theory, evidence = project
    r = theorycodes.draft_with_ai(ws, theory, FakeModel(), "claude-sonnet-5-5")
    answer = ws.scalar("SELECT raw_json FROM results WHERE kind='theory_codes' AND valid=1")
    assert "example" not in answer.lower()  # the AI gives none
    for c in r["concepts"]:
        assert not c["code"]["examples"] and all(e["doc_id"] == evidence for e in c["suggested"])
    # an AI draft kept with an example from the evidence keeps it; one from the theory, smuggled in, is dropped
    good = theorycodes.suggest_examples(ws, "reinforcing loop")
    assert good and all(e["doc_id"] == evidence for e in good)
    code = {**theorycodes._draft_code("Reinforcing loop", None, "Thinking in systems"),
            "examples": [good[0], {"quote": "A reinforcing loop can make a stock grow", "doc_id": theory,
                                   "title": "Thinking in systems", "page": 2, "start": 0, "end": 10}]}
    cb = codebooks.create(ws, "from_ai", "From the AI", start="theory", source={"doc_id": theory, "codes": [code]})
    assert [e["doc_id"] for c in cb["codes"] for e in c["examples"]] == [evidence]


def test_the_routes_offer_it_and_run_it_as_a_job(api, tmp_path):  # noqa: F811
    from enlens_claims.store import Workspace

    from test_codebook_from_theory import THEORY_PAGES

    assert api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})[0] == 200
    assert api("POST", "/api/projects", {"name": "Lens"})[0] == 200
    d = tmp_path / "in"
    d.mkdir()
    (d / "meadows.txt").write_text("Thinking in systems\n\n" + "\n\n".join("\n\n".join(p) for p in THEORY_PAGES),
                                   encoding="utf-8")
    (d / "carehome.txt").write_text(EVIDENCE, encoding="utf-8")
    ws = Workspace.open(ehome.project_path("Lens"))
    try:
        ingest.ingest(ws, [d])
        theory = ws.scalar("SELECT doc_id FROM documents WHERE text LIKE '%memory of the history%'")
        evidence = ws.scalar("SELECT doc_id FROM documents WHERE doc_id != ?", (theory,))
        docrole.set_role(ws, theory, "theory")
    finally:
        ws.close_all()
    base = f"/api/projects/Lens/codebook-theory/{theory}/ai"
    st, offer = api("GET", base)
    assert st == 200 and offer["offered"] is True and offer["why"] is None
    st, r = api("POST", base)
    assert st == 200 and r["job"]["kind"] == "theory-codes"
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job
    got = job["result"]
    # the offline demo offers the Level-0 candidates the passages use, so every one of them is left out as a repeat
    assert got["ok"] and got["model"] and all(c["ai"] and c["how"] == "ai" for c in got["concepts"])
    level0 = {c["term"].lower() for c in api("GET", f"/api/projects/Lens/codebook-theory/{theory}")[1]["concepts"]}
    assert not {c["term"].lower() for c in got["concepts"]} & level0
    assert all(e["doc_id"] == evidence for c in got["concepts"] for e in c["suggested"])
    # a document marked No AI: not offered, and the draft is refused in one line
    ws = Workspace.open(ehome.project_path("Lens"))
    try:
        access.set_documents(ws, [theory], "none")
    finally:
        ws.close_all()
    st, offer = api("GET", base)
    assert st == 200 and offer == {"offered": False, "why": theorycodes.NO_AI, "reader": None, "level": "none"}
    st, body = api("POST", base)
    assert st == 400 and "No AI" in json.dumps(body)
    assert api("GET", "/api/projects/Lens/codebook-theory/nope/ai")[0] == 404


from test_app import api, home  # noqa: E402,F401  (fixtures)

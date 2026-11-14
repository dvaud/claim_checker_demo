"""K1, the optional AI part: a code's definition, when to use it and when not, drafted from its examples.

One `code_definition` task per draft, given the code's name and only the passages that hold its examples. The
definition and *when to use it* each name a quote from one of them (the quote check sends a quote that is not there
back); each document's own AI setting decides whether its passage is sent and to whom; the same input reuses its
answer (H4). Taken into the editor, the AI's words are marked as a draft until the person rewrites them."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enlens_claims import access, codebooks, codedefine, ingest, researchlog, tasks
from enlens_claims import home as ehome

ROOT = Path(__file__).resolve().parent.parent
_PAD = " ".join(["The interviews went on for a long while about many other matters of the day."] * 4)
WAIT_LIFT = "Residents waited a long time for the lift every morning."
GARDEN = "The garden was quiet and nobody walked in it."
WAIT_NIGHT = "Staff said residents waited for help at night."
WAIT_MEAL = "Relatives saw residents wait an hour for their meal."
DOC_A = "Care home interviews\n\n" + "\n\n".join(f"{p} {_PAD}" for p in (WAIT_LIFT, GARDEN, WAIT_NIGHT))
DOC_B = "Relatives' letters\n\n" + f"{WAIT_MEAL} {_PAD}"


def _blocks(prompt: str) -> list[tuple[int, str]]:
    import re

    return [(int(n), " ".join(t.split())) for n, t in
            re.findall(r"^P(\d+)(?: \(page [^)]*\))?\n(.+?)(?=\n\nP\d+[ \n(]|\Z)", prompt, re.S | re.M)]


def _answer(prompt: str, definition_quote: str | None = None, use_quote: str | None = None) -> dict:
    blocks = _blocks(prompt)
    n1 = next((n for n, t in blocks if WAIT_LIFT[:20] in t), 1)
    n2 = next((n for n, t in blocks if WAIT_NIGHT[:20] in t), n1)
    return {"definition": "Residents left waiting for something they need from the home.",
            "definition_quote": {"passage": n1, "quote": definition_quote or "waited a long time for the lift"},
            "when_to_use": "When a passage says a resident waits for staff, help or a service.",
            "when_to_use_quote": {"passage": n2, "quote": use_quote or "residents waited for help at night"},
            "when_not_to_use": "Not for staff shortages named without a resident waiting.", "note": None}


class FakeModel:
    """A model server that drafts as `_answer` does and counts its calls. `local`: one on this computer."""

    def __init__(self, local: bool = False, **kw):
        self.name = "ollama" if local else "anthropic"
        if local:
            self.base_url = "http://127.0.0.1:11434"
        self.calls, self.prompts, self.kw = 0, [], kw

    def complete(self, kind, system, user, model, payload):
        assert kind == "code_definition" and system.startswith("You draft the definition of one code")
        self.calls += 1
        self.prompts.append(user)
        return json.dumps(_answer(user, **self.kw))


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    ehome.save_settings({**ehome.load_settings(), "backend": "anthropic", "allow_cloud": True, "embed_backend": "off"})
    ws = ehome.create_project("T")
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.txt").write_text(DOC_A, encoding="utf-8")
    (d / "b.txt").write_text(DOC_B, encoding="utf-8")
    ingest.ingest(ws, [d])
    a = ws.scalar("SELECT doc_id FROM documents WHERE text LIKE '%garden%'")
    b = ws.scalar("SELECT doc_id FROM documents WHERE doc_id != ?", (a,))
    yield ws, a, b
    ws.close_all()


EXAMPLES = [WAIT_LIFT, WAIT_NIGHT, WAIT_MEAL]


def _draft(ws, model=None, quotes=EXAMPLES, **kw):
    return codedefine.draft(ws, "waits", "Waiting", "Daily life", list(quotes), model or FakeModel(), "claude-sonnet-5-5",
                            **kw)


def test_the_kind_is_registered_with_its_prompt_helper_and_row():
    from enlens_claims import prompts, routing, schema, taskqueue

    assert prompts.VERSIONS["code_definition"] == "code-definition-v1"
    assert routing.HELPERS["code_definition"] == "enlens-namer"
    assert routing.CLAUDE_DEFAULTS["code_definition"] == ("sonnet", "opus")
    assert routing.LOCAL_DEFAULTS["code_definition"] == "large" and taskqueue.BATCH["code_definition"] == 1
    assert set(schema.output_schema("code_definition")["properties"]) == {
        "definition", "definition_quote", "when_to_use", "when_to_use_quote", "when_not_to_use", "note"}
    namer = (ROOT / "src/enlens_claims/claude_plugin/agents/enlens-namer.md").read_text(encoding="utf-8")
    assert "code_definition" in namer and "three whole words" in namer
    assert "code_definition" in (ROOT / "src/enlens_claims/claude_plugin/SKILL.md").read_text(encoding="utf-8")


def test_it_needs_two_example_passages(project):
    ws, _a, _b = project
    off = codedefine.offer(ws, [WAIT_LIFT])
    assert off["offered"] is False and off["why"] == codedefine.NO_EXAMPLES and off["passages"] == 1
    # two quotes of one passage are still one passage
    assert codedefine.offer(ws, [WAIT_LIFT, "for the lift every morning"])["offered"] is False
    off = codedefine.offer(ws, EXAMPLES)
    assert off["offered"] is True and off["reader"] == "claude" and off["passages"] == 3 and off["left_line"] is None
    # an example not in this project's documents is left out, and said
    off = codedefine.offer(ws, EXAMPLES + ["words that are in no document of this project at all"])
    assert off["offered"] and off["left_out"]["elsewhere"] == 1 and "not found in this project" in off["left_line"]
    with pytest.raises(ValueError, match="at least 2 examples"):
        _draft(ws, quotes=[WAIT_LIFT])


def test_the_ai_reads_only_the_passages_that_hold_the_examples(project):
    ws, a, b = project
    model = FakeModel()
    r = _draft(ws, model)
    assert r["ok"] and model.calls == 1 and r["passages"] == 3
    prompt = model.prompts[0]
    assert "CODE: Waiting (group: Daily life)" in prompt
    assert "garden" not in prompt.lower()            # the passage with no example is not sent
    assert prompt.count("EXAMPLE: ") == 3
    t = ws.query("SELECT payload_json, access FROM tasks WHERE kind='code_definition'")
    assert len(t) == 1 and t[0]["access"] == "cloud"
    payload = json.loads(t[0]["payload_json"])
    assert payload["docs"] == sorted([a, b])
    assert {ws.scalar("SELECT doc_id FROM passages WHERE passage_id=?", (p["passage_id"],)) for p in payload["passages"]} \
        == {a, b}
    d = r["draft"]
    assert d["description"].startswith("Residents left waiting") and d["include"] and d["exclude"]
    assert d["quotes"]["description"]["quote"] == "waited a long time for the lift"
    assert d["quotes"]["description"]["doc_id"] == a and d["quotes"]["include"]["title"]
    # in the research log, as a draft that changes nothing yet
    e = researchlog.entries(ws)["entries"][0]
    assert e["kind"] == "codebook-drafted" and "draft to rewrite" in e["text"] and "“Waiting”" in e["text"]


def test_a_quote_not_in_the_passages_or_too_short_or_a_bare_name_is_sent_back(project):
    ws, _a, _b = project
    payload = codedefine.payload_for(ws, "Waiting for help", "", EXAMPLES)
    prompt = "\n\n".join(f"P{p['n']}\n{p['text']}" for p in payload["passages"])
    ok, errs = codedefine.store_answer(None, None, payload, _answer(prompt, definition_quote="the residents were happy"),
                                       "m")
    assert not ok and "definition_quote: quote not found" in errs[0]
    ok, errs = codedefine.store_answer(None, None, payload, _answer(prompt, use_quote="waited for"), "m")
    assert not ok and "when_to_use_quote" in errs[0] and "too short" in errs[0]
    bare = {**_answer(prompt), "definition": "Waiting for help."}
    ok, errs = codedefine.store_answer(None, None, payload, bare, "m")
    assert not ok and "repeats the code's name" in errs[0]
    assert codedefine.store_answer(None, None, payload, _answer(prompt), "m") == (True, [])


def test_a_model_that_never_quotes_drafts_nothing(project):
    ws, _a, _b = project
    r = _draft(ws, FakeModel(definition_quote="words that are not in any passage here"))
    assert not r["ok"] and r["draft"] is None and r["problems"]
    assert "could not draft" in researchlog.entries(ws)["entries"][0]["text"]


def test_a_document_marked_no_ai_is_never_sent(project):
    ws, a, b = project
    access.set_documents(ws, [b], "none")
    model = FakeModel()
    off = codedefine.offer(ws, EXAMPLES)
    assert off["offered"] and off["passages"] == 2 and off["left_out"]["no_ai"] == 1 and "No AI" in off["left_line"]
    r = _draft(ws, model)
    assert r["ok"] and WAIT_MEAL[:20] not in model.prompts[0]
    # with too few left, not offered, and no task
    access.set_documents(ws, [a], "none")
    assert codedefine.offer(ws, EXAMPLES)["offered"] is False
    n = ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='code_definition'")
    with pytest.raises(ValueError):
        _draft(ws, model)
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='code_definition'") == n and model.calls == 1


def test_only_a_local_ai_uses_the_local_model_and_never_claude(project, monkeypatch):
    ws, a, _b = project
    access.set_documents(ws, [a], "local")
    cloud, local = FakeModel(), FakeModel(local=True)
    off = codedefine.offer(ws, EXAMPLES)  # no local model chosen: its passages are left out, one is not enough
    assert not off["offered"] and off["left_out"]["local"] == 2 and "no local AI is chosen" in off["why"]
    ehome.save_settings({**ehome.load_settings(), "restricted_server": "ollama", "restricted_model": "big"})
    monkeypatch.setattr(ehome, "make_restricted_backend", lambda settings: (local, "big"))
    assert codedefine.offer(ws, EXAMPLES)["reader"] == "local"
    r = _draft(ws, cloud)
    assert r["ok"] and r["model"] == "big" and cloud.calls == 0 and local.calls == 1
    assert ws.scalar("SELECT access FROM tasks WHERE kind='code_definition'") == "local"


def test_a_repeat_with_the_same_input_reuses_the_kept_answer(project):
    ws, _a, _b = project
    model = FakeModel()
    first = _draft(ws, model)
    again = _draft(ws, model)
    assert first["ok"] and again["ok"] and again["reused"] and model.calls == 1
    assert again["draft"]["description"] == first["draft"]["description"]
    _draft(ws, model, quotes=[WAIT_LIFT, WAIT_NIGHT])  # other examples: another task
    assert model.calls == 2


def test_a_draft_taken_back_says_so_and_a_stop_stays_quiet(project, monkeypatch):
    ws, _a, _b = project
    monkeypatch.setattr(tasks, "run_one", lambda *a, **k: (False, ["taken back from the queue"]))
    r = _draft(ws)
    assert r["ok"] is False and r["stopped"] is False and r["withdrawn"] is True and r["why"] == codedefine.WITHDRAWN
    r = _draft(ws, should_stop=lambda: True)
    assert r["stopped"] is True and r["withdrawn"] is False and r["why"] is None and r["draft"] is None
    assert ws.query("SELECT 1 FROM research_log WHERE kind='codebook-drafted'") == []


def test_the_ai_words_are_marked_until_rewritten(project):
    ws, _a, _b = project
    cb = codebooks.create(ws, "waits", "Waits")
    d = _draft(ws)["draft"]
    code = {"uid": "", "code": "Waiting", "description": d["description"], "group": "", "include": "my own words here",
            "exclude": d["exclude"], "keywords": [], "examples": [{"quote": q} for q in EXAMPLES],
            "ai_draft": {"model": d["model"], "at": "2026-11-14", "description": d["description"],
                         "include": d["include"], "exclude": d["exclude"]}}
    r = codebooks.save(ws, "waits", {**cb, "codes": [code]})
    assert any("AI's draft wording" in c for c in r["changes"])
    got = r["codebook"]["codes"][0]
    # the include field was the person's own: only the two fields still holding the AI's words are marked
    assert got["ai_draft"] == {"model": d["model"], "at": "2026-11-14", "description": d["description"],
                               "exclude": d["exclude"]}
    meta = json.loads((ws.root / "frameworks" / "waits.json").read_text(encoding="utf-8"))
    assert meta["drafted"][got["uid"]]["description"] == d["description"]
    # the definition rewritten: its mark goes; the CSV holds only the words, never the mark
    got["description"] = "Residents kept waiting by the home, in their own words."
    r = codebooks.save(ws, "waits", {**r["codebook"], "codes": [got]})
    assert r["codebook"]["codes"][0]["ai_draft"] == {"model": d["model"], "at": "2026-11-14", "exclude": d["exclude"]}
    got = r["codebook"]["codes"][0]
    got["exclude"] = "Not for staff shortages alone."
    r = codebooks.save(ws, "waits", {**r["codebook"], "codes": [got]})
    assert "ai_draft" not in r["codebook"]["codes"][0]
    assert "drafted" not in json.loads((ws.root / "frameworks" / "waits.json").read_text(encoding="utf-8"))
    assert "ai_draft" not in (ws.root / "frameworks" / "waits.csv").read_text(encoding="utf-8")


def test_removing_a_document_takes_its_drafts_away(project):
    ws, a, _b = project
    _draft(ws)
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='code_definition'") == 1
    ws.remove_document(a)
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='code_definition'") == 0
    assert ws.scalar("SELECT COUNT(*) FROM results WHERE kind='code_definition'") == 0


def test_the_routes_offer_it_and_run_it_as_a_job(api, tmp_path):  # noqa: F811
    from enlens_claims.store import Workspace

    assert api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})[0] == 200
    assert api("POST", "/api/projects", {"name": "Def"})[0] == 200
    d = tmp_path / "in"
    d.mkdir()
    (d / "a.txt").write_text(DOC_A, encoding="utf-8")
    (d / "b.txt").write_text(DOC_B, encoding="utf-8")
    ws = Workspace.open(ehome.project_path("Def"))
    try:
        ingest.ingest(ws, [d])
        codebooks.create(ws, "waits", "Waits")
    finally:
        ws.close_all()
    base = "/api/projects/Def/codebooks/waits/define"
    st, off = api("POST", f"{base}/offer", {"examples": [{"quote": WAIT_LIFT}]})
    assert st == 200 and off["offered"] is False and off["why"] == codedefine.NO_EXAMPLES
    st, off = api("POST", f"{base}/offer", {"examples": EXAMPLES})
    assert st == 200 and off["offered"] is True and off["passages"] == 3
    st, body = api("POST", base, {"code": "Waiting", "examples": [WAIT_LIFT]})
    assert st == 400 and "at least 2 examples" in json.dumps(body)
    st, r = api("POST", base, {"code": "Waiting", "group": "", "examples": EXAMPLES})
    assert st == 200 and r["job"]["kind"] == "code-define"
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job
    got = job["result"]
    # the offline demo drafts from the first passage's first example, quoted; the passages are in document order, and
    # which document comes first follows its id, made from its path (on Windows the letters' document came first)
    assert got["ok"] and got["draft"]["description"].startswith("Offline demo")
    assert got["draft"]["quotes"]["description"]["quote"] in (WAIT_LIFT, WAIT_MEAL)


from test_app import api, home  # noqa: E402,F401  (fixtures)


def test_the_log_entry_names_the_codebook_by_its_name_and_title(project):
    ws, _a, _b = project
    codedefine.draft(ws, "kxyz", "Waiting", "", EXAMPLES, FakeModel(), "claude-sonnet-5-5", title="Interview codes")
    e = researchlog.entries(ws)["entries"][0]
    assert e["subject_kind"] == "codebook" and e["subject_id"] == "kxyz" and "“Interview codes”" in e["text"]


def test_a_colleagues_ai_draft_mark_comes_with_their_code(shared_codebook):
    from test_codebook_merge import _edit

    anna, ben = shared_codebook
    words = "Water drawn by electrolysers, as the AI drafted it."

    def take_draft(codes):
        a = next(c for c in codes if c["code"] == "A")
        a["description"] = words
        a["ai_draft"] = {"model": "claude-sonnet-5-5", "at": "2026-11-14", "description": words}
    with anna:
        _edit(anna.ws, "water", take_draft)
    with ben:
        _edit(ben.ws, "water", lambda codes: next(c for c in codes if c["code"] == "B").update(
            description="Local jobs and training"))
    rep = ben.bring_in(anna.send())
    assert [(m["theirs"], m["clash"]) for m in rep["codebooks"]["merged"]] == [(["A"], [])]
    with ben:
        got = {c["code"]: c for c in codebooks.load(ben.ws, "water")["codes"]}
    assert got["A"]["description"] == words and got["A"]["ai_draft"]["description"] == words
    assert "ai_draft" not in got["B"]


from test_codebook_merge import shared_codebook  # noqa: E402,F401  (fixture)

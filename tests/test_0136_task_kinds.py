"""0.13.6: one registry for the kinds of AI task (taskkinds.py, docs/EXTENDING.md).

- Every table the eight modules kept (routing.KINDS, taskqueue.ORDER, BATCH, HELPERS, the names, the limits…) is now
  built from the registry, and equals its 0.13.5 value (below, written out as it was).
- An add-on registers a kind of its own; one without a quote check is refused.
- The stand-in add-on's kind (`fake_tag`) goes through the queue, the routing and step-up, the offline demo, storing,
  "How these results were made", the Claude Code plugin's helper list, the size estimate and local-only.
"""
from __future__ import annotations

import json

import pytest

from enlens_claims import access, home, llm, prompts, routing, runs, taskkinds, taskqueue, tasks
from enlens_claims.llm import BaselineBackend
from enlens_claims.store import Workspace

# the tables as 0.13.5 wrote them out (KINDS of routing and tasks: as sets, their order never mattered)
SNAPSHOT_014 = {
    'routing.KINDS': ('label', 'link', 'expand', 'decompose', 'theme', 'resolve', 'check', 'reread', 'second', 'split', 'extract', 'verify', 'verify_set', 'audit'),
    'routing.ROWS': (('label', ('label',), 'Codebook labels (profile)'), ('link', ('link',), 'How concepts relate'), ('expand', ('expand', 'decompose'), 'Search words and splitting a hypothesis'), ('theme', ('theme',), 'Theme names'), ('resolve', ('resolve',), 'References in a document'), ('check', ('check', 'reread'), 'Judging excerpts (checks, reading again)'), ('second', ('second', 'audit'), 'Second opinion (and audits of the SDG pack)'), ('extract', ('extract',), 'SDG pack: impact claims from passages'), ('split', ('split',), "SDG pack: splitting the VCA's justifications"), ('verify', ('verify', 'verify_set'), 'SDG pack: checking claims against their sources')),
    'routing.ROW_OF': {'label': 'label', 'link': 'link', 'expand': 'expand', 'decompose': 'expand', 'theme': 'theme', 'resolve': 'resolve', 'check': 'check', 'reread': 'check', 'second': 'second', 'audit': 'second', 'extract': 'extract', 'split': 'split', 'verify': 'verify', 'verify_set': 'verify'},
    'routing.CLAUDE_DEFAULTS': {'label': ('haiku', 'sonnet'), 'link': ('haiku', 'sonnet'), 'expand': ('sonnet', 'opus'), 'decompose': ('sonnet', 'opus'), 'theme': ('sonnet', 'opus'), 'resolve': ('sonnet', 'opus'), 'check': ('sonnet', 'auditor'), 'reread': ('sonnet', 'auditor'), 'second': ('auditor', None), 'extract': ('sonnet', 'opus'), 'split': ('opus', 'auditor'), 'verify': ('opus', 'auditor'), 'verify_set': ('opus', 'auditor'), 'audit': ('auditor', None)},
    'routing.LOCAL_DEFAULTS': {'label': 'small', 'link': 'small', 'expand': 'large', 'decompose': 'large', 'theme': 'large', 'resolve': 'large', 'check': 'large', 'reread': 'large', 'second': 'second', 'extract': 'large', 'split': 'large', 'verify': 'large', 'verify_set': 'large', 'audit': 'second'},
    'routing.HELPERS': {'label': 'enlens-labeller', 'link': 'enlens-linker', 'theme': 'enlens-namer', 'expand': 'enlens-namer', 'resolve': 'enlens-reader', 'decompose': 'enlens-reader', 'check': 'enlens-checker', 'reread': 'enlens-checker', 'second': 'enlens-auditor', 'extract': 'enlens-extractor', 'split': 'enlens-extractor', 'verify': 'enlens-checker', 'verify_set': 'enlens-checker', 'audit': 'enlens-auditor'},
    'routing.TO_AUDITOR': ('check', 'reread', 'split', 'verify', 'verify_set'),
    'prompts.VERSIONS': {'extract': 'extract-v1', 'split': 'split-v2', 'verify': 'verify-v1', 'verify_set': 'verify-set-v1', 'expand': 'expand-v2', 'check': 'check-v4', 'decompose': 'decompose-v1', 'reread': 'check-v4', 'second': 'check-v4', 'label': 'label-v1', 'link': 'link-v1', 'theme': 'theme-v1', 'resolve': 'resolve-v1'},
    'tasks.KINDS': ('split', 'extract', 'verify', 'verify_set', 'expand', 'check', 'decompose', 'reread', 'second', 'label', 'link', 'theme', 'resolve'),
    'tasks.CORPUS_KINDS': ('label', 'link', 'theme', 'resolve'),
    'taskqueue.BATCH': {'label': 20, 'link': 10, 'theme': 5, 'expand': 5, 'decompose': 5, 'resolve': 4, 'check': 1, 'reread': 1, 'second': 1, 'split': 5, 'extract': 8, 'verify': 10, 'verify_set': 3},
    'taskqueue.ORDER': ('decompose', 'expand', 'check', 'reread', 'second', 'theme', 'link', 'label', 'resolve', 'split', 'verify_set', 'verify', 'extract'),
    'taskqueue.NOUN': {'label': ('passage to label', 'passages to label'), 'link': ('pair of terms', 'pairs of terms'), 'theme': ('theme to name', 'themes to name'), 'expand': ('set of search words', 'sets of search words'), 'decompose': ('hypothesis to split', 'hypotheses to split'), 'resolve': ('window of references', 'windows of references'), 'check': ('set of excerpts to judge', 'sets of excerpts to judge'), 'reread': ('excerpt to read again', 'excerpts to read again'), 'second': ('set of excerpts for a second opinion', 'sets of excerpts for a second opinion'), 'split': ('justification to split', 'justifications to split'), 'extract': ('passage to extract claims from', 'passages to extract claims from'), 'verify': ('claim and passage to check', 'claims and passages to check'), 'verify_set': ('VCA claim to check', 'VCA claims to check')},
    'taskqueue.SHORT': {'label': 'labels', 'link': 'pairs of terms', 'theme': 'theme names', 'expand': 'sets of search words', 'decompose': 'hypotheses to split', 'resolve': 'windows of references', 'check': 'sets of excerpts', 'reread': 'excerpts to read again', 'second': 'second opinions', 'split': 'justifications to split', 'extract': 'passages to extract', 'verify': 'claims to check', 'verify_set': 'VCA claims to check'},
    'taskqueue.KIND_TITLE': {'label': 'Codebook labels', 'link': 'How concepts relate', 'theme': 'Theme names', 'expand': 'Search words', 'decompose': 'Splitting hypotheses', 'resolve': 'References in documents', 'check': 'Judging excerpts', 'reread': 'Reading an excerpt again', 'second': 'Second opinions', 'split': 'SDG pack: splitting justifications', 'extract': 'SDG pack: extracting claims', 'verify': 'SDG pack: checking claims', 'verify_set': 'SDG pack: checking VCA claims'},
    'llm.JUDGING': frozenset({'second', 'check', 'reread'}),
    'llm.OUTPUT_CAP': {'expand': 400, 'decompose': 800, 'check': 1500, 'verify_set': 1500, 'verify': 600, 'split': 1500, 'extract': 3000, 'reread': 600, 'second': 1500, 'label': 1500, 'link': 700, 'theme': 500, 'resolve': 2500},
}


def _table(key):
    mod, name = key.split(".")
    return getattr({"routing": routing, "prompts": prompts, "tasks": tasks, "taskqueue": taskqueue, "llm": llm}[mod], name)


@pytest.mark.parametrize("key", sorted(SNAPSHOT_014))
def test_every_table_is_built_from_the_registry_and_equals_0_14(key):
    old, new = SNAPSHOT_014[key], _table(key)
    if key in ("routing.KINDS", "tasks.KINDS"):
        assert set(new) == set(old) and len(new) == len(old)
    elif isinstance(old, tuple):
        assert tuple(new) == old
    else:
        assert new == old and dict(new) == dict(old) if isinstance(old, dict) else new == old


def test_the_other_tables_too():
    assert dict(runs.taskkinds.Table("run_name")) == {
        "check": "Checking hypotheses", "reread": "Reading an excerpt again", "second": "Second opinion",
        "expand": "Search words", "decompose": "Splitting a hypothesis", "label": "Codebook labels",
        "link": "How concepts relate", "theme": "Theme names", "resolve": "References in a document",
        "extract": "Extracting claims (SDG pack)", "verify_set": "Checking VCA claims (SDG pack)",
        "verify": "Checking claims (SDG pack)", "split": "Splitting justifications (SDG pack)"}
    assert dict(tasks.HANDLERS) == {"extract": tasks._store_extract, "split": tasks._store_split,
                                    "verify": tasks._store_verify, "verify_set": tasks._store_verify_set,
                                    "expand": tasks._store_expand, "check": tasks._store_check,
                                    "decompose": tasks._store_decompose, "reread": tasks._store_reread,
                                    "second": tasks._store_second, "label": tasks._store_label,
                                    "link": tasks._store_link, "theme": tasks._store_theme,
                                    "resolve": tasks._store_resolve}
    assert dict(routing.HELPER_MODEL)["enlens-checker"] == "sonnet" and len(routing.HELPER_MODEL) == 7
    # the certainty of an answer, as 0.13.5 read it
    assert routing.certainty("verify", {"confidence": 0.4}) == 0.4
    assert routing.certainty("label", {"labels": [{"confidence": 0.9}, {"confidence": 0.3}]}) == 0.3
    assert routing.certainty("audit", {"evidence": [{"confidence": 0.7}]}) == 0.7
    assert routing.certainty("expand", {"terms": ["a"]}) is None
    # a table can still be changed for a test (monkeypatch.setitem), and goes back
    mp = pytest.MonkeyPatch()
    mp.setitem(prompts.VERSIONS, "check", "check-test")
    assert prompts.VERSIONS["check"] == "check-test" and taskkinds.get("check").prompt_version == "check-test"
    mp.undo()
    assert prompts.VERSIONS["check"] == "check-v4"


# ---------------------------------------------------------------------------------------------
# registering a kind
# ---------------------------------------------------------------------------------------------
def _kind(**kw):
    base = dict(name="x_kind", prompt_version="x-v1", system=lambda: "s", user=lambda p: "u",
                quote_from=lambda p: p["text"], store=lambda cx, t, p, o, m: (True, []))
    base.update(kw)
    return taskkinds.TaskKind(**base)


def test_a_kind_needs_a_quote_check_and_its_parts():
    with pytest.raises(ValueError, match="no quote check"):
        taskkinds.register(_kind(quote_from=None))
    with pytest.raises(ValueError, match="needs store"):
        taskkinds.register(_kind(store=None))
    with pytest.raises(ValueError, match="one of ENLENS's own"):
        taskkinds.register(_kind(name="check"))
    with pytest.raises(TypeError):
        taskkinds.register({"name": "x"})
    k = taskkinds.register(_kind())
    try:
        # defaults for what it did not say, and it is in every table
        assert k.batch == 5 and k.claude == ("sonnet", "opus") and k.row == "x_kind" and not k.core
        assert "x_kind" in taskqueue.ORDER and taskqueue.ORDER[-1] == "x_kind" and "x_kind" in routing.KINDS
        assert prompts.VERSIONS["x_kind"] == "x-v1" and llm.OUTPUT_CAP["x_kind"] == 2000
        assert ("x_kind", ("x_kind",), "x_kind") in list(routing.ROWS)
    finally:
        taskkinds.unregister("x_kind")
    assert "x_kind" not in taskqueue.ORDER and taskkinds.get("x_kind") is None
    taskkinds.unregister("check")  # ENLENS's own stay
    assert taskkinds.get("check") is not None


def test_the_quote_check_of_an_addon_kind():
    k = _kind()
    assert taskkinds.check_quotes(k, {"text": "Water stress rises in summer."},
                                  {"tags": [{"quote": "water  stress rises"}]}) == []
    bad = taskkinds.check_quotes(k, {"text": "Water stress rises in summer."},
                                 {"tags": [{"quote": "invented"}, {"quote": " "}]})
    assert any("not found in the passage" in b and "character for character" in b for b in bad)
    assert any("empty" in b for b in bad)


# ---------------------------------------------------------------------------------------------
# the stand-in add-on's kind, end to end
# ---------------------------------------------------------------------------------------------
NOTE = "Water stress rises near the electrolysis plant in summer. The town council asked for a study."


@pytest.fixture
def notes(addon, loaded):
    ws = Workspace.open(loaded.root)  # opened again: with the add-on's tables
    with ws.connect() as cx:
        cx.execute("INSERT INTO fake_notes(note_id, text, ai_access) VALUES ('n1', ?, 'cloud')", (NOTE,))
    return ws


def test_the_stand_in_kind_is_in_every_table(addon):
    assert taskqueue.BATCH["fake_tag"] == 7 and taskqueue.NOUN["fake_tag"] == ("note to tag", "notes to tag")
    o = list(taskqueue.ORDER)
    assert o.index("link") < o.index("fake_tag") < o.index("label")  # order 7.5: between link and label
    assert taskqueue.KIND_TITLE["fake_tag"] == "Tagging notes" and taskqueue.noun("fake_tag", 3) == "3 notes to tag"
    assert routing.HELPERS["fake_tag"] == "fake-tagger" and routing.HELPER_MODEL["fake-tagger"] == "haiku"
    assert prompts.VERSIONS["fake_tag"] == "fake-tag-v1" and llm.OUTPUT_CAP["fake_tag"] == 300
    assert "fake_tag" in tasks.KINDS and "fake_tag" not in llm.JUDGING
    assert prompts.system_prompt("fake_tag").startswith("You tag a researcher's note")
    assert prompts.user_prompt("fake_tag", {"text": NOTE}) == f"NOTE:\n{NOTE}"


def test_routing_and_step_up(addon):
    r = routing.Router(route="claude_code")
    assert r.first("fake_tag") == "haiku" and r.step_up("fake_tag") == "sonnet" and r.helper("fake_tag") == "fake-tagger"
    api = routing.Router(route="anthropic")
    assert api.call_model("fake_tag") == routing.API_IDS["haiku"]
    local = routing.Router(route="local", large="big", small="tiny")
    assert local.first("fake_tag") == "tiny" and local.step_up("fake_tag") == "big"
    chosen = routing.Router(route="claude_code", overrides={"fake_tag": "sonnet"})  # its own Settings row
    assert chosen.first("fake_tag") == "sonnet" and chosen.step_up("fake_tag") == "opus"
    assert routing.clean_task_models({"claude": {"fake_tag": "opus"}}) == {"claude": {"fake_tag": "opus"}}
    assert routing.certainty("fake_tag", {"tags": [{"confidence": 0.9}, {"confidence": 0.4}]}) == 0.4
    row = next(x for x in r.table() if x["row"] == "fake_tag")
    assert row["title"] == "Tagging notes" and row["model"] == "haiku" and row["helper"] == "fake-tagger"


def test_through_the_queue(notes):
    ws = notes
    with tasks.queueing(True), ws.connect() as cx:
        tid = addon_tag_task(cx)
    assert ws.query("SELECT queued, access FROM tasks WHERE task_id=?", (tid,))[0][:] == (1, "cloud")
    st = taskqueue.status(ws)
    k = next(x for x in st["kinds"] if x["kind"] == "fake_tag")
    assert k["title"] == "Tagging notes" and k["waiting"] == 1
    batch = taskqueue.next_tasks(ws, kind="fake_tag")
    assert batch["helper"] == "fake-tagger" and batch["model"] == "haiku" and batch["prompt_version"] == "fake-tag-v1"
    assert batch["system"].startswith("You tag") and NOTE in batch["tasks"][0]["prompt"]
    # a quote that is not in the note is refused, by ENLENS, before the add-on stores anything
    r = taskqueue.submit(ws, batch["claim"], [{"task_id": tid, "answer": {"tags": [
        {"tag": "water", "quote": "Water is plentiful everywhere.", "confidence": 0.9}]}}])
    assert r["stored"] == 0 and "not found" in json.dumps(r)
    assert not ws.scalar("SELECT COUNT(*) FROM fake_tags")
    # a good answer is stored, with its route
    r = taskqueue.submit(ws, batch["claim"], [{"task_id": tid, "answer": {"tags": [
        {"tag": "water", "quote": "water stress rises near the electrolysis plant", "confidence": 0.9}]}}])
    assert r["stored"] == 1, r
    assert ws.query("SELECT tag, model FROM fake_tags")[0][:] == ("water", "haiku")
    assert ws.scalar("SELECT route FROM results WHERE task_id=? AND valid=1", (tid,)) == "Claude Code"


def test_an_answer_that_breaks_the_kinds_schema_is_refused(notes):
    ws = notes
    with tasks.queueing(True), ws.connect() as cx:
        tid = addon_tag_task(cx)
    batch = taskqueue.next_tasks(ws, kind="fake_tag")
    r = taskqueue.submit(ws, batch["claim"], [{"task_id": tid, "answer": {"tags": [
        {"tag": "", "quote": "Water stress rises", "confidence": 2}]}}])
    assert r["stored"] == 0 and r["results"][0]["problems"]
    assert not ws.scalar("SELECT COUNT(*) FROM fake_tags")


def addon_tag_task(cx):
    import enlens_fake_addon

    return enlens_fake_addon.tag_task(cx, "n1", NOTE)


def test_a_low_certainty_answer_steps_up(notes):
    ws = notes
    with tasks.queueing(True), ws.connect() as cx:
        tid = addon_tag_task(cx)
    batch = taskqueue.next_tasks(ws, kind="fake_tag")
    taskqueue.submit(ws, batch["claim"], [{"task_id": tid, "answer": {"tags": [
        {"tag": "water", "quote": "Water stress rises", "confidence": 0.3}]}}])
    t = ws.query("SELECT status, step, again FROM tasks WHERE task_id=?", (tid,))[0]
    assert t["step"] == 1  # unsure: read again by the stronger model
    again = taskqueue.next_tasks(ws, kind="fake_tag")
    assert again["model"] == "sonnet"


def test_the_offline_demo_and_how_results_were_made(notes):
    ws = notes
    with ws.connect() as cx:
        tid = addon_tag_task(cx)
    stats = tasks.run(ws, "fake_tag", BaselineBackend(), model="baseline")
    assert stats["done"] == 1, stats
    assert ws.query("SELECT tag, quote FROM fake_tags")[0][:] == ("water", "Water stress rises near the electrolysis "
                                                                   "plant in summer")
    rows = runs.provenance_table(ws, task_ids=[tid])
    assert any("Tags of notes" in json.dumps(r) for r in rows), rows


def test_the_size_estimate_of_the_stand_in_kind(addon):
    small = home.task_tokens("fake_tag", max_chars=500)
    big = home.task_tokens("fake_tag", max_chars=5000)
    assert big - small > 1000  # it grows with the passage, as its `size` says
    assert home.task_tokens("fake_tag") < home.task_tokens("check")


def test_the_claude_code_plugin_has_its_helper(addon, tmp_path):
    from enlens_claims import claude_setup

    root = claude_setup.write_plugin(tmp_path / "market")
    f = root / "plugins" / claude_setup.PLUGIN / "agents" / "fake-tagger.md"
    assert f.is_file() and "{{TOOL_PREFIX}}" not in f.read_text()
    assert claude_setup.check_files(root) == []


def test_local_only_and_the_access_guard(notes, monkeypatch):
    ws = notes
    with ws.connect() as cx:
        cx.execute("INSERT INTO fake_notes(note_id, text, ai_access) VALUES ('n2', ?, 'local')", (NOTE,))
    import enlens_fake_addon

    with tasks.queueing(True), ws.connect() as cx:
        tid = enlens_fake_addon.tag_task(cx, "n2", NOTE)
    t = ws.query("SELECT * FROM tasks WHERE task_id=?", (tid,))[0]
    assert t["access"] == "local" and not t["queued"]  # the note's setting holds for the add-on's own kind
    from enlens_claims.llm import ClaudeCodeBackend

    with pytest.raises(access.AccessError):
        access.require(ClaudeCodeBackend(), t)
    monkeypatch.setattr(home, "local_only", lambda: True)
    with pytest.raises(ValueError, match="local only"):
        taskqueue.next_tasks(ws, kind="fake_tag")


def test_the_registry_is_documented():
    from pathlib import Path

    ext = (Path(__file__).resolve().parent.parent / "docs" / "EXTENDING.md").read_text(encoding="utf-8")
    for name in ("taskkinds.register", "TaskKind", "quote_from", "quote_fields", "helper_file", "certainty"):
        assert name in ext, name
